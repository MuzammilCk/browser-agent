"""Phase 3 — authentication detection means an ACTIVE challenge (Z1 / P0-18).

Reproduces the audit fixture where a help link merely mentioning CAPTCHA
halted a run as a 90%-confidence OTP challenge, and enforces structural
co-occurrence for OTP/CAPTCHA detection.
"""

from __future__ import annotations

from app.browser.observer import PageObserver
from app.models.page_state import (
    AlertState, ElementState, FrameState, ValidationErrorState,
)


def _el(ref, *, role="textbox", accessible_name="", label_text="",
        placeholder=None, input_type=None, disabled=False, visible=True):
    return ElementState(
        ref=ref, role=role, accessible_name=accessible_name,
        label_text=label_text or accessible_name, placeholder=placeholder,
        input_type=input_type, disabled=disabled, visible=visible,
    )


class TestFalsePositiveRegression:
    """The exact audit Z1 repro must come back clean."""

    def setup_method(self):
        self.observer = PageObserver()

    def _audit_fixture_elements(self):
        return [
            _el("e1", role="link", accessible_name="Home"),
            _el("e2", role="link", accessible_name="About Us"),
            _el("e3", role="link", accessible_name="Apply Online"),
            _el("e4", role="link", accessible_name="Track Application Status"),
            _el("e5", role="link",
                accessible_name="Help: How to complete the CAPTCHA during registration"),
            _el("e6", role="button", accessible_name="Search"),
        ]

    def test_help_link_mentioning_captcha_is_not_a_challenge(self):
        auth = self.observer._detect_auth_challenge(
            self._audit_fixture_elements(), [], [], [],
        )
        assert not auth.detected, (
            f"false positive: {auth.challenge_type} @ {auth.confidence} "
            f"({auth.reason})"
        )

    def test_otp_word_on_nav_link_is_not_an_otp_challenge(self):
        elements = [
            _el("e1", role="link", accessible_name="OTP registration help"),
            _el("e2", role="button", accessible_name="Search"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert not auth.detected

    def test_resend_otp_button_alone_is_not_a_challenge(self):
        elements = [_el("e1", role="button", accessible_name="Resend OTP")]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert not auth.detected


class TestTruePositivesPreserved:
    """Removing false positives must not weaken real detection."""

    def setup_method(self):
        self.observer = PageObserver()

    def test_real_otp_input_detected(self):
        elements = [
            _el("e1", accessible_name="Enter 6-digit OTP", input_type="text"),
            _el("e2", role="button", accessible_name="Verify"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert auth.detected
        assert auth.challenge_type == "otp"

    def test_one_time_password_input_detected(self):
        elements = [_el("e1", accessible_name="One-Time Password")]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert auth.detected and auth.challenge_type == "otp"

    def test_captcha_entry_box_detected_as_captcha(self):
        elements = [
            _el("e1", accessible_name="Enter the characters shown above"),
            _el("e2", accessible_name="CAPTCHA code", input_type="text"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert auth.detected
        assert auth.challenge_type == "captcha"

    def test_captcha_alert_dialog_detected(self):
        elements = [
            _el("e1", accessible_name="Full Name"),
            _el("e2", role="button", accessible_name="Submit"),
        ]
        alerts = [AlertState(ref="a1", text="Please complete the CAPTCHA to continue")]
        auth = self.observer._detect_auth_challenge(elements, alerts, [], [])
        assert auth.detected and auth.challenge_type == "captcha"

    def test_recaptcha_iframe_metadata_detected(self):
        frames = [FrameState(
            frame_id="f1",
            url="https://www.google.com/recaptcha/api2/anchor?ar=1",
        )]
        auth = self.observer._detect_auth_challenge([], [], [], frames)
        assert auth.detected and auth.challenge_type == "captcha"

    def test_login_form_pattern_still_detected(self):
        elements = [
            _el("e1", accessible_name="Username", input_type="text"),
            _el("e2", accessible_name="Password", input_type="password"),
            _el("e3", role="button", accessible_name="Login"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert auth.detected
        assert auth.challenge_type == "login"

    def test_disabled_otp_box_is_not_an_active_challenge(self):
        elements = [
            _el("e1", accessible_name="Enter OTP", disabled=True),
            _el("e2", role="button", accessible_name="Submit"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert not auth.detected


class TestPasswordExistenceVsActiveChallenge:
    """P0-18: a password field existing on a big form is NOT an active
    login challenge."""

    def setup_method(self):
        self.observer = PageObserver()

    def test_password_inside_large_registration_form_is_not_login_halt(self):
        elements = [
            _el("e1", accessible_name="Full Name", input_type="text"),
            _el("e2", accessible_name="Mobile", input_type="tel"),
            _el("e3", accessible_name="Email", input_type="email"),
            _el("e4", accessible_name="Address", input_type="text"),
            _el("e5", accessible_name="Create Password", input_type="password"),
            _el("e6", accessible_name="Confirm Password", input_type="password"),
            _el("e7", role="checkbox", accessible_name="I agree to terms"),
            _el("e8", role="button", accessible_name="Register"),
        ]
        auth = self.observer._detect_auth_challenge(elements, [], [], [])
        assert not auth.detected

    def test_validation_errors_do_not_create_auth_challenge(self):
        elements = [_el("e1", accessible_name="Enter verification code")]
        validations = [ValidationErrorState(target_ref="e1", message="Required")]
        auth = self.observer._detect_auth_challenge(elements, [], validations, [])
        # The OTP box is real → detected; validations alone never detect.
        assert auth.detected and auth.challenge_type == "otp"
