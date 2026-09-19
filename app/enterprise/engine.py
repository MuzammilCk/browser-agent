"""WorkerRunEngine — Phase 13 execution wrapper (invariant 4).

The ONLY component in the enterprise runtime that owns live browser
handles. It is a thin WRAPPER around the existing Phase 1-12 execution
stack — it creates NO alternative execution path:

    AgentRuntime → ToolRegistry → PolicyEngine → BrowserExecutor
        → verification → WorldState → checkpoint

The loop structure deliberately mirrors the Phase 12 ScenarioRunner
driving loop (observe → reason → policy → execute → verify → world
update) with three enterprise additions:
  1. lease_guard.ensure_valid() between iterations — lease loss stops
     browser execution immediately (fail closed, invariant 6);
  2. cancellation polling at safe boundaries (durable, invariant on
     cancellation semantics);
  3. durable checkpointing through the EXISTING Phase 8 checkpoint
     store on every pause and terminal state.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from app.agent.evaluation.trace import TraceEventType, TraceRecorder
from app.agent.reasoning import (
    AgentReasoner,
    ReasonerConfig,
    build_reasoning_context,
    decision_to_tool_call,
)
from app.agent.runtime.checkpoint import AgentCheckpoint, CheckpointStore
from app.agent.runtime.decision import AgentDecisionType
from app.agent.runtime.runtime import AgentRuntime
from app.agent.runtime.state import AgentLifecycle, AgentRunState
from app.agent.security.budget import RuntimeBudget, RuntimeBudgetTracker
from app.agent.tools import ToolContext, ToolRegistry, build_registry
from app.agent.world.models import AgentWorldState
from app.agent.world.reducer import reduce_observation
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.policy.engine import PolicyDecision, PolicyEngine

logger = logging.getLogger(__name__)


class LeaseLostError(Exception):
    """Raised when the execution lease can no longer be renewed —
    the worker MUST stop all browser mutation (fail closed)."""


class EngineOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED_HITL = "paused_hitl"
    CANCELLED = "cancelled"
    LEASE_LOST = "lease_lost"


@dataclass
class EngineResult:
    outcome: EngineOutcome
    checkpoint_id: str | None = None
    agent_run_id: str | None = None
    error: str | None = None
    iterations: int = 0


class LeaseGuard:
    """Checks lease validity between safe boundaries and via renewal."""

    def __init__(
        self,
        renew: Callable[[], Any],
        *,
        check_interval_seconds: float = 0.0,
    ) -> None:
        self._renew = renew           # async () -> lease | None
        self._valid = True

    def ensure_valid(self) -> None:
        if not self._valid:
            raise LeaseLostError("execution lease is no longer valid")

    async def renew(self) -> bool:
        try:
            lease = await self._renew()
        except Exception:
            lease = None
        self._valid = lease is not None
        return self._valid


class WorkerRunEngine:
    """Executes one enterprise run through the real agent stack."""

    def __init__(
        self,
        *,
        model: Any,                      # DecisionModel protocol
        settings: Settings | None = None,
        checkpoint_store: CheckpointStore | None = None,
        recorder: TraceRecorder | None = None,
        max_iterations: int = 15,
        max_tool_calls: int = 25,
    ) -> None:
        self._model = model
        self._settings = settings or Settings(headless=True)
        self._checkpoint_store = checkpoint_store
        self._recorder = recorder
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        *,
        goal: str,
        start_url: str,
        agent_run_id: str | None = None,
        checkpoint_id: str | None = None,
        lease_guard: LeaseGuard | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineResult:
        """Run (or resume) one agent run inside the caller's lease.

        Resume path: when checkpoint_id is given, state is restored from
        the EXISTING Phase 8 checkpoint (budget state, world state,
        verified facts, events) and the live browser is re-observed —
        the last browser mutation is never blindly replayed.
        """
        runtime = AgentRuntime(
            checkpoint_store=self._checkpoint_store,
        )

        # ---- Restore or create the runtime run -----------------------
        if checkpoint_id:
            try:
                run_state = runtime.restore_checkpoint(checkpoint_id)
            except KeyError:
                return EngineResult(
                    outcome=EngineOutcome.FAILED,
                    error=f"checkpoint {checkpoint_id} not found",
                )
            except Exception as exc:  # corrupt/incompatible — fail closed
                return EngineResult(
                    outcome=EngineOutcome.FAILED,
                    error=f"checkpoint restore failed: {exc}",
                )
        else:
            session = runtime.create_session(label="enterprise_worker")
            run_state = runtime.create_run(session=session, goal=goal)
        agent_run_id = agent_run_id or run_state.run_id

        # Budget state survives worker replacement (invariant 18):
        tracker: RuntimeBudgetTracker = run_state.get_budget_tracker()
        if not run_state.budget_state:
            tracker = RuntimeBudgetTracker(
                budget=RuntimeBudget(
                    max_iterations=self._max_iterations,
                    max_tool_calls=self._max_tool_calls,
                ),
            )
            run_state.save_budget_tracker(tracker)

        world_state: AgentWorldState = (
            run_state.agent_world_state or AgentWorldState(goal=goal)
        )

        registry = build_registry()
        policy_engine = PolicyEngine()
        executor = BrowserExecutor()
        observer = PageObserver()

        known_tools = frozenset(registry.list_names())
        action_tools = frozenset(
            name for name in known_tools
            if registry.metadata(name) is not None
            and registry.metadata(name).accepts_browser_action
        )
        reasoner = AgentReasoner(
            self._model,
            known_tools=known_tools,
            action_tools=action_tools,
            config=ReasonerConfig(max_attempts=3),
        )

        recent_results: list[Any] = []
        result = EngineResult(outcome=EngineOutcome.FAILED, agent_run_id=agent_run_id)

        # ---- Browser lifecycle (owned exclusively by this worker) ----
        async with BrowserManager(self._settings) as manager:
            try:
                page = await manager.open(start_url)
                initial_obs = await observer.observe(page)
                reduce_observation(world_state, initial_obs)
                run_state.agent_world_state = world_state

                ctx = ToolContext(
                    observation=initial_obs,
                    page=page,
                    executor=executor,
                    observer=observer,
                )

                outcome, error, iterations = await self._loop(
                    run_state=run_state,
                    runtime=runtime,
                    reasoner=reasoner,
                    registry=registry,
                    policy_engine=policy_engine,
                    ctx=ctx,
                    world_state=world_state,
                    tracker=tracker,
                    recent_results=recent_results,
                    lease_guard=lease_guard,
                    cancel_check=cancel_check,
                )
                result.outcome = outcome
                result.error = error
                result.iterations = iterations
            except LeaseLostError:
                result.outcome = EngineOutcome.LEASE_LOST
                result.error = "lease lost — browser execution stopped (fail closed)"
            except Exception as exc:
                result.outcome = EngineOutcome.FAILED
                result.error = f"{type(exc).__name__}: {exc}"
                logger.exception("worker engine execution failed")

        # ---- Durable checkpoint on every exit path --------------------
        try:
            cp: AgentCheckpoint = runtime.checkpoint_run(
                run_state,
                reason=f"enterprise:{result.outcome.value}",
            )
            if self._checkpoint_store is not None and hasattr(
                self._checkpoint_store, "save_checkpoint",
            ):
                await self._checkpoint_store.save_checkpoint(cp)
            result.checkpoint_id = cp.checkpoint_id
        except Exception as exc:
            logger.error("final checkpoint failed: %s", exc)

        return result

    # ------------------------------------------------------------------
    # The loop (mirrors Phase 12 ScenarioRunner; enterprise guards added)
    # ------------------------------------------------------------------

    async def _loop(
        self,
        *,
        run_state: AgentRunState,
        runtime: AgentRuntime,
        reasoner: AgentReasoner,
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
        ctx: ToolContext,
        world_state: AgentWorldState,
        tracker: RuntimeBudgetTracker,
        recent_results: list[Any],
        lease_guard: LeaseGuard | None,
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[EngineOutcome, str | None, int]:
        iterations = 0
        rec = self._recorder

        while run_state.iteration < tracker.budget.max_iterations:
            # -- Enterprise guards at the safe boundary ----------------
            if lease_guard is not None:
                lease_guard.ensure_valid()
            if cancel_check is not None and cancel_check():
                return EngineOutcome.CANCELLED, "cancellation observed at safe boundary", iterations

            run_state.iteration += 1
            iterations = run_state.iteration
            if rec:
                rec.set_iteration(run_state.iteration)
            runtime.transition_toward(run_state, AgentLifecycle.OBSERVING)

            # -- Budget (preserved across worker replacement) ----------
            try:
                tracker.record_iteration()
            except Exception as exc:
                return EngineOutcome.FAILED, f"budget exhausted: {exc}", iterations

            if rec:
                rec.record(
                    TraceEventType.OBSERVATION,
                    subsystem="browser",
                    component="PageObserver",
                    output_summary={
                        "observation_id": ctx.observation.observation_id,
                        "url": ctx.observation.page_state.url,
                    },
                    world_state_version=world_state.version,
                )

            reasoning_ctx = build_reasoning_context(
                goal=run_state.goal,
                subgoal=run_state.current_subgoal or "Current workflow step",
                observation=ctx.observation,
                tool_metadata=[
                    registry.metadata(name) for name in registry.list_names()
                ],
                recent_results=recent_results[-5:],
                unresolved_questions=[],
            )

            runtime.transition_toward(run_state, AgentLifecycle.REASONING)
            outcome = await reasoner.reason(
                reasoning_ctx,
                observation_id=ctx.observation.observation_id,
            )
            if not outcome.decided:
                return (
                    EngineOutcome.FAILED,
                    f"model failure: {outcome.model_failure_code}",
                    iterations,
                )
            decision = outcome.decision
            assert decision is not None

            if rec:
                rec.record(
                    TraceEventType.MODEL_DECISION,
                    subsystem="reasoning",
                    component="AgentReasoner",
                    output_summary={
                        "decision_type": decision.decision_type.value,
                        "tool_name": decision.tool_name,
                    },
                )

            if decision.decision_type is AgentDecisionType.COMPLETE:
                runtime.transition_toward(run_state, AgentLifecycle.COMPLETED)
                return EngineOutcome.COMPLETED, None, iterations
            if decision.decision_type is not AgentDecisionType.TOOL_CALL:
                runtime.transition_toward(run_state, AgentLifecycle.REFLECTING)
                continue

            tool_call = decision_to_tool_call(decision)

            # -- Policy evaluation (PolicyEngine stays authoritative) ---
            if decision.action:
                policy_res = policy_engine.evaluate(
                    decision.action, ctx.observation.page_state,
                )
                if rec:
                    rec.record(
                        TraceEventType.POLICY_EVALUATION,
                        subsystem="policy",
                        component="PolicyEngine",
                        policy_decision=policy_res.decision.value,
                        output_summary={
                            "risk_level": policy_res.risk_level.value,
                            "allowed": policy_res.allowed,
                        },
                    )
                if policy_res.decision is PolicyDecision.DENY:
                    runtime.transition_toward(run_state, AgentLifecycle.FAILED)
                    return (
                        EngineOutcome.FAILED,
                        f"policy denied: {decision.action.action}",
                        iterations,
                    )
                if policy_res.decision is PolicyDecision.REQUIRE_CONFIRMATION:
                    # Durable HITL pause through the EXISTING runtime path.
                    runtime.transition_toward(
                        run_state, AgentLifecycle.WAITING_FOR_USER,
                    )
                    interrupt = runtime.raise_human_interrupt(
                        run_state,
                        reason=__import__(
                            "app.agent.interrupts.models",
                            fromlist=["InterruptReason"],
                        ).InterruptReason.USER_CONFIRMATION_REQUIRED,
                        description=(
                            f"Action requires confirmation: {decision.action.action}"
                        ),
                        observation_id=ctx.observation.observation_id,
                        world_state_version=world_state.version,
                    )
                    if rec:
                        rec.record(
                            TraceEventType.HITL_INTERRUPT,
                            subsystem="interrupts",
                            component="AgentRuntime",
                            input_summary={
                                "interrupt_id": interrupt.interrupt_id,
                                "reason": interrupt.reason.value,
                            },
                        )
                    return EngineOutcome.PAUSED_HITL, interrupt.interrupt_id, iterations

            # -- Execute through the typed registry (existing path) ----
            runtime.transition_toward(run_state, AgentLifecycle.ACTING)
            tool_result = await registry.execute(tool_call, ctx)
            recent_results.append(tool_result)
            runtime.transition_toward(run_state, AgentLifecycle.VERIFYING)

            if rec:
                rec.record(
                    TraceEventType.BROWSER_RESULT,
                    subsystem="tools",
                    component="ToolRegistry",
                    tool_name=tool_call.tool_name,
                    output_summary={
                        "success": tool_result.success,
                        "error": tool_result.error_code,
                    },
                    verification_status=tool_result.verification_status,
                )

            if tool_result.post_observation:
                ctx.observation = tool_result.post_observation
                reduce_observation(world_state, ctx.observation)

            runtime.transition_toward(run_state, AgentLifecycle.REFLECTING)

        return EngineOutcome.FAILED, "max iterations reached", iterations
