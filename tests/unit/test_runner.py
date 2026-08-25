"""Tests for AgentRunner — full observe→map→plan→execute→verify loop.

Audit issues covered: #25, #26, #28, #43
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.runner import AgentRunner
from app.agent.field_mapper_models import FieldBinding, MappingConfidence, MappingResult, MappingStrategy
from app.models.page_state import (
    AuthenticationState,
    ElementState,
    PageObservation,
    PageState,
)
from app.models.workflow_state import WorkflowState, WorkflowStatus
from app.policy.engine import PolicyDecision, PolicyEngine
from app.vault.resolver import UserVault


def _make_runner(**kwargs) -> AgentRunner:
    """Runner with a populated vault — deterministic planning only emits
    fills it can actually resolve (audit C4)."""
    return AgentRunner(llm=None, vault=UserVault(full_name="Test User"), **kwargs)


def _runner_with_llm(mock_llm) -> AgentRunner:
    return AgentRunner(llm=mock_llm, vault=UserVault(full_name="Test User"))


def _make_element(
    ref: str,
    *,
    role: str = "textbox",
    accessible_name: str = "",
    label_text: str = "",
    value: str = "",
    required: bool = False,
    disabled: bool = False,
    selected_options: list[str] | None = None,
) -> ElementState:
    return ElementState(
        ref=ref,
        role=role,
        accessible_name=accessible_name,
        label_text=label_text,
        value=value,
        required=required,
        disabled=disabled,
        selected_options=selected_options or [],
    )


def _make_observation(
    elements: list[ElementState] | None = None,
    *,
    url: str = "https://example.gov.in/form",
    page_type: str = "form",
    auth_detected: bool = False,
    auth_type: str | None = None,
    obs_id: str = "obs_test",
) -> PageObservation:
    auth = AuthenticationState(
        detected=auth_detected,
        challenge_type=auth_type,
        confidence=0.9 if auth_detected else 0.0,
    )
    page_state = PageState(
        url=url,
        title="Application Form",
        page_type=page_type,
        elements=elements or [],
        authentication=auth,
    )
    return PageObservation(
        page_state=page_state,
        aria_snapshot="",
        observation_id=obs_id,
    )


def _make_mapping_result(
    bindings: list[FieldBinding] | None = None,
    unmapped: list[str] | None = None,
) -> MappingResult:
    return MappingResult(
        bindings=bindings or [],
        unmapped_fields=unmapped or [],
        total_fields=len(bindings) if bindings else 0,
        mapped_count=len(bindings) if bindings else 0,
    )


# ============================================================
# WorkflowState Tests
# ============================================================


class TestWorkflowState:
    """Test WorkflowState model."""

    def test_initial_state(self):
        ws = WorkflowState()
        assert ws.status == WorkflowStatus.INITIALIZED
        assert ws.total_actions == 0
        assert ws.completed_bindings == []
        assert ws.pending_fields == []

    def test_record_action_success(self):
        ws = WorkflowState()
        from app.models.workflow_state import ActionRecord
        record = ActionRecord(
            action_type="fill",
            target_ref="e1",
            success=True,
        )
        ws.record_action(record)
        assert ws.total_actions == 1
        assert ws.successful_actions == 1
        assert "e1" in ws.completed_bindings

    def test_record_action_failure(self):
        ws = WorkflowState()
        from app.models.workflow_state import ActionRecord
        record = ActionRecord(
            action_type="fill",
            target_ref="e1",
            success=False,
        )
        ws.record_action(record)
        assert ws.total_actions == 1
        assert ws.failed_actions == 1

    def test_mark_field_completed(self):
        ws = WorkflowState()
        ws.pending_fields = ["e1", "e2"]
        ws.mark_field_completed("e1")
        assert "e1" in ws.completed_bindings
        assert "e1" not in ws.pending_fields
        assert "e2" in ws.pending_fields

    def test_can_retry(self):
        ws = WorkflowState(max_recovery_attempts=3)
        assert ws.can_retry() is True
        ws.recovery_attempts = 3
        assert ws.can_retry() is False

    def test_increment_recovery(self):
        ws = WorkflowState()
        ws.increment_recovery()
        assert ws.recovery_attempts == 1

    def test_reset_recovery(self):
        ws = WorkflowState()
        ws.recovery_attempts = 2
        ws.reset_recovery()
        assert ws.recovery_attempts == 0

    def test_summary(self):
        ws = WorkflowState(workflow_id="test123", domain="example.gov.in")
        summary = ws.summary()
        assert "test123" in summary
        assert "example.gov.in" in summary


# ============================================================
# Authentication Checkpoint Tests
# ============================================================


class TestAuthenticationCheckpoints:
    """Test that CAPTCHA/OTP/password cause workflow to pause."""

    @pytest.mark.asyncio
    async def test_captcha_pauses_workflow(self):
        runner = _make_runner()
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Enter CAPTCHA")]
        observation = _make_observation(
            elements, auth_detected=True, auth_type="captcha"
        )

        with patch.object(runner._observer, "observe", return_value=observation):
            workflow = await runner.run(mock_page, task="Test")

        # Audit C10: CAPTCHA gets its own, more precise status
        assert workflow.status in (
            WorkflowStatus.WAITING_FOR_CAPTCHA,
            WorkflowStatus.WAITING_FOR_AUTH,
        )
        assert "captcha" in workflow.checkpoints

    @pytest.mark.asyncio
    async def test_otp_pauses_workflow(self):
        runner = _make_runner()
        mock_page = MagicMock()

        observation = _make_observation(
            [_make_element("e1", accessible_name="Enter OTP")],
            auth_detected=True, auth_type="otp",
        )

        with patch.object(runner._observer, "observe", return_value=observation):
            workflow = await runner.run(mock_page, task="Test")

        assert workflow.status == WorkflowStatus.WAITING_FOR_AUTH
        assert "otp" in workflow.checkpoints

    @pytest.mark.asyncio
    async def test_password_pauses_workflow(self):
        runner = _make_runner()
        mock_page = MagicMock()

        observation = _make_observation(
            [_make_element("e1", accessible_name="Password")],
            auth_detected=True, auth_type="password",
        )

        with patch.object(runner._observer, "observe", return_value=observation):
            workflow = await runner.run(mock_page, task="Test")

        assert workflow.status == WorkflowStatus.WAITING_FOR_AUTH


# ============================================================
# Deterministic Planning Tests
# ============================================================


class TestDeterministicPlanning:
    """Test deterministic planning without LLM."""

    @pytest.mark.asyncio
    async def test_fills_fields_in_order(self):
        runner = _make_runner()
        mock_page = MagicMock()

        elements = [
            _make_element("e1", accessible_name="Full Name"),
            _make_element("e2", accessible_name="Email"),
        ]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute") as mock_exec:
                    mock_result = MagicMock()
                    mock_result.success = True
                    mock_result.user_action_required = False
                    mock_result.recovery_required = False
                    mock_result.verification = MagicMock()
                    mock_result.verification.status.value = "success"
                    mock_result.post_observation = observation
                    mock_result.message = "OK"
                    mock_exec.return_value = mock_result

                    workflow = await runner.run(mock_page, task="Fill form")

        # Should have executed at least one fill action
        assert workflow.total_actions >= 1
        assert workflow.actions_taken[0].action_type == "fill"

    @pytest.mark.asyncio
    async def test_clicks_submit_after_filling(self):
        runner = _make_runner()
        mock_page = MagicMock()

        elements = [
            _make_element("e1", accessible_name="Full Name", role="textbox"),
            _make_element("e2", accessible_name="Submit Application", role="button"),
        ]
        observation = _make_observation(elements)

        # All fields already completed
        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute") as mock_exec:
                    mock_result = MagicMock()
                    mock_result.success = True
                    mock_result.user_action_required = False
                    mock_result.recovery_required = False
                    mock_result.verification = MagicMock()
                    mock_result.verification.status.value = "success"
                    mock_result.post_observation = observation
                    mock_result.message = "OK"
                    mock_exec.return_value = mock_result

                    workflow = await runner.run(
                        mock_page, task="Fill and submit"
                    )
                    workflow.completed_bindings = ["e1"]

        # Should eventually try to click submit — or halt at confirmation gate (audit B2)
        action_types = [a.action_type for a in workflow.actions_taken]
        assert "click" in action_types or workflow.status in (
            WorkflowStatus.READY_FOR_SUBMISSION,
            WorkflowStatus.WAITING_FOR_USER,
            WorkflowStatus.READY_FOR_CONFIRMATION,  # B2: submit button now correctly gated
        )

    @pytest.mark.asyncio
    async def test_stops_when_no_action_needed(self):
        runner = _make_runner()
        mock_page = MagicMock()

        observation = _make_observation([])
        mapping = _make_mapping_result([])

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                workflow = await runner.run(mock_page, task="Empty page")

        # No elements → no action → workflow should finish
        assert workflow.status in (
            WorkflowStatus.READY_FOR_SUBMISSION,
            WorkflowStatus.WAITING_FOR_USER,
        )


# ============================================================
# LLM Planning Tests (Mocked)
# ============================================================


class TestLLMPlanning:
    """Test LLM-based planning."""

    @pytest.mark.asyncio
    async def test_llm_produces_action(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {
            "action": "fill",
            "target_ref": "e1",
            "value_ref": "USER.full_name",
            "confidence": 0.9,
        }
        mock_llm.complete = AsyncMock(return_value=mock_response)

        runner = _runner_with_llm(mock_llm)
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute") as mock_exec:
                    mock_result = MagicMock()
                    mock_result.success = True
                    mock_result.user_action_required = False
                    mock_result.recovery_required = False
                    mock_result.verification = MagicMock()
                    mock_result.verification.status.value = "success"
                    mock_result.post_observation = observation
                    mock_result.message = "OK"
                    mock_exec.return_value = mock_result

                    workflow = await runner.run(mock_page, task="Fill form")

        assert workflow.total_actions >= 1

    @pytest.mark.asyncio
    async def test_llm_stop_action(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {"action": "stop"}
        mock_llm.complete = AsyncMock(return_value=mock_response)

        runner = _runner_with_llm(mock_llm)
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)
        mapping = _make_mapping_result([])

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                workflow = await runner.run(mock_page, task="Stop immediately")

        # LLM said stop → no actions taken
        assert workflow.total_actions == 0

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API error"))

        runner = _runner_with_llm(mock_llm)
        mock_page = MagicMock()

        observation = _make_observation([])
        mapping = _make_mapping_result([])

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                workflow = await runner.run(mock_page, task="Test")

        # Should not crash, should finish gracefully
        assert workflow.status in (
            WorkflowStatus.READY_FOR_SUBMISSION,
            WorkflowStatus.WAITING_FOR_USER,
        )


# ============================================================
# Recovery Logic Tests
# ============================================================


class TestRecoveryLogic:
    """Test bounded retry and recovery."""

    @pytest.mark.asyncio
    async def test_recovery_on_failure(self):
        runner = _make_runner(max_iterations=5)
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        call_count = 0

        async def mock_execute(page, action, obs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.success = False
            result.user_action_required = False
            result.recovery_required = True
            result.verification = MagicMock()
            result.verification.status.value = "failure"
            result.post_observation = obs
            result.message = "Simulated failure"
            return result

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(mock_page, task="Test recovery")

        # Should have attempted recovery up to max
        assert workflow.failed_actions > 0
        assert workflow.recovery_attempts > 0

    @pytest.mark.asyncio
    async def test_stops_after_max_recovery(self):
        runner = _make_runner(max_iterations=3)
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        async def mock_execute(page, action, obs):
            result = MagicMock()
            result.success = False
            result.user_action_required = False
            result.recovery_required = True
            result.verification = MagicMock()
            result.verification.status.value = "failure"
            result.post_observation = obs
            result.message = "Always fails"
            return result

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(mock_page, task="Test max recovery")

        assert workflow.status == WorkflowStatus.FAILED


# ============================================================
# Max Iterations Test
# ============================================================


class TestMaxIterations:
    """Test that runner stops at max iterations."""

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations(self):
        runner = _make_runner(max_iterations=2)
        mock_page = MagicMock()

        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping = _make_mapping_result(bindings)

        async def mock_execute(page, action, obs):
            result = MagicMock()
            result.success = True
            result.user_action_required = False
            result.recovery_required = False
            result.verification = MagicMock()
            result.verification.status.value = "success"
            result.post_observation = obs
            result.message = "OK"
            return result

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(mock_page, task="Infinite loop test")

        # Should have stopped at max iterations
        assert workflow.total_actions <= 2
