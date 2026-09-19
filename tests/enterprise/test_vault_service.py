"""Unit tests: VaultIntegrationService (Phase 13).

Required behaviors:
10. Vault raw secret never enters model context (payload/serialization surface).
16. Vault raw secret never enters queue payload.
18. Vault raw secret never enters audit.
11. Vault service does not grant authority (lease/authorization required).
16b. Vault reference misuse fails closed.
"""

from __future__ import annotations

import json

import pytest

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
from app.enterprise.vault_service import (
    ResolvedSecret,
    VaultIntegrationService,
    VaultNotAuthorizedError,
    VaultReferenceError,
)


@pytest.fixture
def store():
    return InMemoryEnterpriseStore()


@pytest.fixture
def vault(tmp_path):
    return VaultIntegrationService(vault_root=tmp_path / "vault")


@pytest.fixture
def run_and_lease(store):
    async def _make(worker_id="worker_A", status=RunStatus.RUNNING):
        wf = Workflow(tenant_id="t1", user_id="u1")
        await store.create_workflow(wf)
        run = WorkflowRun(
            workflow_id=wf.workflow_id, tenant_id="t1", user_id="u1",
        )
        await store.create_run(run)
        await store.enqueue_run(run)
        claimed = await store.claim_next_run(worker_id, lease_seconds=30)
        run = claimed[0]
        run.status = status
        await store.save_run_with_fencing(run, run.fencing_token)
        lease = await store.get_lease(run.run_id)
        worker = Identity(
            actor_type=ActorType.WORKER, tenant_id="",
            subject_id=worker_id, role=Role.WORKER,
        )
        return run, lease, worker
    return _make


class TestReferenceValidation:
    async def test_invalid_shape_rejected(self, vault, run_and_lease):
        run, lease, worker = await run_and_lease()
        for bad in ("", "noprefix", "EMAIL.full_name", "USER.", "USER.!!"):
            with pytest.raises(VaultReferenceError):
                await vault.resolve(
                    bad, run=run, lease=lease,
                    fencing_token=run.fencing_token, identity=worker,
                )

    async def test_unknown_reference_rejected(self, vault, run_and_lease):
        run, lease, worker = await run_and_lease()
        with pytest.raises(VaultReferenceError):
            await vault.resolve(
                "USER.does_not_exist", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=worker,
            )


class TestAuthorization:
    async def test_resolution_requires_active_lease(
        self, vault, run_and_lease,
    ):
        run, _lease, worker = await run_and_lease()
        with pytest.raises(VaultNotAuthorizedError):
            await vault.resolve(
                "USER.full_name", run=run, lease=None,
                fencing_token=run.fencing_token, identity=worker,
            )

    async def test_resolution_requires_current_fencing_token(
        self, vault, run_and_lease,
    ):
        run, lease, worker = await run_and_lease()
        with pytest.raises(VaultNotAuthorizedError):
            await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=lease.fencing_token + 100, identity=worker,
            )

    async def test_non_owning_worker_rejected(self, vault, run_and_lease):
        run, lease, _worker = await run_and_lease(worker_id="worker_A")
        outsider = Identity(
            actor_type=ActorType.WORKER, tenant_id="",
            subject_id="worker_evil", role=Role.WORKER,
        )
        with pytest.raises(VaultNotAuthorizedError):
            await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=outsider,
            )

    async def test_terminal_run_cannot_resolve(self, vault, run_and_lease):
        run, lease, worker = await run_and_lease(status=RunStatus.COMPLETED)
        with pytest.raises(VaultNotAuthorizedError):
            await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=worker,
            )


class TestSecretIsolation:
    async def test_resolved_secret_never_serializes_to_audit_or_queue(
        self, vault, run_and_lease, store,
    ):
        run, lease, worker = await run_and_lease()
        # Seed a value for the tenant/user vault.
        vault._manager_for("t1", "u1").vault.full_name = "Asha Kumar"
        try:
            resolved = await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=worker,
            )
            assert resolved.value == "Asha Kumar"
            # Audit metadata: reference only, never the value.
            meta = vault.audit_metadata(resolved)
            assert meta["reference"] == "USER.full_name"
            assert "Asha Kumar" not in json.dumps(meta)
            # Queue payload: references only.
            item = await store.get_queue_item(run.run_id)
            assert "Asha Kumar" not in json.dumps(item.payload)
            # The ResolvedSecret itself serializes with the value — it
            # must never be passed to serializers in real flows; assert
            # the type documents this and is not a BaseModel.
            assert not hasattr(ResolvedSecret, "model_dump")
        finally:
            vault._manager_for("t1", "u1").vault.full_name = ""

    async def test_missing_value_fails_closed(self, vault, run_and_lease):
        run, lease, worker = await run_and_lease()
        vault._manager_for("t1", "u1").vault.full_name = ""
        with pytest.raises(VaultReferenceError):
            await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=worker,
            )

    async def test_tenant_scoping_uses_run_owner_not_caller(
        self, vault, run_and_lease,
    ):
        """The resolution reads t1/u1's vault because the RUN says so —
        even if a worker served multiple tenants."""
        run, lease, worker = await run_and_lease(worker_id="worker_A")
        vault._manager_for("t1", "u1").vault.full_name = "T1 Owner"
        vault._manager_for("t2", "u2").vault.full_name = "T2 Owner"
        try:
            resolved = await vault.resolve(
                "USER.full_name", run=run, lease=lease,
                fencing_token=run.fencing_token, identity=worker,
            )
            assert resolved.value == "T1 Owner"
            assert resolved.tenant_id == "t1"
        finally:
            vault._manager_for("t1", "u1").vault.full_name = ""
            vault._manager_for("t2", "u2").vault.full_name = ""
