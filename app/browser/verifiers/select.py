"""Select action verifier — checks selected option and dependent fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    describe_value_mismatch, find_element, make_failure, make_success,
    make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState


def _norm(s: str | None) -> str:
    """Normalize for option comparison: collapse whitespace, casefold."""
    return " ".join((s or "").split()).casefold()


def _option_matches(action_option: str, selected: list[str], value: str | None) -> bool:
    """Match the requested option against selected labels / element value.

    Vault values often differ from page label text only by case or
    whitespace ("kerala" vs "Kerala"); both refer to the same option.
    """
    wanted = _norm(action_option)
    if not wanted:
        return True
    if any(_norm(s) == wanted for s in selected):
        return True
    return _norm(value) == wanted


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

    if action.option and not _option_matches(action.option, target.selected_options, target.value):
        # Phase 15 H1: option may be a vault-resolved value — never echo it
        # (or the page's selected values) into the failure message.
        return make_failure(
            "select", ref,
            message=describe_value_mismatch(
                action.option,
                ", ".join(target.selected_options) if target.selected_options else None,
                subject="Selected option",
            ),
        )

    new_elements = len(curr.elements) - len(prev.elements)
    if new_elements > 0:
        return make_success("select", ref, f"Verified + {new_elements} new dependent elements")

    return make_success("select", ref, "Select verified")
