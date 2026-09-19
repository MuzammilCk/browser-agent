"""Live PostgreSQL integration tests — PostgresEnterpriseStore (Phase 13).

Same live-PostgreSQL pattern as the Phase 8 integration tests. Verifies
real database semantics: atomic SKIP LOCKED claim, conditional lease
upserts with monotonic fencing tokens, durable idempotency keys, and
append-only audit persistence.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.config.settings import Settings
from app.enterprise.models import (
    ActorType,
    IdempotencyRecord,
    Identity,
    LeaseState,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
)
from app.enterprise.postgres_store import PostgresEnterpriseStore

POSTGRES_TEST_DSN = (
    os.getenv("POSTGRES_TEST_DSN")
    or os.getenv("POSTGRES_URL")
    or Settings().postgres_url
)


@pytest.fixture
async def pg_store():
    store = PostgresEnterpriseStore(POSTGRES_TEST_DSN)
    await store.connect()
    yield store
    await store.close()


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _make_run(store: PostgresEnterpriseStore) -> tuple[WorkflowRun, str]:
    suffix = _unique_suffix()
    tenant = f"t_{suffix}"
    wf = Workflow(
        workflow_id=f"wf_pgtest_{suffix}",
        tenant_id=tenant, user_id="u1",
    )
    await store.create_workflow(wf)
    run = WorkflowRun(
        run_id=f"run_pgtest_{suffix}",
        workflow_id=wf.workflow_id,
        tenant_id=tenant, user_id="u1",
    )
    await store.create_run(run)
    await store.enqueue_run(run)
    return run, tenant


class TestQueueClaimAtomicity:
    @pytest.mark.asyncio
    async def test_single_claim_two_workers(self, pg_store):
        run, tenant = await _make_run(pg_store)
        first = await pg_store.claim_next_run(
            "worker_A", lease_seconds=30, tenant_id=tenant,
        )
        assert first is not None
        assert first[0].run_id == run.run_id
        # Mutual exclusion: the same run is never handed out twice while
        # worker A holds the lease.
        second = await pg_store.claim_next_run(
            "worker_B", lease_seconds=30, tenant_id=tenant,
        )
        assert second is None

    @pytest.mark.asyncio
    async def test_claim_updates_run_and_queue_rows(self, pg_store):
        run, tenant = await _make_run(pg_store)
        claimed = await pg_store.claim_next_run(
            "worker_X", lease_seconds=30, tenant_id=tenant,
        )
        assert claimed is not None
        fresh = await pg_store.get_run(run.run_id)
        assert fresh.worker_id == "worker_X"
        assert fresh.status is RunStatus.DISPATCHED
        item = await pg_store.get_queue_item(run.run_id)
        assert item.state.value == "claimed"
        assert item.claimed_by == "worker_X"
        assert item.attempts == 1


class TestLeaseFencingSQL:
    @pytest.mark.asyncio
    async def test_conditional_lease_upsert_mutual_exclusion(self, pg_store):
        run = await _make_run(pg_store)
        suffix = _unique_suffix()
        lease_a = await pg_store.acquire_lease(
            f"run_fence_{suffix}", "worker_A", 30.0,
        )
        assert lease_a is not None
        assert lease_a.fencing_token == 1
        # Active foreign lease → None
        lease_b = await pg_store.acquire_lease(
            f"run_fence_{suffix}", "worker_B", 30.0,
        )
        assert lease_b is None
        # Same worker renew → same token
        lease_a2 = await pg_store.acquire_lease(
            f"run_fence_{suffix}", "worker_A", 30.0,
        )
        assert lease_a2.fencing_token == 1

    @pytest.mark.asyncio
    async def test_expired_lease_takeover_increments_token(self, pg_store):
        suffix = _unique_suffix()
        run_id = f"run_fence2_{suffix}"
        lease_a = await pg_store.acquire_lease(run_id, "worker_A", 0.5)
        assert lease_a.fencing_token == 1
        await asyncio.sleep(0.7)
        lease_b = await pg_store.acquire_lease(run_id, "worker_B", 30.0)
        assert lease_b is not None
        assert lease_b.fencing_token == 2
        # Stale worker A cannot renew
        renewed = await pg_store.renew_lease(run_id, "worker_A", 1, 30.0)
        assert renewed is None
        # Current worker renews
        renewed_b = await pg_store.renew_lease(run_id, "worker_B", 2, 30.0)
        assert renewed_b is not None

    @pytest.mark.asyncio
    async def test_fenced_run_write_rejects_stale_token(self, pg_store):
        run, tenant = await _make_run(pg_store)
        claimed = await pg_store.claim_next_run(
            "worker_A", lease_seconds=0.4, tenant_id=tenant,
        )
        stale_token = claimed[1].fencing_token
        await asyncio.sleep(0.6)
        claimed_b = await pg_store.claim_next_run(
            "worker_B", lease_seconds=30, tenant_id=tenant,
        )
        assert claimed_b is not None
        stale_run = claimed[0]
        stale_run.status = RunStatus.RUNNING
        ok = await pg_store.save_run_with_fencing(stale_run, stale_token)
        assert ok is False
        ok_b = await pg_store.save_run_with_fencing(
            claimed_b[0], claimed_b[1].fencing_token,
        )
        assert ok_b is True


class TestLeaseReaping:
    @pytest.mark.asyncio
    async def test_reap_marks_expired_and_flags_recovery(self, pg_store):
        run, tenant = await _make_run(pg_store)
        await pg_store.claim_next_run(
            "worker_A", lease_seconds=0.4, tenant_id=tenant,
        )
        await asyncio.sleep(0.6)
        reaped = await pg_store.reap_expired_leases()
        assert reaped >= 1
        fresh = await pg_store.get_run(run.run_id)
        assert fresh.status is RunStatus.RECOVERY_REQUIRED
        lease = await pg_store.get_lease(run.run_id)
        assert lease.state is LeaseState.EXPIRED


class TestIdempotencyPersistence:
    @pytest.mark.asyncio
    async def test_durable_key_semantics(self, pg_store):
        key = f"idem_{_unique_suffix()}"
        rec = IdempotencyRecord(
            key=key, tenant_id="t_idem", operation="create_run",
            request_hash="hash1",
        )
        first = await pg_store.put_idempotency_if_absent(rec)
        assert first is not None
        again = await pg_store.put_idempotency_if_absent(rec)
        assert again is None
        got = await pg_store.get_idempotency(key, "t_idem")
        assert got.request_hash == "hash1"
        await pg_store.update_idempotency_response(
            key, "t_idem", 201, {"run_id": "r1"},
        )
        got2 = await pg_store.get_idempotency(key, "t_idem")
        assert got2.status_code == 201
        assert got2.response == {"run_id": "r1"}


class TestAuditAppendOnly:
    @pytest.mark.asyncio
    async def test_events_persist_and_scope(self, pg_store):
        from app.enterprise.models import AuditEvent
        suffix = _unique_suffix()
        tenant = f"t_audit_{suffix}"
        event = AuditEvent(
            event_type="RUN_QUEUED", tenant_id=tenant,
            user_id="u1", payload={"n": 1},
        )
        await pg_store.append_audit(event)
        events = await pg_store.list_audit(tenant_id=tenant)
        assert any(e.event_id == event.event_id for e in events)
        # Other tenant sees nothing
        assert await pg_store.list_audit(tenant_id=f"other_{suffix}") == []
        count = await pg_store.count_audit(tenant_id=tenant)
        assert count == 1


class TestCancellationPersistence:
    @pytest.mark.asyncio
    async def test_cancel_running_run_durably(self, pg_store):
        run, tenant = await _make_run(pg_store)
        claimed = await pg_store.claim_next_run(
            "worker_A", lease_seconds=30, tenant_id=tenant,
        )
        run_fresh = claimed[0]
        run_fresh.status = RunStatus.RUNNING
        await pg_store.save_run_with_fencing(
            run_fresh, run_fresh.fencing_token,
        )
        updated = await pg_store.request_cancellation(
            run.run_id, tenant_id=run.tenant_id,
        )
        assert updated.status is RunStatus.CANCELLATION_REQUESTED
        fresh = await pg_store.get_run(run.run_id)
        assert fresh.cancellation_requested is True
