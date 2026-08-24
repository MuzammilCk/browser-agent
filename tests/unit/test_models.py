"""Unit tests for Pydantic data models."""

from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState,
    ElementState,
    FrameState,
    NavigationState,
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


def test_element_state() -> None:
    """ElementState model."""
    el = ElementState(
        ref="e1",
        role="textbox",
        name="Full Name",
        label="Full Name",
        required=True,
    )
    assert el.ref == "e1"
    assert el.required is True
    assert el.disabled is False


def test_page_state_defaults() -> None:
    """PageState initializes with sensible defaults."""
    ps = PageState()
    assert ps.page_type == "unknown"
    assert ps.elements == []
    assert ps.alerts == []
    assert ps.validation_errors == []
    assert ps.frames == []


def test_page_state_with_elements() -> None:
    """PageState with elements."""
    ps = PageState(
        url="https://example.gov.in/form",
        title="Application Form",
        page_type="form",
        elements=[
            ElementState(ref="e1", role="textbox", name="Name", required=True),
            ElementState(ref="e2", role="combobox", name="State", required=True),
        ],
    )
    assert len(ps.elements) == 2
    assert ps.elements[0].ref == "e1"


def test_alert_state() -> None:
    """AlertState model."""
    alert = AlertState(ref="a1", role="alert", text="Session expired")
    assert alert.text == "Session expired"


def test_validation_error_state() -> None:
    """ValidationErrorState model."""
    ve = ValidationErrorState(target_ref="e5", message="Required field")
    assert ve.target_ref == "e5"


def test_frame_state() -> None:
    """FrameState model."""
    frame = FrameState(frame_id="f1", url="https://example.gov.in/embed", name="upload-frame")
    assert frame.frame_id == "f1"


def test_navigation_state() -> None:
    """NavigationState model."""
    nav = NavigationState(can_go_back=True, current_url="https://example.gov.in/form")
    assert nav.can_go_back is True


def test_authentication_state() -> None:
    """AuthenticationState model."""
    auth = AuthenticationState(challenge_detected=True, challenge_type="otp")
    assert auth.challenge_detected is True
    assert auth.challenge_type == "otp"
