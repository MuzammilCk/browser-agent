"""Tests for deterministic planning (audit C4 fixes).

- Combobox selection resolves through the vault resolver, not the
  already-selected option
- Already-satisfied fields (textbox value set, combobox showing desired
  option, checkbox checked) are skipped instead of replayed
- Unresolvable bindings are skipped rather than emitted with empty values
"""

from __future__ import annotations

from app.agent.planner import plan_deterministic
from app.agent.planning_result import ActionPlanned, NoValidAction
from app.agent.field_mapper_models import (
    FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
)
from app.models.page_state import (
    ElementState, PageObservation, PageState,
)
from app.models.workflow_state import WorkflowState


def _el(ref, *, role="textbox", accessible_name="", value="", selected=None, checked=None):
    return ElementState(
        ref=ref, role=role, accessible_name=accessible_name,
        label_text=accessible_name, value=value,
        selected_options=selected or [],
        checked=checked,
    )


def _observation(elements):
    page_state = PageState(
        url="https://uidai.gov.in/form", title="Form", page_type="form",
        elements=elements,
    )
    return PageObservation(page_state=page_state, aria_snapshot="", observation_id="obs1")


def _binding(ref, binding, field_type):
    return FieldBinding(
        field_ref=ref, binding=binding,
        confidence=MappingConfidence.HIGH,
        strategy=MappingStrategy.DETERMINISTIC,
        field_type=field_type,
    )


class _FakeResolver:
    def __init__(self, values):
        self._values = values

    def resolve(self, ref):
        return self._values.get(ref)


class TestDeterministicSelect:
    def test_select_uses_vault_value_not_current_selection(self):
        # Gender dropdown currently shows "Select" but vault says "Male"
        elements = [_el("e1", role="combobox", accessible_name="Gender",
                        value="Select", selected=["Select"])]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.gender", "combobox")]),
            value_resolver=_FakeResolver({"USER.gender": "Male"}),
        )
        assert isinstance(action, ActionPlanned)
        assert action.action.action == "select"
        assert action.action.option == "Male"

    def test_select_skips_when_desired_already_selected(self):
        elements = [_el("e1", role="combobox", accessible_name="Gender",
                        value="Male", selected=["Male"])]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.gender", "combobox")]),
            value_resolver=_FakeResolver({"USER.gender": "Male"}),
        )
        assert isinstance(action, NoValidAction)  # nothing left to do (no submit button either)

    def test_select_skips_unresolvable_binding(self):
        elements = [_el("e1", role="combobox", accessible_name="Gender")]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.gender", "combobox")]),
            value_resolver=_FakeResolver({}),  # empty vault
        )
        assert isinstance(action, NoValidAction)  # unresolvable → skipped, not emitted empty


class TestDeterministicCheckbox:
    def test_check_only_when_unchecked(self):
        elements = [_el("e1", role="checkbox", accessible_name="Declaration", checked=False)]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.declaration", "checkbox")]),
            value_resolver=_FakeResolver({}),
        )
        assert isinstance(action, ActionPlanned) and action.action.action == "check"

    def test_skips_checked_checkbox(self):
        elements = [_el("e1", role="checkbox", accessible_name="Declaration", checked=True)]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.declaration", "checkbox")]),
            value_resolver=_FakeResolver({}),
        )
        assert isinstance(action, NoValidAction)


class TestDeterministicFill:
    def test_fill_skips_field_already_holding_value(self):
        elements = [_el("e1", accessible_name="Full Name", value="Rajesh Kumar Singh")]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.full_name", "textbox")]),
            value_resolver=_FakeResolver({"USER.full_name": "Rajesh Kumar Singh"}),
        )
        assert isinstance(action, NoValidAction)

    def test_fill_emitted_when_value_differs(self):
        elements = [_el("e1", accessible_name="Full Name", value="")]
        wf = WorkflowState()
        action = plan_deterministic(
            wf, _observation(elements),
            MappingResult(bindings=[_binding("e1", "USER.full_name", "textbox")]),
            value_resolver=_FakeResolver({"USER.full_name": "Rajesh Kumar Singh"}),
        )
        assert isinstance(action, ActionPlanned)
        assert action.action.action == "fill"
        assert action.action.value_ref == "USER.full_name"
