"""Unit tests: Enterprise API Gateway (Phase 13).

Required behaviors:
1. API authentication required (#40).
2. Cross-tenant workflow/run access denied (#2, #3).
3. Unauthorized cancellation/resume denied (#4, #5).
24. API never exposes browser handles.
25. API never exposes raw checkpoints.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.enterprise.api.gateway import router, set_enterprise_state
from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.security import IdentityProvider
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def client():
    store = InMemoryEnterpriseStore()
    audit = AuditService(store)
    service = WorkflowService(store, audit)
    provider = IdentityProvider()
    provider.register_principal(
        "tok-t1", tenant_id="t1", subject_id="user-1",
    )
    provider.register_principal(
        "tok-t2", tenant_id="t2", subject_id="user-2",
    )
    set_enterprise_state(
        store=store, identity_provider=provider,
        service=service, audit=audit,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), store


AUTH = {"Authorization": "Bearer tok-t1"}
AUTH_T2 = {"Authorization": "Bearer tok-t2"}


def _create_workflow(client, goal="Fill the pension form"):
    resp = client.post(
        "/enterprise/workflows",
        json={"goal": goal, "start_url": "http://test.local/form"},
        headers=AUTH,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestAuthentication:
    def test_missing_token_rejected(self, client):
        c, _store = client
        resp = c.get("/enterprise/workflows/some-id")
        assert resp.status_code == 401

    def test_unknown_token_rejected(self, client):
        c, _store = client
        resp = c.get(
            "/enterprise/workflows/some-id",
            headers={"Authorization": "Bearer nope"},
        )
        assert resp.status_code == 401

    def test_valid_token_accepted(self, client):
        c, _store = client
        resp = c.get("/enterprise/workflows/some-id", headers=AUTH)
        assert resp.status_code == 404  # authenticated but not found


class TestWorkflowAPI:
    def test_create_and_get_workflow(self, client):
        c, _store = client
        body = _create_workflow(c)
        wf_id = body["workflow_id"]
        got = c.get(f"/enterprise/workflows/{wf_id}", headers=AUTH).json()
        assert got["workflow_id"] == wf_id
        assert got["tenant_id"] == "t1"
        assert got["user_id"] == "user-1"

    def test_cross_tenant_workflow_hidden(self, client):
        c, _store = client
        body = _create_workflow(c)
        resp = c.get(
            f"/enterprise/workflows/{body['workflow_id']}", headers=AUTH_T2,
        )
        assert resp.status_code == 404

    def test_strict_schema_rejects_client_identity_fields(self, client):
        c, _store = client
        resp = c.post(
            "/enterprise/workflows",
            json={
                "goal": "g",
                "start_url": "http://test.local/",
                "tenant_id": "other-tenant",       # must be rejected
                "user_id": "someone",              # must be rejected
                "role": "admin",                   # must be rejected
            },
            headers=AUTH,
        )
        assert resp.status_code == 422

    def test_no_browser_handles_or_checkpoints_in_responses(self, client):
        c, _store = client
        wf = _create_workflow(c)
        run = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=AUTH,
        ).json()
        # Ensure a checkpoint id would never be a live handle; response
        # keys must not contain forbidden internals.
        forbidden = {"page", "browser", "context", "executor", "state_payload"}
        assert forbidden.isdisjoint(run.keys())
        run_get = c.get(f"/enterprise/runs/{run['run_id']}", headers=AUTH).json()
        assert forbidden.isdisjoint(run_get.keys())
        assert "state_payload" not in run_get

    def test_run_creation_scoped_to_owner(self, client):
        c, _store = client
        wf = _create_workflow(c)
        resp = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=AUTH_T2,
        )
        assert resp.status_code == 404


class TestRunAPI:
    def test_cancel_and_resume_authorization(self, client):
        c, store = client
        wf = _create_workflow(c)
        run = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=AUTH,
        ).json()
        # Cross-tenant cancel is denied
        resp = c.post(
            f"/enterprise/runs/{run['run_id']}/cancel",
            json={}, headers=AUTH_T2,
        )
        assert resp.status_code == 404
        # Owner cancel works
        resp = c.post(
            f"/enterprise/runs/{run['run_id']}/cancel",
            json={"reason": "changed my mind"}, headers=AUTH,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        # Cancelled run cannot resume (invariant: cancelled never resumes)
        resp = c.post(
            f"/enterprise/runs/{run['run_id']}/resume",
            json={}, headers=AUTH,
        )
        assert resp.status_code == 409

    def test_get_run_cross_tenant_hidden(self, client):
        c, _store = client
        wf = _create_workflow(c)
        run = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=AUTH,
        ).json()
        resp = c.get(f"/enterprise/runs/{run['run_id']}", headers=AUTH_T2)
        assert resp.status_code == 404

    def test_audit_events_scoped_to_tenant(self, client):
        c, _store = client
        wf = _create_workflow(c)
        run = c.post(
            f"/enterprise/workflows/{wf['workflow_id']}/runs",
            json={}, headers=AUTH,
        ).json()
        resp = c.get(
            f"/enterprise/runs/{run['run_id']}/events", headers=AUTH_T2,
        )
        assert resp.json() == []
        resp = c.get(
            f"/enterprise/runs/{run['run_id']}/events", headers=AUTH,
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
