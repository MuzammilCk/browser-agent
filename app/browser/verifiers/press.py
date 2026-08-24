"""Press action verifier — checks page state changed after key press.

Audit B4: press (especially Enter in forms) can trigger state changes
that should be verified, not silently skipped.
"""

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


async def verify_press(
    page: Page, action: BrowserAction, prev: PageState, curr: PageState,
) -> VerificationResult:
    """Verify a press action had the intended effect.

    Check: URL changed, page type changed, or element count changed.
    If nothing changed, report UNCERTAIN (not SUCCESS).
    """
    ref = action.target_ref
    key = action.key or ""

    # If pressed on a specific target, check it still exists
    if ref:
        target = find_element(ref, curr)
        if target is None and key.lower() not in ("escape",):
            # Element disappeared — could mean form submitted, dialog closed, etc.
            # This is expected for Enter on submit buttons, so treat as success
            url_changed = curr.url != prev.url
            if url_changed:
                return make_success("press", ref, f"Page navigated after pressing '{key}'")
            return make_uncertain(
                "press", ref,
                message=f"Element {ref} disappeared after pressing '{key}' (may have navigated)",
            )

    # Check for state changes
    url_changed = curr.url != prev.url
    page_type_changed = curr.page_type != prev.page_type
    element_count_changed = len(curr.elements) != len(prev.elements)
    new_alerts = len(curr.alerts) > len(prev.alerts)
    new_errors = len(curr.validation_errors) > len(prev.validation_errors)

    if url_changed:
        return make_success("press", ref, f"Page navigated after pressing '{key}'")

    if new_errors:
        error_msgs = [v.message for v in curr.validation_errors if v.message]
        return make_failure(
            "press", ref,
            message=f"Validation errors appeared after pressing '{key}': {error_msgs[:3]}",
        )

    if new_alerts:
        return make_failure(
            "press", ref,
            message=f"New alerts appeared after pressing '{key}'",
        )

    if page_type_changed or element_count_changed:
        return make_success("press", ref, f"Page state changed after pressing '{key}'")

    # No observable change — UNCERTAIN, not SUCCESS
    return make_uncertain(
        "press", ref,
        message=f"No observable change after pressing '{key}'",
    )
