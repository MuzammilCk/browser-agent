"""Phase 1 — typed planning result + honest workflow status.

Implements audit findings Z2 / Z5 / Z8 and completes P0-13 / P0-37 from
context_fix_plan.md:

- ``PlanOutcome`` replaces the overloaded ``BrowserAction | None``
- page_type-aware dispatch: a stall on navigation/unknown pages is
  WAITING_FOR_USER, never READY_FOR_SUBMISSION
- an unparseable structured LLM response is a surfaced error, not silence
- planning_mode / llm_model / llm_disabled_reason are on WorkflowState
  from the very first iteration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.field_mapper_models import (
    FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
)
from app.agent.planner import plan_deterministic, plan_with_llm
from app.agent.planning_result import (
    ActionPlanned, NoValidAction, PlanLLMError, TaskComplete,
)
from app.agent.runner import AgentRunner
from app.models.page_state import (
    ElementState, PageObservation, PageState,
)
from app.models.workflow_state import WorkflowState, WorkflowStatus
from app.vault.resolver import UserVault


def _make_runner(**kwargs) -> AgentRunner:
    return AgentRunner(llm=None, vault=UserVault(full_name="Test User"), **kwargs)


def _make_element(
    ref: str,
    *,
    role: str = "textbox",
    accessible_name: str = "",
) -> ElementState:
    return ElementState(
        ref=ref,
        role=role,
        accessible_name=accessible_name,
        label_text=accessible_name,
    )


def _make_observation(
    elements: list[ElementState] | None = None,
    *,
    page_type: str = "form",
    obs_id: str = "obs_test",
) -> PageObservation:
    page_state = PageState(
        url="https://example.gov.in/page",
        title="Portal",
        page_type=page_type,
        elements=elements or [],
    )
    return PageObservation(
        page_state=page_state,
        aria_snapshot="",
        observation_id=obs_id,
    )


def _clean_mapping() -> MappingResult:
    """Zero unmapped, zero ambiguous — nothing left to map."""
    return MappingResult(bindings=[], unmapped_fields=[])


# ============================================================
# Planner-level typed outcomes
# ============================================================


class TestPlanWithLLMOutcomes:
    @pytest.mark.asyncio
    async def test_valid_response_yields_action_planned(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {
            "action": "fill",
            "target_ref": "e1",
            "value_ref": "USER.full_name",
        }
        mock_llm.complete = AsyncMock(return_value=mock_response)

        wf = WorkflowState()
        obs = _make_observation([_make_element("e1", accessible_name="Full Name")])
        outcome = await plan_with_llm(mock_llm, wf, obs, _clean_mapping())

        assert isinstance(outcome, ActionPlanned)
        assert outcome.action.action == "fill"
        assert outcome.action.target_ref == "e1"

    @pytest.mark.asyncio
    async def test_gateway_exception_yields_llm_error(self):
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API error"))

        wf = WorkflowState()
        outcome = await plan_with_llm(
            mock_llm, wf, _make_observation(), _clean_mapping(),
        )

        assert isinstance(outcome, PlanLLMError)
        assert "API error" in outcome.message

    @pytest.mark.asyncio
    async def test_unparseable_structured_response_yields_llm_error(self):
        """Z5: malformed JSON under a schema request must be an error,
        not silently identical to 'nothing to do'."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.content = "```json\n{\"action\": \"fill\", \"target\""
        mock_llm.complete = AsyncMock(return_value=mock_response)

        wf = WorkflowState()
        outcome = await plan_with_llm(
            mock_llm, wf, _make_observation(), _clean_mapping(),
        )

        assert isinstance(outcome, PlanLLMError)

    @pytest.mark.asyncio
    async def test_deliberate_stop_yields_no_valid_action_with_reason(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {"action": "stop", "reason": "target not present"}
        mock_llm.complete = AsyncMock(return_value=mock_response)

        wf = WorkflowState()
        outcome = await plan_with_llm(
            mock_llm, wf, _make_observation(), _clean_mapping(),
        )

        assert isinstance(outcome, NoValidAction)
        assert "target not present" in outcome.reason

    @pytest.mark.asyncio
    async def test_stop_on_success_page_yields_task_complete(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {"action": "stop", "reason": "done"}
        mock_llm.complete = AsyncMock(return_value=mock_response)

        wf = WorkflowState()
        obs = _make_observation([], page_type="success")
        outcome = await plan_with_llm(mock_llm, wf, obs, _clean_mapping())

        assert isinstance(outcome, TaskComplete)


class TestDeterministicOutcomes:
    def test_resolvable_binding_yields_action_planned(self):
        class _Resolver:
            def resolve(self, ref):
                return "Test User"

        elements = [_make_element("e1", accessible_name="Full Name")]
        binding = FieldBinding(
            field_ref="e1", binding="USER.full_name",
            confidence=MappingConfidence.HIGH,
            strategy=MappingStrategy.DETERMINISTIC,
            field_type="textbox",
        )
        outcome = plan_deterministic(
            WorkflowState(), _make_observation(elements),
            MappingResult(bindings=[binding]),
            value_resolver=_Resolver(),
        )
        assert isinstance(outcome, ActionPlanned)
        assert outcome.action.action == "fill"

    def test_exhausted_planner_yields_no_valid_action_with_reason(self):
        outcome = plan_deterministic(
            WorkflowState(), _make_observation([]), _clean_mapping(),
        )
        assert isinstance(outcome, NoValidAction)
        assert outcome.reason


# ============================================================
# Runner dispatch — page_type-aware (closes Z2)
# ============================================================


class TestPlanOutcomeDispatch:
    def _dispatch(self, workflow, outcome, *, page_type, mapping=None):
        runner = _make_runner()
        workflow.current_page_type = page_type
        runner._handle_plan_outcome(
            workflow, outcome, mapping or _clean_mapping(),
        )

    def test_navigation_stall_is_waiting_for_user_never_ready(self):
        wf = WorkflowState(actions_taken=[])
        self._dispatch(wf, NoValidAction(reason="no matching link"),
                       page_type="navigation")
        assert wf.status == WorkflowStatus.WAITING_FOR_USER
        assert wf.error_message

    def test_unknown_page_stall_is_waiting_for_user(self):
        wf = WorkflowState()
        self._dispatch(wf, NoValidAction(reason="nothing found"),
                       page_type="unknown")
        assert wf.status == WorkflowStatus.WAITING_FOR_USER

    def test_clean_form_is_legitimate_ready_for_submission(self):
        wf = WorkflowState(submission_state="not_ready")
        self._dispatch(wf, NoValidAction(reason="all fields satisfied"),
                       page_type="form")
        assert wf.status == WorkflowStatus.READY_FOR_SUBMISSION

    def test_form_with_unmapped_fields_waits_for_user(self):
        wf = WorkflowState()
        mapping = MappingResult(unmapped_fields=["e9"], ambiguous_fields=["e10"])
        self._dispatch(wf, NoValidAction(reason="gave up"), page_type="form",
                       mapping=mapping)
        assert wf.status == WorkflowStatus.WAITING_FOR_USER

    def test_task_complete_on_success_page_completes(self):
        wf = WorkflowState()
        self._dispatch(wf, TaskComplete(reason="acknowledged"),
                       page_type="success")
        assert wf.status == WorkflowStatus.COMPLETED

    def test_task_complete_off_success_page_does_not_complete(self):
        wf = WorkflowState()
        self._dispatch(wf, TaskComplete(reason="done?"), page_type="form")
        assert wf.status != WorkflowStatus.COMPLETED

    def test_llm_error_surfaces_message_and_waits_for_user(self):
        wf = WorkflowState()
        self._dispatch(wf, PlanLLMError(message="unparseable structured "
                                                "response"), page_type="form")
        assert wf.status == WorkflowStatus.WAITING_FOR_USER
        assert "unparseable" in wf.error_message


# ============================================================
# End-to-end through run() — the exact Z2 scenario
# ============================================================


class TestNavigationStallEndToEnd:
    @pytest.mark.asyncio
    async def test_menu_page_zero_actions_reports_waiting_not_ready(self):
        """The near-universal first-page scenario: portal landing page with
        links only, nothing mapped yet. Must be reported as stalled."""
        runner = _make_runner()
        mock_page = MagicMock()

        elements = [
            _make_element("e1", role="link", accessible_name="Home"),
            _make_element("e2", role="link", accessible_name="About Us"),
            _make_element("e3", role="button", accessible_name="Search"),
        ]
        observation = _make_observation(elements, page_type="navigation")

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields",
                              return_value=_clean_mapping()):
                workflow = await runner.run(mock_page, task="Apply online")

        assert workflow.actions_taken == []
        assert workflow.status != WorkflowStatus.READY_FOR_SUBMISSION
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_malformed_llm_run_never_reports_ready(self):
        """Z5 end-to-end: garbage LLM output on a clean form page must not
        be mislabeled as submission-ready."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.content = "I cannot answer in JSON, sorry!"
        mock_llm.complete = AsyncMock(return_value=mock_response)

        runner = AgentRunner(llm=mock_llm, vault=UserVault(full_name="Test User"))
        mock_page = MagicMock()

        with patch.object(runner._observer, "observe",
                          return_value=_make_observation()):
            with patch.object(runner._mapper, "map_fields",
                              return_value=_clean_mapping()):
                workflow = await runner.run(mock_page, task="Fill form")

        assert workflow.status != WorkflowStatus.READY_FOR_SUBMISSION
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER
        assert workflow.error_message


# ============================================================
# Planning-mode visibility (closes Z8 / P0-37)
# ============================================================


class TestPlanningModeVisibility:
    @pytest.mark.asyncio
    async def test_deterministic_fallback_declared_when_no_llm(self):
        runner = _make_runner()
        mock_page = MagicMock()

        with patch.object(runner._observer, "observe",
                          return_value=_make_observation()):
            with patch.object(runner._mapper, "map_fields",
                              return_value=_clean_mapping()):
                workflow = await runner.run(mock_page, task="Test")

        assert workflow.planning_mode == "deterministic_fallback"
        assert workflow.llm_disabled_reason
        assert workflow.llm_model is None

    @pytest.mark.asyncio
    async def test_llm_mode_declared_and_reason_cleared(self):
        mock_llm = MagicMock()
        mock_llm.model_name = "test/mock-model"
        mock_response = MagicMock()
        mock_response.parsed = {"action": "stop", "reason": "nothing"}
        mock_llm.complete = AsyncMock(return_value=mock_response)

        runner = AgentRunner(llm=mock_llm, vault=UserVault(full_name="T"))
        mock_page = MagicMock()

        with patch.object(runner._observer, "observe",
                          return_value=_make_observation()):
            with patch.object(runner._mapper, "map_fields",
                              return_value=_clean_mapping()):
                workflow = await runner.run(mock_page, task="Test")

        assert workflow.planning_mode == "llm"
        assert workflow.llm_model == "test/mock-model"
        assert workflow.llm_disabled_reason is None

    def test_explicit_disabled_reason_preserved(self):
        runner = AgentRunner(
            llm=None, llm_disabled_reason="gateway_init_failed: boom",
        )
        ws = WorkflowState()
        runner._apply_planning_metadata(ws)
        assert ws.planning_mode == "deterministic_fallback"
        assert ws.llm_disabled_reason == "gateway_init_failed: boom"
