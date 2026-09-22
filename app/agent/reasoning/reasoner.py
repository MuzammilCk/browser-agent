"""AgentReasoner — Phase 4 decision-making controller (implementation_plan.md).

One method, one contract:

    reason(context) → ReasoningOutcome
        decided=True  → schema-validated AgentDecision
        decided=False → explicit MODEL_FAILURE (code + prefixed reason)

Boundary guarantees (user instruction, Phase 4):

- The model is consulted through the narrow DecisionModel protocol only.
  It receives the assembled system prompt + bounded context; it never
  sees the registry, the runtime, the browser, paths, or secrets.
- Every model answer passes parse_model_decision (strict schema + typed
  BrowserAction) before it can become an AgentDecision.
- Bounded retries: on a rejected/malformed answer the reasoner retries
  up to max_attempts − 1 more times, feeding the validation error back
  so the model can repair it. Retries are bounded — never infinite.
- After the final attempt the outcome is an explicit MODEL_FAILURE with
  a machine-readable code. NOTHING falls back silently: no deterministic
  decision is fabricated, no default action is guessed, and the caller
  (runtime/loop) is expected to surface the failure in state and events
  (AGENT_PROTOCOL.md "No silent fallback").
- The reasoner never executes anything: it has no registry handle, no
  executor handle, no page handle. Execution happens only after the
  caller routes the decision through ToolRegistry → PolicyEngine.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from app.agent.reasoning.context import ReasoningContext
from app.agent.reasoning.parser import parse_model_decision
from app.agent.reasoning.protocol import (
    DECISION_PARSE_FAILED,
    DecisionModel,
    ReasoningOutcome,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DECISION_TIMEOUT_SECONDS = 60.0


class ReasonerConfig(BaseModel):
    """Bounds for the reasoning loop (fail closed, never unbounded)."""

    max_attempts: int = Field(
        default=DEFAULT_MAX_ATTEMPTS, ge=1, le=5,
        description="Total model attempts per decision (bounded retries)",
    )
    decision_timeout_seconds: float = Field(
        default=DEFAULT_DECISION_TIMEOUT_SECONDS, gt=0.0,
        description=(
            "Wall-clock bound on each model call. A hung model call is "
            "treated as a failed attempt (never an unbounded block)."
        ),
    )


class AgentReasoner:
    """Turns one assembled reasoning context into one validated decision."""

    def __init__(
        self,
        model: DecisionModel,
        *,
        known_tools: frozenset[str] | set[str],
        action_tools: frozenset[str] | set[str],
        config: ReasonerConfig | None = None,
    ) -> None:
        """``known_tools``/``action_tools`` come from the ToolRegistry —
        the reasoner holds only these frozen name sets, never the
        registry itself, so it cannot execute anything by construction.
        ``action_tools`` are the tools that consume a typed BrowserAction.
        """
        self._model = model
        self._known_tools = frozenset(known_tools)
        self._action_tools = frozenset(action_tools)
        self._config = config or ReasonerConfig()

    @property
    def max_attempts(self) -> int:
        return self._config.max_attempts

    @property
    def decision_timeout_seconds(self) -> float:
        return self._config.decision_timeout_seconds

    async def reason(
        self,
        context: ReasoningContext,
        *,
        observation_id: str = "",
    ) -> ReasoningOutcome:
        """Consult the model with bounded retries; fail closed to MODEL_FAILURE.

        Retryable failures (schema-invalid output, unknown tool, malformed
        action) are fed back verbatim so the model can repair its own
        output within the attempt budget. Transport-level errors (the
        model raised) are also retried within the same budget — a flaky
        network is a model failure to recover from, not a crash.
        """
        prompt = context.render()
        last_failure: tuple[str, str] | None = None

        for attempt in range(1, self._config.max_attempts + 1):
            # On repair attempts, prepend the previous rejection reason so
            # the model knows exactly what was wrong.
            user_message = prompt
            if last_failure is not None:
                user_message = (
                    f"YOUR PREVIOUS OUTPUT WAS REJECTED.\n"
                    f"Rejection ({last_failure[0]}): {last_failure[1]}\n\n"
                    f"Return a corrected decision as the specified JSON object.\n\n"
                    f"{prompt}"
                )

            try:
                raw = await asyncio.wait_for(
                    self._model.decide(
                        system=context.system_prompt,
                        context=user_message,
                    ),
                    timeout=self._config.decision_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Phase 15 H2: a hung model call must never block the run
                # past the worker lease. The timeout consumes an attempt so
                # the existing bounded-retry budget still bounds total time;
                # after the final attempt the standard explicit MODEL_FAILURE
                # path fires — no silent fallback, fail closed.
                last_failure = (
                    DECISION_PARSE_FAILED,
                    (
                        f"model call timed out after "
                        f"{self._config.decision_timeout_seconds}s"
                    ),
                )
                logger.warning(
                    "Reasoner attempt %d/%d: model call timed out "
                    "after %.1fs",
                    attempt, self._config.max_attempts,
                    self._config.decision_timeout_seconds,
                )
                continue
            except Exception as e:  # transport/provider error → bounded retry
                last_failure = (DECISION_PARSE_FAILED, f"model call failed: {e}")
                logger.warning(
                    "Reasoner attempt %d/%d: model raised %s",
                    attempt, self._config.max_attempts, e,
                )
                continue

            decision, failure = parse_model_decision(
                raw,
                known_tools=self._known_tools,
                action_tools=self._action_tools,
                observation_id=observation_id,
            )
            if decision is not None:
                outcome = ReasoningOutcome.decided_ok(decision, attempts=attempt)
                if attempt > 1:
                    logger.info(
                        "Reasoner accepted decision on attempt %d/%d (%s)",
                        attempt, self._config.max_attempts,
                        decision.decision_type.value,
                    )
                return outcome

            last_failure = failure
            assert failure is not None
            logger.warning(
                "Reasoner attempt %d/%d rejected: %s — %s",
                attempt, self._config.max_attempts, failure[0], failure[1],
            )

        # Retries exhausted → EXPLICIT model failure. No silent fallback,
        # no guessed decision. The caller must surface this state.
        code, detail = last_failure or (
            DECISION_PARSE_FAILED, "model produced no usable decision",
        )
        return ReasoningOutcome.model_failure(
            code, detail, attempts=self._config.max_attempts,
        )
