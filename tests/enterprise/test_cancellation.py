"""Unit tests: durable cancellation semantics (Phase 13).

Required behaviors:
29. Cancellation propagates durably.
30. Cancelled run cannot resume accidentally.
4. Unauthorized cancellation denied.
"""

from __future__ import annotations

import asyncio

import pytest

from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    LeaseState,
    NotFoundError,
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
def other():
    return Identity(
        actor_type=ActorType.USER, tenant_id="t2", subject_id="u2",
        role=Role.USER,
    )


async def _queued(store, service, user):
    wf = await service.create_workflow(user, goal="Fill the form")
    return await service.create_run(user, wf.workflow_id)


class TestDurableCancellation:
    async def test_queued_run_cancels_immediately(self, store, service, user):
        run = await _queued(store, service, user)
        cancelled = await service.cancel_run(user, run.run_id)
        assert cancelled.status is RunStatus.CANCELLED
        fresh = await store.get_run(run.run_id)
        assert fresh.status is RunStatus.CANCELLED  # durable, not in-memory

    async def test_running_run_records_cancellation_request(
        self, store, service, user,
    ):
        run = await _queued(store, service, user)
        await store.claim_next_run("worker_A", lease_seconds=30)
        run_fresh = await store.get_run(run.run_id)
        run_fresh.status = RunStatus.RUNNING
        await store.save_run_with_fencing(
            run_fresh, run_fresh.fencing_token,
        )
        updated = await service.cancel_run(user, run.run_id)
        assert updated.status is RunStatus.CANCELLATION_REQUESTED
        assert updated.cancellation_requested is True
        # Durable: a fresh read sees the flag.
        fresh = await store.get_run(run.run_id)
        assert fresh.cancellation_requested is True

    async def test_worker_observes_cancellation_at_safe_boundary(
        self, store, service, user,
    ):
        run = await _queued(store, service, user)
        await store.claim_next_run("worker_A", lease_seconds=30)
        fresh = await store.get_run(run.run_id)
        fresh.status = RunStatus.RUNNING
        await store.save_run_with_fencing(fresh, fresh.fencing_token)
        await service.cancel_run(user, run.run_id)
        # The worker's cancel_check reads the durable flag.
        observed = await store.get_run(run.run_id)
        assert observed.cancellation_requested is True

    async def test_worker_confirms_cancellation(self, store, service, user):
        run = await _queued(store, service, user)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        fresh = claimed[0]
        fresh.status = RunStatus.RUNNING
        await store.save_run_with_fencing(fresh, fresh.fencing_token)
        await service.cancel_run(user, run.run_id)
        # Worker observes at safe boundary → CANCELLATION_REQUESTED → CANCELLED
        fresh = await store.get_run(run.run_id)
        fresh.status = RunStatus.CANCELLED
        fresh.completed_at = "2026-09-19T00:00:00+00:00"
        await store.save_run_with_fencing(fresh, fresh.fencing_token)
        final = await store.get_run(run.run_id)
        assert final.status is RunStatus.CANCELLED
        assert final.is_terminal()

    async def test_cancellation_is_idempotent(self, store, service, user):
        run = await _queued(store, service, user)
        first = await service.cancel_run(user, run.run_id)
        second = await service.cancel_run(user, run.run_id)
        assert first.status is RunStatus.CANCELLED
        assert second.status is RunStatus.CANCELLED

    async def test_unauthorized_cancellation_denied(
        self, store, service, user, other,
    ):
        run = await _queued(store, service, user)
        with pytest.raises(NotFoundError):
            await service.cancel_run(other, run.run_id)
        fresh = await store.get_run(run.run_id)
        assert fresh.status is RunStatus.QUEUED

    async def test_cancelled_run_cannot_resume(
        self, store, service, user,
    ):
        run = await _queued(store, service, user)
        await service.cancel_run(user, run.run_id)
        with pytest.raises(RunTransitionError):
            await service.request_resume(user, run.run_id)
        # And it is never re-dispatched.
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        assert claimed is None

    async def test_hitl_pause_with_pending_cancellation_stays_cancellable(
        self, store, service, user,
    ):
        """A cancellation request must not be lost by a later pause report."""
        run = await _queued(store, service, user)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        fresh = claimed[0]
        fresh.status = RunStatus.RUNNING
        await store.save_run_with_fencing(fresh, fresh.fencing_token)
        await service.cancel_run(user, run.run_id)  # → CANCELLATION_REQUESTED
        # Worker (not yet seeing the flag) reports a HITL pause.
        paused = await service.report_pause(
            __import__(
                "app.enterprise.models", fromlist=["Identity"],
            ).Identity(
                actor_type=ActorType.WORKER, tenant_id="",
                subject_id="worker_A", role=Role.WORKER,
            ),
            run.run_id,
            fencing_token=fresh.fencing_token,
            paused_hitl=True,
        )
        # The pause must NOT clear the cancellation request.
        assert paused.cancellation_requested is True
        # Resume is refused while cancellation is pending.
        with pytest.raises(RunTransitionError):
            await service.request_resume(user, run.run_id)
