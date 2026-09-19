"""Unit tests: durable execution queue (Phase 13).

Covers: FIFO ordering, visibility-timeout reclaim of crashed claims,
dead-letter after bounded attempts, idempotent dispatch (invariant 17),
and payload reference-safety.
"""

from __future__ import annotations

import asyncio

import pytest

from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    QueueItemState,
    Workflow,
    WorkflowRun,
)


@pytest.fixture
def store():
    return InMemoryEnterpriseStore()


async def _make_run(store, tenant="t1") -> WorkflowRun:
    wf = Workflow(tenant_id=tenant, user_id="u1")
    await store.create_workflow(wf)
    run = WorkflowRun(workflow_id=wf.workflow_id, tenant_id=tenant, user_id="u1")
    await store.create_run(run)
    return run


class TestDispatch:
    async def test_fifo_dispatch_order(self, store):
        r1 = await _make_run(store)
        r2 = await _make_run(store)
        r3 = await _make_run(store)
        for r in (r1, r2, r3):
            await store.enqueue_run(r)
        first = await store.claim_next_run("worker_A", lease_seconds=30)
        assert first[0].run_id == r1.run_id
        second = await store.claim_next_run("worker_A", lease_seconds=30)
        assert second[0].run_id == r2.run_id

    async def test_claimed_run_not_dispatched_twice(self, store):
        run = await _make_run(store)
        await store.enqueue_run(run)
        first = await store.claim_next_run("worker_A", lease_seconds=60)
        assert first is not None
        second = await store.claim_next_run("worker_B", lease_seconds=60)
        assert second is None

    async def test_visibility_timeout_reclaims_crashed_claim(self, store):
        run = await _make_run(store)
        await store.enqueue_run(run)
        await store.claim_next_run("worker_A", lease_seconds=0.2)
        await asyncio.sleep(0.3)
        # Reaper requeues the expired claim...
        await store.reap_expired_leases()
        # ...and a new worker claims it.
        claimed = await store.claim_next_run("worker_B", lease_seconds=30)
        assert claimed is not None
        assert claimed[0].run_id == run.run_id
        assert claimed[2].attempts == 2


class TestDeadLetter:
    async def test_dead_letter_after_bounded_attempts(self, store):
        run = await _make_run(store)
        item = await store.enqueue_run(run)
        # Exhaust all attempts with claim/expire cycles.
        for _ in range(item.max_attempts):
            await store.claim_next_run("worker_A", lease_seconds=0.2)
            await asyncio.sleep(0.3)
            await store.reap_expired_leases()
            await store.requeue_run(run.run_id)
        final = await store.get_queue_item(run.run_id)
        assert final.state is QueueItemState.DEAD
        # A dead item is never dispatched again.
        nothing = await store.claim_next_run("worker_B", lease_seconds=30)
        assert nothing is None

    async def test_explicit_dead_letter(self, store):
        run = await _make_run(store)
        await store.enqueue_run(run)
        await store.dead_letter_run(run.run_id, "manual_quarantine")
        item = await store.get_queue_item(run.run_id)
        assert item.state is QueueItemState.DEAD
        assert item.payload["dead_letter_reason"] == "manual_quarantine"


class TestIdempotentDispatch:
    async def test_enqueue_twice_creates_single_item(self, store):
        run = await _make_run(store)
        i1 = await store.enqueue_run(run)
        i2 = await store.enqueue_run(run)
        assert i1.run_id == i2.run_id
        assert i1.attempts == i2.attempts

    async def test_terminal_run_never_requeued_for_dispatch(self, store):
        run = await _make_run(store)
        await store.enqueue_run(run)
        claimed = await store.claim_next_run("worker_A", lease_seconds=0.2)
        run = claimed[0]
        run.status = __import__(
            "app.enterprise.models", fromlist=["RunStatus"],
        ).RunStatus.CANCELLED
        await store.save_run(run)
        await asyncio.sleep(0.3)
        await store.reap_expired_leases()
        # Cancelled (terminal) runs are not handed to workers.
        nothing = await store.claim_next_run("worker_B", lease_seconds=30)
        assert nothing is None


class TestPayloadSafety:
    async def test_payload_is_reference_only(self, store):
        run = await _make_run(store)
        item = await store.enqueue_run(run)
        serialized = repr(item.payload)
        for forbidden in (
            "password", "secret", "otp", "token", "page", "browser",
            "playwright", "checkpoint_payload", "state_payload",
        ):
            assert forbidden not in serialized.lower()

    async def test_payload_cannot_carry_tenant_override(self, store):
        run = await _make_run(store, tenant="t1")
        item = await store.enqueue_run(run)
        # The tenant fields are first-class columns derived from the run,
        # not client-influenced payload keys.
        assert item.tenant_id == "t1"
        assert "tenant_id" not in item.payload
