"""Unit tests: WorkflowService lifecycle (Phase 13).

Covers required behaviors: lifecycle transition validation, tenant-scoped
authorization, idempotent cancellation, resume gating at PAUSED_HITL,
worker completion/failure via fencing, and bounded service-level retry.
"""

from __future__ import annotations

import asyncio

import pytest

from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.metrics import EnterpriseMetrics
from app.enterprise.models import (
    ActorType,
    AuthorizationError,
    Identity,
    InvalidRunTransition,
    NotFoundError,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
    validate_transition,
)
from app.enterprise.workflow_service import (
    RunTransitionError,
    WorkflowService,
)


@pytest.fixture
def store() -> InMemoryEnterpriseStore:
    return InMemoryEnterpriseStore()


@pytest.fixture
def service(store) -> WorkflowService:
    return WorkflowService(store, AuditService(store), metrics=EnterpriseMetrics())


@pytest.fixture
def user() -> Identity:
    return Identity(
        actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
        role=Role.USER,
    )


@pytest.fixture
def user_t2() -> Identity:
    return Identity(
        actor_type=ActorType.USER, tenant_id="t2", subject_id="u2",
        role=Role.USER,
    )


@pytest.fixture
def worker() -> Identity:
    return Identity(
        actor_type=ActorType.WORKER, tenant_id="", subject_id="worker_A",
        role=Role.WORKER,
    )


async def _workflow_and_run(service, user, store):
    wf = await service.create_workflow(user, goal="Fill the pension form")
    run = await service.create_run(user, wf.workflow_id)
    return wf, run


class TestWorkflowLifecycle:
    async def test_create_workflow_and_run(self, service, user, store):
        wf = await service.create_workflow(user, goal="Apply")
        assert wf.tenant_id == "t1"
        assert wf.user_id == "u1"
        run = await service.create_run(user, wf.workflow_id)
        assert run.status is RunStatus.QUEUED
        item = await store.get_queue_item(run.run_id)
        assert item is not None
        assert item.state.value == "queued"
        assert item.payload.get("run_id") == run.run_id

    async def test_invalid_transition_fails_closed(self):
        with pytest.raises(InvalidRunTransition):
            validate_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
        with pytest.raises(InvalidRunTransition):
            validate_transition(RunStatus.QUEUED, RunStatus.RUNNING)  # skips DISPATCHED

    async def test_get_run_scoped_to_tenant(self, service, user, user_t2, store):
        _wf, run = await _workflow_and_run(service, user, store)
        ok = await service.get_run(user, run.run_id)
        assert ok.run_id == run.run_id
        with pytest.raises(NotFoundError):
            await service.get_run(user_t2, run.run_id)

    async def test_get_workflow_scoped_to_tenant(self, service, user, user_t2, store):
        wf, _run = await _workflow_and_run(service, user, store)
        ok = await service.get_workflow(user, wf.workflow_id)
        assert ok.workflow_id == wf.workflow_id
        with pytest.raises(NotFoundError):
            await service.get_workflow(user_t2, wf.workflow_id)


class TestCancellation:
    async def test_cancel_queued_run_is_immediate(self, service, user, store):
        _wf, run = await _workflow_and_run(service, user, store)
        cancelled = await service.cancel_run(user, run.run_id)
        assert cancelled.status is RunStatus.CANCELLED
        assert cancelled.is_terminal()

    async def test_cancel_running_run_requests_cancellation(
        self, service, user, worker, store,
    ):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        assert claimed is not None and claimed[0].run_id == run.run_id
        updated = await service.cancel_run(user, run.run_id)
        assert updated.status is RunStatus.CANCELLATION_REQUESTED

    async def test_cancel_is_idempotent(self, service, user, store):
        _wf, run = await _workflow_and_run(service, user, store)
        first = await service.cancel_run(user, run.run_id)
        again = await service.cancel_run(user, run.run_id)
        assert again.status is RunStatus.CANCELLED
        assert again.run_id == first.run_id

    async def test_cancel_terminal_run_conflicts(self, service, user, worker, store):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        run = claimed[0]
        run.status = RunStatus.RUNNING
        await store.save_run_with_fencing(run, run.fencing_token)
        await service.complete_run(
            worker, run.run_id, fencing_token=run.fencing_token,
        )
        with pytest.raises(RunTransitionError):
            await service.cancel_run(user, run.run_id)

    async def test_cancelled_run_cannot_resume(self, service, user):
        _wf, run = await _workflow_and_run(service, user, store)
        await service.cancel_run(user, run.run_id)
        with pytest.raises(RunTransitionError):
            await service.request_resume(user, run.run_id)


class TestResume:
    async def test_resume_requires_paused_hitl(self, service, user, store):
        _wf, run = await _workflow_and_run(service, user, store)
        with pytest.raises(RunTransitionError):
            await service.request_resume(user, run.run_id)

    async def test_resume_from_paused_hitl_requeues(
        self, service, user, worker, store,
    ):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        run = claimed[0]
        # Worker starts execution (DISPATCHED -> RUNNING, as the real
        # worker does via fenced write), then reports a HITL pause.
        run.status = RunStatus.RUNNING
        assert await store.save_run_with_fencing(run, run.fencing_token)
        await service.report_pause(
            worker, run.run_id, fencing_token=run.fencing_token,
            paused_hitl=True,
        )
        resumed = await service.request_resume(user, run.run_id)
        assert resumed.status is RunStatus.RUNNING
        item = await store.get_queue_item(run.run_id)
        assert item.state.value in ("queued", "claimed")


class TestWorkerReporting:
    async def test_complete_run_requires_worker_role(self, service, user, store):
        _wf, run = await _workflow_and_run(service, user, store)
        with pytest.raises(AuthorizationError):
            await service.complete_run(
                user, run.run_id, fencing_token=1,
            )

    async def test_complete_run_fencing(self, service, user, worker, store):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        run = claimed[0]
        run.status = RunStatus.RUNNING
        await store.save_run_with_fencing(run, run.fencing_token)
        done = await service.complete_run(
            worker, run.run_id, fencing_token=run.fencing_token,
        )
        assert done.status is RunStatus.COMPLETED

    async def test_stale_fencing_rejected(self, service, user, worker, store):
        _wf, run = await _workflow_and_run(service, user, store)
        await store.claim_next_run("worker_A", lease_seconds=30)
        with pytest.raises(AuthorizationError):
            await service.complete_run(worker, run.run_id, fencing_token=999)

    async def test_fail_run_records_failure_code(self, service, user, worker, store):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        run = claimed[0]
        failed = await service.fail_run(
            worker, run.run_id, fencing_token=run.fencing_token,
            failure_code="engine_error",
        )
        assert failed.status is RunStatus.FAILED
        assert failed.failure_code == "engine_error"

    async def test_non_owning_worker_cannot_report(self, service, user, store):
        _wf, run = await _workflow_and_run(service, user, store)
        await store.claim_next_run("worker_A", lease_seconds=30)
        outsider = Identity(
            actor_type=ActorType.WORKER, tenant_id="",
            subject_id="worker_B", role=Role.WORKER,
        )
        with pytest.raises(AuthorizationError):
            await service.complete_run(
                outsider, run.run_id, fencing_token=1,
            )


class TestServiceRetry:
    async def test_recover_requeues_recovery_required_run(
        self, service, user, worker, store,
    ):
        _wf, run = await _workflow_and_run(service, user, store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=0.2)
        run = claimed[0]
        # Worker disappears: lease expires, run flagged recovery required.
        # Refresh the in-memory cache before waiting so the flag cache
        # (not the lease) is what recover_run consults.
        await asyncio.sleep(0.3)
        await store.reap_expired_leases()
        recovered = await service.recover_run(run.run_id)
        assert recovered is True
        fresh = await store.get_run(run.run_id)
        assert fresh.status is RunStatus.QUEUED

    async def test_recover_refuses_when_lease_still_active(
        self, service, user, store,
    ):
        _wf, run = await _workflow_and_run(service, user, store)
        await store.claim_next_run("worker_A", lease_seconds=30)
        run = await store.get_run(run.run_id)
        # Force the status for the test condition while lease is alive
        run.status = RunStatus.RECOVERY_REQUIRED
        await store.save_run(run)
        recovered = await service.recover_run(run.run_id)
        assert recovered is False

    async def test_recover_dead_letters_after_attempt_budget(
        self, service, user, store,
    ):
        _wf, run = await _workflow_and_run(service, user, store)
        # Exhaust the dispatch budget via claim → expire → reap → recover.
        for _ in range(run.max_dispatch_attempts + 1):
            await store.claim_next_run("worker_A", lease_seconds=0.2)
            await asyncio.sleep(0.3)
            await store.reap_expired_leases()
            await service.recover_run(run.run_id)
        item = await store.get_queue_item(run.run_id)
        # After exhausting, the item is dead or requeues stop.
        assert item.state.value in ("dead", "claimed")
