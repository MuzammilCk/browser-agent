"""PageObserver — normalizes live page into typed PageState."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from app.browser.aria import extract_aria_snapshot, extract_frame_snapshots
from app.browser.dom import (
    extract_alerts,
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
    PageState,
    ValidationErrorState,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PageObserver:
    """Observes a Playwright page and produces a typed PageState."""

    async def observe(self, page: Page) -> PageState:
        """Observe the current page and return a normalized PageState.

        This is the primary perception method. It combines:
        1. DOM metadata extraction (primary — fast, targeted)
        2. ARIA snapshot (for accessibility representation)
        3. Frame discovery
        4. Validation/alert extraction
        """
        page_id = str(uuid.uuid4())[:8]

        logger.info("Observing page: %s (id=%s)", page.url, page_id)

        # Extract all data in parallel-ish (sequential for Playwright safety)
        elements_raw = await extract_interactive_elements(page)
        validations_raw = await extract_validations(page)
        frames_raw = await extract_frames(page)
        alerts_raw = await extract_alerts(page)
        nav_raw = await extract_navigation(page)
        aria_snapshot = await extract_aria_snapshot(page)

        # Convert raw dicts to typed models
        elements = [self._element_from_raw(e) for e in elements_raw]
        validation_errors = [self._validation_from_raw(v) for v in validations_raw]
        frames = [self._frame_from_raw(f) for f in frames_raw]
        alerts = [self._alert_from_raw(a) for a in alerts_raw]
        navigation = NavigationState(
            can_go_back=nav_raw.get("can_go_back", False),
            can_go_forward=nav_raw.get("can_go_forward", False),
            current_url=nav_raw.get("current_url", page.url),
            title=nav_raw.get("title", ""),
        )

        # Detect authentication challenges
        auth = self._detect_auth_challenge(elements, alerts, validation_errors)

        # Classify page type
        page_type = self._classify_page_type(elements, alerts, validation_errors, auth)

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

        logger.info(
            "Page observed: type=%s, elements=%d, validations=%d, alerts=%d",
            page_type,
            len(elements),
            len(validation_errors),
            len(alerts),
        )

        return page_state

    def _element_from_raw(self, raw: dict) -> ElementState:
        """Convert raw DOM element dict to ElementState model."""
        return ElementState(
            ref=raw.get("ref", ""),
            role=raw.get("role"),
            name=raw.get("name"),
            label=raw.get("label"),
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
        )

    def _validation_from_raw(self, raw: dict) -> ValidationErrorState:
        """Convert raw validation dict to ValidationErrorState model."""
        return ValidationErrorState(
            target_ref=raw.get("target_ref"),
            message=raw.get("message"),
            visible=raw.get("visible", True),
        )

    def _frame_from_raw(self, raw: dict) -> FrameState:
        """Convert raw frame dict to FrameState model."""
        return FrameState(
            frame_id=raw.get("frame_id", ""),
            url=raw.get("url"),
            name=raw.get("name"),
            title=raw.get("title"),
        )

    def _alert_from_raw(self, raw: dict) -> AlertState:
        """Convert raw alert dict to AlertState model."""
        return AlertState(
            ref=raw.get("ref", ""),
            role=raw.get("role"),
            name=raw.get("name"),
            text=raw.get("text"),
            visible=raw.get("visible", True),
        )

    def _detect_auth_challenge(
        self,
        elements: list[ElementState],
        alerts: list[AlertState],
        validations: list[ValidationErrorState],
    ) -> AuthenticationState:
        """Detect if the page is showing an authentication challenge."""
        # Check for OTP-related elements
        otp_keywords = ["otp", "one-time", "verification code", "enter code"]
        captcha_keywords = ["captcha", "security check", "prove you"]
        password_keywords = ["password", "login", "sign in"]

        all_text = " ".join(
            (e.label or "") + " " + (e.name or "") + " " + (e.placeholder or "")
            for e in elements
        ).lower()

        alert_text = " ".join((a.text or "") for a in alerts).lower()

        combined = all_text + " " + alert_text

        for kw in otp_keywords:
            if kw in combined:
                return AuthenticationState(
                    challenge_detected=True,
                    challenge_type="otp",
                    challenge_reason=f"OTP/verification code element detected: '{kw}'",
                )

        for kw in captcha_keywords:
            if kw in combined:
                return AuthenticationState(
                    challenge_detected=True,
                    challenge_type="captcha",
                    challenge_reason=f"CAPTCHA element detected: '{kw}'",
                )

        for kw in password_keywords:
            if kw in combined:
                # Only flag if it seems to be a login page (not just a form with "password" field)
                has_submit = any(e.role == "button" for e in elements)
                if has_submit and len(elements) <= 10:
                    return AuthenticationState(
                        challenge_detected=True,
                        challenge_type="password",
                        challenge_reason="Login form detected",
                    )

        return AuthenticationState()

    def _classify_page_type(
        self,
        elements: list[ElementState],
        alerts: list[AlertState],
        validations: list[ValidationErrorState],
        auth: AuthenticationState,
    ) -> str:
        """Classify the page type based on observed elements."""
        if auth.challenge_detected:
            if auth.challenge_type == "otp":
                return "otp"
            if auth.challenge_type == "captcha":
                return "captcha"
            return "authentication"

        has_form_fields = any(
            e.role in ("textbox", "combobox", "listbox", "checkbox", "radio", "searchbox")
            for e in elements
        )
        has_buttons = any(e.role == "button" for e in elements)

        if has_form_fields:
            return "form"
        if has_buttons:
            return "navigation"

        return "unknown"
