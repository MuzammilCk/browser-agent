"""Multi-tenant + vault isolation acceptance scenarios — Phase 13.

Acceptance scenario 3 (multi-tenant):
    Tenant A creates workflow A → Tenant B attempts access → DENIED.

Acceptance scenario 4 (vault):
    vault reference → authorized worker (active lease) → local secret
    resolution → secret absent from: queue payload, run serialization,
    audit payload, workflow metadata.
"""

from __future__ import annotations

import json

import pytest

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
from app.enterprise.vault_service import (
    VaultIntegrationService,
    VaultNotAuthorizedError,
)
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def env(tmp_path):
    store = InMemoryEnterpriseStore()
    audit = AuditService(store)
    service = WorkflowService(store, audit)
    vault = VaultIntegrationService(vault_root=tmp_path / "vault")
    return store, audit, service, vault


def _user(tenant: str, user: str) -> Identity:
    return Identity(
        actor_type=ActorType.USER, tenant_id=tenant,
        subject_id=user, role=Role.USER,
    )


def _worker(worker_id: str) -> Identity:
    return Identity(
        actor_type=ActorType.WORKER, tenant_id="",
        subject_id=worker_id, role=Role.WORKER,
    )


class TestMultiTenantAcceptance:
    async def test_tenant_b_denied_tenant_a_workflow(self, env):
        store, audit, service, _vault = env
        tenant_a = _user("tenant-A", "citizen-A")
        tenant_b = _user("tenant-B", "citizen-B")

        # Tenant A creates workflow A and a run.
        wf_a = await service.create_workflow(tenant_a, goal="A's pension form")
        run_a = await service.create_run(tenant_a, wf_a.workflow_id)

        # Tenant B attempts access → DENIED (no information leak).
        from app.enterprise.models import NotFoundError
        with pytest.raises(NotFoundError):
            await service.get_workflow(tenant_b, wf_a.workflow_id)
        with pytest.raises(NotFoundError):
            await service.get_run(tenant_b, run_a.run_id)
        with pytest.raises(NotFoundError):
            await service.cancel_run(tenant_b, run_a.run_id)
        with pytest.raises(NotFoundError):
            await service.request_resume(tenant_b, run_a.run_id)

        # Tenant B cannot create runs inside A's workflow.
        with pytest.raises(NotFoundError):
            await service.create_run(tenant_b, wf_a.workflow_id)

        # Tenant B sees no A audit events.
        events_b = await audit.read(identity=tenant_b)
        assert all(e.tenant_id != "tenant-A" for e in events_b)

        # Tenant A retains full access.
        assert (await service.get_workflow(tenant_a, wf_a.workflow_id)).workflow_id == wf_a.workflow_id


class TestVaultAcceptance:
    async def test_vault_resolution_isolation_end_to_end(self, env):
        store, audit, service, vault = env
        tenant_a = _user("tenant-A", "citizen-A")

        # Citizen stores a real value in their tenant vault.
        manager = vault._manager_for("tenant-A", "citizen-A")
        manager.vault.full_name = "Asha Kumar"

        # Workflow + run + worker claim (active lease = execution authority).
        wf = await service.create_workflow(
            tenant_a, goal="Fill the application",
            metadata={"start_url": "http://test.local/form"},
        )
        run = await service.create_run(tenant_a, wf.workflow_id)
        await store.claim_next_run("worker_V1", lease_seconds=30)
        fresh = await store.get_run(run.run_id)
        fresh.status = RunStatus.RUNNING
        await store.save_run_with_fencing(fresh, fresh.fencing_token)
        lease = await store.get_lease(run.run_id)

        # Authorized worker resolves the reference LOCALLY at the
        # execution boundary.
        resolved = await vault.resolve(
            "USER.full_name",
            run=fresh, lease=lease,
            fencing_token=lease.fencing_token,
            identity=_worker("worker_V1"),
        )
        assert resolved.value == "Asha Kumar"

        # The secret is absent from every durable/observable surface:
        surfaces: list[str] = [
            json.dumps((await store.get_queue_item(run.run_id)).payload),
            (await store.get_run(run.run_id)).model_dump_json(),
            json.dumps([
                e.model_dump(mode="json")
                for e in await audit.read(identity=tenant_a)
            ]),
            json.dumps(wf.metadata),
            json.dumps(vault.audit_metadata(resolved)),
        ]
        for surface in surfaces:
            assert "Asha Kumar" not in surface
        # Audit metadata records the REFERENCE (a name, not a secret).
        assert vault.audit_metadata(resolved)["reference"] == "USER.full_name"

    async def test_unauthorized_worker_cannot_resolve(self, env):
        store, _audit, service, vault = env
        tenant_a = _user("tenant-A", "citizen-A")
        wf = await service.create_workflow(tenant_a, goal="g")
        run = await service.create_run(tenant_a, wf.workflow_id)
        # No claim: no lease, no execution authority.
        fresh = await store.get_run(run.run_id)
        with pytest.raises(VaultNotAuthorizedError):
            await vault.resolve(
                "USER.full_name",
                run=fresh, lease=None, fencing_token=0,
                identity=_worker("worker_evil"),
            )

    async def test_cross_tenant_vault_directories_are_isolated(self, env):
        _store, _audit, _service, vault = env
        vault._manager_for("tenant-A", "citizen-A").vault.full_name = "A Owner"
        vault._manager_for("tenant-B", "citizen-B").vault.full_name = "B Owner"
        a = vault._manager_for("tenant-A", "citizen-A").vault
        b = vault._manager_for("tenant-B", "citizen-B").vault
        assert a.full_name == "A Owner"
        assert b.full_name == "B Owner"
        # Distinct directories on disk.
        from pathlib import Path
        assert vault._managers[("tenant-A", "citizen-A")].vault_dir != \
               vault._managers[("tenant-B", "citizen-B")].vault_dir
