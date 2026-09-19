"""Unit tests: ExecutionWorker claim/finalize behavior (Phase 13).

Uses a stub engine (monkeypatched WorkerRunEngine.execute) so tests run
fast and hermetically; real-browser execution is covered by the
acceptance tests.
"""

from __future__ import annotations

import asyncio

import pytest

from app.enterprise import worker as worker_module
from app.enterprise.audit import AuditService
from app.enterprise.engine import EngineOutcome, EngineResult
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    LeaseState,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
)
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def store() -> InMemoryEnterpriseStore:
    return InMemoryEnterpriseStore()


@pytest.fixture
def service(store) -> WorkflowService:
    return WorkflowService(store, AuditService(store))


def _worker(store, service, worker_id="worker_A") -> worker_module.ExecutionWorker:
    return worker_module.ExecutionWorker(
        worker_id=worker_id,
        store=store,
        service=service,
        lease_seconds=30.0,
        renewal_interval_seconds=0.05,
    )


async def _queued_run(store, tenant="t1", user="u1") -> WorkflowRun:
    wf = Workflow(
        tenant_id=tenant, user_id=user,
        metadata={"goal": "Fill form", "start_url": "http://test.local/form"},
    )
    await store.create_workflow(wf)
    run = WorkflowRun(
        workflow_id=wf.workflow_id, tenant_id=tenant, user_id=user,
    )
    await store.create_run(run)
    await store.enqueue_run(run)
    return run


class TestClaimAndRun:
    async def test_claim_acquires_lease_and_dispatches(self, store, service):
        w = _worker(store, service)
        run = await _queued_run(store)
        claimed = await w.claim_next_run()
        assert claimed is not None
        assert claimed.run_id == run.run_id
        lease = await store.get_lease(run.run_id)
        assert lease.worker_id == w.worker_id
        assert lease.state is LeaseState.ACTIVE

    async def test_worker_without_claim_cannot_run(self, store, service):
        w = _worker(store, service)
        run = await _queued_run(store)
        with pytest.raises(RuntimeError):
            await w.run_claimed_run(run, goal="g", start_url="http://x/")

    async def test_finalization_completes_run(self, store, service, monkeypatch):
        w = _worker(store, service)
        await _queued_run(store)
        claimed = await w.claim_next_run()

        async def _fake_execute(self_engine, **kwargs):
            return EngineResult(outcome=EngineOutcome.COMPLETED, checkpoint_id="cp_1")

        monkeypatch.setattr(
            worker_module.WorkerRunEngine, "execute", _fake_execute,
        )
        outcome = await w.run_claimed_run(
            claimed, goal="g", start_url="http://test.local/",
        )
        assert outcome is EngineOutcome.COMPLETED
        fresh = await store.get_run(claimed.run_id)
        assert fresh.status is RunStatus.COMPLETED
        assert fresh.checkpoint_id == "cp_1"

    async def test_finalization_reports_pause_and_releases_lease(
        self, store, service, monkeypatch,
    ):
        w = _worker(store, service)
        await _queued_run(store)
        claimed = await w.claim_next_run()
        claimed.status = RunStatus.RUNNING
        await store.save_run_with_fencing(claimed, claimed.fencing_token)

        async def _fake_execute(self_engine, **kwargs):
            return EngineResult(
                outcome=EngineOutcome.PAUSED_HITL, checkpoint_id="cp_2",
            )

        monkeypatch.setattr(
            worker_module.WorkerRunEngine, "execute", _fake_execute,
        )
        outcome = await w.run_claimed_run(
            claimed, goal="g", start_url="http://test.local/",
        )
        assert outcome is EngineOutcome.PAUSED_HITL
        fresh = await store.get_run(claimed.run_id)
        assert fresh.status is RunStatus.PAUSED_HITL
        lease = await store.get_lease(claimed.run_id)
        assert lease.state is LeaseState.RELEASED

    async def test_stale_worker_cannot_finalize(self, store, service, monkeypatch):
        w = _worker(store, service, worker_id="worker_A")
        await _queued_run(store)
        # Real crash path: worker A claims with a short lease, then dies.
        claimed = await w.claim_next_run(lease_seconds=0.2)
        claimed.status = RunStatus.RUNNING
        await store.save_run_with_fencing(claimed, claimed.fencing_token)
        await asyncio.sleep(0.3)
        # Reaper expires the lease, flags recovery, requeues; worker B claims.
        await store.reap_expired_leases()
        claimed_b = await store.claim_next_run(
            "worker_B", lease_seconds=30,
        )
        assert claimed_b is not None

        async def _fake_execute(self_engine, **kwargs):
            return EngineResult(outcome=EngineOutcome.COMPLETED)

        monkeypatch.setattr(
            worker_module.WorkerRunEngine, "execute", _fake_execute,
        )
        # Stale worker A completes its (now stale) view of the run.
        outcome = await w.run_claimed_run(
            claimed, goal="g", start_url="http://test.local/",
        )
        fresh = await store.get_run(claimed.run_id)
        # Run remains owned by worker B (not corrupted by stale A).
        assert fresh.worker_id == "worker_B"
        assert fresh.status is not RunStatus.COMPLETED
