"""Phase 5 — model configuration guardrails (audit Z6).

Real vault data (Aadhaar/PAN/DOB) must never silently ride an anonymous
free-tier model. The resolved model is logged and exposed in workflow
state, and a populated-vault + free-tier-model combination is refused at
start unless explicitly overridden.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import routes
from app.config.settings import (
    ANONYMOUS_DEFAULT_MODEL,
    get_settings,
    is_free_tier_model,
)


@pytest.fixture()
def settings_env(tmp_path, monkeypatch):
    """Cached Settings instance pointed at temp dirs with test values."""
    s = get_settings()
    monkeypatch.setattr(s, "data_dir", tmp_path)
    yield s


def _make_wf_record(workflow_id: str) -> dict:
    return {
        "workflow_id": workflow_id,
        "domain": "uidai.gov.in",
        "task": "Download Aadhaar",
        "url": "https://uidai.gov.in",
        "status": "starting",
        "current_url": "https://uidai.gov.in",
        "actions": [],
        "error": None,
        "screenshots": [],
        "page_title": "",
        "checkpoints": [],
        "pending_action": None,
        "vault_loaded": False,
        "vault_warning": None,
        "planning_mode": None,
        "llm_model": None,
        "llm_disabled_reason": None,
        "confirm_event": asyncio.Event(),
        "approved": None,
    }


class TestFreeTierDetection:
    def test_shipped_default_is_free_tier(self):
        assert is_free_tier_model(ANONYMOUS_DEFAULT_MODEL)
        assert ANONYMOUS_DEFAULT_MODEL == "stealth/ox-alpha"

    def test_openrouter_free_suffix_detected(self):
        """Whatever the .env pins, any ':free' model is free-tier — e.g.
        this repo's actual .env pins dots-studio/dots-3-note-preview:free."""
        assert is_free_tier_model("dots-studio/dots-3-note-preview:free")
        assert is_free_tier_model("meta-llama/llama-3-8b:free")

    def test_named_paid_models_not_free_tier(self):
        assert not is_free_tier_model("anthropic/claude-sonnet-4-20250514")
        assert not is_free_tier_model("openai/gpt-4o")
        assert not is_free_tier_model(None)
        assert not is_free_tier_model("")


class TestVaultModelGuard:
    def test_no_vault_allows_any_model(self):
        assert routes._vault_model_guard(
            False, ANONYMOUS_DEFAULT_MODEL, allow_override=False,
        ) is None

    def test_no_llm_with_vault_is_local_only(self):
        # Deterministic mode keeps values on-device — nothing to refuse.
        assert routes._vault_model_guard(True, None, allow_override=False) is None

    def test_named_model_with_vault_allowed(self):
        assert routes._vault_model_guard(
            True, "anthropic/claude-sonnet-4-20250514", allow_override=False,
        ) is None

    def test_anonymous_model_with_vault_refused_without_override(self):
        reason = routes._vault_model_guard(
            True, ANONYMOUS_DEFAULT_MODEL, allow_override=False,
        )
        assert reason
        assert ANONYMOUS_DEFAULT_MODEL in reason
        assert "OPENROUTER_MODEL" in reason  # tells the operator the fix

    def test_other_free_tier_model_with_vault_refused_too(self):
        """The .env may pin any free model — the guard must not key on a
        single hardcoded string."""
        reason = routes._vault_model_guard(
            True, "dots-studio/dots-3-note-preview:free", allow_override=False,
        )
        assert reason and "dots-3-note-preview:free" in reason

    def test_explicit_override_permits_but_is_observable(self):
        assert routes._vault_model_guard(
            True, ANONYMOUS_DEFAULT_MODEL, allow_override=True,
        ) is None


def _populate_vault(data_dir) -> None:
    from app.vault.manager import VaultManager
    from app.vault.resolver import UserVault
    VaultManager(data_dir / "vault").save_vault(UserVault(full_name="Test User"))


class TestRunAutomationRefusal:
    @pytest.mark.asyncio
    async def test_refusal_happens_before_browser_launch(
        self, settings_env, monkeypatch,
    ):
        """The guard must fire before BrowserManager.start() — no browser,
        no navigation, no LLM call."""
        monkeypatch.setattr(settings_env, "openrouter_api_key", "sk-test-key-123")
        monkeypatch.setattr(settings_env, "openrouter_model", ANONYMOUS_DEFAULT_MODEL)
        _populate_vault(settings_env.data_dir)

        mock_manager_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        mock_manager_cls.return_value = mock_instance

        wf = _make_wf_record("guard1")
        routes._workflows["guard1"] = wf
        try:
            with patch("app.browser.manager.BrowserManager", mock_manager_cls):
                await routes._run_automation("guard1", "https://uidai.gov.in", "t")

            assert wf["status"] == "failed"
            assert ANONYMOUS_DEFAULT_MODEL in wf["error"]
            assert wf["vault_loaded"] is True
            assert wf["planning_mode"] == "llm"
            mock_instance.start.assert_not_called()
        finally:
            routes._workflows.pop("guard1", None)

    @pytest.mark.asyncio
    async def test_free_tier_env_model_also_refused(
        self, settings_env, monkeypatch,
    ):
        """This repo's real .env pins a different free-tier model — the
        guard must catch that shape too."""
        monkeypatch.setattr(settings_env, "openrouter_api_key", "sk-test-key-123")
        monkeypatch.setattr(
            settings_env, "openrouter_model",
            "dots-studio/dots-3-note-preview:free",
        )
        _populate_vault(settings_env.data_dir)

        wf = _make_wf_record("guard3")
        routes._workflows["guard3"] = wf
        try:
            await routes._run_automation("guard3", "https://uidai.gov.in", "t")
            assert wf["status"] == "failed"
            assert "dots-3-note-preview:free" in wf["error"]
        finally:
            routes._workflows.pop("guard3", None)

    @pytest.mark.asyncio
    async def test_named_model_proceeds_to_browser_launch(
        self, settings_env, monkeypatch,
    ):
        monkeypatch.setattr(settings_env, "openrouter_api_key", "sk-test-key-123")
        monkeypatch.setattr(
            settings_env, "openrouter_model",
            "anthropic/claude-sonnet-4-20250514",
        )
        _populate_vault(settings_env.data_dir)

        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="UIDAI")
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG")
        mock_manager_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        mock_instance.open = AsyncMock(return_value=mock_page)
        mock_instance.stop = AsyncMock()
        mock_manager_cls.return_value = mock_instance

        from app.models.workflow_state import WorkflowState, WorkflowStatus
        completed = WorkflowState(status=WorkflowStatus.COMPLETED)

        wf = _make_wf_record("guard2")
        routes._workflows["guard2"] = wf
        try:
            with patch("app.browser.manager.BrowserManager", mock_manager_cls), \
                 patch("app.agent.runner.AgentRunner.run",
                       AsyncMock(return_value=completed)):
                await routes._run_automation("guard2", "https://uidai.gov.in", "t")

            mock_instance.start.assert_awaited_once()
            assert wf["status"] == "completed"
        finally:
            routes._workflows.pop("guard2", None)
