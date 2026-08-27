"""Phase 2 — a real way to get user data into the vault (audit Z3).

- GET/POST /api/vault endpoints populate and inspect the vault without
  ever returning values
- unknown fields on POST fail loudly (extra="forbid")
- the committed example template parses as a complete UserVault
- vault_loaded / vault_warning are visible on workflow state and in the
  polled workflow record from the first iteration
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api import routes, vault_routes
from app.api.vault_routes import VaultSummary, VaultUpdate
from app.config.settings import get_settings
from app.vault.manager import VaultManager
from app.vault.resolver import UserVault


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    """Point settings.data_dir at a temp dir so tests never touch real PII."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    yield tmp_path


class TestExampleTemplate:
    def test_example_file_exists_and_parses_as_vault(self):
        path = REPO_ROOT / "data" / "vault" / "user_vault.example.json"
        assert path.exists(), (
            "user_vault.example.json must be committed as the fill-in template"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        vault = UserVault(**data)  # no extra keys tolerated by model
        # Every UserVault field is represented in the template
        assert set(vault.model_dump().keys()) == set(data.keys())
        # And the template ships blank (never with real-looking data)
        assert not any(bool(v) for v in data.values())

    def test_real_vault_file_is_gitignored(self):
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "data/vault/*" in ignored


class TestVaultEndpoints:
    def test_post_populates_and_persists(self, vault_env):
        result = asyncio.run(vault_routes.update_vault(
            VaultUpdate(full_name="Test User", state="Kerala"),
        ))
        assert isinstance(result, VaultSummary)
        assert "full_name" in result.fields_filled

        persisted = VaultManager(vault_env / "vault").vault
        assert persisted.full_name == "Test User"
        assert persisted.state == "Kerala"

    def test_get_returns_names_never_values(self, vault_env):
        asyncio.run(vault_routes.update_vault(VaultUpdate(mobile="9876543210")))
        summary = asyncio.run(vault_routes.get_vault_summary())
        dumped = summary.model_dump()
        assert "mobile" in dumped["fields_filled"]
        flat = json.dumps(dumped)
        assert "9876543210" not in flat

    def test_partial_update_preserves_existing_fields(self, vault_env):
        asyncio.run(vault_routes.update_vault(VaultUpdate(full_name="Test User")))
        asyncio.run(vault_routes.update_vault(VaultUpdate(email="t@example.com")))
        summary = asyncio.run(vault_routes.get_vault_summary())
        assert {"full_name", "email"} <= set(summary.fields_filled)

    def test_unknown_field_rejected_loudly(self):
        with pytest.raises(ValidationError):
            VaultUpdate(fullname="typo")  # wrong field name

    def test_empty_values_do_not_count_as_filled(self, vault_env):
        summary = asyncio.run(vault_routes.update_vault(VaultUpdate(gender="")))
        assert "gender" in summary.fields_empty


class TestWorkflowVaultVisibility:
    @pytest.mark.asyncio
    async def test_runner_declares_vault_state_from_start(self):
        from unittest.mock import MagicMock, patch

        from app.agent.field_mapper_models import MappingResult
        from app.agent.runner import AgentRunner
        from app.models.page_state import PageObservation, PageState
        from app.models.workflow_state import WorkflowStatus

        runner = AgentRunner(
            llm=None,
            vault_loaded=False,
            vault_warning="Vault is empty",
        )
        page_state = PageState(url="https://x.gov.in/", title="X", page_type="navigation")
        obs = PageObservation(page_state=page_state, aria_snapshot="", observation_id="o1")

        with patch.object(runner._observer, "observe", return_value=obs):
            with patch.object(runner._mapper, "map_fields",
                              return_value=MappingResult()):
                ws = await runner.run(MagicMock(), task="T")

        assert ws.vault_loaded is False
        assert ws.vault_warning == "Vault is empty"

    def test_sync_carries_vault_fields_into_poll_record(self):
        from app.models.workflow_state import WorkflowState

        ws = WorkflowState(vault_loaded=False, vault_warning="Vault is empty")
        wf = {
            "actions": [], "checkpoints": [], "total_actions": 0,
            "successful_actions": 0, "failed_actions": 0,
            "pending_action": None,
        }
        routes._sync_workflow_to_wf(wf, ws)
        assert wf["vault_loaded"] is False
        assert wf["vault_warning"] == "Vault is empty"

    def test_populated_vault_produces_real_fill_end_to_end(self):
        """Acceptance: populated vault fixture → real fills planned."""
        from app.agent.field_mapper_models import (
            FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
        )
        from app.agent.planner import plan_deterministic
        from app.agent.planning_result import ActionPlanned
        from app.models.page_state import ElementState, PageObservation, PageState
        from app.models.workflow_state import WorkflowState

        class _Resolver:
            def resolve(self, ref):
                return "Test User"

        el = ElementState(ref="e1", role="textbox", accessible_name="Full Name")
        page_state = PageState(
            url="https://x.gov.in/f", title="F", page_type="form", elements=[el],
        )
        obs = PageObservation(page_state=page_state, aria_snapshot="", observation_id="o1")
        binding = FieldBinding(
            field_ref="e1", binding="USER.full_name",
            confidence=MappingConfidence.HIGH,
            strategy=MappingStrategy.DETERMINISTIC, field_type="textbox",
        )
        result = plan_deterministic(
            WorkflowState(),
            obs,
            MappingResult(bindings=[binding]),
            value_resolver=_Resolver(),
        )
        assert isinstance(result, ActionPlanned)
        assert result.action.action == "fill"
