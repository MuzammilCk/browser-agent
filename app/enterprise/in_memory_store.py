"""In-memory EnterpriseStore — Phase 13.

Semantically faithful to the PostgreSQL implementation (mutual exclusion,
monotonic fencing tokens, claim-time visibility timeout, idempotent
enqueue, append-only audit, durable idempotency records) so unit tests
exercise the same contracts without a database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.enterprise.models import (
    AuditEvent,
    ExecutionQueueItem,
    IdempotencyRecord,
    LeaseState,
    QueueItemState,
    RunStatus,
    WorkerLease,
    Workflow,
    WorkflowRun,
    new_id,
    utc_now_iso,
)
from app.enterprise.store import EnterpriseStore


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class InMemoryEnterpriseStore(EnterpriseStore):
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._workflows: dict[str, Workflow] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._leases: dict[str, WorkerLease] = {}
        self._queue: dict[str, ExecutionQueueItem] = {}   # run_id -> item
        self._idempotency: dict[tuple[str, str], IdempotencyRecord] = {}
        self._audit: list[AuditEvent] = []

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def create_workflow(self, workflow: Workflow) -> Workflow:
        if workflow.workflow_id in self._workflows:
            raise ValueError(f"workflow exists: {workflow.workflow_id}")
        self._workflows[workflow.workflow_id] = workflow.model_copy(deep=True)
        return workflow

    async def get_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> Workflow | None:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return None
        if tenant_id is not None and wf.tenant_id != tenant_id:
            return None
        return wf.model_copy(deep=True)

    async def save_workflow(self, workflow: Workflow) -> Workflow:
        workflow.updated_at = utc_now_iso()
        workflow.version += 1
        self._workflows[workflow.workflow_id] = workflow.model_copy(deep=True)
        return workflow

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        if run.run_id in self._runs:
            raise ValueError(f"run exists: {run.run_id}")
        self._runs[run.run_id] = run.model_copy(deep=True)
        return run

    async def get_run(
        self, run_id: str, *, tenant_id: str | None = None,
    ) -> WorkflowRun | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        if tenant_id is not None and run.tenant_id != tenant_id:
            return None
        return run.model_copy(deep=True)

    async def save_run(self, run: WorkflowRun) -> WorkflowRun:
        run.updated_at = utc_now_iso()
        run.version += 1
        self._runs[run.run_id] = run.model_copy(deep=True)
        return run

    async def save_run_with_fencing(
        self, run: WorkflowRun, fencing_token: int,
    ) -> bool:
        lease = self._leases.get(run.run_id)
        if (
            lease is None
            or lease.state is not LeaseState.ACTIVE
            or lease.fencing_token != fencing_token
            or lease.worker_id != run.worker_id
        ):
            return False  # stale worker — fail closed
        await self.save_run(run)
        return True

    async def list_runs_for_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> list[WorkflowRun]:
        runs = [
            r for r in self._runs.values()
            if r.workflow_id == workflow_id
            and (tenant_id is None or r.tenant_id == tenant_id)
        ]
        return [r.model_copy(deep=True) for r in runs]

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    async def enqueue_run(self, run: WorkflowRun) -> ExecutionQueueItem:
        if run.run_id in self._queue:
            item = self._queue[run.run_id]
            if item.state is QueueItemState.QUEUED:
                return item  # idempotent
            item.state = QueueItemState.QUEUED
            item.available_at = utc_now_iso()
            item.claimed_by = None
            item.claim_expires_at = None
            return item
        item = ExecutionQueueItem(
            run_id=run.run_id,
            workflow_id=run.workflow_id,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            payload={
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "agent_run_id": run.agent_run_id,
                # References only — never secrets/handles/checkpoints.
            },
        )
        self._queue[run.run_id] = item
        return item

    async def claim_next_run(
        self, worker_id: str, *, lease_seconds: float,
        tenant_id: str | None = None,
    ) -> tuple[WorkflowRun, WorkerLease, ExecutionQueueItem] | None:
        async with self._lock:
            now = datetime.now(timezone.utc)
            # Dispatchable: QUEUED and available, or CLAIMED with an
            # expired visibility timeout (crashed claimant).
            candidates: list[ExecutionQueueItem] = []
            for item in self._queue.values():
                if item.state is QueueItemState.DEAD:
                    continue
                if tenant_id is not None and item.tenant_id != tenant_id:
                    continue
                if _parse(item.available_at) > now:
                    continue
                if item.state is QueueItemState.CLAIMED:
                    if (
                        item.claim_expires_at
                        and _parse(item.claim_expires_at) > now
                    ):
                        continue  # actively claimed
                candidates.append(item)
            candidates.sort(key=lambda i: i.created_at)
            for item in candidates:
                lease = await self.acquire_lease(
                    item.run_id, worker_id, lease_seconds,
                )
                if lease is None:
                    continue  # another worker owns the run
                run = self._runs.get(item.run_id)
                if run is None or run.is_terminal():
                    await self.release_lease(
                        item.run_id, worker_id, lease.fencing_token,
                    )
                    continue
                item.state = QueueItemState.CLAIMED
                item.claimed_by = worker_id
                item.claim_expires_at = (
                    (now + timedelta(seconds=lease_seconds)).isoformat()
                )
                item.attempts += 1
                run.worker_id = worker_id
                run.lease_id = lease.lease_id
                run.fencing_token = lease.fencing_token
                run.dispatch_attempts = item.attempts
                if run.status is RunStatus.QUEUED:
                    run.status = RunStatus.DISPATCHED
                    run.started_at = utc_now_iso()
                await self.save_run(run)
                return (
                    run.model_copy(deep=True),
                    lease.model_copy(deep=True),
                    item.model_copy(deep=True),
                )
            return None

    async def requeue_run(
        self, run_id: str, *, delay_seconds: float = 0.0,
    ) -> None:
        item = self._queue.get(run_id)
        if item is None:
            return
        if item.attempts >= item.max_attempts:
            item.state = QueueItemState.DEAD
            return
        item.state = QueueItemState.QUEUED
        item.available_at = (
            datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        ).isoformat()
        item.claimed_by = None
        item.claim_expires_at = None

    async def dead_letter_run(self, run_id: str, reason: str) -> None:
        item = self._queue.get(run_id)
        if item is not None:
            item.state = QueueItemState.DEAD
            item.payload["dead_letter_reason"] = reason

    async def get_queue_item(self, run_id: str) -> ExecutionQueueItem | None:
        item = self._queue.get(run_id)
        return item.model_copy(deep=True) if item else None

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    async def acquire_lease(
        self, run_id: str, worker_id: str, lease_seconds: float,
    ) -> WorkerLease | None:
        now = datetime.now(timezone.utc)
        existing = self._leases.get(run_id)
        if (
            existing is not None
            and existing.state is LeaseState.ACTIVE
            and not existing.is_expired(now)
        ):
            if existing.worker_id == worker_id:
                # Same worker re-claiming: extend, token unchanged.
                existing.expires_at = (
                    now + timedelta(seconds=lease_seconds)
                ).isoformat()
                existing.renewed_at = utc_now_iso()
                return existing
            return None  # active foreign lease — mutual exclusion
        # New lease or takeover of an expired/released one: token + 1.
        token = (existing.fencing_token + 1) if existing else 1
        lease = WorkerLease(
            run_id=run_id,
            worker_id=worker_id,
            fencing_token=token,
            acquired_at=utc_now_iso(),
            expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
            renewed_at=utc_now_iso(),
            state=LeaseState.ACTIVE,
        )
        self._leases[run_id] = lease
        return lease

    async def renew_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
        lease_seconds: float,
    ) -> WorkerLease | None:
        lease = self._leases.get(run_id)
        if (
            lease is None
            or lease.state is not LeaseState.ACTIVE
            or lease.worker_id != worker_id
            or lease.fencing_token != fencing_token
            or lease.is_expired()
        ):
            return None  # lease lost — caller must fail closed
        lease.expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        lease.renewed_at = utc_now_iso()
        return lease

    async def release_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
    ) -> bool:
        lease = self._leases.get(run_id)
        if (
            lease is None
            or lease.worker_id != worker_id
            or lease.fencing_token != fencing_token
        ):
            return False
        lease.state = LeaseState.RELEASED
        return True

    async def get_lease(self, run_id: str) -> WorkerLease | None:
        lease = self._leases.get(run_id)
        return lease.model_copy(deep=True) if lease else None

    async def count_active_leases(self) -> int:
        now = datetime.now(timezone.utc)
        return sum(
            1 for l in self._leases.values()
            if l.state is LeaseState.ACTIVE and not l.is_expired(now)
        )

    async def reap_expired_leases(
        self, now: datetime | None = None,
    ) -> int:
        now = now or datetime.now(timezone.utc)
        reaped = 0
        for lease in self._leases.values():
            if (
                lease.state is LeaseState.ACTIVE
                and lease.is_expired(now)
            ):
                lease.state = LeaseState.EXPIRED
                reaped += 1
                run = self._runs.get(lease.run_id)
                if run is not None and not run.is_terminal():
                    from app.enterprise.models import validate_transition
                    target = RunStatus.RECOVERY_REQUIRED
                    if run.status is not target:
                        validate_transition(run.status, target)
                        run.status = target
                        await self.save_run(run)
                    await self.requeue_run(lease.run_id)
        return reaped

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def put_idempotency_if_absent(
        self, record: IdempotencyRecord,
    ) -> IdempotencyRecord | None:
        k = (record.tenant_id, record.key)
        if k in self._idempotency:
            return None
        self._idempotency[k] = record.model_copy(deep=True)
        return record

    async def get_idempotency(
        self, key: str, tenant_id: str,
    ) -> IdempotencyRecord | None:
        rec = self._idempotency.get((tenant_id, key))
        return rec.model_copy(deep=True) if rec else None

    async def update_idempotency_response(
        self, key: str, tenant_id: str, status_code: int,
        response: dict[str, Any],
    ) -> None:
        rec = self._idempotency.get((tenant_id, key))
        if rec is not None:
            rec.status_code = status_code
            rec.response = dict(response)

    # ------------------------------------------------------------------
    # Audit (append-only)
    # ------------------------------------------------------------------

    async def append_audit(self, event: AuditEvent) -> AuditEvent:
        self._audit.append(event.model_copy(deep=True))
        return event

    async def list_audit(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        out = [
            e for e in self._audit
            if e.tenant_id == tenant_id
            and (workflow_id is None or e.workflow_id == workflow_id)
            and (run_id is None or e.run_id == run_id)
        ]
        return out[-limit:]

    async def count_audit(self, *, tenant_id: str | None = None) -> int:
        if tenant_id is None:
            return len(self._audit)
        return sum(1 for e in self._audit if e.tenant_id == tenant_id)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def request_cancellation(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None:
        run = self._runs.get(run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        if run.is_terminal():
            return run
        from app.enterprise.models import validate_transition
        if run.status is RunStatus.QUEUED:
            run.status = RunStatus.CANCELLED
            run.cancellation_requested = True
            run.completed_at = utc_now_iso()
        elif run.status in (
            RunStatus.RUNNING,
            RunStatus.DISPATCHED,
            RunStatus.PAUSED_HITL,
            RunStatus.PAUSED_RECOVERY,
        ):
            run.cancellation_requested = True
            if run.status is not RunStatus.CANCELLATION_REQUESTED:
                validate_transition(run.status, RunStatus.CANCELLATION_REQUESTED)
                run.status = RunStatus.CANCELLATION_REQUESTED
        else:
            # CANCELLATION_REQUESTED / RECOVERY_REQUIRED: just flag.
            run.cancellation_requested = True
        await self.save_run(run)
        return run

    async def cancel_queued_run(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None:
        return await self.request_cancellation(run_id, tenant_id=tenant_id)
