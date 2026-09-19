"""Unit tests: HITL in the enterprise runtime (Phase 13).

Required behaviors:
14. HITL approval remains valid only for exact bound state.
15. HITL approval invalidates on material state change.
Resume revalidation happens through the EXISTING Phase 8 ApprovalBinding
validation (no second HITL system).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.interrupts.models import ApprovalBinding
from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
)
from app.enterprise.workflow_service import (
    RunTransitionError,
    WorkflowService,
)


@pytest.fixture
def store():
    return InMemoryEnterpriseStore()


@pytest.fixture
def service(store):
    return WorkflowService(store, AuditService(store))


@pytest.fixture
def user():
    return Identity(
        actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
        role=Role.USER,
    )


@pytest.fixture
def worker():
    return Identity(
        actor_type=ActorType.WORKER, tenant_id="", subject_id="worker_A",
        role=Role.WORKER,
    )


async def _paused_run(store, service, user, worker):
    wf = await service.create_workflow(user, goal="Fill the form")
    run = await service.create_run(user, wf.workflow_id)
    claimed = await store.claim_next_run("worker_A", lease_seconds=30)
    fresh = claimed[0]
    fresh.status = RunStatus.RUNNING
    await store.save_run_with_fencing(fresh, fresh.fencing_token)
    paused = await service.report_pause(
        worker, run.run_id,
        fencing_token=fresh.fencing_token,
        paused_hitl=True,
    )
    return paused, fresh.fencing_token


class TestEnterpriseHITLFlow:
    async def test_pause_is_durable(self, store, service, user, worker):
        paused, _tok = await _paused_run(store, service, user, worker)
        fresh = await store.get_run(paused.run_id)
        assert fresh.status is RunStatus.PAUSED_HITL

    async def test_resume_only_from_paused_state(
        self, store, service, user, worker,
    ):
        paused, _tok = await _paused_run(store, service, user, worker)
        resumed = await service.request_resume(user, paused.run_id)
        assert resumed.status is RunStatus.RUNNING
        # Resume re-enqueues for a (possibly different) worker.
        item = await store.get_queue_item(paused.run_id)
        assert item is not None

    async def test_resume_rejected_when_not_paused(
        self, store, service, user,
    ):
        wf = await service.create_workflow(user, goal="g")
        run = await service.create_run(user, wf.workflow_id)
        with pytest.raises(RunTransitionError):
            await service.request_resume(user, run.run_id)


class TestApprovalBindingSurvival:
    def test_approval_valid_for_exact_bound_state(self):
        approval = ApprovalBinding(
            run_id="run_x",
            interrupt_id="int_x",
            requested_action="confirm_step",
            target_identity="button:submit",
            world_state_version=7,
            observation_id="obs_1",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
        )
        valid, reason = approval.is_valid_for(
            current_world_state_version=7,
            current_action="confirm_step",
            current_target_identity="button:submit",
            current_semantic_id=None,
        )
        assert valid is True

    def test_approval_invalid_on_material_state_change(self):
        approval = ApprovalBinding(
            run_id="run_x",
            interrupt_id="int_x",
            requested_action="confirm_step",
            target_identity="button:submit",
            world_state_version=7,
            observation_id="obs_1",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
        )
        # Version drift → invalid
        ok, reason = approval.is_valid_for(
            current_world_state_version=8,
            current_action="confirm_step",
            current_target_identity="button:submit",
        )
        assert ok is False
        assert "world_state_version" in reason
        # Target change → invalid
        ok2, reason2 = approval.is_valid_for(
            current_world_state_version=7,
            current_action="confirm_step",
            current_target_identity="button:cancel",
        )
        assert ok2 is False
        assert "target" in reason2
        # Action change → invalid
        ok3, _ = approval.is_valid_for(
            current_world_state_version=7,
            current_action="click",
            current_target_identity="button:submit",
        )
        assert ok3 is False

    def test_approval_invalid_after_worker_replacement_state_drift(self):
        """Worker A gets approval at v5; worker B restores checkpoint
        where WorldState advanced to v6 — approval must be rejected."""
        approval = ApprovalBinding(
            run_id="run_x",
            interrupt_id="int_x",
            requested_action="confirm_step",
            target_identity="button:submit",
            world_state_version=5,
            observation_id="obs_old",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
        )
        ok, reason = approval.is_valid_for(
            current_world_state_version=6,
            current_action="confirm_step",
            current_target_identity="button:submit",
        )
        assert ok is False
        assert "v5" in reason and "v6" in reason
