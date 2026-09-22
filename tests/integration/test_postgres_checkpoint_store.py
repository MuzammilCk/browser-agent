"""Integration tests for PostgresCheckpointStore — Phase 8 Part B & Part D.

Tests real PostgreSQL persistence, transactions, atomic concurrency locking with
fencing tokens, crash recovery, and audit trails against the live PostgreSQL server.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.interrupts.lifecycle import InvalidInterruptTransition
from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
)
from app.agent.persistence.postgres_store import PostgresCheckpointStore
from app.agent.runtime.checkpoint import AgentCheckpoint
from app.agent.runtime.events import AgentEvent, AgentEventType
from app.agent.runtime.state import AgentLifecycle, AgentRunState
from app.agent.world.models import AgentWorldState, EpistemicStatus, SemanticField

import os
from app.config.settings import Settings

POSTGRES_TEST_DSN = (
    os.getenv("POSTGRES_TEST_DSN")
    or os.getenv("POSTGRES_URL")
    or Settings().postgres_url
)


@pytest.fixture
async def pg_store():
    store = PostgresCheckpointStore(POSTGRES_TEST_DSN)
    await store.connect()
    yield store
    await store.close()


class TestPostgresPersistencePartB:
    """Part B tests: Real PostgreSQL checkpoint & interrupt persistence (Tests 8–14)."""

    @pytest.mark.asyncio
    async def test_checkpoint_persisted_and_loaded_from_postgres(self, pg_store):
        """8–14: Checkpoint, RunState, WorldState, Plan/Subgoal, Interrupt, and Approval preserved."""
        run_id = f"run_pg_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=15)

        # 1. Build complex world state with semantic fields and verified facts
        ws = AgentWorldState(
            version=42,
            portal="https://citizen.gov.in",
            current_observation_id="obs_initial_1",
        )
        ws.semantic_fields["field:applicant_name"] = SemanticField(
            semantic_id="field:applicant_name",
            label="Applicant Full Name",
            value="Asha Kumar",
            verified_value="Asha Kumar",
            status=EpistemicStatus.VERIFIED,
            current_ref="e1",
            current_observation_id="obs_initial_1",
        )
        ws.verified_values["field:applicant_name"] = "Asha Kumar"

        # 2. Build HumanInterrupt and ApprovalBinding
        intr_id = f"int_{uuid.uuid4().hex[:8]}"
        approval = ApprovalBinding(
            run_id=run_id,
            interrupt_id=intr_id,
            requested_action="confirm_step",
            target_identity="button:confirm",
            semantic_id=None,
            world_state_version=42,
            observation_id="obs_initial_1",
            created_at=now.isoformat(),
            expires_at=exp.isoformat(),
            approved_by="citizen_user",
        )

        intr = HumanInterrupt(
            interrupt_id=intr_id,
            run_id=run_id,
            reason=InterruptReason.OTP_REQUIRED,
            status=InterruptStatus.APPROVED,
            description="OTP verification required",
            observation_id="obs_initial_1",
            world_state_version=42,
            subgoal_id="sg_otp_verify",
            required_action="confirm_step",
            target_identity="button:confirm",
            created_at=now.isoformat(),
            expires_at=exp.isoformat(),
            approval_binding=approval,
        )

        # 3. Build AgentRunState
        run_state = AgentRunState(
            run_id=run_id,
            goal="Apply for income certificate",
            current_subgoal="sg_otp_verify",
            plan=[
                {"id": "sg_details", "title": "Fill details", "status": "completed"},
                {"id": "sg_otp_verify", "title": "Verify OTP", "status": "active"},
            ],
            lifecycle=AgentLifecycle.WAITING_FOR_USER,
            iteration=3,
            agent_world_state=ws,
            human_interrupt=intr,
            approval_binding=approval,
        )

        # 4. Build Checkpoint with events
        cp_id = f"cp_{uuid.uuid4().hex[:8]}"
        event = AgentEvent(
            sequence=1,
            event_type=AgentEventType.INTERRUPT_RAISED,
            run_id=run_id,
            timestamp=now.isoformat(),
            iteration=3,
            data={"reason": "otp_required"},
        )

        checkpoint = AgentCheckpoint(
            checkpoint_id=cp_id,
            run_id=run_id,
            format_version=2,
            created_at=now.isoformat(),
            reason="otp_pause",
            state_version=42,
            state=run_state,
            events=[event],
            human_interrupt=intr,
            approval_binding=approval,
        )

        # 5. Persist to PostgreSQL
        await pg_store.save_checkpoint(checkpoint)
        await pg_store.save_interrupt(intr)
        await pg_store.save_approval(approval)

        # 6. Simulate fresh process: load from database
        loaded_cp = await pg_store.load_checkpoint(cp_id)
        assert loaded_cp is not None
        assert loaded_cp.checkpoint_id == cp_id
        assert loaded_cp.run_id == run_id
        assert loaded_cp.format_version == 2
        assert loaded_cp.state_version == 42

        # Verify AgentRunState preserved
        restored_state = loaded_cp.state
        assert restored_state.run_id == run_id
        assert restored_state.goal == "Apply for income certificate"
        assert restored_state.current_subgoal == "sg_otp_verify"
        assert restored_state.iteration == 3
        assert len(restored_state.plan) == 2

        # Verify AgentWorldState preserved
        restored_ws = restored_state.agent_world_state
        assert restored_ws is not None
        assert restored_ws.version == 42
        assert restored_ws.verified_values["field:applicant_name"] == "Asha Kumar"
        name_field = restored_ws.semantic_fields.get("field:applicant_name")
        assert name_field is not None
        assert name_field.status == EpistemicStatus.VERIFIED
        assert name_field.verified_value == "Asha Kumar"

        # Verify interrupt and approval preserved in PostgreSQL
        loaded_intr = await pg_store.get_interrupt(intr_id)
        assert loaded_intr is not None
        assert loaded_intr.interrupt_id == intr_id
        assert loaded_intr.reason == InterruptReason.OTP_REQUIRED
        assert loaded_intr.status == InterruptStatus.APPROVED
        assert loaded_intr.approval_binding is not None
        assert loaded_intr.approval_binding.approved_by == "citizen_user"

        # Verify load_latest_for_run
        latest_cp = await pg_store.load_latest_for_run(run_id)
        assert latest_cp is not None
        assert latest_cp.checkpoint_id == cp_id

        # Verify list_checkpoints_for_run
        cp_list = await pg_store.list_checkpoints_for_run(run_id)
        assert cp_id in cp_list


class TestPostgresConcurrencyPartD:
    """Part D tests: PostgreSQL Concurrency, Lease Locking & Crash Recovery (Tests 27–30)."""

    @pytest.mark.asyncio
    async def test_concurrent_resume_mutual_exclusion(self, pg_store):
        """27 & 28: Two resume attempts cannot both acquire run lock; second fails deterministically."""
        run_id = f"run_lock_{uuid.uuid4().hex[:8]}"

        # Seed run in DB
        intr = HumanInterrupt(
            run_id=run_id,
            reason=InterruptReason.OTP_REQUIRED,
            description="test lock",
            observation_id="obs_1",
            world_state_version=1,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        await pg_store.save_interrupt(intr)

        # Worker A attempts acquisition
        acquired_a, token_a = await pg_store.acquire_resume_lock(
            run_id=run_id,
            worker_id="worker_A",
            lease_duration_seconds=30.0,
        )
        assert acquired_a is True
        assert token_a == 1

        # Worker B attempts acquisition on same run concurrently -> MUST FAIL
        acquired_b, token_b = await pg_store.acquire_resume_lock(
            run_id=run_id,
            worker_id="worker_B",
            lease_duration_seconds=30.0,
        )
        assert acquired_b is False
        assert token_b == 0

        # Worker A releases lock
        released = await pg_store.release_resume_lock(run_id=run_id, worker_id="worker_A")
        assert released is True

        # Worker B can now acquire
        acquired_b2, token_b2 = await pg_store.acquire_resume_lock(
            run_id=run_id,
            worker_id="worker_B",
            lease_duration_seconds=30.0,
        )
        assert acquired_b2 is True
        assert token_b2 >= 1

    @pytest.mark.asyncio
    async def test_crashed_worker_lease_expiration_and_recovery(self, pg_store):
        """29 & 30: Expired/stale lock recovered safely; crashed worker does not permanently block run."""
        run_id = f"run_crash_{uuid.uuid4().hex[:8]}"

        intr = HumanInterrupt(
            run_id=run_id,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="test crash",
            observation_id="obs_1",
            world_state_version=1,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        await pg_store.save_interrupt(intr)

        # Worker A acquires lock with a very short lease (0.5 seconds)
        acquired_a, token_a = await pg_store.acquire_resume_lock(
            run_id=run_id,
            worker_id="worker_A_crashed",
            lease_duration_seconds=0.5,
        )
        assert acquired_a is True
        assert token_a == 1

        # Worker A "crashes" — process terminates without calling release_resume_lock()!

        # Immediate attempt by Worker B while lease active fails
        acq_early, _ = await pg_store.acquire_resume_lock(run_id=run_id, worker_id="worker_B")
        assert acq_early is False

        # Wait for lease to expire
        await asyncio.sleep(0.7)

        # Worker B attempts to resume: stale lease MUST be safely recovered
        acquired_b, token_b = await pg_store.acquire_resume_lock(
            run_id=run_id,
            worker_id="worker_B_healthy",
            lease_duration_seconds=10.0,
        )
        assert acquired_b is True
        # Fencing token must be incremented to protect against zombie Worker A writes!
        assert token_b > token_a

    @pytest.mark.asyncio
    async def test_audit_events_recorded_in_postgres(self, pg_store):
        """Verifies full audit trail is recorded in PostgreSQL with zero exposed secrets."""
        run_id = f"run_audit_{uuid.uuid4().hex[:8]}"
        await pg_store.record_audit_event(
            run_id=run_id,
            event_type="TEST_ACTION",
            payload={
                "action": "fill_otp",
                "otp_value": "123456",  # Should be stripped!
                "password": "secret_password",  # Should be stripped!
                "field": "field:otp",
            },
        )

        events = await pg_store.get_audit_events(run_id)
        assert len(events) >= 1
        last_event = events[-1]
        assert last_event["event_type"] == "TEST_ACTION"
        payload = last_event["payload"]
        assert "field" in payload
        # Security: sensitive keys carry no raw values. Phase 15 H6 stores an
        # explicit redaction marker (stronger than silent dropping — the
        # value is gone AND the redaction is auditable).
        assert "123456" not in str(payload)
        assert "secret_password" not in str(payload)
        assert payload["otp_value"] == "[REDACTED:restricted_secret]"
        assert payload["password"] == "[REDACTED:restricted_secret]"
