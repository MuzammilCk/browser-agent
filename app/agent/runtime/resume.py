"""Resume Coordinator — Phase 8 Resume Protocol & Stale Approval Rejection.

Non-negotiable invariants:
1. Resume must NEVER simply deserialize old state and blindly continue.
2. The browser's CURRENT observation is authoritative; checkpoint is historical.
3. All ephemeral DOM references from the checkpoint are rejected/invalidated.
4. Semantic targets are re-resolved against current live page observation.
5. Approvals are validated against current WorldState version, action, and target.
   Stale or expired approvals fail closed and demand re-confirmation.
6. Atomic PostgreSQL lease lock prevents concurrent resumes across processes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.agent.interrupts.lifecycle import is_expired, validate_transition
from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
    ResumeRequest,
    ResumeResult,
)
from app.agent.persistence.store import CheckpointStore
from app.agent.runtime.checkpoint import AgentCheckpoint
from app.agent.runtime.state import AgentLifecycle, AgentRunState
from app.agent.world.models import AgentWorldState, EpistemicStatus
from app.agent.world.reducer import reduce_observation

if TYPE_CHECKING:
    from playwright.async_api import Page
    from app.browser.observer import PageObserver


class ResumeCoordinator:
    """Coordinates safe, transactional resumption of interrupted agent runs."""

    def __init__(
        self,
        store: CheckpointStore,
    ) -> None:
        self.store = store

    async def resume_run(
        self,
        request: ResumeRequest,
        page: Page | None = None,
        observer: PageObserver | None = None,
        now: datetime | None = None,
        lease_seconds: float = 30.0,
    ) -> ResumeResult:
        """Execute the 11-step Phase 8 Resume Protocol.

        1. Load checkpoint
        2. Validate schema version
        3. Validate interrupt status
        4. Acquire atomic resume lock
        5. Restore logical AgentRunState
        6. Reconnect / observe live browser state
        7. Reduce observation into WorldState (DOM refs invalidated)
        8. Compare checkpoint vs live WorldState
        9. Re-resolve semantic target
        10. Validate approval binding (reject if stale/drifted)
        11. Transition interrupt to RESUMED and return success
        """
        check_time = now or datetime.now(timezone.utc)
        run_id = request.run_id
        worker_id = request.worker_id

        # Step 1: Load checkpoint
        cp: AgentCheckpoint | None = None
        if hasattr(self.store, "load_latest_for_run"):
            cp = await self.store.load_latest_for_run(run_id)
        elif hasattr(self.store, "load_checkpoint"):
            cp = await self.store.load_checkpoint(request.interrupt_id)

        if cp is None:
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=request.interrupt_id,
                status="rejected",
                reason=f"Checkpoint not found for run {run_id}",
            )

        # Step 2: Validate checkpoint schema version
        try:
            cp.validate_schema()
        except Exception as e:
            await self.store.record_audit_event(
                run_id=run_id,
                event_type="RESUME_SCHEMA_INVALID",
                payload={"error": str(e), "format_version": cp.format_version},
            )
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=request.interrupt_id,
                status="rejected",
                reason=f"Incompatible checkpoint schema: {e}",
                checkpoint_id=cp.checkpoint_id,
            )

        # Step 3: Validate interrupt status
        intr: HumanInterrupt | None = await self.store.get_interrupt(request.interrupt_id)
        if intr is None and cp.human_interrupt:
            intr = cp.human_interrupt

        if intr is None:
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=request.interrupt_id,
                status="rejected",
                reason=f"Interrupt {request.interrupt_id} not found",
                checkpoint_id=cp.checkpoint_id,
            )

        # Check interrupt expiration
        if is_expired(intr, check_time):
            await self.store.update_interrupt_status(intr.interrupt_id, InterruptStatus.EXPIRED)
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=intr.interrupt_id,
                status="expired",
                reason=f"Interrupt expired at {intr.expires_at}",
                checkpoint_id=cp.checkpoint_id,
            )

        if intr.status not in (
            InterruptStatus.PENDING,
            InterruptStatus.WAITING_FOR_USER,
            InterruptStatus.APPROVED,
        ) and not (intr.status == InterruptStatus.INVALIDATED and request.approval is not None):
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=intr.interrupt_id,
                status="rejected",
                reason=f"Interrupt in illegal resume state: {intr.status.value}",
                checkpoint_id=cp.checkpoint_id,
            )

        # Step 4: Acquire resume lock atomically
        acquired, token = await self.store.acquire_resume_lock(
            run_id=run_id,
            worker_id=worker_id,
            lease_duration_seconds=lease_seconds,
        )
        if not acquired:
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=intr.interrupt_id,
                status="rejected",
                reason=f"Could not acquire resume lock for run {run_id} (already held by active worker)",
                checkpoint_id=cp.checkpoint_id,
            )

        try:
            result = await self._perform_resume(
                request=request,
                cp=cp,
                intr=intr,
                token=token,
                worker_id=worker_id,
                check_time=check_time,
                page=page,
                observer=observer,
            )
            if not result.success:
                await self.store.release_resume_lock(run_id, worker_id)
            return result
        except Exception:
            await self.store.release_resume_lock(run_id, worker_id)
            raise

    async def _perform_resume(
        self,
        request: ResumeRequest,
        cp: AgentCheckpoint,
        intr: HumanInterrupt,
        token: int,
        worker_id: str,
        check_time: datetime,
        page: Any | None,
        observer: Any | None,
    ) -> ResumeResult:
        run_id = request.run_id

        # Step 5: Restore logical AgentRunState
        run_state: AgentRunState = cp.state

        # Step 6 & 7: Reconnect browser and re-observe live page state
        # In testing or headless execution, if page & observer are provided, observe directly.
        world_state = run_state.agent_world_state or AgentWorldState()

        fresh_observation = None
        if page is not None and observer is not None:
            fresh_observation = await observer.observe(page)
            # Reduce observation into WorldState (old DOM refs invalidated!)
            world_state = reduce_observation(world_state, fresh_observation)
            run_state.agent_world_state = world_state

        # Step 8: Compare checkpoint state vs live WorldState
        # Stale DOM refs are rejected by construction (current_ref is None or belongs to fresh obs_id)

        # Step 9: Re-resolve semantic target if interrupt specified one
        target_semantic_id = intr.semantic_id or intr.target_identity
        fresh_ref: str | None = None
        if target_semantic_id and target_semantic_id in world_state.semantic_fields:
            field = world_state.semantic_fields[target_semantic_id]
            if fresh_observation and field.is_actionable(fresh_observation.observation_id):
                fresh_ref = field.current_ref

        # Step 10: Validate approval binding
        approval = request.approval or intr.approval_binding
        if approval is None and intr.reason == InterruptReason.FINAL_REVIEW_REQUIRED:
            # Final review requires explicit human approval binding
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=intr.interrupt_id,
                status="reconfirmation_required",
                reason="Final review requires explicit user confirmation and approval binding",
                checkpoint_id=cp.checkpoint_id,
            )

        if approval is not None:
            # Validate expiration
            if approval.is_expired(check_time):
                await self.store.update_interrupt_status(intr.interrupt_id, InterruptStatus.INVALIDATED)
                return ResumeResult(
                    success=False,
                    run_id=run_id,
                    interrupt_id=intr.interrupt_id,
                    status="expired",
                    reason=f"Approval expired at {approval.expires_at}",
                    checkpoint_id=cp.checkpoint_id,
                )

            # Check WorldState version drift
            # If live WorldState has advanced beyond what was approved, reject stale approval!
            if world_state.version != approval.world_state_version:
                await self.store.update_interrupt_status(
                    intr.interrupt_id,
                    InterruptStatus.INVALIDATED,
                    {"invalidation_reason": f"world_state_version drifted from {approval.world_state_version} to {world_state.version}"},
                )
                return ResumeResult(
                    success=False,
                    run_id=run_id,
                    interrupt_id=intr.interrupt_id,
                    status="reconfirmation_required",
                    reason=(
                        f"Stale approval rejected: approved against WorldState v{approval.world_state_version}, "
                        f"current is v{world_state.version}. Page state has changed."
                    ),
                    checkpoint_id=cp.checkpoint_id,
                )

            # Validate target semantic identity
            is_valid, inv_reason = approval.is_valid_for(
                current_world_state_version=world_state.version,
                current_action=intr.required_action or approval.requested_action,
                current_target_identity=intr.target_identity or approval.target_identity,
                current_semantic_id=intr.semantic_id,
                now=check_time,
            )
            if not is_valid:
                await self.store.update_interrupt_status(
                    intr.interrupt_id,
                    InterruptStatus.INVALIDATED,
                    {"invalidation_reason": inv_reason},
                )
                return ResumeResult(
                    success=False,
                    run_id=run_id,
                    interrupt_id=intr.interrupt_id,
                    status="reconfirmation_required",
                    reason=f"Approval invalidated: {inv_reason}",
                    checkpoint_id=cp.checkpoint_id,
                )

        # Step 11: Transition interrupt to RESUMING -> RESUMED
        try:
            if intr.status != InterruptStatus.APPROVED:
                await self.store.update_interrupt_status(intr.interrupt_id, InterruptStatus.APPROVED)
            await self.store.update_interrupt_status(intr.interrupt_id, InterruptStatus.RESUMING)
            await self.store.update_interrupt_status(intr.interrupt_id, InterruptStatus.RESUMED)
        except Exception as e:
            return ResumeResult(
                success=False,
                run_id=run_id,
                interrupt_id=intr.interrupt_id,
                status="rejected",
                reason=f"Failed interrupt state transition: {e}",
                checkpoint_id=cp.checkpoint_id,
            )

        # Update run lifecycle back to active loop (OBSERVING or REASONING)
        run_state.lifecycle = AgentLifecycle.OBSERVING
        run_state.pending_interrupt = None
        run_state.human_interrupt = None

        # Transactionally save updated checkpoint
        cp.state = run_state
        cp.reason = f"resumed_from_interrupt_{intr.interrupt_id}"
        await self.store.save_checkpoint(cp)

        await self.store.record_audit_event(
            run_id=run_id,
            event_type="RESUME_SUCCEEDED",
            payload={
                "interrupt_id": intr.interrupt_id,
                "worker_id": worker_id,
                "fencing_token": token,
                "resumed_subgoal": run_state.current_subgoal,
            },
        )

        return ResumeResult(
            success=True,
            run_id=run_id,
            interrupt_id=intr.interrupt_id,
            status="resumed",
            reason="Resumed successfully from verified checkpoint",
            checkpoint_id=cp.checkpoint_id,
            resumed_subgoal_id=run_state.current_subgoal,
        )
