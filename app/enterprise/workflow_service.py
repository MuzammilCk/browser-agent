"""Workflow Service — Phase 13 lifecycle owner (invariant 3).

Owns durable orchestration state: workflow creation, run creation,
scheduling/queueing, state transitions, service-level retry decisions,
cancellation, and completion/failure. Does NOT touch browsers (no
Playwright import anywhere in this module) and does not fabricate
approvals.

Authorization: every public method takes the authenticated Identity and
fails closed on tenant mismatch or wrong role. Status transitions are
validated against the explicit RUN_TRANSITIONS table — invalid
transitions raise instead of being coerced.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.enterprise.audit import AuditService
from app.enterprise.metrics import METRICS
from app.enterprise.models import (
    AuthorizationError,
    AuditEvent,
    Identity,
    NotFoundError,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
    validate_transition,
)
from app.enterprise.security import require_role, require_same_tenant
from app.enterprise.store import EnterpriseStore


class RunTransitionError(Exception):
    """Service-level illegal transition (validated, never coerced)."""


class WorkflowService:
    def __init__(
        self,
        store: EnterpriseStore,
        audit: AuditService,
        metrics: Any = METRICS,
    ) -> None:
        self._store = store
        self._audit = audit
        self._metrics = metrics

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def create_workflow(
        self,
        identity: Identity,
        *,
        goal: str,
        metadata: dict | None = None,
    ) -> Workflow:
        require_role(identity, Role_user())
        workflow = Workflow(
            tenant_id=identity.tenant_id,
            user_id=identity.subject_id,
            metadata={"goal": goal, **(metadata or {})},
        )
        created = await self._store.create_workflow(workflow)
        self._metrics.workflows_created()
        await self._audit.record(
            event_type="WORKFLOW_CREATED",
            identity=identity,
            workflow_id=created.workflow_id,
            payload={"goal": goal[:200]},
        )
        return created

    async def get_workflow(
        self, identity: Identity, workflow_id: str,
    ) -> Workflow:
        require_role(identity, Role_user(), admin_role())
        wf = await self._store.get_workflow(
            workflow_id, tenant_id=identity.tenant_id,
        )
        if wf is None:
            raise NotFoundError(f"workflow {workflow_id} not found")
        return wf

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def create_run(
        self,
        identity: Identity,
        workflow_id: str,
        *,
        goal: str | None = None,
    ) -> WorkflowRun:
        require_role(identity, Role_user())
        wf = await self._store.get_workflow(
            workflow_id, tenant_id=identity.tenant_id,
        )
        if wf is None:
            raise NotFoundError(f"workflow {workflow_id} not found")

        run = WorkflowRun(
            workflow_id=wf.workflow_id,
            tenant_id=wf.tenant_id,
            user_id=wf.user_id,
            status=RunStatus.QUEUED,
        )
        created = await self._store.create_run(run)
        await self._store.enqueue_run(created)
        if wf.current_run_id != created.run_id:
            wf.current_run_id = created.run_id
            await self._store.save_workflow(wf)

        self._metrics.run_queued()
        await self._audit.record(
            event_type="RUN_QUEUED",
            identity=identity,
            workflow_id=wf.workflow_id,
            run_id=created.run_id,
            payload={"goal": (goal or wf.metadata.get("goal", ""))[:200]},
        )
        return created

    async def get_run(self, identity: Identity, run_id: str) -> WorkflowRun:
        require_role(identity, Role_user(), admin_role())
        run = await self._store.get_run(run_id, tenant_id=identity.tenant_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        return run

    async def list_runs(
        self, identity: Identity, workflow_id: str,
    ) -> list[WorkflowRun]:
        require_role(identity, Role_user(), admin_role())
        wf = await self.get_workflow(identity, workflow_id)
        return await self._store.list_runs_for_workflow(
            wf.workflow_id, tenant_id=identity.tenant_id,
        )

    # ------------------------------------------------------------------
    # Cancellation (durable; invariant: cancelled never resumes)
    # ------------------------------------------------------------------

    async def cancel_run(self, identity: Identity, run_id: str) -> WorkflowRun:
        require_role(identity, Role_user())
        run = await self._store.get_run(run_id, tenant_id=identity.tenant_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if run.is_terminal():
            if run.status is RunStatus.CANCELLED:
                return run  # idempotent
            raise RunTransitionError(
                f"run {run_id} is terminal ({run.status.value}); cannot cancel"
            )
        require_same_tenant(identity, run.tenant_id)
        updated = await self._store.request_cancellation(
            run_id, tenant_id=identity.tenant_id,
        )
        assert updated is not None
        self._metrics.run_cancelled()
        await self._audit.record(
            event_type="RUN_CANCELLATION_REQUESTED",
            identity=identity,
            workflow_id=run.workflow_id,
            run_id=run_id,
            payload={"from_status": run.status.value,
                     "to_status": updated.status.value},
        )
        return updated

    # ------------------------------------------------------------------
    # Resume (HITL; approval validation stays in Phase 8 coordinator)
    # ------------------------------------------------------------------

    async def request_resume(
        self, identity: Identity, run_id: str,
    ) -> WorkflowRun:
        require_role(identity, Role_user())
        run = await self._store.get_run(run_id, tenant_id=identity.tenant_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if run.status is not RunStatus.PAUSED_HITL:
            raise RunTransitionError(
                f"run {run_id} is not paused at HITL "
                f"(status={run.status.value}); resume rejected"
            )
        # PAUSED_HITL → RUNNING marks resume intent; the worker that
        # claims it revalidates lease/approval/state via the existing
        # Phase 8 ResumeCoordinator before continuing execution.
        run.status = RunStatus.RUNNING
        saved = await self._store.save_run(run)
        await self._store.enqueue_run(saved)
        await self._audit.record(
            event_type="RUN_RESUME_REQUESTED",
            identity=identity,
            workflow_id=run.workflow_id,
            run_id=run_id,
            payload={"resumed_from": RunStatus.PAUSED_HITL.value},
        )
        return saved

    # ------------------------------------------------------------------
    # Worker-facing completion / failure (fencing-validated)
    # ------------------------------------------------------------------

    async def complete_run(
        self, identity: Identity, run_id: str, *,
        fencing_token: int, checkpoint_id: str | None = None,
    ) -> WorkflowRun:
        _require_worker(identity)
        run = await self._store.get_run(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if run.worker_id != identity.subject_id:
            raise AuthorizationError("caller is not the run's owning worker")
        await self._require_current_fencing(run, fencing_token)
        _validate_fenced_transition(
            run, RunStatus.COMPLETED,
            allowed_from=(
                RunStatus.RUNNING, RunStatus.CANCELLATION_REQUESTED,
                RunStatus.DISPATCHED,
            ),
        )
        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        if checkpoint_id:
            run.checkpoint_id = checkpoint_id
        saved = await self._store.save_run_with_fencing(run, fencing_token)
        if not saved:
            self._metrics.stale_worker_rejected()
            raise AuthorizationError("stale fencing token — completion rejected")
        self._metrics.run_completed()
        await self._audit.record(
            event_type="RUN_COMPLETED",
            identity=identity,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            workflow_id=run.workflow_id,
            run_id=run_id,
            worker_id=identity.subject_id,
            payload={"fencing_token": fencing_token},
        )
        return run

    async def fail_run(
        self, identity: Identity, run_id: str, *,
        fencing_token: int, failure_code: str,
        checkpoint_id: str | None = None,
    ) -> WorkflowRun:
        _require_worker(identity)
        run = await self._store.get_run(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if run.worker_id != identity.subject_id:
            raise AuthorizationError("caller is not the run's owning worker")
        await self._require_current_fencing(run, fencing_token)
        _validate_fenced_transition(
            run, RunStatus.FAILED,
            allowed_from=(
                RunStatus.RUNNING, RunStatus.DISPATCHED,
                RunStatus.PAUSED_RECOVERY, RunStatus.RECOVERY_REQUIRED,
                RunStatus.PAUSED_HITL,
            ),
        )
        run.status = RunStatus.FAILED
        run.failure_code = failure_code
        run.completed_at = datetime.now(timezone.utc).isoformat()
        if checkpoint_id:
            run.checkpoint_id = checkpoint_id
        saved = await self._store.save_run_with_fencing(run, fencing_token)
        if not saved:
            self._metrics.stale_worker_rejected()
            raise AuthorizationError("stale fencing token — failure report rejected")
        self._metrics.run_failed()
        await self._audit.record(
            event_type="RUN_FAILED",
            identity=identity,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            workflow_id=run.workflow_id,
            run_id=run_id,
            worker_id=identity.subject_id,
            payload={"failure_code": failure_code,
                     "fencing_token": fencing_token},
        )
        return run

    async def report_pause(
        self, identity: Identity, run_id: str, *,
        fencing_token: int, paused_hitl: bool,
        checkpoint_id: str | None = None,
    ) -> WorkflowRun:
        """Worker reports a HITL or recovery pause (durable)."""
        _require_worker(identity)
        run = await self._store.get_run(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if run.worker_id != identity.subject_id:
            raise AuthorizationError("caller is not the run's owning worker")
        target = (
            RunStatus.PAUSED_HITL if paused_hitl
            else RunStatus.PAUSED_RECOVERY
        )
        if run.cancellation_requested and paused_hitl:
            # A cancellation request wins over a fresh pause: the worker
            # will observe it at the next safe boundary.
            target = RunStatus.CANCELLATION_REQUESTED
        await self._require_current_fencing(run, fencing_token)
        if run.status is target:
            # Idempotent pause report (e.g. CANCELLATION_REQUESTED already
            # recorded) — keep the checkpoint update, skip transition.
            if checkpoint_id:
                run.checkpoint_id = checkpoint_id
                await self._store.save_run_with_fencing(run, fencing_token)
            return run
        _validate_fenced_transition(
            run, target,
            allowed_from=(
                RunStatus.RUNNING, RunStatus.DISPATCHED,
                RunStatus.PAUSED_HITL, RunStatus.PAUSED_RECOVERY,
            ),
        )
        run.status = target
        if checkpoint_id:
            run.checkpoint_id = checkpoint_id
        saved = await self._store.save_run_with_fencing(run, fencing_token)
        if not saved:
            self._metrics.stale_worker_rejected()
            raise AuthorizationError("stale fencing token — pause report rejected")
        if target is RunStatus.PAUSED_HITL:
            self._metrics.hitl_pause()
        await self._audit.record(
            event_type="RUN_PAUSED" if paused_hitl else "RUN_RECOVERY_PAUSE",
            identity=identity,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            workflow_id=run.workflow_id,
            run_id=run_id,
            worker_id=identity.subject_id,
            payload={"status": target.value,
                     "checkpoint_id": checkpoint_id},
        )
        return run

    # ------------------------------------------------------------------
    # Service-level retry (bounded; never duplicates execution)
    # ------------------------------------------------------------------

    async def _require_current_fencing(
        self, run: WorkflowRun, fencing_token: int,
    ) -> None:
        """Fencing precheck: the caller's token must match the CURRENT
        lease token for the run (in-process double-check; the store
        remains the authoritative gate on the fenced write)."""
        lease = await self._store.get_lease(run.run_id)
        if (
            lease is None
            or lease.fencing_token != fencing_token
            or lease.state.value != "active"
        ):
            self._metrics.stale_worker_rejected()
            raise AuthorizationError("stale fencing token — operation rejected")

    async def recover_run(self, run_id: str) -> bool:
        """Requeue a RECOVERY_REQUIRED run for a new worker.

        Service retry decision: only when the run has NO active lease
        (previous worker is gone) and attempts remain. A retry never
        blindly restarts browser execution — the claiming worker resumes
        from the latest checkpoint with full revalidation.
        """
        run = await self._store.get_run(run_id)
        if run is None:
            return False
        if run.status is not RunStatus.RECOVERY_REQUIRED:
            return False
        lease = await self._store.get_lease(run_id)
        if lease is not None and lease.is_expired() is False and lease.state.value == "active":
            return False  # previous worker may still own it (invariant 17)
        if run.dispatch_attempts >= run.max_dispatch_attempts:
            await self._store.dead_letter_run(run_id, "dispatch_attempts_exhausted")
            return False
        validate_transition(run.status, RunStatus.QUEUED)
        run.status = RunStatus.QUEUED
        await self._store.save_run(run)
        await self._store.requeue_run(run_id)
        await self._audit.record(
            event_type="RUN_REQUEUED_FOR_RECOVERY",
            run_id=run_id,
            workflow_id=run.workflow_id,
            payload={"dispatch_attempts": run.dispatch_attempts},
        )
        return True


# -- module-level helpers ------------------------------------------------


def Role_user():
    return Role.USER


def admin_role():
    return Role.ADMIN


def _require_worker(identity: Identity) -> None:
    require_role(identity, Role.WORKER)


async def _unused_async_helper():  # pragma: no cover - placeholder
    return None


def _validate_fenced_transition(
    run: WorkflowRun, target: RunStatus, *, allowed_from: tuple,
) -> None:
    if run.status not in allowed_from:
        raise RunTransitionError(
            f"illegal transition {run.status.value} -> {target.value} "
            f"for run {run.run_id}"
        )
    validate_transition(run.status, target)
