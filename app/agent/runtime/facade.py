"""AgentRunner compatibility facade — Phase 2.

``RuntimeBackedAgentRunner`` is a drop-in replacement for AgentRunner
with the exact same ``run``/``resume`` signatures (implementation_plan.md
Phase 2: "AgentRunner compatibility facade"). It wraps the existing
AgentRunner — the browser foundation is NOT reimplemented — and layers
the persistent runtime on top:

- every run executes inside an AgentSession + AgentRunState
- lifecycle transitions are derived from the run's WorkflowState (the
  runtime observes; it does not duplicate the browser loop)
- every pause (WAITING_FOR_USER / READY_FOR_CONFIRMATION / auth) raises
  a durable interrupt + checkpoint
- agent decisions can be recorded via record_decision()

Facade inheritance strategy: inherit from AgentRunner so isinstance()
checks and attribute access keep working (tests and routes patch
``runner._observer``, ``runner._mapper`` etc.); the runtime wraps the
same base behavior. run/resume are overridden to add runtime tracking.
"""

from __future__ import annotations

import logging

from app.agent.runner import AgentRunner
from app.agent.runtime.checkpoint import utc_now_iso
from app.agent.runtime.decision import AgentDecision
from app.agent.runtime.runtime import AgentRuntime
from app.agent.runtime.state import AgentRunState
from app.models.workflow_state import WorkflowState

logger = logging.getLogger(__name__)


class RuntimeBackedAgentRunner(AgentRunner):
    """AgentRunner-compatible facade backed by AgentRuntime.

    The facade re-enters the base _loop exactly like the base class; the
    runtime tracks state, events, interrupts and checkpoints around it.
    """

    def __init__(self, *args, runtime: AgentRuntime | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._agent_runtime = runtime or AgentRuntime()
        self._session = self._agent_runtime.create_session(label="runner")
        self._current_run: AgentRunState | None = None

    @property
    def agent_runtime(self) -> AgentRuntime:
        return self._agent_runtime

    @property
    def session(self):
        return self._session

    @property
    def current_run(self) -> AgentRunState | None:
        return self._current_run

    # ------------------------------------------------------------------
    # run / resume
    # ------------------------------------------------------------------

    async def run(self, page, task: str = "", domain: str = "") -> WorkflowState:
        """Run the loop with runtime tracking (same contract as base)."""
        self._current_run = self._agent_runtime.create_run(
            session=self._session, goal=task or "(no goal)",
        )
        run = self._current_run
        run.world_state.domain = domain
        run.world_state.created_at = utc_now_iso()
        workflow = await super().run(page, task=task, domain=domain)
        self._absorb(run, workflow)
        # Terminal completion events (COMPLETED/FAILED/ABORTED came from
        # the workflow sync; RUN_COMPLETED/RUN_FAILED/RUN_ABORTED add the
        # explicit terminal marker event).
        self._emit_terminal_event(run, workflow)
        return workflow

    async def resume(
        self, page, workflow: WorkflowState, approved: bool,
    ) -> WorkflowState:
        """Resume with runtime tracking (same contract as base)."""
        run = self._current_run
        if run is None:
            # Same fail-closed behavior as base: no run tracking without
            # a prior run(); still delegate so behavior matches.
            return await super().resume(page, workflow, approved)
        if run.pending_interrupt is not None:
            self._agent_runtime.resolve_interrupt(
                run, resolution="user_responded" if approved else "user_declined",
            )
        workflow = await super().resume(page, workflow, approved)
        self._absorb(run, workflow)
        self._emit_terminal_event(run, workflow)
        return workflow

    # ------------------------------------------------------------------
    # Decision recording (the Phase 4 loop will call this)
    # ------------------------------------------------------------------

    def record_decision(self, decision: AgentDecision):
        run = self._current_run
        if run is None:
            raise RuntimeError(
                "record_decision called before run() — no active run"
            )
        return self._agent_runtime.record_decision(run, decision)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _absorb(self, run: AgentRunState, workflow: WorkflowState) -> None:
        """Copy runner-visible metadata into run state and sync lifecycle.

        The workflow object is the runner's own WorkflowState (created in
        the base class); run.world_state must reflect it for checkpoints
        to carry the logical task state.
        """
        run.world_state = workflow
        run.goal = workflow.task_description or run.goal
        self._agent_runtime.sync_lifecycle_from_workflow(run)

    def _emit_terminal_event(self, run: AgentRunState, workflow: WorkflowState) -> None:
        from app.agent.runtime.events import AgentEventType
        from app.models.workflow_state import WorkflowStatus

        match workflow.status:
            case WorkflowStatus.COMPLETED:
                event_type = AgentEventType.RUN_COMPLETED
            case WorkflowStatus.FAILED:
                event_type = AgentEventType.RUN_FAILED
            case WorkflowStatus.ABORTED:
                event_type = AgentEventType.RUN_ABORTED
            case _:
                return
        self._agent_runtime._emit(  # noqa: SLF001 — facade is runtime-adjacent
            run, event_type,
            data={"status": workflow.status.value},
            message=f"Run {event_type.value}: {workflow.status.value}",
        )
        self._agent_runtime.checkpoint_run(run, reason=f"terminal:{event_type.value}")
        self._session.end_run(run.run_id)
