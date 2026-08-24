"""Tests for PolicyEngine — Phase B safety engine.

Audit issues covered: #21, #22, #23, #24
"""

from __future__ import annotations

import pytest

from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState,
    PageObservation,
    PageState,
)
from app.policy.engine import (
    PolicyDecision,
    PolicyEngine,
    PolicyResult,
    RiskLevel,
    _classify_action_risk,
)


def _make_page_state(
    *,
    auth_detected: bool = False,
    auth_type: str | None = None,
    elements: list | None = None,
) -> PageState:
    """Helper to create a PageState for testing."""
    auth = AuthenticationState(
        detected=auth_detected,
        challenge_type=auth_type,
        confidence=0.9 if auth_detected else 0.0,
    )
    return PageState(
        url="https://example.gov.in/form",
        title="Application Form",
        page_type="form",
        authentication=auth,
        elements=elements or [],
    )


# ============================================================
# Risk Classification Tests
# ============================================================


class TestRiskClassification:
    """Test risk level classification for actions."""

    def test_fill_low_risk(self):
        action = BrowserAction(action="fill", target_ref="e1", literal_value="John")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_fill_sensitive_with_value_ref(self):
        action = BrowserAction(
            action="fill", target_ref="e1", value_ref="USER.aadhaar_number"
        )
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.SENSITIVE

    def test_fill_sensitive_pan(self):
        action = BrowserAction(
            action="fill", target_ref="e1", value_ref="USER.pan_number"
        )
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.SENSITIVE

    def test_upload_always_sensitive(self):
        action = BrowserAction(
            action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar"
        )
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.SENSITIVE

    def test_click_low_risk(self):
        action = BrowserAction(action="click", target_ref="e1")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_select_low_risk(self):
        action = BrowserAction(action="select", target_ref="e1", option="Kerala")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_check_low_risk(self):
        action = BrowserAction(action="check", target_ref="e1")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_scroll_low_risk(self):
        action = BrowserAction(action="scroll", direction="down")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_press_low_risk(self):
        action = BrowserAction(action="press", key="Enter")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_stop_low_risk(self):
        action = BrowserAction(action="stop")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW

    def test_request_user_action_low_risk(self):
        action = BrowserAction(action="request_user_action", reason="Need OTP")
        risk = _classify_action_risk(action)
        assert risk == RiskLevel.LOW


# ============================================================
# Authentication Context Tests (Audit #23)
# ============================================================


class TestAuthenticationContext:
    """Test policy decisions for authentication challenges."""

    def test_captcha_pauses_for_user(self):
        page_state = _make_page_state(auth_detected=True, auth_type="captcha")
        action = BrowserAction(action="fill", target_ref="e1", literal_value="test")
        engine = PolicyEngine()
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.PAUSE_FOR_USER
        assert result.risk_level == RiskLevel.AUTHENTICATION

    def test_otp_pauses_for_user(self):
        page_state = _make_page_state(auth_detected=True, auth_type="otp")
        action = BrowserAction(action="fill", target_ref="e1", literal_value="123456")
        engine = PolicyEngine()
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.PAUSE_FOR_USER
        assert result.risk_level == RiskLevel.AUTHENTICATION

    def test_password_pauses_for_user(self):
        page_state = _make_page_state(auth_detected=True, auth_type="password")
        action = BrowserAction(action="fill", target_ref="e1", literal_value="secret")
        engine = PolicyEngine()
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.PAUSE_FOR_USER

    def test_login_pauses_for_user(self):
        page_state = _make_page_state(auth_detected=True, auth_type="login")
        action = BrowserAction(action="click", target_ref="e1")
        engine = PolicyEngine()
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.PAUSE_FOR_USER

    def test_no_auth_allows_action(self):
        page_state = _make_page_state(auth_detected=False)
        action = BrowserAction(action="fill", target_ref="e1", literal_value="John")
        engine = PolicyEngine()
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.ALLOW


# ============================================================
# Policy Decision Tests
# ============================================================


class TestPolicyDecisions:
    """Test policy decisions for various action types."""

    def test_low_risk_allowed(self):
        engine = PolicyEngine()
        action = BrowserAction(action="click", target_ref="e1")
        result = engine.evaluate(action)
        assert result.decision == PolicyDecision.ALLOW
        assert result.allowed is True
        assert result.blocked is False

    def test_sensitive_needs_confirmation(self):
        engine = PolicyEngine()
        action = BrowserAction(
            action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar"
        )
        result = engine.evaluate(action)
        assert result.decision == PolicyDecision.REQUIRE_CONFIRMATION
        assert result.needs_confirmation is True

    def test_authentication_pauses(self):
        engine = PolicyEngine()
        page_state = _make_page_state(auth_detected=True, auth_type="captcha")
        action = BrowserAction(action="click", target_ref="e1")
        result = engine.evaluate(action, page_state)
        assert result.decision == PolicyDecision.PAUSE_FOR_USER
        assert result.needs_user is True

    def test_result_has_reason(self):
        engine = PolicyEngine()
        action = BrowserAction(action="fill", target_ref="e1", literal_value="test")
        result = engine.evaluate(action)
        assert result.reason != ""
        assert "fill" in result.reason.lower()


# ============================================================
# PolicyResult Tests
# ============================================================


class TestPolicyResult:
    """Test PolicyResult helper properties."""

    def test_allowed_property(self):
        result = PolicyResult(PolicyDecision.ALLOW, RiskLevel.LOW)
        assert result.allowed is True
        assert result.blocked is False
        assert result.needs_confirmation is False
        assert result.needs_user is False

    def test_blocked_property(self):
        result = PolicyResult(PolicyDecision.DENY, RiskLevel.HIGH_RISK)
        assert result.blocked is True
        assert result.allowed is False

    def test_confirmation_property(self):
        result = PolicyResult(PolicyDecision.REQUIRE_CONFIRMATION, RiskLevel.SENSITIVE)
        assert result.needs_confirmation is True
        assert result.needs_user is False

    def test_pause_property(self):
        result = PolicyResult(PolicyDecision.PAUSE_FOR_USER, RiskLevel.AUTHENTICATION)
        assert result.needs_user is True
        assert result.needs_confirmation is False

    def test_repr(self):
        result = PolicyResult(PolicyDecision.ALLOW, RiskLevel.LOW, reason="test")
        assert "allow" in repr(result)
        assert "low" in repr(result)


# ============================================================
# Click Risk with Payment/Submission Keywords (Audit #24)
# ============================================================


class TestClickRiskKeywords:
    """Test that click on payment/submission buttons is classified as HIGH_RISK."""

    def test_payment_button_high_risk(self):
        from app.models.page_state import ElementState
        elements = [
            ElementState(ref="e1", accessible_name="Pay Now", role="button"),
        ]
        page_state = _make_page_state(elements=elements)
        action = BrowserAction(action="click", target_ref="e1")
        risk = _classify_action_risk(action, page_state)
        assert risk == RiskLevel.HIGH_RISK

    def test_submit_button_high_risk(self):
        from app.models.page_state import ElementState
        elements = [
            ElementState(ref="e1", accessible_name="Final Submit", role="button"),
        ]
        page_state = _make_page_state(elements=elements)
        action = BrowserAction(action="click", target_ref="e1")
        risk = _classify_action_risk(action, page_state)
        assert risk == RiskLevel.HIGH_RISK

    def test_declare_button_high_risk(self):
        from app.models.page_state import ElementState
        elements = [
            ElementState(ref="e1", accessible_name="I hereby declare", role="button"),
        ]
        page_state = _make_page_state(elements=elements)
        action = BrowserAction(action="click", target_ref="e1")
        risk = _classify_action_risk(action, page_state)
        assert risk == RiskLevel.HIGH_RISK

    def test_normal_button_low_risk(self):
        from app.models.page_state import ElementState
        elements = [
            ElementState(ref="e1", accessible_name="Save Draft", role="button"),
        ]
        page_state = _make_page_state(elements=elements)
        action = BrowserAction(action="click", target_ref="e1")
        risk = _classify_action_risk(action, page_state)
        assert risk == RiskLevel.LOW
