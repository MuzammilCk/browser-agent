"""Persistence protocol for durable agent checkpoints and interrupts — Phase 8.

The AgentRuntime interacts ONLY with this protocol, never directly with SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.agent.interrupts.models import (
        ApprovalBinding,
        HumanInterrupt,
        InterruptStatus,
    )
    from app.agent.runtime.checkpoint import AgentCheckpoint


@runtime_checkable
class CheckpointStore(Protocol):
    """Storage boundary for checkpoints, interrupts, approvals, locks, and audits."""

    async def save_checkpoint(self, checkpoint: AgentCheckpoint) -> None:
        """Persist a complete agent checkpoint transactionally."""
        ...

    async def load_checkpoint(self, checkpoint_id: str) -> AgentCheckpoint | None:
        """Load a checkpoint by ID. Returns None if not found."""
        ...

    async def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None:
        """Load the most recent checkpoint for a given run."""
        ...

    async def list_checkpoints_for_run(self, run_id: str) -> list[str]:
        """List checkpoint IDs for a given run in chronological order."""
        ...

    async def save_interrupt(self, interrupt: HumanInterrupt) -> None:
        """Persist a human interrupt."""
        ...

    async def get_interrupt(self, interrupt_id: str) -> HumanInterrupt | None:
        """Fetch interrupt by ID."""
        ...

    async def get_latest_interrupt_for_run(self, run_id: str) -> HumanInterrupt | None:
        """Fetch the most recent interrupt for a run."""
        ...

    async def update_interrupt_status(
        self,
        interrupt_id: str,
        status: InterruptStatus,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        """Transition interrupt status."""
        ...

    async def save_approval(self, approval: ApprovalBinding) -> None:
        """Persist an approval binding."""
        ...

    async def get_approval_for_interrupt(self, interrupt_id: str) -> ApprovalBinding | None:
        """Fetch approval binding associated with an interrupt."""
        ...

    async def acquire_resume_lock(
        self, run_id: str, worker_id: str, lease_duration_seconds: float = 30.0
    ) -> tuple[bool, int]:
        """Atomically acquire distributed mutual exclusion lease for resuming a run.

        Returns (acquired: bool, fencing_token: int).
        If lock is held and unexpired by another worker, returns (False, 0).
        If lock was expired, safely recovers lease with incremented fencing token.
        """
        ...

    async def release_resume_lock(self, run_id: str, worker_id: str) -> bool:
        """Release the resume lock held by worker_id."""
        ...

    async def expire_records(self, now: datetime | None = None) -> int:
        """Scan and transition expired interrupts and approvals to EXPIRED."""
        ...

    async def record_audit_event(
        self, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Record an immutable HITL audit event."""
        ...

    async def list_pending_interrupts(
        self, run_id: str | None = None
    ) -> list[HumanInterrupt]:
        """List interrupts in WAITING_FOR_USER or PENDING state."""
        ...
