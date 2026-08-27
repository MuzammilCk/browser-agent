"""PageObserver — normalizes live page into typed PageState + PageObservation.

Updated per audit findings:
- #2: Now produces PageObservation (not just PageState)
- #6: Improved page classification with confidence candidates
- #7: Multi-signal auth detection with confidence scoring
- #15: Frame-aware element extraction
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from app.browser.aria import (
    extract_aria_snapshot,
    extract_aria_snapshot_with_refs,
    extract_frame_snapshots,
)
from app.browser.dom import (
    extract_alerts,
    extract_frame_elements,
    extract_frames,
    extract_interactive_elements,
    extract_navigation,
    extract_validations,
)
from app.models.page_state import (
    AlertState,
    AuthenticationState,
    ElementState,
    FrameState,
    NavigationState,
    PageObservation,
    PageState,
    ValidationErrorState,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PageObserver:
    """Observes a Playwright page and produces a typed PageObservation."""

    async def observe(self, page: Page) -> PageObservation:
        """Observe the current page and return a complete PageObservation.

        This is the primary perception method. It combines:
        1. DOM metadata extraction (primary — fast, targeted)
        2. ARIA snapshot (for accessibility representation)
        3. Frame-aware element extraction
        4. Validation/alert extraction
        """
        page_id = str(uuid.uuid4())[:8]

        logger.info("Observing page: %s (id=%s)", page.url, page_id)

        # Extract main frame data
        elements_raw = await extract_interactive_elements(page)
        validations_raw = await extract_validations(page)
        frames_raw = await extract_frames(page)
        alerts_raw = await extract_alerts(page)
        nav_raw = await extract_navigation(page)
        aria_snapshot = await extract_aria_snapshot_with_refs(page)

        # Extract elements from each frame (#15)
        frame_elements_raw = []
        for frame_info in frames_raw:
            frame_id = frame_info.get("frame_id", "")
            frame_url = frame_info.get("url", "")
            if frame_url:
                fe = await extract_frame_elements(page, frame_id, frame_url)
                frame_elements_raw.extend(fe)

        # Combine main + frame elements
        all_elements_raw = elements_raw + frame_elements_raw

        # Convert raw dicts to typed models
        elements = [self._element_from_raw(e) for e in all_elements_raw]
        validation_errors = [self._validation_from_raw(v) for v in validations_raw]
        frames = [self._frame_from_raw(f) for f in frames_raw]
        alerts = [self._alert_from_raw(a) for a in alerts_raw]
        navigation = NavigationState(
            can_go_back=nav_raw.get("can_go_back", False),
            can_go_forward=nav_raw.get("can_go_forward", False),
            current_url=nav_raw.get("current_url", page.url),
            title=nav_raw.get("title", ""),
        )

        # Improved auth detection with confidence scoring (#7, P0-18):
        # frame metadata participates so reCAPTCHA iframes are detected.
        auth = self._detect_auth_challenge(elements, alerts, validation_errors, frames)

        # Improved page type classification (#6)
        page_type = self._classify_page_type(
            elements, alerts, validation_errors, auth, navigation
        )

        page_state = PageState(
            url=page.url,
            title=navigation.title,
            page_id=page_id,
            page_type=page_type,
            elements=elements,
            alerts=alerts,
            validation_errors=validation_errors,
            frames=frames,
            navigation=navigation,
            authentication=auth,
            visual_fallback_available=True,
        )

        observation = PageObservation(
            page_state=page_state,
            aria_snapshot=aria_snapshot,
            frame_snapshots=await extract_frame_snapshots(page),
            screenshot_available=True,
            observation_id=page_id,
        )

        logger.info(
            "Page observed: type=%s, elements=%d, frames=%d, validations=%d, alerts=%d",
            page_type,
            len(elements),
            len(frames),
            len(validation_errors),
            len(alerts),
        )

        return observation

    def _element_from_raw(self, raw: dict) -> ElementState:
        """Convert raw DOM element dict to ElementState model."""
        return ElementState(
            ref=raw.get("ref", ""),
            role=raw.get("role"),
            accessible_name=raw.get("accessible_name"),
            html_name=raw.get("html_name"),
            label_text=raw.get("label_text"),
            value=raw.get("value"),
            input_type=raw.get("input_type"),
            required=raw.get("required", False),
            disabled=raw.get("disabled", False),
            checked=raw.get("checked"),
            selected_options=raw.get("selected_options", []),
            placeholder=raw.get("placeholder"),
            autocomplete=raw.get("autocomplete"),
            description=raw.get("description"),
            visible=raw.get("visible", True),
            frame_id=raw.get("frame_id"),
            section_heading=raw.get("section_heading"),
            group_label=raw.get("group_label"),
            help_text=raw.get("help_text"),
            nearby_text=raw.get("nearby_text"),
        )

    def _validation_from_raw(self, raw: dict) -> ValidationErrorState:
        return ValidationErrorState(
            target_ref=raw.get("target_ref"),
            message=raw.get("message"),
            visible=raw.get("visible", True),
        )

    def _frame_from_raw(self, raw: dict) -> FrameState:
        return FrameState(
            frame_id=raw.get("frame_id", ""),
            url=raw.get("url"),
            name=raw.get("name"),
            title=raw.get("title"),
        )

    def _alert_from_raw(self, raw: dict) -> AlertState:
        return AlertState(
            ref=raw.get("ref", ""),
            role=raw.get("role"),
            name=raw.get("name"),
            text=raw.get("text"),
            visible=raw.get("visible", True),
        )

    # Keywords that indicate an OTP challenge. "captcha" is deliberately
    # NOT here — it belongs to the CAPTCHA branch (audit Z1 category
    # confusion made a help link mentioning CAPTCHA read as live OTP).
    _OTP_KEYWORDS = ("otp", "one-time", "one time password",
                     "verification code", "enter code")
    _CAPTCHA_KEYWORDS = ("captcha", "recaptcha", "security check",
                         "prove you", "prove you're human", "robot")
    # Roles that can actually receive typed OTP/CAPTCHA input. A link or
    # button whose NAME mentions OTP is not an input field (audit Z1).
    _EDITABLE_INPUT_ROLES = frozenset({"textbox", "searchbox", "spinbutton"})

    @staticmethod
    def _element_text(el: ElementState) -> str:
        return (
            (el.accessible_name or "") + " " + (el.label_text or "") + " "
            + (el.placeholder or "")
        ).lower()

    def _is_otp_input(self, el: ElementState) -> bool:
        """A real OTP input: editable, enabled, visible, OTP-named."""
        return (
            el.visible
            and not el.disabled
            and el.role in self._EDITABLE_INPUT_ROLES
            and any(kw in self._element_text(el) for kw in self._OTP_KEYWORDS)
        )

    def _is_captcha_widget(self, el: ElementState) -> bool:
        """Structural CAPTCHA widget: an editable entry box or a challenge
        image (role=img) — NOT a mere text mention on links/buttons."""
        if not el.visible or el.disabled:
            return False
        if el.role not in self._EDITABLE_INPUT_ROLES | {"img"}:
            return False
        return any(kw in self._element_text(el) for kw in self._CAPTCHA_KEYWORDS)

    def _detect_auth_challenge(
        self,
        elements: list[ElementState],
        alerts: list[AlertState],
        validations: list[ValidationErrorState],
        frames: list[FrameState] | None = None,
    ) -> AuthenticationState:
        """Multi-signal auth detection with confidence scoring (#7, P0-18).

        A detection means "a challenge is actively blocking progress right
        now" and always requires STRUCTURAL co-occurrence, never a bare
        keyword mention anywhere on the page:

        - login: classic small login form shape (few fields + button)
        - otp: an editable, enabled input named like an OTP box
        - captcha: an editable/image CAPTCHA widget, an active dialog
          instructing to complete one, or a reCAPTCHA iframe on the page

        A password field inside a large registration form, a help link
        explaining CAPTCHAs, or a "Resend OTP" button alone do NOT halt.
        """
        has_password_field = False
        otp_inputs: list[ElementState] = []
        captcha_widgets: list[ElementState] = []
        field_count = 0
        button_count = 0
        signals: list[str] = []

        for el in elements:
            if not el.visible:
                continue

            if el.input_type == "password":
                has_password_field = True
                field_count += 1
                signals.append("password_field")

            if self._is_otp_input(el):
                otp_inputs.append(el)
                field_count += 1
                signals.append(f"otp_field: {el.accessible_name}")
            elif self._is_captcha_widget(el):
                captcha_widgets.append(el)
                signals.append(f"captcha_widget: {el.accessible_name}")

            if el.role in ("textbox", "combobox", "listbox", "checkbox", "radio", "searchbox"):
                field_count += 1
            if el.role == "button":
                button_count += 1

        # Alert/dialog-based signals: an active dialog telling the user to
        # complete a CAPTCHA IS a blocking challenge.
        alert_text = " ".join((a.text or "").lower() for a in alerts)
        if alert_text and any(kw in alert_text for kw in self._CAPTCHA_KEYWORDS):
            signals.append("captcha_dialog")

        # reCAPTCHA-style challenge frames are structurally present.
        frame_text = " ".join(
            f"{f.url or ''} {f.title or ''} {f.name or ''}".lower()
            for f in (frames or [])
        )
        if frame_text and "recaptcha" in frame_text:
            signals.append("recaptcha_iframe")

        # Confidence scoring
        if has_password_field and field_count <= 6 and button_count >= 1:
            # Classic login form pattern
            confidence = 0.85
            return AuthenticationState(
                detected=True,
                challenge_type="login",
                reason=f"Login form detected: {', '.join(signals)}",
                confidence=confidence,
            )

        if otp_inputs:
            confidence = 0.9 if field_count <= 4 else 0.6
            return AuthenticationState(
                detected=True,
                challenge_type="otp",
                reason=f"OTP element detected: {', '.join(signals)}",
                confidence=confidence,
            )

        if captcha_widgets or "captcha_dialog" in signals or "recaptcha_iframe" in signals:
            return AuthenticationState(
                detected=True,
                challenge_type="captcha",
                reason=f"CAPTCHA challenge detected: {', '.join(signals)}",
                confidence=0.8,
            )

        return AuthenticationState()

    def _classify_page_type(
        self,
        elements: list[ElementState],
        alerts: list[AlertState],
        validations: list[ValidationErrorState],
        auth: AuthenticationState,
        navigation: NavigationState,
    ) -> str:
        """Improved page type classification with signal-based approach (#6).

        Returns page_type candidates. Uses deterministic signals first.
        """
        # Auth pages take priority
        if auth.detected:
            if auth.challenge_type == "otp":
                return "otp"
            if auth.challenge_type == "captcha":
                return "captcha"
            return "authentication"

        # Count signals
        form_field_roles = {"textbox", "combobox", "listbox", "checkbox", "radio", "searchbox", "spinbutton"}
        form_fields = [e for e in elements if e.role in form_field_roles and e.visible]
        buttons = [e for e in elements if e.role == "button" and e.visible]
        links = [e for e in elements if e.role == "link" and e.visible]

        # Check for error state
        if validations:
            has_form = len(form_fields) > 0
            if has_form:
                return "form"  # Form with validation errors
            return "error"

        # Check for success patterns
        alert_text = " ".join((a.text or "").lower() for a in alerts)
        if any(kw in alert_text for kw in ["success", "submitted", "completed", "acknowledgement"]):
            return "success"

        # Form detection: has text inputs, selects, etc.
        has_text_inputs = any(e.input_type in ("text", "email", "tel", "date", "number") for e in form_fields)
        has_dropdowns = any(e.role == "combobox" for e in form_fields)
        has_checkboxes = any(e.role in ("checkbox", "radio") for e in form_fields)

        if has_text_inputs or has_dropdowns or has_checkboxes:
            # Distinguish form vs review
            has_submit = any(
                b.accessible_name and any(
                    kw in (b.accessible_name or "").lower()
                    for kw in ["submit", "apply", "next", "save", "continue"]
                )
                for b in buttons
            )
            if has_submit:
                return "form"

            # Could be a review page — form fields present but no submit
            # Check if fields are disabled (review pattern)
            disabled_fields = [e for e in form_fields if e.disabled]
            if len(disabled_fields) > len(form_fields) * 0.5:
                return "review"

            return "form"

        # Navigation page: only buttons and links
        if buttons and not form_fields:
            return "navigation"

        # Empty or unknown
        return "unknown"
