"""Phase 15 H6 regression tests — audit-event redaction defense in depth.

The durable checkpoint stores must filter audit-event payloads with the
same key patterns as the Phase 11 trace recorder. Sensitive keys are
replaced with an explicit redaction marker (not silently dropped) and
nested payloads are filtered recursively.
"""

from __future__ import annotations

import pytest

from app.agent.persistence.redaction import (
    filter_sensitive_payload,
    is_sensitive_key,
)


class TestSensitiveKeyDetection:
    @pytest.mark.parametrize("key", [
        "password", "user_password", "passwd", "pwd_hash",
        "otp", "one_time_password", "totp_code",
        "pin", "mpin", "cvv", "card_security_code",
        "api_key", "secret_key", "private_key",
        "access_token", "auth_token", "refresh_token", "bearer",
        "cookie", "session_cookie", "session_id",
        "authorization", "auth_header",
        "credential", "vault_secret",
        "aadhaar_number", "pan_number", "passport_no", "voter_id",
    ])
    def test_sensitive_keys_detected(self, key):
        assert is_sensitive_key(key), key

    @pytest.mark.parametrize("key", [
        "run_id", "workflow_id", "checkpoint_id", "status",
        "iteration", "observation_id", "url", "reason", "count",
    ])
    def test_safe_keys_pass(self, key):
        assert not is_sensitive_key(key), key


class TestPayloadFiltering:
    def test_sensitive_keys_replaced_with_marker(self):
        payload = {
            "run_id": "r-1",
            "worker_id": "w-1",
            "password": "hunter2",
            "api_key": "sk-live-123",
        }
        safe = filter_sensitive_payload(payload)
        assert safe["run_id"] == "r-1"
        assert safe["worker_id"] == "w-1"
        assert safe["password"] == "[REDACTED:restricted_secret]"
        assert safe["api_key"] == "[REDACTED:restricted_secret]"
        assert "hunter2" not in str(safe)
        assert "sk-live-123" not in str(safe)

    def test_nested_payloads_filtered(self):
        payload = {
            "context": {
                "session_id": "sess-123",
                "attempt": 2,
                "deeper": {"authorization": "Bearer abc"},
            },
            "items": [{"otp": "123456"}, {"ok": "fine"}],
        }
        safe = filter_sensitive_payload(payload)
        assert safe["context"]["session_id"] == "[REDACTED:restricted_secret]"
        assert safe["context"]["attempt"] == 2
        assert safe["context"]["deeper"]["authorization"] == "[REDACTED:restricted_secret]"
        assert safe["items"][0]["otp"] == "[REDACTED:restricted_secret]"
        assert safe["items"][1]["ok"] == "fine"

    def test_wider_than_old_substring_filter(self):
        """Regression: the old filter only covered password/secret/otp/pin/
        credential — token/cookie/api_key/authorization leaked through."""
        payload = {
            "token": "tok-123",
            "cookie": "sid=xyz",
            "session_id": "sess-9",
            "authorization": "Bearer zzz",
        }
        safe = filter_sensitive_payload(payload)
        for key in payload:
            assert safe[key] == "[REDACTED:restricted_secret]", key


class TestStoreAuditRedaction:
    async def test_in_memory_store_redacts_audit_events(self):
        from app.agent.persistence.in_memory_store import InMemoryCheckpointStore

        store = InMemoryCheckpointStore()
        await store.record_audit_event(
            run_id="r-1", event_type="TEST_EVENT",
            payload={
                "run_id": "r-1",
                "password": "hunter2",
                "access_token": "tok-9",
                "detail": "safe",
            },
        )
        events = store.get_audit_events("r-1")
        assert len(events) == 1
        payload = events[0]["payload"]
        assert payload["detail"] == "safe"
        assert payload["password"] == "[REDACTED:restricted_secret]"
        assert payload["access_token"] == "[REDACTED:restricted_secret]"

    async def test_postgres_store_redacts_before_sql(self, monkeypatch):
        """The SQL layer must receive the redacted payload — verified by
        intercepting pool.execute without a live database."""
        from app.agent.persistence.postgres_store import PostgresCheckpointStore

        store = PostgresCheckpointStore(dsn="postgresql://unused")
        captured: dict = {}

        class FakePool:
            async def execute(self, sql, *args):
                captured["sql"] = sql
                captured["args"] = args

        monkeypatch.setattr(
            store, "_ensure_pool", lambda: FakePool(),
        )
        await store.record_audit_event(
            run_id="r-1", event_type="TEST_EVENT",
            payload={"password": "hunter2", "run_id": "r-1"},
        )
        import json
        persisted = json.loads(captured["args"][2])
        assert persisted["password"] == "[REDACTED:restricted_secret]"
        assert persisted["run_id"] == "r-1"
        assert "hunter2" not in captured["args"][2]
