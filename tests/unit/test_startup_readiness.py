"""Phase 15 H8 — startup production-readiness validation + /ready endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestReadinessValidation:
    def test_dev_defaults_produce_warnings_not_blocks(self, monkeypatch):
        """Local-dev defaults: no blocking conditions (behavior unchanged),
        but the warnings are explicit instead of silent. Environment
        (.env) values are cleared so the test sees pure defaults."""
        import os

        from app.config.settings import Settings

        for key in list(os.environ):
            if key.startswith(("VAULT_", "API_TOKEN", "OPENROUTER_", "ENTERPRISE_", "PRODUCTION_")):
                monkeypatch.delenv(key, raising=False)

        s = Settings(headless=True, vault_encryption_key="", api_token="")
        blockers, warnings = s.validate_production_readiness()
        assert blockers == []
        assert any("api_token" in w for w in warnings)
        assert any("vault" in w.lower() for w in warnings)

    def test_production_mode_blocks_missing_auth(self):
        from app.config.settings import Settings

        s = Settings(production_mode=True, api_token="", headless=True)
        blockers, _warnings = s.validate_production_readiness()
        assert any("api_token" in b for b in blockers)

    def test_production_mode_blocks_plaintext_vault(self):
        from app.config.settings import Settings

        s = Settings(
            production_mode=True, api_token="tok-123", vault_encryption_key="",
        )
        blockers, _warnings = s.validate_production_readiness()
        assert any("vault_encryption_key" in b for b in blockers)

    def test_production_mode_blocks_anonymous_model_with_vault_key_set(self):
        """Production + encrypted vault + anonymous free-tier model =
        contested data retention (audit Z6) — must block."""
        from app.config.settings import Settings

        s = Settings(
            production_mode=True,
            api_token="tok-123",
            vault_encryption_key="k",
            openrouter_model="stealth/ox-alpha",
        )
        blockers, _warnings = s.validate_production_readiness()
        assert any("openrouter_model" in b for b in blockers)

    def test_production_mode_blocks_worker_api_without_token(self):
        from app.config.settings import Settings

        s = Settings(
            production_mode=True,
            api_token="tok-123",
            vault_encryption_key="k",
            openrouter_model="anthropic/claude-sonnet-4-20250514",
            enterprise_worker_token="",
        )
        blockers, _warnings = s.validate_production_readiness()
        assert any("enterprise_worker_token" in b for b in blockers)

    def test_fully_configured_production_has_no_blockers(self):
        from app.config.settings import Settings

        s = Settings(
            production_mode=True,
            api_token="tok-123",
            vault_encryption_key="k",
            openrouter_model="anthropic/claude-sonnet-4-20250514",
            enterprise_worker_token="wtok",
        )
        blockers, _warnings = s.validate_production_readiness()
        assert blockers == []

    def test_blocker_reasons_never_echo_secret_values(self):
        """Validation messages name the setting, never its value."""
        from app.config.settings import Settings

        s = Settings(production_mode=True, api_token="", headless=True)
        blockers, warnings = s.validate_production_readiness()
        for text in blockers + warnings:
            assert "sk-" not in text
            # No secret-looking values in messages
            assert "tok-" not in text or "api_token" in text


class TestReadyEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        from app.config.settings import get_settings
        from app.main import app, refresh_app_settings

        monkeypatch.setenv("PRODUCTION_MODE", "false")
        get_settings.cache_clear()
        try:
            refresh_app_settings()
            yield TestClient(app)
        finally:
            get_settings.cache_clear()
            refresh_app_settings()

    def test_ready_reports_components(self, client):
        c = client
        resp = c.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["ready"] is True
        assert "checks" in body
        checks = body["checks"]
        assert "api_auth" in checks
        assert "vault_encryption" in checks
        assert "enterprise_worker_auth" in checks
        assert "model" in checks

    def test_ready_fails_when_production_blockers_present(self, monkeypatch):
        from app.config.settings import get_settings
        from app.main import app, refresh_app_settings

        monkeypatch.setenv("PRODUCTION_MODE", "true")
        monkeypatch.setenv("API_TOKEN", "")
        get_settings.cache_clear()
        try:
            refresh_app_settings()
            c = TestClient(app)
            resp = c.get("/ready")
            assert resp.status_code == 503
            body = resp.json()
            assert body["ready"] is False
            assert body["status"] == "not_ready"
            assert body["blocking"]
        finally:
            get_settings.cache_clear()
            refresh_app_settings()

    def test_health_still_works(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
