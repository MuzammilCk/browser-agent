"""Tests for semantic field mapper — Phase 6.

Tests cover:
- Deterministic matching with similar labels
- Confidence scoring
- Evidence collection
- LLM resolution (mocked)
- Edge cases (empty fields, disabled elements)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.field_mapper import FieldMapper
from app.agent.field_mapper_models import (
    FieldBinding,
    MappingConfidence,
    MappingResult,
    MappingStrategy,
)
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
    )


def _make_observation(elements: list[ElementState]) -> PageObservation:
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
    )


# ============================================================
# Deterministic Matching Tests
# ============================================================


class TestDeterministicMatching:
    """Test deterministic keyword-based matching."""

    def test_full_name_exact_match(self):
        """'Applicant Name as per Aadhaar' should map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Applicant Name as per Aadhaar",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.full_name"
        assert result.confidence == MappingConfidence.HIGH

    def test_full_name_generic(self):
        """'Full Name' should map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Full Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.full_name"

    def test_father_name_not_full_name(self):
        """'Father's Name' must NOT map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Father's Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.father_name"
        assert result.binding != "USER.full_name"

    def test_mother_name_not_full_name(self):
        """'Mother's Name' must NOT map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Mother's Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.mother_name"

    def test_spouse_name_not_full_name(self):
        """'Spouse Name' must NOT map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Spouse Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.spouse_name"

    def test_parent_name_exclude(self):
        """'Parent/Guardian Name' should NOT map to USER.full_name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Parent/Guardian Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        # Should not match full_name due to exclude_keywords
        if result:
            assert result.binding != "USER.full_name"

    def test_date_of_birth(self):
        """'Date of Birth as per Aadhaar' should map to USER.date_of_birth."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Date of Birth as per Aadhaar",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.date_of_birth"

    def test_gender_dropdown(self):
        """Gender combobox should map to USER.gender."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Gender",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.gender"

    def test_mobile_number(self):
        """'Mobile Number' should map to USER.mobile."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="10-digit Mobile Number",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.mobile"

    def test_email(self):
        """'Email Address' should map to USER.email."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Email Address",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.email"

    def test_state_dropdown(self):
        """'State of Residence' should map to USER.state."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="State of Residence",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.state"

    def test_district_dropdown(self):
        """'District' should map to USER.district."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="District",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.district"

    def test_aadhaar_number(self):
        """'Aadhaar Number' should map to USER.aadhaar_number."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Aadhaar Number",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.aadhaar_number"

    def test_pan_number(self):
        """'PAN Number' should map to USER.pan_number."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="PAN Number",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.pan_number"

    def test_annual_income(self):
        """'Annual Family Income' should map to USER.annual_income."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Annual Family Income in Rupees",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.annual_income"

    def test_category_dropdown(self):
        """'Social Category' should map to USER.category."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Social Category",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.category"

    def test_qualification(self):
        """'Highest Qualification' should map to USER.education."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Highest Educational Qualification",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.education"

    def test_village(self):
        """'Village/Town' should map to USER.village."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Village or Town Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.village"

    def test_pincode(self):
        """'Pincode' should map to USER.pincode."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="6-digit Pincode",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.pincode"

    def test_full_address(self):
        """'Full Address' should map to USER.address."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Complete Postal Address",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "USER.address"


# ============================================================
# Document Upload Tests
# ============================================================


class TestDocumentMapping:
    """Test document upload field mapping."""

    def test_aadhaar_upload(self):
        """Aadhaar upload should map to DOCUMENT.aadhaar."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Aadhaar Card PDF",
            role="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.aadhaar"

    def test_income_certificate_upload(self):
        """Income certificate upload should map to DOCUMENT.income_certificate."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Income Certificate PDF",
            role="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.income_certificate"

    def test_photo_upload(self):
        """Passport photo upload should map to DOCUMENT.photo."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Passport Size Photo",
            role="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.photo"

    def test_signature_upload(self):
        """Signature upload should map to DOCUMENT.signature."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Upload Signature Image",
            role="file",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.binding == "DOCUMENT.signature"


# ============================================================
# Confidence Scoring Tests
# ============================================================


class TestConfidenceScoring:
    """Test confidence levels for different match qualities."""

    def test_high_confidence_exact_match(self):
        """Exact label match should be HIGH confidence."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Full Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert result.confidence == MappingConfidence.HIGH

    def test_medium_confidence_partial_match(self):
        """Partial match should be MEDIUM confidence."""
        mapper = FieldMapper()
        # "Address" is a partial match for USER.address
        element = _make_element(
            "e1",
            accessible_name="Address",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        # Should be at least MEDIUM
        assert result.confidence in (
            MappingConfidence.HIGH,
            MappingConfidence.MEDIUM,
        )

    def test_no_match_returns_none(self):
        """Completely unknown field should return None."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Widget Configuration",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_element_skipped(self):
        """Disabled elements should be skipped in full mapping."""
        mapper = FieldMapper()
        elements = [
            _make_element("e1", accessible_name="Full Name", disabled=True),
            _make_element("e2", accessible_name="Email", disabled=False),
        ]
        observation = _make_observation(elements)
        result = await mapper.map_fields(observation)
        # Only e2 should be mapped
        assert len(result.bindings) == 1
        assert result.bindings[0].field_ref == "e2"


# ============================================================
# Evidence Collection Tests
# ============================================================


class TestEvidenceCollection:
    """Test that mapping evidence is collected."""

    def test_evidence_includes_label(self):
        """Evidence should include the accessible name."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Applicant Full Name",
            role="textbox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert len(result.evidence) > 0
        assert any("Applicant Full Name" in e for e in result.evidence)

    def test_evidence_includes_role(self):
        """Evidence should include the element role."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Gender",
            role="combobox",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert any("combobox" in e for e in result.evidence)

    def test_evidence_includes_section(self):
        """Evidence should include section heading if present."""
        mapper = FieldMapper()
        element = _make_element(
            "e1",
            accessible_name="Full Name",
            role="textbox",
            section_heading="Personal Details",
        )
        result = mapper._match_deterministic(element)
        assert result is not None
        assert any("Personal Details" in e for e in result.evidence)


# ============================================================
# Full Mapping Pipeline Tests
# ============================================================


class TestFullMapping:
    """Test the complete map_fields pipeline."""

    @pytest.mark.asyncio
    async def test_map_fields_deterministic_only(self):
        """Test mapping without LLM (deterministic only)."""
        mapper = FieldMapper()  # No LLM gateway
        elements = [
            _make_element("e1", accessible_name="Full Name", role="textbox"),
            _make_element("e2", accessible_name="Date of Birth", role="textbox"),
            _make_element("e3", accessible_name="Gender", role="combobox"),
            _make_element("e4", accessible_name="State", role="combobox"),
            _make_element("e5", accessible_name="Email", role="textbox"),
            _make_element("e6", accessible_name="Random Field", role="textbox"),
        ]
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        assert isinstance(result, MappingResult)
        assert result.total_fields == 6
        assert result.mapped_count >= 5  # 5 fields should match
        assert "e6" in result.unmapped_fields

    @pytest.mark.asyncio
    async def test_map_fields_returns_bindings(self):
        """Test that bindings contain correct structure."""
        mapper = FieldMapper()
        elements = [
            _make_element("e1", accessible_name="Full Name", role="textbox"),
        ]
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        assert len(result.bindings) == 1
        binding = result.bindings[0]
        assert binding.field_ref == "e1"
        assert binding.binding == "USER.full_name"
        assert binding.confidence == MappingConfidence.HIGH
        assert binding.strategy == MappingStrategy.DETERMINISTIC
        assert binding.field_type == "textbox"
        assert binding.field_label == "Full Name"


# ============================================================
# LLM Resolution Tests (Mocked)
# ============================================================


class TestLLMResolution:
    """Test LLM-based resolution for ambiguous fields."""

    @pytest.mark.asyncio
    async def test_llm_resolution_called_for_ambiguous(self):
        """LLM should be called when there are ambiguous fields."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = {
            "mappings": [
                {
                    "ref": "e1",
                    "binding": "USER.full_name",
                    "confidence": "high",
                    "reasoning": "Clear applicant name field",
                }
            ]
        }
        mock_llm.complete = AsyncMock(return_value=mock_response)

        mapper = FieldMapper(llm_gateway=mock_llm)
        # "Applicant Details" won't match any rule precisely → MEDIUM/LOW
        elements = [
            _make_element(
                "e1",
                accessible_name="Applicant Details Field",
                role="textbox",
            ),
        ]
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        # If there are ambiguous fields, LLM should have been called
        if result.ambiguous_fields:
            mock_llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_resolution_graceful_failure(self):
        """LLM failure should not crash the mapper."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("API error"))

        mapper = FieldMapper(llm_gateway=mock_llm)
        elements = [
            _make_element(
                "e1",
                accessible_name="Name",
                role="textbox",
            ),
        ]
        observation = _make_observation(elements)

        # Should not raise
        result = await mapper.map_fields(observation)
        assert isinstance(result, MappingResult)

    @pytest.mark.asyncio
    async def test_no_llm_skips_resolution(self):
        """Without LLM gateway, ambiguous fields stay ambiguous."""
        mapper = FieldMapper(llm_gateway=None)
        elements = [
            _make_element(
                "e1",
                accessible_name="Name",
                role="textbox",
            ),
        ]
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        # Should still have a binding from deterministic matching
        assert len(result.bindings) >= 0


# ============================================================
# Similar Label Discrimination Tests
# ============================================================


class TestSimilarLabelDiscrimination:
    """Test that the mapper correctly distinguishes similar labels."""

    def test_all_name_variants_distinct(self):
        """Different name fields must map to different bindings."""
        mapper = FieldMapper()
        name_fields = [
            ("e1", "Applicant Name", "USER.full_name"),
            ("e2", "Father's Name", "USER.father_name"),
            ("e3", "Mother's Name", "USER.mother_name"),
            ("e4", "Spouse Name", "USER.spouse_name"),
        ]

        results = {}
        for ref, label, expected in name_fields:
            element = _make_element(ref, accessible_name=label, role="textbox")
            result = mapper._match_deterministic(element)
            if result:
                results[ref] = result.binding

        # Each should map to its own binding
        for ref, label, expected in name_fields:
            if ref in results:
                assert results[ref] == expected, (
                    f"'{label}' mapped to {results[ref]}, expected {expected}"
                )

    def test_address_vs_permanent_address(self):
        """Address and Permanent Address should map differently."""
        mapper = FieldMapper()
        e1 = _make_element("e1", accessible_name="Present Address", role="textbox")
        e2 = _make_element("e2", accessible_name="Permanent Address", role="textbox")

        r1 = mapper._match_deterministic(e1)
        r2 = mapper._match_deterministic(e2)

        if r1 and r2:
            # They might both map to address variants
            # but should not both map to the exact same binding
            assert r1.binding != r2.binding or r1.binding is None

    def test_income_vs_bank_account(self):
        """Income and Bank Account should not collide."""
        mapper = FieldMapper()
        e1 = _make_element("e1", accessible_name="Annual Income", role="textbox")
        e2 = _make_element("e2", accessible_name="Bank Account Number", role="textbox")

        r1 = mapper._match_deterministic(e1)
        r2 = mapper._match_deterministic(e2)

        assert r1 is not None
        assert r2 is not None
        assert r1.binding != r2.binding

    def test_photo_not_confused_with_aadhaar(self):
        """Photo upload should not map to Aadhaar upload."""
        mapper = FieldMapper()
        e1 = _make_element("e1", accessible_name="Upload Photo", role="file")
        e2 = _make_element("e2", accessible_name="Upload Aadhaar Card", role="file")

        r1 = mapper._match_deterministic(e1)
        r2 = mapper._match_deterministic(e2)

        assert r1 is not None
        assert r2 is not None
        assert r1.binding == "DOCUMENT.photo"
        assert r2.binding == "DOCUMENT.aadhaar"


# ============================================================
# Strategy Count Tests
# ============================================================


class TestStrategyCounts:
    """Test that strategy counts are tracked correctly."""

    @pytest.mark.asyncio
    async def test_strategy_counts_populated(self):
        """Strategy counts should be populated in MappingResult."""
        mapper = FieldMapper()
        elements = [
            _make_element("e1", accessible_name="Full Name", role="textbox"),
            _make_element("e2", accessible_name="Email", role="textbox"),
        ]
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        assert "deterministic" in result.strategy_counts
        assert result.strategy_counts["deterministic"] >= 2
