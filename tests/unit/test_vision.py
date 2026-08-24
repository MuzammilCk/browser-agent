"""Tests for vision fallback — completeness assessment.

Audit issue #30: vision fallback trigger.
"""

from __future__ import annotations

import pytest

from app.browser.vision import CompletenessAssessment, assess_completeness
from app.models.page_state import (
    ElementState,
    FrameState,
    PageObservation,
    PageState,
)


def _make_observation(
    elements: list[ElementState] | None = None,
    *,
    page_type: str = "form",
    frames: list[FrameState] | None = None,
    aria_snapshot: str = "test snapshot content",
) -> PageObservation:
    page_state = PageState(
        url="https://example.gov.in/form",
        title="Test Form",
        page_type=page_type,
        elements=elements or [],
        frames=frames or [],
    )
    return PageObservation(
        page_state=page_state,
        aria_snapshot=aria_snapshot,
    )


class TestCompletenessAssessment:
    """Test vision fallback completeness assessment."""

    def test_sufficient_with_many_elements(self):
        """Form with many named elements should be sufficient."""
        elements = [
            ElementState(ref=f"e{i}", accessible_name=f"Field {i}", role="textbox")
            for i in range(10)
        ]
        obs = _make_observation(elements)
        result = assess_completeness(obs)
        assert result.is_sufficient is True
        assert result.confidence >= 0.7

    def test_insufficient_with_no_elements(self):
        """Page with no elements should trigger vision fallback."""
        obs = _make_observation([])
        result = assess_completeness(obs)
        assert result.is_sufficient is False
        assert "no_interactive_elements" in result.missing_signals

    def test_insufficient_with_captcha(self):
        """CAPTCHA page should trigger vision fallback."""
        elements = [
            ElementState(ref="e1", accessible_name="CAPTCHA image", role="image"),
        ]
        obs = _make_observation(elements, page_type="captcha")
        result = assess_completeness(obs)
        assert result.is_sufficient is False
        assert "visual_challenge_detected" in result.missing_signals

    def test_insufficient_with_otp(self):
        """OTP page should trigger vision fallback."""
        obs = _make_observation(
            [ElementState(ref="e1", accessible_name="Enter OTP")],
            page_type="otp",
        )
        result = assess_completeness(obs)
        assert result.is_sufficient is False

    def test_low_name_coverage(self):
        """Elements without names should reduce confidence."""
        elements = [
            ElementState(ref="e1", role="textbox"),  # no name
            ElementState(ref="e2", role="textbox"),  # no name
            ElementState(ref="e3", role="textbox"),  # no name
            ElementState(ref="e4", accessible_name="Named", role="textbox"),
        ]
        obs = _make_observation(elements, aria_snapshot="a" * 60)
        result = assess_completeness(obs)
        assert result.confidence < 1.0
        assert "low_name_coverage" in result.missing_signals

    def test_unknown_page_type(self):
        """Unknown page type should reduce confidence."""
        elements = [
            ElementState(ref="e1", accessible_name="Field", role="textbox"),
        ]
        obs = _make_observation(elements, page_type="unknown")
        result = assess_completeness(obs)
        assert "unknown_page_type" in result.missing_signals

    def test_frames_not_extracted(self):
        """Frames without extracted elements should reduce confidence."""
        elements = []  # No frame elements extracted
        frames = [FrameState(frame_id="f1", url="https://example.com/frame")]
        obs = _make_observation(elements, frames=frames)
        result = assess_completeness(obs)
        assert "frames_not_extracted" in result.missing_signals

    def test_thin_aria_snapshot(self):
        """Very short ARIA snapshot should reduce confidence."""
        elements = [
            ElementState(ref="e1", accessible_name="Field", role="textbox"),
        ]
        obs = _make_observation(elements, aria_snapshot="short")
        result = assess_completeness(obs)
        assert "thin_aria_snapshot" in result.missing_signals

    def test_sparse_elements(self):
        """Very few elements on a form page should reduce confidence."""
        elements = [
            ElementState(ref="e1", accessible_name="Field", role="textbox"),
        ]
        obs = _make_observation(elements, page_type="form")
        result = assess_completeness(obs)
        assert "sparse_elements" in result.missing_signals

    def test_success_page_is_sufficient(self):
        """Success page with few elements is still sufficient."""
        elements = [
            ElementState(ref="e1", accessible_name="Done", role="button"),
        ]
        obs = _make_observation(elements, page_type="success")
        result = assess_completeness(obs)
        assert result.is_sufficient is True

    def test_confidence_clamped(self):
        """Confidence should be clamped between 0 and 1."""
        obs = _make_observation([])
        result = assess_completeness(obs)
        assert 0.0 <= result.confidence <= 1.0

    def test_landing_page_sufficient(self):
        """Landing page with elements is sufficient."""
        elements = [
            ElementState(ref="e1", accessible_name="Login", role="button"),
            ElementState(ref="e2", accessible_name="Register", role="button"),
        ]
        obs = _make_observation(elements, page_type="landing")
        result = assess_completeness(obs)
        assert result.is_sufficient is True
