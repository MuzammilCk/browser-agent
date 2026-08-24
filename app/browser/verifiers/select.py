"""Select action verifier — checks selected option and dependent fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    find_element, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState


async def verify_select(
    page, action: BrowserAction, prev: PageState, curr: PageState,
):
    """Verify a select action."""
    ref = action.target_ref
    if not ref:
        return make_uncertain("select", message="No target ref to verify")

    target = find_element(ref, curr)
    if target is None:
        return make_failure("select", ref, message=f"Element {ref} disappeared")

    if action.option:
        selected = target.selected_options
        if action.option not in selected and target.value != action.option:
            return make_failure(
                "select", ref, expected=action.option, actual=str(selected),
                message=f"Expected '{action.option}' but got {selected}",
            )

    new_elements = len(curr.elements) - len(prev.elements)
    if new_elements > 0:
        return make_success("select", ref, f"Verified + {new_elements} new dependent elements")

    return make_success("select", ref, "Select verified")
