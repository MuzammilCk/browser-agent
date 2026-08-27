"""Phase 6 — wire the existing vision utilities into the loop (Z7 / P0-16).

When semantic planning honestly reports NO_VALID_ACTION on an observation
assessed as incomplete (VISUAL_REQUIRED analog), the runner attempts
exactly one vision-fallback pass — screenshot → vision model → grounded
element → single Playwright click — before surfacing WAITING_FOR_USER.
Disabled flag skips the path entirely. Ungroundable vision answers are
never guessed into actions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.field_mapper_models import MappingResult
from app.agent.runner import AgentRunner
from app.browser.vision import assess_completeness
from app.models.page_state import (
    ElementState, PageObservation, PageState,
)
from app.models.workflow_state import WorkflowStatus
from app.vault.resolver import UserVault


def _el(ref: str, role: str, name: str) -> ElementState:
    return ElementState(
        ref=ref, role=role, accessible_name=name, label_text=name,
    )


def _nav_observation(*, aria_snapshot: str = "") -> PageObservation:
    """Portal landing page: links only — deterministic planner finds
    nothing (it only clicks submit-ish BUTTONS), so planning reports
    NO_VALID_ACTION honestly."""
    page_state = PageState(
        url="https://portal.gov.in/home",
        title="Portal Home",
        page_type="navigation",
        elements=[
            _el("e1", "link", "Home"),
            _el("e2", "link", "About Us"),
            _el("e3", "link", "Apply For Certificate"),
        ],
    )
    return PageObservation(
        page_state=page_state,
        aria_snapshot=aria_snapshot,
        observation_id="obs_nav",
    )


def _resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.parsed = payload
    resp.content = ""
    return resp


def _make_fake_llm(vision_payload_or_exc):
    """LLM mock where PLANNING calls stall honestly and VISION calls
    (those carrying images) answer with the given payload/exception."""
    calls: list[dict] = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        if "images" in kwargs:
            if isinstance(vision_payload_or_exc, Exception):
                raise vision_payload_or_exc
            return _resp(vision_payload_or_exc)
        return _resp({"action": "stop",
                      "reason": "semantic planner stalled on this page"})

    mock = MagicMock()
    mock.model_name = "test/mock"
    mock.complete = AsyncMock(side_effect=fake_complete)
    return mock, calls


def _make_runner(llm=None, *, vision_enabled=True) -> AgentRunner:
    return AgentRunner(
        llm=llm,
        vault=UserVault(full_name="Test User"),
        vision_fallback_enabled=vision_enabled,
    )


class TestCompletenessGate:
    def test_navigation_page_with_named_links_is_sufficient(self):
        assessment = assess_completeness(_nav_observation())
        assert assessment.is_sufficient

    def test_empty_page_is_insufficient(self):
        page_state = PageState(url="x", title="", page_type="unknown")
        obs = PageObservation(page_state=page_state, aria_snapshot="", observation_id="o")
        assessment = assess_completeness(obs)
        assert not assessment.is_sufficient
        assert "no_interactive_elements" in assessment.missing_signals


class TestVisionFallbackIntegration:
    @pytest.mark.asyncio
    async def test_stall_triggers_exactly_one_vision_attempt(self):
        """Acceptance: NO_VALID_ACTION → exactly one vision attempt,
        visible in checkpoints, producing a grounded click; afterwards the
        workflow surfaces WAITING_FOR_USER (budget spent)."""
        mock_llm, calls = _make_fake_llm({
            "found_target": True,
            "action_type": "click",
            "target_name": "Apply For Certificate",
            "reason": "Primary task link visible on screen",
        })

        runner = _make_runner(mock_llm)
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG-bytes")

        executed = []

        async def mock_execute(page, action, obs, *a, **kw):
            executed.append(action)
            result = MagicMock()
            result.success = True
            result.user_action_required = False
            result.recovery_required = False
            result.verification = MagicMock()
            result.verification.status.value = "success"
            result.post_observation = None   # force fresh observe next iter
            result.message = "clicked"
            return result

        with patch.object(runner._observer, "observe",
                          return_value=_nav_observation()), \
             patch.object(runner._mapper, "map_fields",
                          return_value=MappingResult()), \
             patch.object(runner._executor, "execute", side_effect=mock_execute):
            workflow = await runner.run(mock_page, task="Apply for certificate")

        # Exactly one VISION call (images-carrying) across all iterations
        # — planning calls carry no images.
        vision_calls = [c for c in calls if "images" in c]
        assert len(vision_calls) == 1
        assert vision_calls[0]["images"] == [b"\x89PNG-bytes"]

        # The grounded click actually executed
        assert len(executed) == 1
        assert executed[0].action == "click"
        assert executed[0].target_ref == "e3"

        assert workflow.vision_fallback_attempts == 1
        assert any("Vision fallback" in c for c in workflow.checkpoints)
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_disabled_flag_skips_vision_entirely(self):
        mock_llm, calls = _make_fake_llm({"found_target": False})

        runner = _make_runner(mock_llm, vision_enabled=False)
        mock_page = MagicMock()

        with patch.object(runner._observer, "observe",
                          return_value=_nav_observation()), \
             patch.object(runner._mapper, "map_fields",
                          return_value=MappingResult()):
            workflow = await runner.run(mock_page, task="Apply")

        assert not any("images" in c for c in calls), \
            "no screenshot may be sent when vision is disabled"
        assert workflow.vision_fallback_attempts == 0
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_ungroundable_target_never_guessed(self):
        """Vision names an element that is not in the observation → no
        action may be constructed (P0-41 no-guess)."""
        mock_llm, calls = _make_fake_llm({
            "found_target": True,
            "action_type": "click",
            "target_name": "Totally Invisible Widget",
            "reason": "looks clickable",
        })

        runner = _make_runner(mock_llm)
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG")

        with patch.object(runner._observer, "observe",
                          return_value=_nav_observation()), \
             patch.object(runner._mapper, "map_fields",
                          return_value=MappingResult()), \
             patch.object(runner._executor, "execute") as mock_exec:
            workflow = await runner.run(mock_page, task="Apply")

        mock_exec.assert_not_called()
        assert workflow.total_actions == 0
        assert workflow.vision_fallback_attempts == 1
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_vision_not_found_reports_stall(self):
        mock_llm, _ = _make_fake_llm({
            "found_target": False,
            "reason": "nothing task-relevant on screen",
        })

        runner = _make_runner(mock_llm)
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG")

        with patch.object(runner._observer, "observe",
                          return_value=_nav_observation()), \
             patch.object(runner._mapper, "map_fields",
                          return_value=MappingResult()):
            workflow = await runner.run(mock_page, task="Apply")

        assert workflow.total_actions == 0
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_vision_transport_failure_fails_loud_not_crash(self):
        mock_llm, _ = _make_fake_llm(Exception("vision timeout"))

        runner = _make_runner(mock_llm)
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG")

        with patch.object(runner._observer, "observe",
                          return_value=_nav_observation()), \
             patch.object(runner._mapper, "map_fields",
                          return_value=MappingResult()):
            workflow = await runner.run(mock_page, task="Apply")

        assert workflow.status == WorkflowStatus.WAITING_FOR_USER
        assert workflow.vision_fallback_attempts == 1
