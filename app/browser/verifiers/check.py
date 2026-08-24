"""Check/uncheck action verifier — verifies checkbox state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    find_element, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState


async def verify_check(
    page, action: BrowserAction, prev: PageState, curr: PageState,
):
    """Verify a check/uncheck action."""
    ref = action.target_ref
    if not ref:
        return make_uncertain(action.action, message="No target ref")

    target = find_element(ref, curr)
    if target is None:
        return make_failure(action.action, ref, message=f"Element {ref} disappeared")

    expected_checked = action.action == "check"
    if target.checked is not None and target.checked != expected_checked:
        return make_failure(
            action.action, ref,
            expected=str(expected_checked), actual=str(target.checked),
            message=f"Mismatch: expected {expected_checked}, got {target.checked}",
        )

    return make_success(action.action, ref, f"{action.action} verified")
