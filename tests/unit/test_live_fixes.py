"""Regression tests for issues found during live verification.

1. Field mapper scoring: qualified labels ("Applicant Full Name") must
   stay HIGH confidence — keyword tokens fully contained in the
   accessible name are not diluted by qualifier words.
2. Select verifier: vault value vs page label differences limited to
   case/whitespace ("kerala" vs "Kerala") must pass.
3. Resume safety: a pending action whose target vanished or changed
   identity during the pause must NOT execute.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.agent.field_mapper import FieldMapper
from app.browser.verifiers.select import verify_select
from app.agent.runner import AgentRunner
from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState, ElementState, PageObservation, PageState,
)
from app.models.workflow_state import WorkflowStatus
from app.vault.resolver import UserVault


# ── 1. Field mapper scoring ────────────────────────────────

def _el(ref, role, accessible_name, input_type=None):
    return ElementState(
        ref=ref, role=role, accessible_name=accessible_name,
        label_text=accessible_name, input_type=input_type,
    )


class TestQualifiedLabelScoring:
    def _map(self, element):
        return FieldMapper(llm_gateway=None)._match_deterministic(element)

    def test_applicant_full_name_is_high(self):
        b = self._map(_el("e1", "textbox", "Applicant Full Name", "text"))
        assert b is not None and b.binding == "USER.full_name"
        assert b.confidence.value == "high"

    def test_state_of_residence_is_high(self):
        b = self._map(_el("e2", "combobox", "State of Residence"))
        assert b is not None and b.binding == "USER.state"
        assert b.confidence.value == "high"

    def test_unrelated_label_not_mapped(self):
        b = self._map(_el("e3", "textbox", "Favourite cricket team", "text"))
        assert b is None


# ── 2. Select verifier normalization ───────────────────────

def _state_with_select(selected, value):
    el = ElementState(
        ref="e5", role="combobox", accessible_name="State",
        label_text="State", selected_options=selected, value=value,
    )
    page_state = PageState(url="x", title="t", page_type="form", elements=[el])
    return page_state


class TestSelectVerifierNormalization:
    def test_case_difference_passes(self):
        prev = _state_with_select([], "")
        curr = _state_with_select(["Kerala"], "kerala")
        action = BrowserAction(action="select", target_ref="e5", option="kerala")
        result = asyncio.run(verify_select(None, action, prev, curr))
        assert result.status.value == "success"

    def test_wrong_option_fails(self):
        prev = _state_with_select([], "")
        curr = _state_with_select(["Tamil Nadu"], "tamil_nadu")
        action = BrowserAction(action="select", target_ref="e5", option="kerala")
        result = asyncio.run(verify_select(None, action, prev, curr))
        assert result.status.value == "failure"


# ── 3. Resume target-safety ────────────────────────────────

def _obs(elements, obs_id):
    return PageObservation(
        page_state=PageState(
            url="https://uidai.gov.in/f", title="Form", page_type="form",
            elements=elements, authentication=AuthenticationState(),
        ),
        aria_snapshot="", observation_id=obs_id,
    )


def _runner():
    return AgentRunner(llm=None, vault=UserVault(aadhaar_number="1234 5678 9012"))


class TestResumeTargetSafety:
    @pytest.mark.asyncio
    async def test_vanished_target_blocks_execution(self):
        runner = _runner()
        page = MagicMock()
        original = [_el("e1", "textbox", "Enter Aadhaar Number", "text")]
        first_obs = _obs(original, "obs_1")
        empty_obs = _obs([], "obs_2")  # target gone after pause

        from app.agent.field_mapper_models import (
            FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
        )
        mapping = MappingResult(bindings=[
            FieldBinding(
                field_ref="e1", binding="USER.aadhaar_number",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC, field_type="textbox",
            ),
        ], unmapped_fields=[], ambiguous_fields=[])

        observations = [first_obs, empty_obs]

        async def fake_observe(p):
            return observations.pop(0)

        with patch.object(runner._observer, "observe", side_effect=fake_observe):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                workflow = await runner.run(page, task="Fill")
                assert workflow.status == WorkflowStatus.READY_FOR_CONFIRMATION

                exec_mock = MagicMock()
                with patch.object(runner._executor, "execute", exec_mock):
                    workflow = await runner.resume(
                        page=page, workflow=workflow, approved=True,
                    )

        exec_mock.assert_not_called()
        assert workflow.status == WorkflowStatus.WAITING_FOR_USER
