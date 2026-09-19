"""In-memory implementation of CheckpointStore for unit testing — Phase 8.

Faithfully implements the CheckpointStore protocol including lease-based concurrency locking,
fencing tokens, transactional update emulation, expiration, and audit logging.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.interrupts.lifecycle import is_expired, validate_transition
from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptStatus,
    utc_now_iso,
)
from app.agent.runtime.checkpoint import AgentCheckpoint


class InMemoryCheckpointStore:
    """In-memory CheckpointStore implementation."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, AgentCheckpoint] = {}
        self._interrupts: dict[str, HumanInterrupt] = {}
        self._approvals: dict[str, ApprovalBinding] = {}
        # run_id -> (worker_id, expires_at: datetime, fencing_token: int)
        self._locks: dict[str, tuple[str, datetime, int]] = {}
        self._audit_events: list[dict[str, Any]] = []

    def save(self, checkpoint: AgentCheckpoint) -> None:
        """Synchronous save for runtime."""
        cloned = AgentCheckpoint.from_json(checkpoint.to_json())
        self._checkpoints[checkpoint.checkpoint_id] = cloned
        if cloned.human_interrupt:
            self._interrupts[cloned.human_interrupt.interrupt_id] = cloned.human_interrupt.model_copy(deep=True)

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None:
        """Synchronous load for runtime."""
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            return None
        return AgentCheckpoint.from_json(cp.to_json())

    def list_for_run(self, run_id: str) -> list[str]:
        """Synchronous list for runtime."""
        cps = [cp for cp in self._checkpoints.values() if cp.run_id == run_id]
        cps.sort(key=lambda c: c.created_at)
        return [c.checkpoint_id for c in cps]

    async def save_checkpoint(self, checkpoint: AgentCheckpoint) -> None:
        # Deep copy via model serialization to ensure crash-safe / memory isolation
        cloned = AgentCheckpoint.from_json(checkpoint.to_json())
        self._checkpoints[checkpoint.checkpoint_id] = cloned

        # Also store pending interrupt if attached
        if cloned.human_interrupt:
            await self.save_interrupt(cloned.human_interrupt)

        await self.record_audit_event(
            run_id=checkpoint.run_id,
            event_type="CHECKPOINT_CREATED",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "reason": checkpoint.reason,
                "format_version": checkpoint.format_version,
                "state_version": getattr(checkpoint, "state_version", 0),
            },
        )

    async def load_checkpoint(self, checkpoint_id: str) -> AgentCheckpoint | None:
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            return None
        return AgentCheckpoint.from_json(cp.to_json())

    async def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None:
        latest: AgentCheckpoint | None = None
        for cp in self._checkpoints.values():
            if cp.run_id == run_id:
                if latest is None or cp.created_at > latest.created_at:
                    latest = cp
        if latest is None:
            return None
        return AgentCheckpoint.from_json(latest.to_json())

    async def list_checkpoints_for_run(self, run_id: str) -> list[str]:
        cps = [
            cp for cp in self._checkpoints.values() if cp.run_id == run_id
        ]
        cps.sort(key=lambda c: c.created_at)
        return [c.checkpoint_id for c in cps]

    async def save_interrupt(self, interrupt: HumanInterrupt) -> None:
        cloned = HumanInterrupt.model_validate(interrupt.model_dump())
        self._interrupts[interrupt.interrupt_id] = cloned
        await self.record_audit_event(
            run_id=interrupt.run_id,
            event_type="INTERRUPT_CREATED",
            payload={
                "interrupt_id": interrupt.interrupt_id,
                "reason": interrupt.reason.value,
                "status": interrupt.status.value,
                "observation_id": interrupt.observation_id,
                "world_state_version": interrupt.world_state_version,
            },
        )

    async def get_interrupt(self, interrupt_id: str) -> HumanInterrupt | None:
        intr = self._interrupts.get(interrupt_id)
        if intr is None:
            return None
        return HumanInterrupt.model_validate(intr.model_dump())

    async def get_latest_interrupt_for_run(self, run_id: str) -> HumanInterrupt | None:
        latest: HumanInterrupt | None = None
        for intr in self._interrupts.values():
            if intr.run_id == run_id:
                if latest is None or intr.created_at > latest.created_at:
                    latest = intr
        if latest is None:
            return None
        return HumanInterrupt.model_validate(latest.model_dump())

    async def update_interrupt_status(
        self,
        interrupt_id: str,
        status: InterruptStatus,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        intr = self._interrupts.get(interrupt_id)
        if not intr:
            raise KeyError(f"Interrupt {interrupt_id} not found")

        validate_transition(intr.status, status)
        intr.status = status
        if metadata_update:
            intr.metadata.update(metadata_update)

        await self.record_audit_event(
            run_id=intr.run_id,
            event_type=f"INTERRUPT_{status.value.upper()}",
            payload={
                "interrupt_id": interrupt_id,
                "status": status.value,
                "metadata": metadata_update or {},
            },
        )

    async def save_approval(self, approval: ApprovalBinding) -> None:
        cloned = ApprovalBinding.model_validate(approval.model_dump())
        self._approvals[approval.interrupt_id] = cloned

        # Also update interrupt status to APPROVED if valid
        intr = self._interrupts.get(approval.interrupt_id)
        if intr and intr.status in (InterruptStatus.PENDING, InterruptStatus.WAITING_FOR_USER, InterruptStatus.INVALIDATED):
            intr.status = InterruptStatus.APPROVED
            intr.approval_binding = cloned

        await self.record_audit_event(
            run_id=approval.run_id,
            event_type="APPROVAL_GRANTED",
            payload={
                "approval_id": approval.approval_id,
                "interrupt_id": approval.interrupt_id,
                "requested_action": approval.requested_action,
                "target_identity": approval.target_identity,
                "world_state_version": approval.world_state_version,
                "expires_at": approval.expires_at,
            },
        )

    async def get_approval_for_interrupt(self, interrupt_id: str) -> ApprovalBinding | None:
        appr = self._approvals.get(interrupt_id)
        if appr is None:
            return None
        return ApprovalBinding.model_validate(appr.model_dump())

    async def acquire_resume_lock(
        self, run_id: str, worker_id: str, lease_duration_seconds: float = 30.0
    ) -> tuple[bool, int]:
        now = datetime.now(timezone.utc)
        current_lock = self._locks.get(run_id)

        if current_lock is not None:
            holder, expires_at, fencing_token = current_lock
            if expires_at > now:
                # Lock is active and held
                if holder == worker_id:
                    # Same worker renewing lease
                    new_exp = now + timedelta(seconds=lease_duration_seconds)
                    self._locks[run_id] = (worker_id, new_exp, fencing_token)
                    return True, fencing_token
                # Different worker trying to acquire active lease -> conflict
                await self.record_audit_event(
                    run_id=run_id,
                    event_type="RESUME_LOCK_CONFLICT",
                    payload={"requested_by": worker_id, "held_by": holder},
                )
                return False, 0
            else:
                # Stale/expired lease -> recover safely with incremented token
                new_token = fencing_token + 1
                new_exp = now + timedelta(seconds=lease_duration_seconds)
                self._locks[run_id] = (worker_id, new_exp, new_token)
                await self.record_audit_event(
                    run_id=run_id,
                    event_type="RESUME_LOCK_RECOVERED",
                    payload={"recovered_by": worker_id, "previous_holder": holder, "token": new_token},
                )
                return True, new_token

        # Free lock -> acquire with token 1
        new_exp = now + timedelta(seconds=lease_duration_seconds)
        self._locks[run_id] = (worker_id, new_exp, 1)
        await self.record_audit_event(
            run_id=run_id,
            event_type="RESUME_LOCK_ACQUIRED",
            payload={"worker_id": worker_id, "token": 1},
        )
        return True, 1

    async def release_resume_lock(self, run_id: str, worker_id: str) -> bool:
        current_lock = self._locks.get(run_id)
        if current_lock and current_lock[0] == worker_id:
            del self._locks[run_id]
            await self.record_audit_event(
                run_id=run_id,
                event_type="RESUME_LOCK_RELEASED",
                payload={"worker_id": worker_id},
            )
            return True
        return False

    async def expire_records(self, now: datetime | None = None) -> int:
        check_time = now or datetime.now(timezone.utc)
        count = 0
        for intr in self._interrupts.values():
            if intr.status not in (
                InterruptStatus.EXPIRED,
                InterruptStatus.RESUMED,
                InterruptStatus.REJECTED,
                InterruptStatus.CANCELLED,
            ):
                if is_expired(intr, check_time):
                    intr.status = InterruptStatus.EXPIRED
                    count += 1
                    await self.record_audit_event(
                        run_id=intr.run_id,
                        event_type="INTERRUPT_EXPIRED",
                        payload={"interrupt_id": intr.interrupt_id},
                    )
        return count

    async def record_audit_event(
        self, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        # Strip potential secrets defensively
        safe_payload = {
            k: v for k, v in payload.items()
            if not any(secret in k.lower() for secret in ("password", "secret", "otp", "pin", "credential"))
        }
        self._audit_events.append({
            "run_id": run_id,
            "event_type": event_type,
            "payload": safe_payload,
            "timestamp": utc_now_iso(),
        })

    async def list_pending_interrupts(
        self, run_id: str | None = None
    ) -> list[HumanInterrupt]:
        results = [
            HumanInterrupt.model_validate(intr.model_dump())
            for intr in self._interrupts.values()
            if (run_id is None or intr.run_id == run_id)
            and intr.status in (InterruptStatus.PENDING, InterruptStatus.WAITING_FOR_USER)
        ]
        results.sort(key=lambda x: x.created_at)
        return results

    def get_audit_events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            return list(self._audit_events)
        return [e for e in self._audit_events if e["run_id"] == run_id]
