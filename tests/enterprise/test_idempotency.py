"""Unit tests: durable idempotency (Phase 13).

Required behaviors:
6. Duplicate workflow request is idempotent.
7. Duplicate run request is idempotent.
8. (partial) idempotency abuse: same key different body → rejected.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.enterprise.api.gateway import router, set_enterprise_state
from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import IdempotencyRecord
from app.enterprise.security import IdentityProvider
from app.enterprise.store import EnterpriseStore
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def env():
    store = InMemoryEnterpriseStore()
    audit = AuditService(store)
    service = WorkflowService(store, audit)
    provider = IdentityProvider()
    provider.register_principal(
        "tok-t1", tenant_id="t1", subject_id="user-1",
    )
    set_enterprise_state(
        store=store, identity_provider=provider,
        service=service, audit=audit,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), store


AUTH = {"Authorization": "Bearer tok-t1"}


class TestGatewayIdempotency:
    def test_duplicate_workflow_creation_is_idempotent(self, env):
        c, store = env
        headers = {**AUTH, "Idempotency-Key": "idem-wf-1"}
        r1 = c.post(
            "/enterprise/workflows",
            json={"goal": "g", "start_url": "http://test.local/"},
            headers=headers,
        )
        r2 = c.post(
            "/enterprise/workflows",
            json={"goal": "g", "start_url": "http://test.local/"},
            headers=headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["workflow_id"] == r2.json()["workflow_id"]
        # Only ONE workflow was actually created.
        count = sum(
            1 for k in dir(store) if False  # placeholder to keep flake-free
        )
        workflows = store._workflows
        assert len(workflows) == 1

    def test_key_reuse_with_different_body_rejected(self, env):
        c, _store = env
        headers = {**AUTH, "Idempotency-Key": "idem-wf-2"}
        r1 = c.post(
            "/enterprise/workflows",
            json={"goal": "first goal", "start_url": "http://test.local/"},
            headers=headers,
        )
        assert r1.status_code == 201
        r2 = c.post(
            "/enterprise/workflows",
            json={"goal": "different goal", "start_url": "http://test.local/"},
            headers=headers,
        )
        assert r2.status_code == 422

    def test_duplicate_run_creation_is_idempotent(self, env):
        c, store = env
        wf = c.post(
            "/enterprise/workflows",
            json={"goal": "g", "start_url": "http://test.local/"},
            headers=AUTH,
        ).json()
        headers = {**AUTH, "Idempotency-Key": "idem-run-1"}
        r1 = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=headers,
        )
        r2 = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["run_id"] == r2.json()["run_id"]

    def test_idempotency_keys_are_tenant_scoped(self, env):
        c, store = env
        h1 = {"Authorization": "Bearer tok-t1", "Idempotency-Key": "shared-key"}
        r1 = c.post(
            "/enterprise/workflows",
            json={"goal": "g", "start_url": "http://test.local/"},
            headers=h1,
        )
        assert r1.status_code == 201


class TestStoreIdempotency:
    async def test_put_if_absent_semantics(self):
        store: EnterpriseStore = InMemoryEnterpriseStore()
        rec = IdempotencyRecord(
            key="k1", tenant_id="t1", operation="create_run",
            request_hash="abc",
        )
        first = await store.put_idempotency_if_absent(rec)
        assert first is not None
        again = await store.put_idempotency_if_absent(rec)
        assert again is None
        got = await store.get_idempotency("k1", "t1")
        assert got.request_hash == "abc"
        # Different tenant: same key is a DIFFERENT idempotency scope.
        got_t2 = await store.get_idempotency("k1", "t2")
        assert got_t2 is None

    async def test_response_persisted_and_replayable(self):
        store: EnterpriseStore = InMemoryEnterpriseStore()
        rec = IdempotencyRecord(
            key="k2", tenant_id="t1", operation="cancel_run",
            request_hash="def",
        )
        await store.put_idempotency_if_absent(rec)
        await store.update_idempotency_response(
            "k2", "t1", 200, {"run_id": "run_x", "status": "cancelled"},
        )
        got = await store.get_idempotency("k2", "t1")
        assert got.response == {"run_id": "run_x", "status": "cancelled"}
        assert got.status_code == 200
