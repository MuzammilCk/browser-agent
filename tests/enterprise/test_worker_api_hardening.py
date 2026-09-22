"""Phase 15 H5 regression tests — worker API heartbeat/token robustness.

Before H5:
- The heartbeat resolved the fencing token ONLY from a process-local
  cache that nothing populated, so a legitimate out-of-process worker
  (which received its token in the /claim response body) always got 400.
- A missing cache entry raised KeyError inside .get(), uncaught → 500.

After H5:
- /claim caches the token for the claiming (run, worker) pair;
- the heartbeat accepts a fencing_token in the request body (validated
  against the lease) with the cache as fallback;
- missing token → 400 (explicit, never 500); wrong/stale token → 409.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.enterprise.api.gateway import set_enterprise_state
from app.enterprise.api.worker_api import worker_router
from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    LeaseState,
    Role,
    Workflow,
    WorkflowRun,
)
from app.enterprise.security import IdentityProvider
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def env():
    store = InMemoryEnterpriseStore()
    audit = AuditService(store)
    service = WorkflowService(store, audit)
    provider = IdentityProvider()
    provider.register_principal(
        "tok-worker", tenant_id="t1", subject_id="worker-1",
        role=Role.WORKER,
    )
    provider.register_principal(
        "tok-worker2", tenant_id="t1", subject_id="worker-2",
        role=Role.WORKER,
    )
    set_enterprise_state(
        store=store, identity_provider=provider,
        service=service, audit=audit,
    )
    app = FastAPI()
    app.include_router(worker_router)
    return TestClient(app), store


WORKER = {"Authorization": "Bearer tok-worker"}
WORKER2 = {"Authorization": "Bearer tok-worker2"}


async def _seed_claimed_run(store: InMemoryEnterpriseStore) -> tuple[str, int]:
    """Create a workflow + run, enqueue and claim it; return (run_id, token)."""
    wf = Workflow(
        tenant_id="t1", user_id="user-1",
        metadata={"goal": "Fill", "start_url": "http://test.local/form"},
    )
    await store.create_workflow(wf)
    run = WorkflowRun(workflow_id=wf.workflow_id, tenant_id="t1", user_id="user-1")
    await store.create_run(run)
    await store.enqueue_run(run)
    claimed = await store.claim_next_run("worker-1", lease_seconds=60.0)
    assert claimed is not None
    _run, lease, _item = claimed
    return run.run_id, lease.fencing_token


class TestHeartbeatWithBodyToken:
    def test_body_token_renews_lease_without_cache(self, env):
        """The /claim-cache is empty (fresh process) but the worker
        presents the token it got from /claim — must succeed."""
        c, store = env
        run_id, token = _seed_claimed_run_sync(store)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={"fencing_token": token},
            headers=WORKER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["fencing_token"] == token

    def test_wrong_token_is_409_not_500(self, env):
        c, store = env
        run_id, token = _seed_claimed_run_sync(store)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={"fencing_token": token + 100},
            headers=WORKER,
        )
        assert resp.status_code == 409

    def test_non_integer_token_is_400(self, env):
        c, store = env
        run_id, _token = _seed_claimed_run_sync(store)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={"fencing_token": "abc"},
            headers=WORKER,
        )
        assert resp.status_code == 400

    def test_missing_token_without_cache_is_400_not_500(self, env):
        """Regression: pre-H5 this crashed with KeyError → 500."""
        c, store = env
        run_id, _token = _seed_claimed_run_sync(store)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={},
            headers=WORKER,
        )
        assert resp.status_code == 400
        assert "fencing_token" in resp.json()["detail"]

    def test_lease_lost_after_expiry_is_409(self, env):
        c, store = env
        run_id, token = _seed_claimed_run_sync(store)
        # Expire the lease behind the API's back.
        lease = store._leases[run_id]
        lease.state = LeaseState.EXPIRED
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={"fencing_token": token},
            headers=WORKER,
        )
        assert resp.status_code == 409

    def test_wrong_worker_is_409(self, env):
        c, store = env
        run_id, token = _seed_claimed_run_sync(store)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={"fencing_token": token},
            headers=WORKER2,
        )
        assert resp.status_code == 409

    def test_claim_populates_cache_and_empty_body_works(self, env):
        """After claiming THROUGH the API, the token cache is populated:
        an empty-body heartbeat still renews (backward compatibility)."""
        c, store = env
        run_id, _token = _seed_claimed_run_sync(store)
        # Simulate the claim having gone through the API endpoint.
        from app.enterprise.api.worker_api import cache_worker_token
        cache_worker_token(run_id, "worker-1", store._leases[run_id].fencing_token)
        resp = c.post(
            f"/enterprise/worker/runs/{run_id}/heartbeat",
            json={},
            headers=WORKER,
        )
        assert resp.status_code == 200


class TestReportEndpointsTokenValidation:
    def test_complete_with_non_integer_token_is_400(self, env):
        c, _store = env
        resp = c.post(
            "/enterprise/worker/runs/some-run/complete",
            json={"fencing_token": "not-a-number"},
            headers=WORKER,
        )
        assert resp.status_code == 400

    def test_fail_with_non_integer_token_is_400(self, env):
        c, _store = env
        resp = c.post(
            "/enterprise/worker/runs/some-run/fail",
            json={"fencing_token": []},
            headers=WORKER,
        )
        assert resp.status_code == 400

    def test_pause_with_non_integer_token_is_400(self, env):
        c, _store = env
        resp = c.post(
            "/enterprise/worker/runs/some-run/pause",
            json={"fencing_token": {}},
            headers=WORKER,
        )
        assert resp.status_code == 400


# The store fixture is async-created; expose a sync wrapper for these
# API-level tests (the in-memory store methods are safe to call from
# the pytest event loop via asyncio.run in sync context).
def _seed_claimed_run_sync(store: InMemoryEnterpriseStore) -> tuple[str, int]:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        return loop.run_until_complete(_seed_claimed_run(store))
    return asyncio.run(_seed_claimed_run(store))
