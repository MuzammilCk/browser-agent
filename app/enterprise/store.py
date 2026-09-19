"""Enterprise persistence protocol — Phase 13.

The gateway, workflow service, and worker interact with durable
enterprise state ONLY through this boundary. Implementations:
  - InMemoryEnterpriseStore  (unit tests, hermetic)
  - PostgresEnterpriseStore  (production; extends the existing Phase 8
    PostgreSQL infrastructure — no second state database)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.enterprise.models import (
    AuditEvent,
    ExecutionQueueItem,
    IdempotencyRecord,
    RunStatus,
    WorkerLease,
    Workflow,
    WorkflowRun,
)


class EnterpriseStore(ABC):
    """Durable state boundary for the enterprise runtime.

    Fencing invariant: worker-side mutations (save_run_with_fencing,
    lease renew/release validation) must fail when the caller's fencing
    token is stale — enforcement lives in the STORE, not in worker
    honesty (Phase 13 invariant 6).
    """

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_workflow(self, workflow: Workflow) -> Workflow: ...

    @abstractmethod
    async def get_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> Workflow | None:
        """Fetch a workflow. When tenant_id is given the lookup is
        tenant-scoped (cross-tenant access returns None — never distinguish
        'missing' from 'not yours' to the caller)."""

    @abstractmethod
    async def save_workflow(self, workflow: Workflow) -> Workflow: ...

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_run(self, run: WorkflowRun) -> WorkflowRun: ...

    @abstractmethod
    async def get_run(
        self, run_id: str, *, tenant_id: str | None = None,
    ) -> WorkflowRun | None: ...

    @abstractmethod
    async def save_run(self, run: WorkflowRun) -> WorkflowRun: ...

    @abstractmethod
    async def save_run_with_fencing(
        self, run: WorkflowRun, fencing_token: int,
    ) -> bool:
        """Persist run state ONLY if fencing_token matches the current
        lease token for run.run_id. Returns False when the worker is
        stale (fail closed)."""

    @abstractmethod
    async def list_runs_for_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> list[WorkflowRun]: ...

    # ------------------------------------------------------------------
    # Queue (durable dispatch; idempotent per run)
    # ------------------------------------------------------------------

    @abstractmethod
    async def enqueue_run(self, run: WorkflowRun) -> ExecutionQueueItem:
        """Idempotently enqueue a run for dispatch (unique per run_id)."""

    @abstractmethod
    async def claim_next_run(
        self, worker_id: str, *, lease_seconds: float,
        tenant_id: str | None = None,
    ) -> tuple[WorkflowRun, WorkerLease, ExecutionQueueItem] | None:
        """Atomically claim the next dispatchable run for this worker:
        queue item → worker lease with monotonic fencing token → run to
        DISPATCHED/RUNNING. When tenant_id is given, only that tenant's
        runs are claimable (tenant-restricted worker). Returns None when
        nothing is available."""

    @abstractmethod
    async def requeue_run(
        self, run_id: str, *, delay_seconds: float = 0.0,
    ) -> None:
        """Return a run to the queue (recovery re-dispatch). Marks the
        item QUEUED again, bumps attempts, dead-letters beyond max."""

    @abstractmethod
    async def dead_letter_run(self, run_id: str, reason: str) -> None: ...

    @abstractmethod
    async def get_queue_item(self, run_id: str) -> ExecutionQueueItem | None: ...

    # ------------------------------------------------------------------
    # Leases (durable ownership with fencing tokens)
    # ------------------------------------------------------------------

    @abstractmethod
    async def acquire_lease(
        self, run_id: str, worker_id: str, lease_seconds: float,
    ) -> WorkerLease | None:
        """Acquire or renew the durable lease for run_id.

        - No lease / expired lease → acquire, token = previous + 1.
        - Held by same worker → renew (token unchanged).
        - Held ACTIVE by another worker → None (mutual exclusion).
        """

    @abstractmethod
    async def renew_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
        lease_seconds: float,
    ) -> WorkerLease | None:
        """Renew ONLY if worker+token still own the lease (fenced).
        Returns None when the lease was lost — worker must fail closed."""

    @abstractmethod
    async def release_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
    ) -> bool: ...

    @abstractmethod
    async def get_lease(self, run_id: str) -> WorkerLease | None: ...

    @abstractmethod
    async def count_active_leases(self) -> int:
        """Worker utilization metric."""

    @abstractmethod
    async def reap_expired_leases(self, now: datetime | None = None) -> int:
        """Mark expired leases EXPIRED, flip owning runs to
        RECOVERY_REQUIRED, and requeue dispatchable runs. Returns the
        number of leases reaped."""

    # ------------------------------------------------------------------
    # Idempotency (durable; invariant 16)
    # ------------------------------------------------------------------

    @abstractmethod
    async def put_idempotency_if_absent(
        self, record: IdempotencyRecord,
    ) -> IdempotencyRecord | None:
        """Insert only if the key is free. Returns None when the key
        already exists (caller replays the stored response)."""

    @abstractmethod
    async def get_idempotency(self, key: str, tenant_id: str) -> IdempotencyRecord | None: ...

    @abstractmethod
    async def update_idempotency_response(
        self, key: str, tenant_id: str, status_code: int,
        response: dict[str, Any],
    ) -> None: ...

    # ------------------------------------------------------------------
    # Audit (append-only; invariant 12)
    # ------------------------------------------------------------------

    @abstractmethod
    async def append_audit(self, event: AuditEvent) -> AuditEvent: ...

    @abstractmethod
    async def list_audit(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]: ...

    @abstractmethod
    async def count_audit(self, *, tenant_id: str | None = None) -> int: ...

    # ------------------------------------------------------------------
    # Cancellation (durable; invariant: cancelled runs never resume)
    # ------------------------------------------------------------------

    @abstractmethod
    async def request_cancellation(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None:
        """Durably mark cancellation. Queued runs cancel immediately;
        running runs flip to CANCELLATION_REQUESTED for the worker to
        observe at a safe boundary. Returns the updated run."""

    @abstractmethod
    async def cancel_queued_run(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None: ...
