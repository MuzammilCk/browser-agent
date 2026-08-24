"""Fill action verifier — checks field value, validation errors, alerts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    VerificationResult, find_element, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from app.models.actions import BrowserAction
    from app.models.page_state import PageState

logger = logging.getLogger(__name__)


async def verify_fill(
    page: Page, action: BrowserAction, prev: PageState, curr: PageState,
) -> VerificationResult:
    """Verify a fill action had the intended effect."""
    ref = action.target_ref
    if not ref:
        return make_uncertain("fill", message="No target ref to verify")

    target = find_element(ref, curr)
    if target is None:
        return make_failure("fill", ref, message=f"Element {ref} disappeared after fill")

    if target.disabled:
        return make_failure("fill", ref, message=f"Element {ref} became disabled after fill")

    # Live DOM value check
    expected_value = action.literal_value or ""
    if expected_value:
        live_value = await _read_live_value(page, ref, target)
        if live_value is not None and live_value.strip() != expected_value.strip():
            return make_failure(
                "fill", ref, expected=expected_value, actual=live_value,
                message=f"Live value '{live_value}' != expected '{expected_value}'",
            )

    # Check validation errors on this field
    new_errors = [v for v in curr.validation_errors if v.target_ref == ref]
    if new_errors:
        messages = [v.message for v in new_errors if v.message]
        return make_failure(
            "fill", ref, message=f"Validation errors: {', '.join(messages)}",
            validation_errors=messages,
        )

    # Check new alerts
    prev_alerts = len([a for a in prev.alerts if a.visible])
    curr_alerts = len([a for a in curr.alerts if a.visible])
    if curr_alerts > prev_alerts:
        new_texts = [a.text for a in curr.alerts if a.visible and a.text]
        return make_failure("fill", ref, message=f"New alerts: {new_texts[:3]}")

    return make_success("fill", ref, "Fill verified")


async def _read_live_value(page: Page, ref: str, element) -> str | None:
    """Read actual current value from live DOM."""
    try:
        pw_role = {
            "textbox": "textbox", "combobox": "combobox",
            "listbox": "listbox", "spinbutton": "spinbutton",
            "searchbox": "searchbox",
        }.get(element.role or "textbox")

        if pw_role and element.accessible_name:
            loc = page.get_by_role(pw_role, name=element.accessible_name, exact=True)
            if await loc.count() == 1:
                return await loc.input_value()

        if element.label_text:
            loc = page.get_by_label(element.label_text)
            if await loc.count() == 1:
                return await loc.input_value()

        if element.html_name:
            loc = page.locator(f"[name='{element.html_name}']")
            if await loc.count() == 1:
                return await loc.input_value()
    except Exception as e:
        logger.debug("Live value read failed for %s: %s", ref, e)
    return None
