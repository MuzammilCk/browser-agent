"""Click action verifier — checks page changes, element state, content."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    VerificationResult, find_element, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState

logger = logging.getLogger(__name__)


async def verify_click(
    page, action: BrowserAction, prev: PageState, curr: PageState,
) -> VerificationResult:
    """Verify a click action had the intended effect."""
    ref = action.target_ref

    # Page-level changes
    if curr.url != prev.url or curr.title != prev.title or curr.page_type != prev.page_type:
        return make_success("click", ref, "Page changed after click", page_changed=True)

    # Element count changed
    if len(curr.elements) != len(prev.elements):
        return make_success(
            "click", ref,
            f"Element count: {len(prev.elements)} -> {len(curr.elements)}",
            page_changed=True,
        )

    # New alerts/dialogs
    if len(curr.alerts) > len(prev.alerts):
        return make_success("click", ref, "Dialog appeared", page_changed=True)

    # Validation errors changed
    if len(curr.validation_errors) != len(prev.validation_errors):
        return make_success(
            "click", ref,
            f"Validation changed: {len(prev.validation_errors)} -> {len(curr.validation_errors)}",
            page_changed=True,
        )

    # Element state changed
    if ref:
        result = _check_element_state_change(ref, prev, curr)
        if result:
            return result

    # Content changed (any element value modified)
    result = _check_content_changed(prev, curr)
    if result:
        return result

    return make_uncertain(
        "click", ref,
        "No observable change — may be expected (toggle, hover, AJAX)",
    )


def _check_element_state_change(ref, prev, curr):
    """Check if the clicked element's state changed."""
    prev_el = find_element(ref, prev)
    curr_el = find_element(ref, curr)
    if not prev_el or not curr_el:
        return None

    if prev_el.checked != curr_el.checked:
        return make_success(
            "click", ref,
            f"State changed: checked {prev_el.checked} -> {curr_el.checked}",
        )
    if prev_el.value != curr_el.value:
        return make_success(
            "click", ref,
            f"Value changed: '{prev_el.value}' -> '{curr_el.value}'",
        )
    if prev_el.disabled != curr_el.disabled:
        return make_success(
            "click", ref,
            f"Disabled state: {prev_el.disabled} -> {curr_el.disabled}",
        )
    return None


def _check_content_changed(prev, curr):
    """Check if any element values changed between states."""
    prev_values = {e.ref: e.value for e in prev.elements if e.value}
    curr_values = {e.ref: e.value for e in curr.elements if e.value}
    if prev_values != curr_values:
        changed = {
            k: (prev_values.get(k), curr_values.get(k))
            for k in set(prev_values) | set(curr_values)
            if prev_values.get(k) != curr_values.get(k)
        }
        return make_success(
            "click", None,
            f"Content changed: {len(changed)} element(s) modified",
        )
    return None
