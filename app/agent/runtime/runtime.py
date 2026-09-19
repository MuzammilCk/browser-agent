"""AgentRuntime — Phase 2 deterministic lifecycle orchestrator.

The runtime OWNS lifecycle, state, events, interrupts, decisions and
checkpoints (docs/ARCHITECTURE_TARGET.md: AgentRuntime responsibilities).
Phase 2 implements this deterministically, without the LLM loop: there is
no reasoning yet, but every state transition, event, decision record and
checkpoint already flows through the same validated paths the Phase 4
reasoning loop will use.

Hard rules encoded here:
- Transitions are validated against LIFECYCLE_TRANSITIONS — an illegal
  transition raises instead of being coerced (fail closed).
- Every state change emits an immutable AgentEvent (append-only log).
- Interrupts are durable: they live in AgentRunState, emit events, and
  trigger a checkpoint (AGENTS.md rule 14: durable and resumable).
- The runtime orchestrates the existing foundation; it does not call
  Playwright and does not duplicate BrowserExecutor/PageObserver.
"""

from __future__ import annotations

import logging
import uuid

from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
)
from app.agent.runtime.checkpoint import (
    AgentCheckpoint,
    CheckpointStore,
    InMemoryCheckpointStore,
    utc_now_iso,
)
from app.agent.runtime.decision import AgentDecision, AgentDecisionType
from app.agent.runtime.events import AgentEvent, AgentEventLog, AgentEventType
from app.agent.runtime.session import AgentSession
from app.agent.runtime.state import (
    LIFECYCLE_TRANSITIONS,
    TERMINAL_LIFECYCLE_STATES,
    AgentLifecycle,
    AgentRunState,
    PendingInterrupt,
    UsageCounters,
    can_transition,
)
from app.models.workflow_state import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

# WorkflowStatus (existing runner contract) → AgentLifecycle (Phase 2).
# WAITING_FOR_AUTH / WAITING_FOR_CAPTCHA collapse into WAITING_FOR_USER;
# the specific cause remains in the pending interrupt and workflow state.
_WORKFLOW_STATUS_TO_LIFECYCLE: dict[WorkflowStatus, AgentLifecycle] = {
    WorkflowStatus.INITIALIZED: AgentLifecycle.INITIALIZING,
    WorkflowStatus.RUNNING: AgentLifecycle.REASONING,
    WorkflowStatus.WAITING_FOR_USER: AgentLifecycle.WAITING_FOR_USER,
    WorkflowStatus.WAITING_FOR_AUTH: AgentLifecycle.WAITING_FOR_USER,
    WorkflowStatus.WAITING_FOR_CAPTCHA: AgentLifecycle.WAITING_FOR_USER,
    WorkflowStatus.READY_FOR_CONFIRMATION: AgentLifecycle.READY_FOR_CONFIRMATION,
    WorkflowStatus.READY_FOR_SUBMISSION: AgentLifecycle.READY_FOR_REVIEW,
    WorkflowStatus.COMPLETED: AgentLifecycle.COMPLETED,
    WorkflowStatus.FAILED: AgentLifecycle.FAILED,
    WorkflowStatus.ABORTED: AgentLifecycle.ABORTED,
}

_INTERRUPT_KIND_BY_STATUS: dict[WorkflowStatus, str] = {
    WorkflowStatus.WAITING_FOR_USER: "user_input",
    WorkflowStatus.WAITING_FOR_AUTH: "authentication",
    WorkflowStatus.WAITING_FOR_CAPTCHA: "captcha",
    WorkflowStatus.READY_FOR_CONFIRMATION: "confirmation",
}


class InvalidLifecycleTransition(Exception):
    """Raised when a lifecycle transition is not in the transition table."""


def lifecycle_for_workflow_status(status: WorkflowStatus) -> AgentLifecycle:
    """Deterministic mapping from the existing WorkflowStatus contract."""
    return _WORKFLOW_STATUS_TO_LIFECYCLE[status]


class AgentRuntime:
    """Deterministic orchestrator for one or more agent runs.

    Usage (Phase 2, no LLM):
        runtime = AgentRuntime()
        session = runtime.create_session()
        run = runtime.create_run(session=session, goal="Fill form X")
        runtime.sync_lifecycle_from_workflow(run)   # after runner advances
        checkpoint = runtime.checkpoint_run(run, reason="paused")
        # later / other process boundary:
        restored = runtime.restore_checkpoint(cp.checkpoint_id)
    """

    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        self._checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
        self._sessions: dict[str, AgentSession] = {}
        self._runs: dict[str, AgentRunState] = {}
        self._event_logs: dict[str, AgentEventLog] = {}
        self._decisions: dict[str, list[AgentDecision]] = {}

    # ------------------------------------------------------------------
    # Sessions / runs
    # ------------------------------------------------------------------

    def create_session(self, *, label: str = "") -> AgentSession:
        session = AgentSession(
            session_id=self._new_id("session"),
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            label=label,
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def create_run(
        self,
        *,
        session: AgentSession,
        goal: str,
        workflow: WorkflowState | None = None,
        parent_run_id: str | None = None,
        specialist_kind: str | None = None,
    ) -> AgentRunState:
        """Create a run in INITIALIZING with its own event log."""
        now = utc_now_iso()
        run = AgentRunState(
            run_id=self._new_id("run"),
            created_at=now,
            updated_at=now,
            goal=goal,
            lifecycle=AgentLifecycle.INITIALIZING,
            world_state=workflow or WorkflowState(
                workflow_id=self._new_id("wf")[:8],
                task_description=goal,
                created_at=now,
            ),
            agent=_identity_for(parent_run_id, specialist_kind),
        )
        run.memory.episodic_event_log_id = run.run_id
        self._runs[run.run_id] = run
        self._event_logs[run.run_id] = AgentEventLog(run_id=run.run_id)
        self._decisions[run.run_id] = []
        session.start_run(run.run_id)
        self._emit(
            run, AgentEventType.RUN_STARTED,
            data={"goal": goal, "session_id": session.session_id},
            message=f"Run started: {goal}",
        )
        return run

    def get_run(self, run_id: str) -> AgentRunState | None:
        return self._runs.get(run_id)

    def get_event_log(self, run_id: str) -> AgentEventLog:
        return self._event_logs[run_id]

    # ------------------------------------------------------------------
    # Lifecycle transitions (deterministic, validated, evented)
    # ------------------------------------------------------------------

    def set_lifecycle(
        self,
        run: AgentRunState,
        target: AgentLifecycle,
        *,
        reason: str = "",
    ) -> AgentEvent:
        """Transition the run to ``target``.

        Deterministic and fail-closed: an illegal transition raises
        InvalidLifecycleTransition; nothing mutates silently.
        """
        if not can_transition(run.lifecycle, target):
            raise InvalidLifecycleTransition(
                f"run {run.run_id}: illegal transition "
                f"{run.lifecycle.value} → {target.value}"
            )
        previous = run.lifecycle
        run.lifecycle = target
        run.updated_at = utc_now_iso()
        if target in TERMINAL_LIFECYCLE_STATES and run.pending_interrupt is not None:
            # Terminal states resolve any open interrupt: nothing is
            # left dangling waiting for a user who can no longer act.
            run.pending_interrupt = None
        return self._emit(
            run, AgentEventType.STATE_CHANGED,
            data={"from": previous.value, "to": target.value},
            message=reason or f"{previous.value} → {target.value}",
        )

    def sync_lifecycle_from_workflow(
        self, run: AgentRunState, *, raise_interrupts: bool = True,
    ) -> AgentLifecycle:
        """Derive lifecycle from the run's WorkflowState.

        This is the bridge from the EXISTING browser foundation (the
        AgentRunner mutates WorkflowStatus) into the runtime lifecycle —
        the runtime observes; it does not duplicate the browser loop.
        Paused statuses raise a durable interrupt (optionally), which
        also triggers a checkpoint.
        """
        target = lifecycle_for_workflow_status(run.world_state.status)
        if target is not run.lifecycle:
            self.transition_toward(run, target)
        if raise_interrupts and run.is_paused() and run.pending_interrupt is None:
            ws = run.world_state
            reason = ws.error_message or (
                ws.checkpoints[-1] if ws.checkpoints else ""
            )
            self.raise_interrupt(
                run,
                kind=_INTERRUPT_KIND_BY_STATUS.get(
                    run.world_state.status, "unknown",
                ),
                reason=reason or "run paused",
            )
        return run.lifecycle

    def transition_toward(
        self, run: AgentRunState, target: AgentLifecycle,
    ) -> list[AgentEvent]:
        """Walk the transition table deterministically until ``target``.

        The runner can move a WorkflowStatus several steps at once (e.g.
        RUNNING → READY_FOR_CONFIRMATION on a sensitive fill). A single
        set_lifecycle would reject the multi-hop; this walks the shortest
        path through legal intermediate states, emitting an event per hop,
        so external state changes remain representable and auditable.
        """
        events: list[AgentEvent] = []
        guard = 0
        while run.lifecycle is not target:
            guard += 1
            if guard > 16:
                raise InvalidLifecycleTransition(
                    f"run {run.run_id}: no path "
                    f"{run.lifecycle.value} → {target.value}"
                )
            path = self._shortest_path(run.lifecycle, target)
            if not path:
                raise InvalidLifecycleTransition(
                    f"run {run.run_id}: no path "
                    f"{run.lifecycle.value} → {target.value}"
                )
            events.append(self.set_lifecycle(run, path[0]))
        return events

    @staticmethod
    def _shortest_path(
        current: AgentLifecycle, target: AgentLifecycle,
    ) -> list[AgentLifecycle]:
        """Deterministic shortest path through the transition table (BFS).

        Neighbors are visited in enum-definition order so the chosen path
        is stable across runs. Empty list means unreachable.
        """
        if current is target:
            return []
        order = list(AgentLifecycle)
        visited = {current}
        queue: list[tuple[AgentLifecycle, list[AgentLifecycle]]] = [
            (current, [])
        ]
        while queue:
            node, path = queue.pop(0)
            for neighbor in sorted(
                LIFECYCLE_TRANSITIONS[node], key=order.index,
            ):
                if neighbor is target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return []

    def begin_iteration(self, run: AgentRunState) -> None:
        """Advance to OBSERVING for the next loop iteration."""
        run.iteration += 1
        run.usage.observations_made += 0  # observations counted by caller
        self.set_lifecycle(run, AgentLifecycle.OBSERVING)

    # ------------------------------------------------------------------
    # Interrupts (durable, checkpointed)
    # ------------------------------------------------------------------

    def raise_interrupt(
        self,
        run: AgentRunState,
        *,
        kind: str,
        reason: str,
        observation_id: str = "",
        payload: dict | None = None,
        checkpoint: bool = True,
    ) -> PendingInterrupt:
        """Record a durable human interrupt.

        AGENTS.md rule 14: interrupts must be durable and resumable. The
        interrupt lives in run state, is announced via an event, and by
        default snapshots a checkpoint so a crash right here loses
        nothing. ``kind`` must be a PendingInterrupt literal.
        """
        interrupt = PendingInterrupt(
            kind=kind,  # type: ignore[arg-type]  # validated by pydantic
            reason=reason,
            raised_at_iteration=run.iteration,
            observation_id=observation_id,
            payload=dict(payload or {}),
        )
        run.pending_interrupt = interrupt
        run.updated_at = utc_now_iso()
        self._emit(
            run, AgentEventType.INTERRUPT_RAISED,
            data={"kind": kind, "reason": reason},
            message=f"Interrupt ({kind}): {reason}",
        )
        if checkpoint:
            self.checkpoint_run(run, reason=f"interrupt:{kind}")
        return interrupt

    def resolve_interrupt(
        self, run: AgentRunState, *, resolution: str,
    ) -> AgentEvent:
        """Clear the active interrupt after a user decision."""
        if run.pending_interrupt is None:
            raise ValueError(
                f"run {run.run_id}: no pending interrupt to resolve"
            )
        kind = run.pending_interrupt.kind
        run.pending_interrupt = None
        run.updated_at = utc_now_iso()
        return self._emit(
            run, AgentEventType.INTERRUPT_RESOLVED,
            data={"kind": kind, "resolution": resolution},
            message=f"Interrupt resolved: {resolution}",
        )

    def raise_human_interrupt(
        self,
        run: AgentRunState,
        *,
        reason: InterruptReason,
        description: str,
        observation_id: str = "",
        world_state_version: int | None = None,
        subgoal_id: str | None = None,
        required_action: str | None = None,
        target_identity: str | None = None,
        semantic_id: str | None = None,
        expires_at: str | None = None,
        metadata: dict | None = None,
        checkpoint: bool = True,
    ) -> HumanInterrupt:
        """Record a durable Phase 8 HumanInterrupt and snapshot checkpoint."""
        from datetime import datetime, timedelta, timezone
        from app.agent.interrupts.models import utc_now_iso

        now = datetime.now(timezone.utc)
        if not expires_at:
            # Default 15 minute lease for human pause
            exp_dt = now + timedelta(minutes=15)
            expires_at = exp_dt.isoformat()

        ws_ver = world_state_version
        if ws_ver is None:
            ws_ver = getattr(run.agent_world_state, "version", 0) if run.agent_world_state else 0

        interrupt = HumanInterrupt(
            run_id=run.run_id,
            reason=reason,
            status=InterruptStatus.WAITING_FOR_USER,
            description=description,
            observation_id=observation_id,
            world_state_version=ws_ver,
            subgoal_id=subgoal_id or run.current_subgoal or None,
            required_action=required_action,
            target_identity=target_identity,
            semantic_id=semantic_id,
            created_at=now.isoformat(),
            expires_at=expires_at,
            metadata=dict(metadata or {}),
        )

        run.human_interrupt = interrupt
        run.updated_at = utc_now_iso()
        self.transition_toward(run, AgentLifecycle.WAITING_FOR_USER)

        self._emit(
            run,
            AgentEventType.INTERRUPT_RAISED,
            data={"reason": reason.value, "description": description, "interrupt_id": interrupt.interrupt_id},
            message=f"Human Interrupt ({reason.value}): {description}",
        )

        if checkpoint:
            cp = self.checkpoint_run(run, reason=f"human_interrupt:{reason.value}")
            interrupt.checkpoint_id = cp.checkpoint_id

        return interrupt

    def approve_interrupt(
        self,
        run: AgentRunState,
        approval: ApprovalBinding,
    ) -> HumanInterrupt:
        """Attach an approval binding to the pending human interrupt."""
        if run.human_interrupt is None:
            raise ValueError(f"run {run.run_id}: no human interrupt to approve")
        if run.human_interrupt.interrupt_id != approval.interrupt_id:
            raise ValueError(
                f"approval interrupt_id {approval.interrupt_id} does not match active {run.human_interrupt.interrupt_id}"
            )

        run.human_interrupt.approval_binding = approval
        run.human_interrupt.status = InterruptStatus.APPROVED
        run.approval_binding = approval
        run.updated_at = utc_now_iso()

        self._emit(
            run,
            AgentEventType.USER_DECISION,
            data={"approval_id": approval.approval_id, "action": approval.requested_action},
            message=f"Human approval granted for {approval.requested_action} on {approval.target_identity}",
        )
        self.checkpoint_run(run, reason="approval_granted")
        return run.human_interrupt

    # ------------------------------------------------------------------
    # Decisions (schema-validated records; the LLM loop arrives Phase 4)
    # ------------------------------------------------------------------

    def record_decision(
        self, run: AgentRunState, decision: AgentDecision,
    ) -> AgentDecision:
        """Validate, stamp and record a decision.

        The decision model's own validators run during construction;
        recording additionally binds it to this run and iteration.
        """
        stamped = decision.model_copy(update={
            "run_id": run.run_id,
            "iteration": run.iteration,
            "decision_id": self._new_id("decision"),
        })
        self._decisions[run.run_id].append(stamped)
        self._emit(
            run, AgentEventType.DECISION_RECORDED,
            data={
                "decision_type": stamped.decision_type.value,
                "decision_id": stamped.decision_id,
                "action_type": (
                    stamped.action.action if stamped.action else None
                ),
            },
            message=f"Decision: {stamped.decision_type.value}",
        )
        if stamped.decision_type == AgentDecisionType.ASK_USER:
            self.raise_interrupt(
                run,
                kind=stamped.interrupt_kind,
                reason=stamped.question,
                checkpoint=True,
            )
        return stamped

    def decisions_for(self, run_id: str) -> list[AgentDecision]:
        return list(self._decisions.get(run_id, []))

    # ------------------------------------------------------------------
    # Usage counters
    # ------------------------------------------------------------------

    def add_usage(
        self,
        run: AgentRunState,
        *,
        llm_calls: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_cost_usd: float = 0.0,
        actions_executed: int = 0,
        observations_made: int = 0,
    ) -> None:
        """Accumulate usage counters (no event per increment; the counts
        are part of state snapshots)."""
        u: UsageCounters = run.usage
        u.llm_calls += llm_calls
        u.prompt_tokens += prompt_tokens
        u.completion_tokens += completion_tokens
        u.total_cost_usd = round(u.total_cost_usd + total_cost_usd, 6)
        u.actions_executed += actions_executed
        u.observations_made += observations_made
        run.updated_at = utc_now_iso()

    # ------------------------------------------------------------------
    # Checkpoints (serialize / restore)
    # ------------------------------------------------------------------

    def checkpoint_run(
        self, run: AgentRunState, *, reason: str = "manual",
    ) -> AgentCheckpoint:
        """Snapshot the run: full state + full event log.

        The CHECKPOINT_CREATED event is emitted BEFORE the snapshot so the
        captured log is self-inclusive: a restored run's history contains
        the record that this checkpoint was taken.
        """
        checkpoint_id = self._new_id("checkpoint")
        self._emit(
            run, AgentEventType.CHECKPOINT_CREATED,
            data={"checkpoint_id": checkpoint_id, "reason": reason},
            message=f"Checkpoint ({reason})",
        )
        ws_ver = getattr(run.agent_world_state, "version", 0) if run.agent_world_state else 0
        checkpoint = AgentCheckpoint(
            checkpoint_id=checkpoint_id,
            run_id=run.run_id,
            created_at=utc_now_iso(),
            expires_at=run.human_interrupt.expires_at if run.human_interrupt else None,
            reason=reason,
            state_version=ws_ver,
            state=run.model_copy(deep=True),
            events=list(self.get_event_log(run.run_id).events),
            human_interrupt=run.human_interrupt.model_copy(deep=True) if run.human_interrupt else None,
            approval_binding=run.approval_binding.model_copy(deep=True) if run.approval_binding else None,
        )
        self._checkpoint_store.save(checkpoint)
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> AgentCheckpoint | None:
        """Fetch a stored checkpoint by ID."""
        return self._checkpoint_store.load(checkpoint_id)

    def restore_checkpoint(self, checkpoint_id: str) -> AgentRunState:
        """Restore a run from a stored checkpoint.

        Replaces the in-memory run state and replays the captured event
        log, emitting RUN_RESTORED as the first new event of the restored
        run. Logical task state is exactly what was captured.
        """
        checkpoint = self._checkpoint_store.load(checkpoint_id)
        if checkpoint is None:
            raise KeyError(f"unknown checkpoint: {checkpoint_id}")
        run = checkpoint.state.model_copy(deep=True)
        log = AgentEventLog(run_id=run.run_id, events=list(checkpoint.events))
        self._runs[run.run_id] = run
        self._event_logs[run.run_id] = log
        self._decisions.setdefault(run.run_id, [])
        self._emit(
            run, AgentEventType.RUN_RESTORED,
            data={"checkpoint_id": checkpoint.checkpoint_id},
            message=f"Run restored from checkpoint {checkpoint.checkpoint_id}",
        )
        # Re-register with any known session (restored run keeps identity)
        for session in self._sessions.values():
            if run.run_id in session.run_ids:
                session.start_run(run.run_id)
                break
        return run

    def restore_checkpoint_from_json(self, raw: str | bytes) -> AgentRunState:
        """Restore from raw JSON (cross-process path). Stores the
        checkpoint first so restore_checkpoint's invariants apply."""
        checkpoint = AgentCheckpoint.from_json(raw)
        self._checkpoint_store.save(checkpoint)
        return self.restore_checkpoint(checkpoint.checkpoint_id)

    def export_run_json(self, run: AgentRunState) -> str:
        """Lossless export of a paused run (state + events) as JSON."""
        return self.checkpoint_run(run, reason="export").to_json()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _emit(
        self,
        run: AgentRunState,
        event_type: AgentEventType,
        *,
        data: dict | None = None,
        message: str = "",
    ) -> AgentEvent:
        # Runs may be constructed outside create_run (e.g. bare state
        # objects driven through the transition table); give them a log
        # on first emit instead of failing the state machine.
        log = self._event_logs.setdefault(
            run.run_id, AgentEventLog(run_id=run.run_id),
        )
        event = log.append(
            event_type,
            run_id=run.run_id,
            iteration=run.iteration,
            data=data,
            message=message,
        )
        logger.debug("run %s event: %s %s", run.run_id, event_type.value, message)
        return event

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _identity_for(
    parent_run_id: str | None, specialist_kind: str | None,
):
    from app.agent.runtime.state import AgentIdentity

    if parent_run_id or specialist_kind:
        return AgentIdentity(
            role="specialist",
            parent_run_id=parent_run_id,
            specialist_kind=specialist_kind,
        )
    return AgentIdentity(role="primary")
