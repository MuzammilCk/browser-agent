"""Unit tests for Phase 6 — WorldState.

Verifies the 10 required proofs (Phase 6 prompt):
1. observation reduces into WorldState — TestObservationReduction
2. verified facts survive DOM rerender — TestVerifiedFactsSurviveRerender
3. stale refs are invalidated — TestStaleRefInvalidation
4. dynamic fields appear without losing existing state — TestDynamicFieldContinuity
5. tab switching preserves state — TestTabSwitchingPreservesState
6. semantic state can be serialized/deserialized — TestSerializationRoundTrip
7. evidence provenance survives serialization — TestProvenanceIntegrity
8. conflicting observations do not silently overwrite verified facts — TestEpistemicIntegrity
9. unverified/inferred data cannot masquerade as verified data — TestNoUnverifiedMasquerade
10. WorldState version increments deterministically — TestDeterministicVersioning
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agent.strategy.criteria import Snapshot, evaluate_criteria
from app.agent.strategy.models import SuccessCriterion
from app.agent.tools.base import ToolCall, ToolResult
from app.agent.world.models import (
    AgentWorldState,
    AuthenticationWorldState,
    DocumentWorldState,
    EpistemicStatus,
    Provenance,
    SemanticField,
    TabWorldState,
)
from app.agent.world.reducer import (
    is_target_ref_valid,
    record_tool_result,
    record_verified_action,
    reduce_observation,
)
from app.agent.world.semantic_id import compute_semantic_id
from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState,
    ElementState,
    PageObservation,
    PageState,
    TabsState,
    TabState,
    ValidationErrorState,
)


def _make_observation(
    elements: list[ElementState],
    *,
    obs_id: str = "obs_1",
    url: str = "https://example.gov.in/form",
    title: str = "Government Form",
    page_type: str = "form",
    validation_errors: list[ValidationErrorState] | None = None,
    auth_detected: bool = False,
    auth_type: str | None = None,
    tabs: list[TabState] | None = None,
    active_tab_index: int = 0,
) -> PageObservation:
    """Helper to create a structured PageObservation."""
    ps = PageState(
        url=url,
        title=title,
        page_type=page_type,
        elements=elements,
        validation_errors=validation_errors or [],
        authentication=AuthenticationState(
            detected=auth_detected,
            challenge_type=auth_type,
            confidence=0.9 if auth_detected else 0.0,
        ),
        tabs=TabsState(
            total=len(tabs) if tabs else 1,
            active_index=active_tab_index,
            tabs=tabs or [TabState(index=0, url=url, active=True)],
        ),
    )
    return PageObservation(page_state=ps, observation_id=obs_id)


class TestObservationReduction:
    """Proof 1: observation reduces cleanly into WorldState."""

    def test_basic_observation_reduces_semantic_fields(self) -> None:
        ws = AgentWorldState(portal="test.gov.in")
        elements = [
            ElementState(ref="e1", role="combobox", html_name="state", label_text="State", required=True),
            ElementState(ref="e2", role="textbox", html_name="full_name", label_text="Full Name"),
        ]
        obs = _make_observation(elements, obs_id="obs_100")

        reduced = reduce_observation(ws, obs)

        assert reduced.current_observation_id == "obs_100"
        assert reduced.current_page_url == "https://example.gov.in/form"
        assert len(reduced.semantic_fields) == 2
        assert "field:state" in reduced.semantic_fields
        assert "field:full_name" in reduced.semantic_fields

        state_field = reduced.semantic_fields["field:state"]
        assert state_field.current_ref == "e1"
        assert state_field.status == EpistemicStatus.OBSERVED
        assert state_field.required is True
        assert state_field.is_actionable("obs_100") is True

    def test_validation_errors_and_auth_reduce(self) -> None:
        ws = AgentWorldState()
        elements = [ElementState(ref="e1", role="textbox", html_name="mobile")]
        errors = [ValidationErrorState(target_ref="e1", message="Invalid mobile number", visible=True)]
        obs = _make_observation(elements, validation_errors=errors, auth_detected=True, auth_type="otp")

        reduced = reduce_observation(ws, obs)

        assert len(reduced.validation_errors) == 1
        assert "Invalid mobile number" in reduced.validation_errors[0]
        assert reduced.authentication.status == "detected"
        assert reduced.authentication.challenge_type == "otp"


class TestVerifiedFactsSurviveRerender:
    """Proof 2: verified facts survive DOM rerender with new ephemeral refs."""

    def test_verified_fact_preserves_value_across_rerender(self) -> None:
        ws = AgentWorldState(portal="test.gov.in")

        # Initial observation: state dropdown is ref e1
        el1 = ElementState(ref="e1", role="combobox", html_name="state", label_text="State")
        obs1 = _make_observation([el1], obs_id="obs_1")
        reduce_observation(ws, obs1)

        # Action executes and is verified: state selected as 'kerala'
        record_verified_action(
            ws,
            target_ref_or_semantic_id="e1",
            verified_value="kerala",
            binding="USER.state",
            tool_name="select_option",
            observation_id="obs_1",
        )

        assert ws.is_field_verified("field:state") is True
        assert ws.get_verified_value("field:state") == "kerala"
        assert ws.get_verified_value("USER.state") == "kerala"
        assert ws.semantic_fields["field:state"].status == EpistemicStatus.VERIFIED

        # Page re-renders: state select gets NEW ephemeral ref e5 in obs_2
        el2 = ElementState(ref="e5", role="combobox", html_name="state", label_text="State", value="kerala")
        obs2 = _make_observation([el2], obs_id="obs_2")
        reduce_observation(ws, obs2)

        # The semantic field MUST preserve its verified status and verified value!
        field = ws.semantic_fields["field:state"]
        assert field.status == EpistemicStatus.VERIFIED
        assert field.verified_value == "kerala"
        assert field.current_ref == "e5"  # Updated to current ref
        assert field.current_observation_id == "obs_2"
        assert ws.verified_values["field:state"] == "kerala"
        assert ws.verified_values["USER.state"] == "kerala"


class TestStaleRefInvalidation:
    """Proof 3: stale refs are invalidated and cannot be targeted."""

    def test_old_refs_become_stale_upon_reobservation(self) -> None:
        ws = AgentWorldState()
        el1 = ElementState(ref="e10", role="textbox", html_name="name")
        obs1 = _make_observation([el1], obs_id="obs_1")
        reduce_observation(ws, obs1)

        assert is_target_ref_valid(ws, target_ref="e10", observation_id="obs_1") is True

        # Page re-renders with obs_2 where the element now has ref e20
        el2 = ElementState(ref="e20", role="textbox", html_name="name")
        obs2 = _make_observation([el2], obs_id="obs_2")
        reduce_observation(ws, obs2)

        # The old ref e10 with old obs_1 is REJECTED
        assert is_target_ref_valid(ws, target_ref="e10", observation_id="obs_1") is False
        # The old ref e10 with new obs_2 is REJECTED
        assert is_target_ref_valid(ws, target_ref="e10", observation_id="obs_2") is False
        # Only the new ref e20 with new obs_2 is ACCEPTED
        assert is_target_ref_valid(ws, target_ref="e20", observation_id="obs_2") is True

    def test_disappeared_element_marked_stale(self) -> None:
        ws = AgentWorldState()
        el1 = ElementState(ref="e1", role="textbox", html_name="temp_field")
        reduce_observation(ws, _make_observation([el1], obs_id="obs_1"))

        field = ws.semantic_fields["field:temp_field"]
        assert field.status == EpistemicStatus.OBSERVED
        assert field.current_ref == "e1"

        # Next observation does not contain temp_field
        reduce_observation(ws, _make_observation([], obs_id="obs_2"))

        assert field.status == EpistemicStatus.STALE
        assert field.current_ref is None
        assert field.is_actionable("obs_2") is False


class TestDynamicFieldContinuity:
    """Proof 4: dynamic fields appear without losing existing state."""

    def test_dependent_field_addition_preserves_prior_fields(self) -> None:
        ws = AgentWorldState()

        # Step 1: Only State field exists
        state_el = ElementState(ref="e1", role="combobox", html_name="state", label_text="State")
        reduce_observation(ws, _make_observation([state_el], obs_id="obs_1"))
        assert len(ws.semantic_fields) == 1

        # Step 2: State is verified
        record_verified_action(ws, "e1", "kerala", binding="USER.state", tool_name="select_option", observation_id="obs_1")

        # Step 3: Dependent District field appears alongside State (which now has ref e3)
        state_el_new = ElementState(ref="e3", role="combobox", html_name="state", label_text="State", value="kerala")
        district_el = ElementState(ref="e4", role="combobox", html_name="district", label_text="District")
        reduce_observation(ws, _make_observation([state_el_new, district_el], obs_id="obs_2"))

        # Both fields exist in WorldState
        assert len(ws.semantic_fields) == 2
        assert "field:state" in ws.semantic_fields
        assert "field:district" in ws.semantic_fields

        # State verified fact is intact
        assert ws.semantic_fields["field:state"].status == EpistemicStatus.VERIFIED
        assert ws.semantic_fields["field:state"].verified_value == "kerala"
        assert ws.semantic_fields["field:state"].current_ref == "e3"

        # District is newly observed
        assert ws.semantic_fields["field:district"].status == EpistemicStatus.OBSERVED
        assert ws.semantic_fields["field:district"].current_ref == "e4"
        assert ws.semantic_fields["field:district"].verified_value is None


class TestTabSwitchingPreservesState:
    """Proof 5: tab switching preserves state across tabs."""

    def test_multi_tab_state_continuity(self) -> None:
        ws = AgentWorldState()

        # Tab 0: has field A and verified value
        tab0 = TabState(index=0, url="https://example.gov.in/tab0", active=True)
        tab1 = TabState(index=1, url="https://example.gov.in/tab1", active=False)
        el_a = ElementState(ref="e1", role="textbox", html_name="field_a")
        obs_tab0 = _make_observation([el_a], obs_id="obs_tab0", tabs=[tab0, tab1], active_tab_index=0)
        reduce_observation(ws, obs_tab0)

        record_verified_action(ws, "e1", "verified_in_tab0", tool_name="fill_field", observation_id="obs_tab0")
        assert ws.get_verified_value("field:field_a") == "verified_in_tab0"

        # Switch to Tab 1
        tab0_inactive = TabState(index=0, url="https://example.gov.in/tab0", active=False)
        tab1_active = TabState(index=1, url="https://example.gov.in/tab1", active=True)
        el_b = ElementState(ref="e10", role="textbox", html_name="field_b")
        obs_tab1 = _make_observation([el_b], obs_id="obs_tab1", url="https://example.gov.in/tab1", tabs=[tab0_inactive, tab1_active], active_tab_index=1)
        reduce_observation(ws, obs_tab1)

        assert ws.current_tab_index == 1
        # Tab 0 state was preserved in ws.tabs[0]
        assert 0 in ws.tabs
        assert "field:field_a" in ws.tabs[0].semantic_fields
        # Action targeting tab 0 ref while on tab 1 is REJECTED
        assert is_target_ref_valid(ws, "e1", "obs_tab0", tab_index=0) is False
        assert is_target_ref_valid(ws, "e1", "obs_tab1", tab_index=1) is False
        assert is_target_ref_valid(ws, "e10", "obs_tab1", tab_index=1) is True

        # Switch back to Tab 0
        tab0_active = TabState(index=0, url="https://example.gov.in/tab0", active=True)
        tab1_inactive = TabState(index=1, url="https://example.gov.in/tab1", active=False)
        el_a_fresh = ElementState(ref="e2", role="textbox", html_name="field_a")
        obs_tab0_fresh = _make_observation([el_a_fresh], obs_id="obs_tab0_v2", url="https://example.gov.in/tab0", tabs=[tab0_active, tab1_inactive], active_tab_index=0)
        reduce_observation(ws, obs_tab0_fresh)

        assert ws.current_tab_index == 0
        assert ws.semantic_fields["field:field_a"].status == EpistemicStatus.VERIFIED
        assert ws.semantic_fields["field:field_a"].verified_value == "verified_in_tab0"
        assert ws.semantic_fields["field:field_a"].current_ref == "e2"


class TestSerializationRoundTrip:
    """Proof 6: semantic state serializes and deserializes losslessly."""

    def test_pydantic_json_round_trip(self) -> None:
        ws = AgentWorldState(portal="test.gov.in", current_page_url="https://test.gov.in/form")
        el = ElementState(ref="e1", role="textbox", html_name="full_name", label_text="Full Name")
        reduce_observation(ws, _make_observation([el], obs_id="obs_1"))
        record_verified_action(ws, "e1", "John Doe", binding="USER.full_name", tool_name="fill_field", observation_id="obs_1")

        raw_json = ws.model_dump_json()
        restored = AgentWorldState.model_validate_json(raw_json)

        assert restored.version == ws.version
        assert restored.portal == ws.portal
        assert restored.verified_values == ws.verified_values
        assert restored.get_verified_value("USER.full_name") == "John Doe"
        assert restored.semantic_fields["field:full_name"].status == EpistemicStatus.VERIFIED
        assert len(restored.evidence) == len(ws.evidence)


class TestProvenanceIntegrity:
    """Proof 7: evidence provenance survives serialization and tracks changes."""

    def test_provenance_records_source_and_version(self) -> None:
        ws = AgentWorldState()
        el = ElementState(ref="e1", role="textbox", html_name="user_id")
        reduce_observation(ws, _make_observation([el], obs_id="obs_init"))
        record_verified_action(ws, "e1", "ID123", tool_name="fill_field", observation_id="obs_init")

        assert len(ws.evidence) >= 2
        ev_obs = ws.evidence[0]
        ev_ver = ws.evidence[1]

        assert ev_obs.source == "observation"
        assert ev_obs.observation_id == "obs_init"
        assert ev_ver.source == "verification"
        assert ev_ver.tool_name == "fill_field"
        assert ev_ver.state_version > ev_obs.state_version

        # Round trip
        restored = AgentWorldState.model_validate_json(ws.model_dump_json())
        assert restored.evidence[1].source == "verification"
        assert restored.evidence[1].tool_name == "fill_field"


class TestEpistemicIntegrity:
    """Proof 8: conflicting observations do not silently overwrite verified facts."""

    def test_blank_or_conflicting_observation_does_not_clear_verified_value(self) -> None:
        ws = AgentWorldState()
        el1 = ElementState(ref="e1", role="textbox", html_name="email", label_text="Email")
        reduce_observation(ws, _make_observation([el1], obs_id="obs_1"))

        record_verified_action(ws, "e1", "citizen@example.gov.in", binding="USER.email", tool_name="fill_field", observation_id="obs_1")
        assert ws.get_verified_value("USER.email") == "citizen@example.gov.in"

        # During re-render, DOM momentarily has an empty or conflicting value
        el2 = ElementState(ref="e2", role="textbox", html_name="email", label_text="Email", value="")
        reduce_observation(ws, _make_observation([el2], obs_id="obs_2"))

        # Invariant: verified value is NOT cleared
        field = ws.semantic_fields["field:email"]
        assert field.status == EpistemicStatus.VERIFIED
        assert field.verified_value == "citizen@example.gov.in"
        assert ws.get_verified_value("USER.email") == "citizen@example.gov.in"


class TestNoUnverifiedMasquerade:
    """Proof 9: unverified or inferred data cannot masquerade as verified."""

    def test_unverified_observation_stays_observed(self) -> None:
        ws = AgentWorldState()
        el = ElementState(ref="e1", role="textbox", html_name="address", value="Draft Address")
        reduce_observation(ws, _make_observation([el], obs_id="obs_1"))

        field = ws.semantic_fields["field:address"]
        assert field.status == EpistemicStatus.OBSERVED
        assert field.verified_value is None
        assert ws.is_field_verified("field:address") is False

    def test_inferred_status_not_verified(self) -> None:
        field = SemanticField(
            semantic_id="field:inferred_field",
            status=EpistemicStatus.INFERRED,
            value="Guessed Value",
        )
        assert field.status == EpistemicStatus.INFERRED
        assert field.verified_value is None


class TestDeterministicVersioning:
    """Proof 10: WorldState version increments deterministically."""

    def test_monotonic_version_increments(self) -> None:
        ws = AgentWorldState()
        assert ws.version == 0

        el = ElementState(ref="e1", role="textbox", html_name="name")
        reduce_observation(ws, _make_observation([el], obs_id="obs_1"))
        assert ws.version == 1

        record_verified_action(ws, "e1", "A Name", tool_name="fill_field", observation_id="obs_1")
        assert ws.version == 2

        reduce_observation(ws, _make_observation([el], obs_id="obs_2"))
        assert ws.version == 3


class TestSnapshotIntegration:
    """Verifies Snapshot.from_world_state connects with criteria evaluation."""

    def test_snapshot_from_world_state_evaluates_criteria(self) -> None:
        ws = AgentWorldState(portal="pmkisan.gov.in", current_page_url="https://pmkisan.gov.in/reg")
        el = ElementState(ref="e1", role="textbox", html_name="name")
        reduce_observation(ws, _make_observation([el], obs_id="obs_1"))
        record_verified_action(ws, "e1", "Farmer Name", binding="USER.full_name", tool_name="fill_field", observation_id="obs_1")

        snapshot = Snapshot.from_world_state(ws)
        assert "USER.full_name" in snapshot.workflow.completed_bindings

        criterion = SuccessCriterion(
            id="c1",
            kind="field_value_bound",
            description="Full name bound",
            params={"binding": "USER.full_name"},
        )
        outcomes = evaluate_criteria([criterion], snapshot)
        assert len(outcomes) == 1
        assert outcomes[0].satisfied is True
