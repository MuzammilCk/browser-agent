"""Scroll_to action verifier — checks viewport state via bounding rect."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    find_element, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState

logger = logging.getLogger(__name__)

_VIEWPORT_JS = """
(elementInfo) => {
    let el = null;
    if (elementInfo.html_name) {
        el = document.querySelector('[name="' + elementInfo.html_name + '"]');
    }
    if (!el && elementInfo.accessible_name) {
        el = document.querySelector('[aria-label="' + elementInfo.accessible_name + '"]');
    }
    if (!el) return { in_viewport: false, reason: 'element not found in DOM' };
    const rect = el.getBoundingClientRect();
    const inView = (
        rect.top >= -100 && rect.left >= -100 &&
        rect.bottom <= window.innerHeight + 100 &&
        rect.right <= window.innerWidth + 100
    );
    return {
        in_viewport: inView,
        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }
    };
}
"""


async def verify_scroll_to(
    page, action: BrowserAction, prev: PageState, curr: PageState,
):
    """Verify element is actually in viewport after scroll."""
    ref = action.target_ref
    if not ref:
        return make_uncertain("scroll_to", message="No target ref")

    target = find_element(ref, curr)
    if target is None:
        return make_failure("scroll_to", ref, message=f"Element {ref} not found")

    try:
        result = await page.evaluate(
            _VIEWPORT_JS,
            {"html_name": target.html_name, "accessible_name": target.accessible_name},
        )

        if result.get("in_viewport"):
            return make_success("scroll_to", ref, "Element is in viewport")
        return make_failure(
            "scroll_to", ref,
            message=f"Element NOT in viewport: {result.get('reason', 'outside bounds')}",
        )
    except Exception as e:
        logger.debug("Viewport check failed: %s", e)
        return make_uncertain("scroll_to", ref, "Could not verify viewport state")
