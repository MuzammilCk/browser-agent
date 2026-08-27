"""Repeated-identical-action stall detector — audit Phase 9 tests.

Two levels:
1. the pure detector (signature, fingerprint, repeat evaluation);
2. the runner behaviour — an agent that keeps planning the same action
   against an unchanged page must stop with a LABELED stall
   (`repeated_action_no_progress`), not a generic max-iteration failure,
   and a workflow that is genuinely progressing must never trip it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.field_mapper_models import (
    FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
)
from app.agent.runner import AgentRunner
from app.agent.stall_detector import (
    REPEATED_ACTION_LIMIT,
    STALL_REASON_REPEATED_ACTION,
    build_signature,
    evaluate_repeat,
    page_fingerprint,
)
from app.models.actions import BrowserAction
from app.models.page_state import (
    AlertState, ElementState, PageObservation, PageState, TabsState,
)
from app.models.workflow_state import WorkflowStatus
from app.vault.resolver import UserVault


def _element(ref: str, **kwargs) -> ElementState:
    defaults = {"ref": ref, "role": "textbox", "accessible_name": "Full Name"}
    defaults.update(kwargs)
    return ElementState(**defaults)


def _observation(
    elements: list[ElementState] | None = None,
    *,
    url: str = "https://example.gov.in/form",
    page_type: str = "form",
    obs_id: str = "obs_1",
    alerts: list[AlertState] | None = None,
    tabs: TabsState | None = None,
) -> PageObservation:
    return PageObservation(
        page_state=PageState(
            url=url,
            title="Form",
            page_type=page_type,
            elements=elements if elements is not None else [_element("e1")],
            alerts=alerts or [],
            tabs=tabs or TabsState(),
        ),
        aria_snapshot="",
        observation_id=obs_id,
    )


# ── 1. The pure detector ───────────────────────────────────


class TestPageFingerprint:
    def test_identical_pages_match(self) -> None:
        a = _observation(obs_id="obs_1")
        b = _observation(obs_id="obs_2")  # observation id must not matter
        assert page_fingerprint(a) == page_fingerprint(b)

    def test_changed_value_changes_fingerprint(self) -> None:
        a = _observation([_element("e1", value="")])
        b = _observation([_element("e1", value="Rahul Sharma")])
        assert page_fingerprint(a) != page_fingerprint(b)

    def test_new_element_changes_fingerprint(self) -> None:
        a = _observation([_element("e1")])
        b = _observation([_element("e1"), _element("e2", accessible_name="Email")])
        assert page_fingerprint(a) != page_fingerprint(b)

    def test_new_alert_changes_fingerprint(self) -> None:
        a = _observation()
        b = _observation(alerts=[AlertState(ref="a1", text="Saved")])
        assert page_fingerprint(a) != page_fingerprint(b)

    def test_new_tab_counts_as_change(self) -> None:
        """Opening a tab IS progress — it must reset the repeat counter."""
        a = _observation(tabs=TabsState(total=1))
        b = _observation(tabs=TabsState(total=2))
        assert page_fingerprint(a) != page_fingerprint(b)

    def test_checked_state_changes_fingerprint(self) -> None:
        a = _observation([_element("e1", role="checkbox", checked=False)])
        b = _observation([_element("e1", role="checkbox", checked=True)])
        assert page_fingerprint(a) != page_fingerprint(b)


class TestSignature:
    def test_signature_tuple_contents(self) -> None:
        obs = _observation()
        action = BrowserAction(action="click", target_ref="e1")
        sig = build_signature(obs, action)
        assert sig.action_type == "click"
        assert sig.target_ref == "e1"
        assert sig.page_type == "form"
        assert sig.url == "https://example.gov.in/form"
        assert sig.fingerprint

    def test_different_target_different_key(self) -> None:
        obs = _observation([_element("e1"), _element("e2")])
        a = build_signature(obs, BrowserAction(action="click", target_ref="e1"))
        b = build_signature(obs, BrowserAction(action="click", target_ref="e2"))
        assert a.key != b.key

    def test_describe_is_readable(self) -> None:
        sig = build_signature(_observation(), BrowserAction(action="click", target_ref="e1"))
        assert "click on e1" in sig.describe()


class TestEvaluateRepeat:
    def _sig(self, target: str = "e1"):
        return build_signature(
            _observation([_element("e1"), _element("e2")]),
            BrowserAction(action="click", target_ref=target),
        )

    def test_first_occurrence_counts_one(self) -> None:
        verdict = evaluate_repeat(self._sig(), "", 0)
        assert verdict.repeat_count == 1
        assert verdict.halt is False
        assert verdict.stall_reason is None

    def test_repeats_accumulate_up_to_the_limit(self) -> None:
        sig = self._sig()
        key, count = "", 0
        for expected in range(1, REPEATED_ACTION_LIMIT + 1):
            verdict = evaluate_repeat(sig, key, count)
            key, count = verdict.key, verdict.repeat_count
            assert verdict.repeat_count == expected
            assert verdict.halt is False, "must tolerate the configured repeats"

    def test_halts_after_limit_repeats_produced_no_change(self) -> None:
        sig = self._sig()
        verdict = evaluate_repeat(sig, sig.key, REPEATED_ACTION_LIMIT)
        assert verdict.halt is True
        assert verdict.stall_reason == STALL_REASON_REPEATED_ACTION
        assert f"last {REPEATED_ACTION_LIMIT} actions produced no change" in verdict.reason
        assert "click on e1" in verdict.reason

    def test_different_action_resets_counter(self) -> None:
        first = self._sig("e1")
        verdict = evaluate_repeat(self._sig("e2"), first.key, REPEATED_ACTION_LIMIT)
        assert verdict.repeat_count == 1
        assert verdict.halt is False

    def test_changed_page_resets_counter(self) -> None:
        before = build_signature(
            _observation([_element("e1", value="")]),
            BrowserAction(action="click", target_ref="e1"),
        )
        after = build_signature(
            _observation([_element("e1", value="typed")]),
            BrowserAction(action="click", target_ref="e1"),
        )
        verdict = evaluate_repeat(after, before.key, REPEATED_ACTION_LIMIT)
        assert verdict.repeat_count == 1
        assert verdict.halt is False


# ── 2. Runner behaviour ────────────────────────────────────


def _mapping(refs: list[str]) -> MappingResult:
    bindings = [
        FieldBinding(
            field_ref=ref, binding="USER.full_name",
            confidence=MappingConfidence.HIGH,
            strategy=MappingStrategy.DETERMINISTIC, field_type="textbox",
        )
        for ref in refs
    ]
    return MappingResult(
        bindings=bindings, unmapped_fields=[], ambiguous_fields=[],
        total_fields=len(bindings), mapped_count=len(bindings),
    )


def _stuck_result(obs):
    """A 'succeeded but nothing changed' result — the Phase 8 signature."""
    result = MagicMock()
    result.success = True
    result.user_action_required = False
    result.recovery_required = False
    result.verification = MagicMock()
    result.verification.status.value = "uncertain"
    result.post_observation = obs
    result.message = "Clicked, no observable change"
    return result


class TestRunnerStallDetection:
    @pytest.mark.asyncio
    async def test_repeated_identical_action_halts_with_label(self) -> None:
        """The stall gets a name, not 'max iterations reached'."""
        runner = AgentRunner(
            llm=None, max_iterations=20, vault=UserVault(full_name="Test User"),
        )
        observation = _observation(
            [_element("e1", value=""), _element("e2", role="button", accessible_name="Next")],
        )
        executed: list[tuple[str, str | None]] = []

        async def mock_execute(page, action, obs, **kwargs):
            executed.append((action.action, action.target_ref))
            return _stuck_result(observation)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_mapping(["e1"])):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(MagicMock(), task="Fill the form")

        assert workflow.status == WorkflowStatus.WAITING_FOR_USER
        assert workflow.stall_reason == STALL_REASON_REPEATED_ACTION
        assert "produced no change" in workflow.error_message
        assert workflow.error_state == "user_required"
        # The fill ran once, then the identical click was tolerated exactly
        # REPEATED_ACTION_LIMIT times and refused on the next attempt —
        # far short of the 20-iteration budget.
        assert executed[0] == ("fill", "e1")
        assert executed[1:] == [("click", "e2")] * REPEATED_ACTION_LIMIT
        assert workflow.repeated_action_count == REPEATED_ACTION_LIMIT + 1
        assert any(
            STALL_REASON_REPEATED_ACTION in cp for cp in workflow.checkpoints
        )

    @pytest.mark.asyncio
    async def test_max_iterations_message_is_not_used_for_a_stall(self) -> None:
        runner = AgentRunner(
            llm=None, max_iterations=20, vault=UserVault(full_name="Test User"),
        )
        observation = _observation([_element("e1", value="")])

        async def mock_execute(page, action, obs, **kwargs):
            return _stuck_result(observation)

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_mapping(["e1"])):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(MagicMock(), task="Fill the form")

        assert "Max iterations" not in workflow.error_message
        assert workflow.status != WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_progress_does_not_trip_the_detector(self) -> None:
        """Different actions on a changing page must run to their own halt."""
        runner = AgentRunner(
            llm=None, max_iterations=10, vault=UserVault(full_name="Test User"),
        )
        states = [
            _observation([_element("e1", value=""), _element("e2", accessible_name="Father's Name")]),
            _observation([_element("e1", value="Test User"), _element("e2", accessible_name="Father's Name")]),
            _observation([
                _element("e1", value="Test User"),
                _element("e2", accessible_name="Father's Name", value="Test User"),
            ]),
        ]
        index = 0

        async def fake_observe(page):
            return states[min(index, len(states) - 1)]

        async def mock_execute(page, action, obs, **kwargs):
            nonlocal index
            index += 1
            result = MagicMock()
            result.success = True
            result.user_action_required = False
            result.recovery_required = False
            result.verification = MagicMock()
            result.verification.status.value = "success"
            result.post_observation = states[min(index, len(states) - 1)]
            result.message = "OK"
            return result

        with patch.object(runner._observer, "observe", side_effect=fake_observe):
            with patch.object(
                runner._mapper, "map_fields", return_value=_mapping(["e1", "e2"]),
            ):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(MagicMock(), task="Fill the form")

        assert workflow.stall_reason is None
        assert workflow.successful_actions >= 2

    @pytest.mark.asyncio
    async def test_recovery_budget_still_owns_short_failure_loops(self) -> None:
        """A failing action inside the recovery budget is not pre-empted."""
        runner = AgentRunner(
            llm=None, max_iterations=3, vault=UserVault(full_name="Test User"),
        )
        observation = _observation([_element("e1", value="")])

        async def mock_execute(page, action, obs, **kwargs):
            result = MagicMock()
            result.success = False
            result.user_action_required = False
            result.recovery_required = True
            result.verification = MagicMock()
            result.verification.status.value = "failure"
            result.post_observation = observation
            result.message = "Always fails"
            return result

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=_mapping(["e1"])):
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(MagicMock(), task="Fill the form")

        assert workflow.status == WorkflowStatus.FAILED
        assert workflow.stall_reason is None
        assert workflow.recovery_attempts == 3
