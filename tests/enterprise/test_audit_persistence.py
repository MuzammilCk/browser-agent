"""Unit tests: append-only audit persistence (Phase 13).

Required behaviors:
19. Tenant A cannot access tenant B audit.
22. Audit events preserve causal parent/child relationships.
23. Audit is append-only.
40. Enterprise trace/audit remains secret-redacted.
"""

from __future__ import annotations

import pytest

from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    Role,
)


@pytest.fixture
def store():
    return InMemoryEnterpriseStore()


@pytest.fixture
def audit(store):
    return AuditService(store)


@pytest.fixture
def user_t1():
    return Identity(
        actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
        role=Role.USER,
    )


@pytest.fixture
def user_t2():
    return Identity(
        actor_type=ActorType.USER, tenant_id="t2", subject_id="u2",
        role=Role.USER,
    )


class TestAppendOnly:
    async def test_events_are_recorded_and_ordered(self, audit, user_t1):
        e1 = await audit.record(
            event_type="RUN_QUEUED", identity=user_t1, run_id="run_x",
        )
        e2 = await audit.record(
            event_type="RUN_STARTED", identity=user_t1, run_id="run_x",
            parent_event_id=e1.event_id,
        )
        events = await audit.read(identity=user_t1, run_id="run_x")
        assert [e.event_id for e in events] == [e1.event_id, e2.event_id]
        assert events[1].parent_event_id == events[0].event_id

    async def test_store_has_no_update_or_delete_path(self, store):
        # The EnterpriseStore interface must not expose audit mutation.
        mutating = [
            name for name in dir(store)
            if any(v in name for v in ("update_audit", "delete_audit", "rewrite"))
        ]
        assert mutating == []

    async def test_count_is_append_growing(self, audit, user_t1):
        before = await audit._store.count_audit(tenant_id="t1")
        await audit.record(event_type="E1", identity=user_t1)
        after = await audit._store.count_audit(tenant_id="t1")
        assert after == before + 1


class TestCausality:
    async def test_parent_child_chain_preserved(self, audit, user_t1):
        e1 = await audit.record(
            event_type="WORKFLOW_CREATED", identity=user_t1,
        )
        e2 = await audit.record(
            event_type="RUN_QUEUED", identity=user_t1,
            parent_event_id=e1.event_id,
        )
        e3 = await audit.record(
            event_type="RUN_STARTED", identity=user_t1,
            parent_event_id=e2.event_id,
        )
        events = await audit.read(identity=user_t1)
        by_id = {e.event_id: e for e in events}
        assert by_id[e3.event_id].parent_event_id == e2.event_id
        assert by_id[e2.event_id].parent_event_id == e1.event_id

    async def test_dangling_parent_rejected(self, audit, user_t1):
        with pytest.raises(ValueError):
            await audit.record(
                event_type="ORPHAN", identity=user_t1,
                parent_event_id="evt_does_not_exist",
            )


class TestRedaction:
    async def test_raw_secret_never_enters_audit(self, audit, user_t1):
        await audit.record(
            event_type="VAULT_RESOLUTION",
            identity=user_t1,
            payload={
                "reference": "USER.password",
                "password": "SuperSecret123!",       # must be stripped
                "otp_value": "123456",               # must be stripped
                "note": "contact contains 123456",   # content-scrubbed
            },
        )
        events = await audit.read(identity=user_t1)
        assert len(events) == 1
        payload = events[0].payload
        # Raw values are replaced with redaction markers (Phase 12 rules)
        assert payload["password"] == "[REDACTED:restricted_secret]"
        assert payload["otp_value"] == "[REDACTED:restricted_secret]"
        assert "SuperSecret123" not in repr(payload)
        assert "123456" not in repr(payload)
        # The reference NAME survives redaction (names are not secrets)
        assert payload["reference"] == "USER.password"

    async def test_vault_value_never_in_audit_even_nested(self, audit, user_t1):
        await audit.record(
            event_type="RUN_DETAIL",
            identity=user_t1,
            payload={
                "nested": {
                    "authorization": "Bearer abc123def456ghi789",
                    "api_key": "sk-xyz",
                },
                "safe": "metadata",
            },
        )
        events = await audit.read(identity=user_t1)
        text = repr(events[0].payload)
        assert "abc123def456ghi789" not in text
        assert "sk-xyz" not in text
        assert "metadata" in text


class TestTenantScoping:
    async def test_tenant_b_cannot_read_tenant_a_events(
        self, audit, user_t1, user_t2,
    ):
        await audit.record(
            event_type="SECRET_BUSINESS_EVENT", identity=user_t1,
        )
        events_b = await audit.read(identity=user_t2)
        assert all(e.tenant_id != "t1" for e in events_b)
        events_a = await audit.read(identity=user_t1)
        assert any(e.event_type == "SECRET_BUSINESS_EVENT" for e in events_a)

    async def test_worker_role_cannot_read_audit(self, audit, store):
        worker = Identity(
            actor_type=ActorType.WORKER, tenant_id="t1",
            subject_id="worker_A", role=Role.WORKER,
        )
        user_t1 = Identity(
            actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
            role=Role.USER,
        )
        await audit.record(
            event_type="SOMETHING", identity=user_t1,
        )
        from app.enterprise.models import AuthorizationError
        with pytest.raises(AuthorizationError):
            await audit.read(identity=worker)
