"""Unit tests for Pydantic data models."""

from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState,
    ElementState,
    FrameState,
    NavigationState,
    PageObservation,
    PageState,
    ValidationErrorState,
    AlertState,
)


def test_browser_action_valid() -> None:
    """Valid browser action with all fields."""
    action = BrowserAction(
        action="fill",
        target_ref="e12",
        value_ref="USER.full_name",
        confidence=0.98,
    )
    assert action.action == "fill"
    assert action.target_ref == "e12"
    assert action.value_ref == "USER.full_name"
    assert action.confidence == 0.98


def test_browser_action_minimal() -> None:
    """Minimal browser action (just action type)."""
    action = BrowserAction(action="stop")
    assert action.action == "stop"
    assert action.target_ref is None


def test_browser_action_invalid_action() -> None:
    """Invalid action type is rejected."""
    try:
        BrowserAction(action="invalid_action")  # type: ignore
        assert False, "Should have raised"
    except Exception:
        pass


def test_browser_action_validation_requires_fields() -> None:
    """Action validation rejects invalid combinations."""
    import pytest

    # fill without target_ref
    with pytest.raises(ValueError, match="fill requires target_ref"):
        BrowserAction(action="fill", literal_value="test")

    # fill without value
    with pytest.raises(ValueError, match="fill requires either value_ref or literal_value"):
        BrowserAction(action="fill", target_ref="e1")

    # select without option
    with pytest.raises(ValueError, match="select requires option"):
        BrowserAction(action="select", target_ref="e1")

    # click without target_ref
    with pytest.raises(ValueError, match="click requires target_ref"):
        BrowserAction(action="click")

    # open without URL
    with pytest.raises(ValueError, match="open requires literal_value"):
        BrowserAction(action="open")


def test_element_state_split_names() -> None:
    """ElementState has split name fields per audit #3."""
    el = ElementState(
        ref="e1",
        role="textbox",
        accessible_name="Applicant Full Name",
        html_name="applicantName",
        label_text="Applicant Full Name",
        required=True,
    )
    assert el.accessible_name == "Applicant Full Name"
    assert el.html_name == "applicantName"
    assert el.label_text == "Applicant Full Name"
    # Backward-compatible .name property
    assert el.name == "Applicant Full Name"


def test_element_state_name_fallback() -> None:
    """ElementState.name property falls back correctly."""
    # accessible_name takes priority
    el1 = ElementState(ref="e1", accessible_name="AN", html_name="hn", label_text="lt")
    assert el1.name == "AN"

    # Falls back to label_text
    el2 = ElementState(ref="e2", html_name="hn", label_text="LT")
    assert el2.name == "LT"

    # Falls back to html_name
    el3 = ElementState(ref="e3", html_name="HN")
    assert el3.name == "HN"

    # Returns None if all empty
    el4 = ElementState(ref="e4")
    assert el4.name is None


def test_element_state_context_fields() -> None:
    """ElementState has context fields per audit #8."""
    el = ElementState(
        ref="e1",
        section_heading="Personal Information",
        group_label="Identity Details",
        help_text="Enter your 12-digit Aadhaar number",
        nearby_text="AADHAAR NUMBER",
    )
    assert el.section_heading == "Personal Information"
    assert el.group_label == "Identity Details"
    assert el.help_text == "Enter your 12-digit Aadhaar number"
    assert el.nearby_text == "AADHAAR NUMBER"


def test_page_state_defaults() -> None:
    """PageState initializes with sensible defaults."""
    ps = PageState()
    assert ps.page_type == "unknown"
    assert ps.elements == []
    assert ps.alerts == []
    assert ps.validation_errors == []
    assert ps.frames == []


def test_page_state_with_elements() -> None:
    """PageState with elements using new split name fields."""
    ps = PageState(
        url="https://example.gov.in/form",
        title="Application Form",
        page_type="form",
        elements=[
            ElementState(ref="e1", role="textbox", accessible_name="Name", required=True),
            ElementState(ref="e2", role="combobox", accessible_name="State", required=True),
        ],
    )
    assert len(ps.elements) == 2
    assert ps.elements[0].ref == "e1"
    assert ps.elements[0].name == "Name"


def test_page_observation_model() -> None:
    """PageObservation wraps PageState + ARIA snapshot."""
    ps = PageState(url="https://example.gov.in", page_type="form")
    obs = PageObservation(
        page_state=ps,
        aria_snapshot="- textbox 'Name' [ref=e1]",
        observation_id="abc123",
    )
    assert obs.page_state.url == "https://example.gov.in"
    assert obs.aria_snapshot == "- textbox 'Name' [ref=e1]"
    assert obs.observation_id == "abc123"


def test_authentication_state_with_confidence() -> None:
    """AuthenticationState has confidence scoring per audit #7."""
    auth = AuthenticationState(
        detected=True,
        challenge_type="otp",
        reason="OTP field detected",
        confidence=0.9,
    )
    assert auth.detected is True
    assert auth.challenge_detected is True  # backward compat
    assert auth.confidence == 0.9


def test_alert_state() -> None:
    alert = AlertState(ref="a1", role="alert", text="Session expired")
    assert alert.text == "Session expired"


def test_validation_error_state() -> None:
    ve = ValidationErrorState(target_ref="e5", message="Required field")
    assert ve.target_ref == "e5"


def test_frame_state() -> None:
    frame = FrameState(frame_id="f1", url="https://example.gov.in/embed", name="upload-frame")
    assert frame.frame_id == "f1"


def test_navigation_state() -> None:
    nav = NavigationState(can_go_back=True, current_url="https://example.gov.in/form")
    assert nav.can_go_back is True
