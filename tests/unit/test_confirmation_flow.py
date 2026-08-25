"""Tests for the confirmation pause/resume flow (audit B2/C1).

Covers:
- REQUIRE_CONFIRMATION halts with pending_action stored
- resume(approved=True) executes the pending action with user confirmation
  and continues the loop in the SAME WorkflowState
- resume(approved=False) aborts cleanly
- resume() re-checks policy against fresh state (DENY still wins)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.runner import AgentRunner
from app.agent.field_mapper_models import (
    FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
)
from app.models.page_state import (
    AuthenticationState, ElementState, PageObservation, PageState,
)
from app.models.workflow_state import WorkflowStatus
from app.vault.resolver import UserVault


def _make_runner() -> AgentRunner:
    """Runner with a populated vault — deterministic planning only emits
    fills it can actually resolve (audit C4)."""
    return AgentRunner(llm=None, vault=UserVault(
        full_name="Rajesh Kumar Singh",
        aadhaar_number="1234 5678 9012",
    ))


def _make_element(
    ref: str,
    *,
    role: str = "textbox",
    accessible_name: str = "",
) -> ElementState:
    return ElementState(
        ref=ref, role=role, accessible_name=accessible_name,
        label_text=accessible_name, value="",
    )


def _make_observation(elements, *, obs_id: str = "obs_test") -> PageObservation:
    page_state = PageState(
        url="https://uidai.gov.in/form",
        title="Form",
        page_type="form",
        elements=elements,
        authentication=AuthenticationState(),
    )
    return PageObservation(page_state=page_state, aria_snapshot="", observation_id=obs_id)


def _mapping(bindings: list[FieldBinding]) -> MappingResult:
    return MappingResult(
        bindings=bindings,
        unmapped_fields=[],
        ambiguous_fields=[],
        total_fields=len(bindings),
        mapped_count=len(bindings),
    )


def _sensitive_mapping() -> MappingResult:
    return _mapping([
        FieldBinding(
            field_ref="e1", binding="USER.aadhaar_number",
            confidence=MappingConfidence.HIGH,
            strategy=MappingStrategy.DETERMINISTIC,
            field_type="textbox",
        ),
    ])


def _ok_result(observation):
    result = MagicMock()
    result.success = True
    result.user_action_required = False
    result.recovery_required = False
    result.verification = MagicMock()
    result.verification.status.value = "success"
    result.post_observation = observation
    result.message = "OK"
    return result


class TestConfirmationHalt:
    @pytest.mark.asyncio
    async def test_sensitive_fill_halts_with_pending_action(self):
        runner = _make_runner()
        mock_page = MagicMock()
        elements = [_make_element("e1", accessible_name="Enter Aadhaar Number")]
        observation = _make_observation(elements)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_sensitive_mapping()):
                workflow = await runner.run(mock_page, task="Fill Aadhaar")

        assert workflow.status == WorkflowStatus.READY_FOR_CONFIRMATION
        assert workflow.pending_action is not None
        assert workflow.pending_action["action"] == "fill"
        assert workflow.pending_action["value_ref"] == "USER.aadhaar_number"
        assert workflow.pending_observation_id == observation.observation_id
        # Nothing executed
        assert workflow.total_actions == 0

    @pytest.mark.asyncio
    async def test_public_fill_does_not_halt(self):
        runner = _make_runner()
        mock_page = MagicMock()
        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)
        mapping = _mapping([
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ])

        async def fake_execute(page, action, obs, **kwargs):
            assert kwargs.get("user_confirmed") is not True
            return _ok_result(obs)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute", side_effect=fake_execute):
                    workflow = await runner.run(mock_page, task="Fill name")

        # full_name is PUBLIC → no confirmation gate; action executed
        assert workflow.total_actions == 1
        assert workflow.status != WorkflowStatus.READY_FOR_CONFIRMATION


class TestResume:
    @pytest.mark.asyncio
    async def test_resume_approved_executes_and_continues(self):
        runner = _make_runner()
        mock_page = MagicMock()
        elements = [_make_element("e1", accessible_name="Enter Aadhaar Number")]
        observation = _make_observation(elements)

        calls = []

        async def fake_execute(page, action, obs, **kwargs):
            calls.append(kwargs.get("user_confirmed"))
            return _ok_result(obs)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_sensitive_mapping()):
                with patch.object(runner._executor, "execute", side_effect=fake_execute):
                    workflow = await runner.run(mock_page, task="Fill")
                    assert workflow.status == WorkflowStatus.READY_FOR_CONFIRMATION

                    workflow = await runner.resume(
                        page=mock_page, workflow=workflow, approved=True,
                    )

        # The confirmed action executed exactly once, with user_confirmed=True
        assert calls == [True]
        assert workflow.total_actions == 1
        assert workflow.actions_taken[0].success is True
        # Pending state cleared; workflow resumed RUNNING then continued looping
        assert workflow.pending_action is None

    @pytest.mark.asyncio
    async def test_resume_declined_aborts(self):
        runner = _make_runner()
        mock_page = MagicMock()
        elements = [_make_element("e1", accessible_name="Enter Aadhaar Number")]
        observation = _make_observation(elements)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_sensitive_mapping()):
                workflow = await runner.run(mock_page, task="Fill")

        execute_spy = AsyncMock(side_effect=lambda *a, **k: _ok_result(observation))
        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._executor, "execute", side_effect=execute_spy):
                workflow = await runner.resume(
                    page=mock_page, workflow=workflow, approved=False,
                )

        assert workflow.status == WorkflowStatus.ABORTED
        execute_spy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_without_pending_fails_cleanly(self):
        runner = _make_runner()
        from app.models.workflow_state import WorkflowState
        wf = WorkflowState(status=WorkflowStatus.RUNNING)
        result = await runner.resume(MagicMock(), wf, approved=True)
        assert result.status == WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_resume_rechecks_policy_deny_wins(self):
        """If fresh policy says DENY after resume, do not execute."""
        runner = _make_runner()
        mock_page = MagicMock()
        elements = [_make_element("e1", accessible_name="Enter Aadhaar Number")]
        observation = _make_observation(elements)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_sensitive_mapping()):
                workflow = await runner.run(mock_page, task="Fill")

        execute_spy = AsyncMock(side_effect=lambda *a, **k: _ok_result(observation))
        denied = MagicMock()
        denied.blocked = True
        denied.needs_user = False
        denied.needs_confirmation = False
        denied.reason = "now denied"
        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._policy, "evaluate", return_value=denied):
                with patch.object(runner._executor, "execute", side_effect=execute_spy):
                    workflow = await runner.resume(
                        page=mock_page, workflow=workflow, approved=True,
                    )

        execute_spy.assert_not_awaited()
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER
