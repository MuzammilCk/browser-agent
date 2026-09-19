"""Unit tests: worker leases, fencing, and queue dispatch (Phase 13).

Required behaviors proven here:
- Two workers cannot own one run simultaneously (required #8).
- Fencing rejects stale workers (required #9).
- Lease expiration allows safe reassignment (required #10).
- Queue payload carries references only (required #17, #33 partial).
- Idempotent enqueue (required #7 partial).
"""

from __future__ import annotations

import asyncio

import pytest

from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    Identity,
    LeaseState,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
)


@pytest.fixture
def store() -> InMemoryEnterpriseStore:
    return InMemoryEnterpriseStore()


async def _queued_run(store, tenant="t1", user="u1") -> WorkflowRun:
    wf = Workflow(tenant_id=tenant, user_id=user)
    await store.create_workflow(wf)
    run = WorkflowRun(
        workflow_id=wf.workflow_id, tenant_id=tenant, user_id=user,
    )
    await store.create_run(run)
    await store.enqueue_run(run)
    return run


class TestMutualExclusion:
    async def test_two_workers_cannot_own_one_run(self, store):
        run = await _queued_run(store)
        first = await store.claim_next_run("worker_A", lease_seconds=30)
        assert first is not None
        assert first[0].run_id == run.run_id
        # Second worker finds nothing else dispatchable; the claimed run
        # is NOT handed out again while the lease is active.
        second = await store.claim_next_run("worker_B", lease_seconds=30)
        assert second is None
        lease = await store.get_lease(run.run_id)
        assert lease.worker_id == "worker_A"
        assert lease.state is LeaseState.ACTIVE

    async def test_claim_marks_run_dispatched(self, store):
        run = await _queued_run(store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        fresh = await store.get_run(run.run_id)
        assert fresh.status is RunStatus.DISPATCHED
        assert fresh.worker_id == "worker_A"
        assert fresh.fencing_token == claimed[1].fencing_token


class TestFencing:
    async def test_fencing_rejects_stale_worker(self, store):
        run = await _queued_run(store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=0.2)
        token_a = claimed[1].fencing_token
        await asyncio.sleep(0.3)
        # Worker A crashed; worker B takes over with a higher token.
        claimed_b = await store.claim_next_run("worker_B", lease_seconds=30)
        assert claimed_b is not None
        token_b = claimed_b[1].fencing_token
        assert token_b > token_a
        # Stale worker A's fenced write is rejected.
        stale_run = claimed[0]
        stale_run.status = RunStatus.RUNNING
        ok = await store.save_run_with_fencing(stale_run, token_a)
        assert ok is False

    async def test_current_fencing_write_succeeds(self, store):
        run = await _queued_run(store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        fresh = claimed[0]
        fresh.status = RunStatus.RUNNING
        ok = await store.save_run_with_fencing(fresh, fresh.fencing_token)
        assert ok is True
        saved = await store.get_run(run.run_id)
        assert saved.status is RunStatus.RUNNING

    async def test_renewal_requires_matching_token(self, store):
        run = await _queued_run(store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        token = claimed[1].fencing_token
        renewed = await store.renew_lease(
            run.run_id, "worker_A", token, 30.0,
        )
        assert renewed is not None
        # Wrong token: rejected (fail closed)
        assert await store.renew_lease(run.run_id, "worker_A", token + 5, 30.0) is None
        # Wrong worker: rejected
        assert await store.renew_lease(run.run_id, "worker_B", token, 30.0) is None

    async def test_release_requires_owner(self, store):
        run = await _queued_run(store)
        claimed = await store.claim_next_run("worker_A", lease_seconds=30)
        token = claimed[1].fencing_token
        assert await store.release_lease(run.run_id, "worker_B", token) is False
        assert await store.release_lease(run.run_id, "worker_A", token + 1) is False
        assert await store.release_lease(run.run_id, "worker_A", token) is True


class TestLeaseExpiry:
    async def test_expiration_allows_safe_reassignment(self, store):
        run = await _queued_run(store)
        await store.claim_next_run("worker_A", lease_seconds=0.2)
        await asyncio.sleep(0.3)
        reaped = await store.reap_expired_leases()
        assert reaped == 1
        lease = await store.get_lease(run.run_id)
        assert lease.state is LeaseState.EXPIRED
        fresh = await store.get_run(run.run_id)
        assert fresh.status is RunStatus.RECOVERY_REQUIRED
        # A new worker can now take over.
        claimed = await store.claim_next_run("worker_B", lease_seconds=30)
        assert claimed is not None
        assert claimed[0].run_id == run.run_id

    async def test_active_lease_not_reaped(self, store):
        run = await _queued_run(store)
        await store.claim_next_run("worker_A", lease_seconds=30)
        reaped = await store.reap_expired_leases()
        assert reaped == 0
        lease = await store.get_lease(run.run_id)
        assert lease.state is LeaseState.ACTIVE


class TestQueue:
    async def test_enqueue_is_idempotent(self, store):
        run = await _queued_run(store)
        item1 = await store.enqueue_run(run)
        item2 = await store.enqueue_run(run)
        assert item1.queue_id == item2.queue_id
        assert item1.attempts == item2.attempts

    async def test_queue_payload_has_no_secrets_or_handles(self, store):
        run = await _queued_run(store)
        item = await store.get_queue_item(run.run_id)
        assert item is not None
        text = repr(item.payload)
        for forbidden in ("password", "otp", "secret", "page", "browser", "checkpoint"):
            assert forbidden not in text.lower()
        # References only
        assert item.payload["run_id"] == run.run_id

    async def test_fifo_order_by_created_at(self, store):
        r1 = await _queued_run(store)
        r2 = await _queued_run(store)
        first = await store.claim_next_run("worker_A", lease_seconds=30)
        assert first is not None
        assert first[0].run_id == r1.run_id  # older run first

    async def test_expired_claim_is_reclaimable(self, store):
        run = await _queued_run(store)
        await store.claim_next_run("worker_A", lease_seconds=0.2)
        await asyncio.sleep(0.3)
        await store.reap_expired_leases()
        claimed = await store.claim_next_run("worker_B", lease_seconds=30)
        assert claimed is not None
        assert claimed[0].run_id == run.run_id


class TestIsolation:
    async def test_tenant_scoped_reads(self, store):
        run_t1 = await _queued_run(store, tenant="t1", user="u1")
        wf = Workflow(tenant_id="t2", user_id="u2")
        await store.create_workflow(wf)
        run_t2 = WorkflowRun(workflow_id=wf.workflow_id, tenant_id="t2", user_id="u2")
        await store.create_run(run_t2)

        assert await store.get_run(run_t1.run_id, tenant_id="t1") is not None
        assert await store.get_run(run_t1.run_id, tenant_id="t2") is None
        assert await store.get_workflow(run_t1.workflow_id, tenant_id="t2") is None
        runs_t2 = await store.list_runs_for_workflow(
            run_t2.workflow_id, tenant_id="t1",
        )
        assert runs_t2 == []
