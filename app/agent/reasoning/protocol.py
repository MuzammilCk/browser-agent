"""Reasoner protocol + decision JSON schema — Phase 4.

The model faces exactly one contract: emit JSON matching
``ReasonerDecisionSchema``. Everything else (execution, policy, state)
stays a deterministic runtime property.

Design notes:
- ``DecisionModel`` is a deliberately narrow Protocol: prompt in, parsed
  JSON out. The OpenRouter adapter implements it over the EXISTING
  ``LLMGateway`` (app/llm/openrouter.py); tests implement it with a
  deterministic mock. The reasoner never imports OpenRouter.
- ``build_decision_json_schema`` derives the OpenRouter structured-output
  schema from the pydantic model, so prompt contract and validation
  contract cannot drift apart.
- ``ReasoningOutcome`` is the reasoner's total answer: either a validated
  AgentDecision or an explicit MODEL_FAILURE. There is no silent
  fallback path — AGENT_PROTOCOL.md "No silent fallback".
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.agent.runtime.decision import AgentDecision, AgentDecisionType
from app.agent.tools.base import ToolCall

# Fail-closed error codes for the decision boundary (Phase 7 owns the
# full recovery taxonomy; these are the ones Phase 4 must produce).
MODEL_FAILURE = "MODEL_FAILURE"
DECISION_PARSE_FAILED = "DECISION_PARSE_FAILED"
DECISION_SCHEMA_INVALID = "DECISION_SCHEMA_INVALID"
DECISION_VALIDATION_FAILED = "DECISION_VALIDATION_FAILED"

# Every MODEL_FAILURE ReasoningOutcome carries a reason starting with
# this prefix so tests, logs and traces can detect the state without
# parsing free text.
MODEL_FAILURE_REASON_PREFIX = "model_failure:"

# Decisions the model may emit (HANDOFF is disallowed; specialists are agent-as-tools
# invoked via TOOL_CALL).
ALLOWED_DECISION_TYPES = frozenset(
    decision_type.value
    for decision_type in (
        AgentDecisionType.TOOL_CALL,
        AgentDecisionType.REPLAN,
        AgentDecisionType.REFLECT,
        AgentDecisionType.ASK_USER,
        AgentDecisionType.COMPLETE,
    )
)


class ReasonerDecisionSchema(BaseModel):
    """The only JSON shape the model may return.

    This mirrors AgentDecision but is a separate model ON PURPOSE: the
    model's output is untrusted data. It passes through schema validation
    here, then re-validation at the AgentDecision boundary, and only then
    reaches the ToolRegistry. Nothing the model emits is trusted directly.

    Extra fields are forbidden (fail closed on prompt-injected keys), and
    arguments values are constrained to JSON scalars/nested lists/dicts —
    never objects that could smuggle executable content (the tool layer
    re-validates against each tool's strict input schema anyway).
    """

    decision_type: str = Field(
        description="One of: tool_call, replan, reflect, ask_user, complete",
    )
    tool_name: str | None = Field(
        default=None,
        description="Registered tool name for tool_call decisions",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool arguments (validated against the tool's schema)",
    )
    action: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Typed browser action for browser-family tools: "
            "{action, target_ref, value_ref, literal_value, option, "
            "document_ref, direction, key, reason}"
        ),
    )
    reason: str = Field(
        default="",
        description="Why this decision was made (required for non-tool decisions)",
    )
    question: str = Field(
        default="",
        description="The question for the user (ask_user decisions)",
    )
    plan: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Proposed plan steps (replan decisions)",
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
    )

    model_config = {"extra": "forbid"}


def build_decision_json_schema() -> dict[str, Any]:
    """JSON schema for OpenRouter structured output, derived from the model."""
    schema = ReasonerDecisionSchema.model_json_schema()
    schema["additionalProperties"] = False
    # OpenRouter strict mode requires every property to be required;
    # pydantic nullable defaults serialize that faithfully.
    schema["required"] = sorted(schema.get("properties", {}).keys())
    return {
        "name": "agent_decision",
        "strict": True,
        "schema": schema,
    }


@runtime_checkable
class DecisionModel(Protocol):
    """The ONLY capability the reasoner gets from a model.

    Prompt in (trusted system prompt + structured context), parsed JSON
    out. No history management, no tools, no execution power. Raising any
    exception is a valid outcome: the reasoner converts it into an
    explicit MODEL_FAILURE after bounded retries.
    """

    async def decide(self, *, system: str, context: str) -> dict[str, Any]:
        """Return the model's parsed decision JSON for one iteration."""
        ...


class ReasoningPhase(str):
    """Why the reasoner returned — for logs, events, and tests."""

    DECIDED = "decided"
    MODEL_FAILURE = "model_failure"


class ReasoningOutcome(BaseModel):
    """Total result of one reasoning attempt.

    decided=True  → decision is a schema-valid AgentDecision ready for
                    the runtime/registry path.
    decided=False → explicit MODEL_FAILURE with a machine-readable code
                    and a reason prefixed MODEL_FAILURE_REASON_PREFIX.
                    The caller must not fall back silently; the state is
                    visible in workflow state and events.
    """

    decided: bool
    decision: AgentDecision | None = None
    model_failure_code: str | None = Field(
        default=None,
        description="Machine-readable failure code (DECISION_* taxonomy)",
    )
    reason: str = Field(
        default="",
        description="Human-readable outcome summary (failure reasons are prefixed)",
    )
    attempts: int = Field(
        default=0,
        description="Model attempts consumed (1 = first try succeeded)",
    )
    phase: str = Field(default=ReasoningPhase.DECIDED)

    @classmethod
    def model_failure(
        cls, code: str, reason: str, *, attempts: int,
    ) -> ReasoningOutcome:
        """Build the explicit failure outcome (never a silent fallback)."""
        return cls(
            decided=False,
            model_failure_code=code,
            reason=f"{MODEL_FAILURE_REASON_PREFIX}{reason}",
            attempts=attempts,
            phase=ReasoningPhase.MODEL_FAILURE,
        )

    @classmethod
    def decided_ok(cls, decision: AgentDecision, *, attempts: int) -> ReasoningOutcome:
        return cls(
            decided=True,
            decision=decision,
            attempts=attempts,
            phase=ReasoningPhase.DECIDED,
        )


def decision_to_tool_call(decision: AgentDecision) -> ToolCall:
    """Convert a validated TOOL_CALL decision into the registry's ToolCall.

    The registry remains the ONLY path to execution; this conversion adds
    no authorization and no fallback — invalid calls still fail closed
    inside ToolRegistry.execute.
    """
    return ToolCall(
        tool_name=decision.tool_name or "",
        arguments=dict(decision.arguments or {}),
        action=decision.action,
        reason=decision.reason,
    )
