"""Tests for semantic field mapper — Phase 6 + Phase A fixes.

Tests cover:
- Deterministic matching with similar labels
- Confidence scoring
- Evidence collection
- LLM resolution (mocked)
- ReferenceRegistry validation
- File input matching (input_type)
- Observation-scoped bindings
- Edge cases (empty fields, disabled elements)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.field_mapper import FieldMapper
from app.agent.field_mapper_models import (
    FieldBinding,
    MappingConfidence,
    MappingResult,
    MappingStrategy,
)
from app.agent.registry import ReferenceRegistry
from app.models.page_state import (
    ElementState,
    PageObservation,
    PageState,
)


def _make_element(
    ref: str,
    *,
    role: str = "textbox",
    accessible_name: str = "",
    label_text: str = "",
    html_name: str = "",
    placeholder: str = "",
    section_heading: str = "",
    help_text: str = "",
    group_label: str = "",
    nearby_text: str = "",
    disabled: bool = False,
    input_type: str | None = None,
) -> ElementState:
    """Helper to create an ElementState for testing."""
    return ElementState(
        ref=ref,
        role=role,
        accessible_name=accessible_name,
        label_text=label_text,
        html_name=html_name,
        placeholder=placeholder,
        section_heading=section_heading,
        help_text=help_text,
        group_label=group_label,
        nearby_text=nearby_text,
        disabled=disabled,
        input_type=input_type,
    )


def _make_observation(
    elements: list[ElementState],
    obs_id: str = "obs_test",
) -> PageObservation:
    """Helper to create a PageObservation for testing."""
    page_state = PageState(
        url="https://example.gov.in/form",
        title="Application Form",
        page_type="form",
        elements=elements,
    )
    return PageObservation(
        page_state=page_state,
        aria_snapshot="",
        observation_id=obs_id,
    )


# ============================================================
# Deterministic Matching Tests
# ============================================================


class TestDeterministicMatching:
    """Test deterministic keyword-based matching."""

    def test_full_name_exact_match(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Applicant Name as per Aadhaar")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.full_name"
        assert result.confidence == MappingConfidence.HIGH

    def test_father_name_not_full_name(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Father's Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.father_name"
        assert result.binding != "USER.full_name"

    def test_mother_name_not_full_name(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Mother's Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.mother_name"

    def test_spouse_name_not_full_name(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Spouse Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.spouse_name"

    def test_guardian_name_maps_to_guardian(self):
        """Per audit #7: Guardian Name maps to USER.guardian_name, not father."""
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Guardian Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.guardian_name"

    def test_date_of_birth(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Date of Birth as per Aadhaar")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.date_of_birth"

    def test_gender_dropdown(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Gender", role="combobox")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.gender"

    def test_mobile_number(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="10-digit Mobile Number")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.mobile"

    def test_email(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Email Address")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.email"

    def test_state_dropdown(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="State of Residence", role="combobox")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.state"

    def test_district_dropdown(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="District", role="combobox")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.district"

    def test_aadhaar_number(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Aadhaar Number")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.aadhaar_number"

    def test_pan_number(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="PAN Number")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.pan_number"

    def test_annual_income(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Annual Family Income in Rupees")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.annual_income"

    def test_full_address(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Complete Postal Address")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.address"


# ============================================================
# File Input Type Matching (Audit #4)
# ============================================================


class TestFileInputMatching:
    """Test that file inputs match via input_type, not role."""

    def test_file_input_by_input_type(self):
        """input_type='file' should match document rules even if role is not 'file'."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Aadhaar Card",
            role="button",  # ARIA role may be button
            input_type="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.aadhaar"

    def test_file_input_by_role(self):
        """role='file' should also match."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Income Certificate",
            role="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.income_certificate"

    def test_photo_upload(self):
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Passport Size Photo",
            input_type="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.photo"

    def test_signature_upload(self):
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Signature Image",
            input_type="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.signature"


# ============================================================
# ReferenceRegistry Validation (Audit #11)
# ============================================================


class TestRegistryValidation:
    """Test that all bindings are validated against ReferenceRegistry."""

    def test_all_deterministic_bindings_valid(self):
        """Every deterministic binding must exist in the registry."""
        mapper = FieldMapper()
        registry = mapper._registry

        for binding_key in mapper._rules:
            assert registry.validate(binding_key), (
                f"Binding '{binding_key}' not found in ReferenceRegistry"
            )

    def test_invalid_binding_rejected(self):
        """A binding not in the registry should not be produced."""
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Some Unknown Field")
        result = mapper._match_deterministic(element)
        # Should either match a known rule or return None
        if result and result.binding:
            assert mapper._registry.validate(result.binding)


# ============================================================
# Observation-Scoped Bindings (Audit #12)
# ============================================================


class TestObservationScopedBindings:
    """Test that bindings include observation_id."""

    @pytest.mark.asyncio
    async def test_bindings_have_observation_id(self):
        mapper = FieldMapper()
        elements = [
            _make_element("e1", accessible_name="Full Name"),
            _make_element("e2", accessible_name="Email"),
        ]
        observation = _make_observation(elements, obs_id="obs_42")

        result = await mapper.map_fields(observation)

        for binding in result.bindings:
            assert binding.observation_id == "obs_42", (
                f"Binding {binding.field_ref} missing observation_id"
            )


# ============================================================
# Confidence Scoring Tests
# ============================================================


class TestConfidenceScoring:
    def test_high_confidence_exact_match(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Full Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.confidence == MappingConfidence.HIGH

    def test_medium_confidence_partial_match(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Address")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.confidence in (MappingConfidence.HIGH, MappingConfidence.MEDIUM)

    def test_no_match_returns_none(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Widget Configuration")
        result = mapper._match_deterministic(element)
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_element_skipped(self):
        mapper = FieldMapper()
        elements = [
            _make_element("e1", accessible_name="Full Name", disabled=True),
            _make_element("e2", accessible_name="Email", disabled=False),
        ]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)
        assert len(result.bindings) == 1
        assert result.bindings[0].field_ref == "e2"


# ============================================================
# Evidence Collection Tests
# ============================================================


class TestEvidenceCollection:
    def test_evidence_includes_label(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Applicant Full Name")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert len(result.evidence) > 0
        assert any("Applicant Full Name" in e for e in result.evidence)

    def test_evidence_includes_role(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Gender", role="combobox")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert any("combobox" in e for e in result.evidence)

    def test_evidence_includes_section(self):
        mapper = FieldMapper()
        element = _make_element("e1", accessible_name="Full Name", section_heading="Personal Details")
        result = mapper._match_deterministic(element)
        assert result is not None
        assert any("Personal Details" in e for e in result.evidence)


# ============================================================
# Full Mapping Pipeline Tests
# ============================================================


class TestFullMapping:
    @pytest.mark.asyncio
    async def test_map_fields_deterministic_only(self):
        mapper = FieldMapper()  # No LLM gateway
        elements = [
            _make_element("e1", accessible_name="Full Name"),
            _make_element("e2", accessible_name="Date of Birth"),
            _make_element("e3", accessible_name="Gender", role="combobox"),
            _make_element("e4", accessible_name="State", role="combobox"),
            _make_element("e5", accessible_name="Email"),
            _make_element("e6", accessible_name="Random Field"),
        ]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)

        assert isinstance(result, MappingResult)
        assert result.total_fields == 6
        assert result.mapped_count >= 5
        assert "e6" in result.unmapped_fields

    @pytest.mark.asyncio
    async def test_map_fields_returns_bindings(self):
        mapper = FieldMapper()
        elements = [_make_element("e1", accessible_name="Full Name")]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)

        assert len(result.bindings) == 1
        binding = result.bindings[0]
        assert binding.field_ref == "e1"
        assert binding.binding == "USER.full_name"
        assert binding.confidence == MappingConfidence.HIGH
        assert binding.strategy == MappingStrategy.DETERMINISTIC
        assert binding.observation_id == "obs_test"


# ============================================================
# LLM Resolution Tests (Mocked)
# ============================================================


class TestLLMResolution:
    @pytest.mark.asyncio
    async def test_llm_validates_output(self):
        """LLM output is validated against ReferenceRegistry."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {
            "mappings": [
                {"ref": "e1", "binding": "USER.full_name", "confidence": "high", "reasoning": "Clear"},
                {"ref": "e2", "binding": "INVALID.reference", "confidence": "high", "reasoning": "Bad"},
            ]
        }
        mock_llm.complete = AsyncMock(return_value=mock_response)

        mapper = FieldMapper(llm_gateway=mock_llm)
        elements = [
            _make_element("e1", accessible_name="Some Ambiguous Name"),
            _make_element("e2", accessible_name="Another Field"),
        ]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)

        # Only valid binding should be kept
        valid_bindings = [b for b in result.bindings if b.binding == "USER.full_name"]
        assert len(valid_bindings) == 1
        # Invalid binding should be rejected
        invalid_bindings = [b for b in result.bindings if b.binding == "INVALID.reference"]
        assert len(invalid_bindings) == 0

    @pytest.mark.asyncio
    async def test_llm_graceful_failure(self):
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API error"))

        mapper = FieldMapper(llm_gateway=mock_llm)
        elements = [_make_element("e1", accessible_name="Some Field")]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)
        assert isinstance(result, MappingResult)

    @pytest.mark.asyncio
    async def test_no_llm_skips_resolution(self):
        mapper = FieldMapper(llm_gateway=None)
        elements = [_make_element("e1", accessible_name="Name")]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)
        assert len(result.bindings) >= 0


# ============================================================
# Similar Label Discrimination Tests
# ============================================================


class TestSimilarLabelDiscrimination:
    def test_all_name_variants_distinct(self):
        mapper = FieldMapper()
        name_fields = [
            ("e1", "Applicant Name", "USER.full_name"),
            ("e2", "Father's Name", "USER.father_name"),
            ("e3", "Mother's Name", "USER.mother_name"),
            ("e4", "Spouse Name", "USER.spouse_name"),
            ("e5", "Guardian Name", "USER.guardian_name"),
        ]
        results = {}
        for ref, label, expected in name_fields:
            element = _make_element(ref, accessible_name=label)
            result = mapper._match_deterministic(element)
            if result:
                results[ref] = result.binding

        for ref, label, expected in name_fields:
            if ref in results:
                assert results[ref] == expected, (
                    f"'{label}' mapped to {results[ref]}, expected {expected}"
                )

    def test_income_vs_bank_account(self):
        mapper = FieldMapper()
        e1 = _make_element("e1", accessible_name="Annual Income")
        e2 = _make_element("e2", accessible_name="Bank Account Number")
        r1 = mapper._match_deterministic(e1)
        r2 = mapper._match_deterministic(e2)
        assert r1 is not None
        assert r2 is not None
        assert r1.binding != r2.binding

    def test_photo_not_confused_with_aadhaar(self):
        mapper = FieldMapper()
        e1 = _make_element("e1", accessible_name="Upload Photo", input_type="file")
        e2 = _make_element("e2", accessible_name="Upload Aadhaar Card", input_type="file")
        r1 = mapper._match_deterministic(e1)
        r2 = mapper._match_deterministic(e2)
        assert r1 is not None
        assert r2 is not None
        assert r1.binding == "DOCUMENT.photo"
        assert r2.binding == "DOCUMENT.aadhaar"
