"""Post-action verification engine.

After every state-changing action, verify the result matches expectations.
Never assume success just because Playwright returned without exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.models.actions import BrowserAction
from app.models.page_state import PageState

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


@dataclass
class VerificationResult:
    """Result of a post-action verification."""

    status: VerificationStatus
    action_type: str
    target_ref: str | None = None
    expected: str | None = None
    actual: str | None = None
    message: str = ""
    page_changed: bool = False
    validation_errors: list[str] = field(default_factory=list)


class ActionVerifier:
    """Verifies that browser actions had the intended effect."""

    async def verify(
        self,
        page: Page,
        action: BrowserAction,
        previous_state: PageState,
        current_state: PageState,
    ) -> VerificationResult:
        """Verify an action's result by comparing page states."""
        action_type = action.action

        if action_type == "fill":
            return await self._verify_fill(page, action, previous_state, current_state)
        elif action_type == "click":
            return await self._verify_click(action, previous_state, current_state)
        elif action_type == "select":
            return await self._verify_select(action, previous_state, current_state)
        elif action_type in ("check", "uncheck"):
            return await self._verify_check(action, previous_state, current_state)
        elif action_type == "open":
            return await self._verify_open(action, previous_state, current_state)
        elif action_type == "upload":
            return await self._verify_upload(action, previous_state, current_state)
        else:
            # Non-state-changing actions
            return VerificationResult(
                status=VerificationStatus.SUCCESS,
                action_type=action_type,
                message="Non-state-changing action, no verification needed",
            )

    async def _verify_fill(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a fill action."""
        ref = action.target_ref
        if not ref:
            return VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                action_type="fill",
                message="No target ref to verify",
            )

        # Find the element in current state
        target = self._find_element(ref, curr)
        if target is None:
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type="fill",
                target_ref=ref,
                message=f"Element {ref} not found after fill",
            )

        # Check if element is disabled
        if target.disabled:
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type="fill",
                target_ref=ref,
                message=f"Element {ref} is disabled after fill",
            )

        # Check for new validation errors on this element
        new_errors = [
            v for v in curr.validation_errors
            if v.target_ref == ref
        ]
        if new_errors:
            messages = [v.message for v in new_errors if v.message]
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type="fill",
                target_ref=ref,
                message=f"Validation errors appeared: {', '.join(messages)}",
                validation_errors=messages,
            )

        return VerificationResult(
            status=VerificationStatus.SUCCESS,
            action_type="fill",
            target_ref=ref,
            message="Fill action verified successfully",
        )

    async def _verify_click(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a click action (check if page changed)."""
        page_changed = (
            curr.url != prev.url
            or curr.title != prev.title
            or len(curr.elements) != len(prev.elements)
            or curr.page_type != prev.page_type
        )

        if page_changed:
            return VerificationResult(
                status=VerificationStatus.SUCCESS,
                action_type="click",
                target_ref=action.target_ref,
                page_changed=True,
                message="Page changed after click",
            )

        # Page didn't change — could be a toggle or no-op click
        return VerificationResult(
            status=VerificationStatus.UNCERTAIN,
            action_type="click",
            target_ref=action.target_ref,
            message="Page did not change after click — may be expected (toggle, dropdown)",
        )

    async def _verify_select(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a select action."""
        ref = action.target_ref
        if not ref:
            return VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                action_type="select",
                message="No target ref to verify",
            )

        target = self._find_element(ref, curr)
        if target is None:
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type="select",
                target_ref=ref,
                message=f"Element {ref} not found after select",
            )

        # Check if selection was made
        if action.option:
            selected = target.selected_options
            if action.option not in selected and target.value != action.option:
                return VerificationResult(
                    status=VerificationStatus.UNCERTAIN,
                    action_type="select",
                    target_ref=ref,
                    expected=action.option,
                    actual=str(selected),
                    message="Selected option may not match expected",
                )

        return VerificationResult(
            status=VerificationStatus.SUCCESS,
            action_type="select",
            target_ref=ref,
            message="Select action verified",
        )

    async def _verify_check(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a check/uncheck action."""
        ref = action.target_ref
        if not ref:
            return VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                action_type=action.action,
                message="No target ref to verify",
            )

        target = self._find_element(ref, curr)
        if target is None:
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type=action.action,
                target_ref=ref,
                message=f"Element {ref} not found after {action.action}",
            )

        expected_checked = action.action == "check"
        if target.checked is not None and target.checked != expected_checked:
            return VerificationResult(
                status=VerificationStatus.FAILURE,
                action_type=action.action,
                target_ref=ref,
                expected=str(expected_checked),
                actual=str(target.checked),
                message=f"Checkbox state mismatch: expected {expected_checked}, got {target.checked}",
            )

        return VerificationResult(
            status=VerificationStatus.SUCCESS,
            action_type=action.action,
            target_ref=ref,
            message=f"{action.action} action verified",
        )

    async def _verify_open(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a navigation (open) action."""
        if curr.url == prev.url and curr.title == prev.title:
            return VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                action_type="open",
                message="Page URL did not change after open",
            )

        return VerificationResult(
            status=VerificationStatus.SUCCESS,
            action_type="open",
            page_changed=True,
            message=f"Navigated to {curr.url}",
        )

    async def _verify_upload(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a file upload action."""
        # Uploads are hard to verify via DOM alone
        return VerificationResult(
            status=VerificationStatus.UNCERTAIN,
            action_type="upload",
            target_ref=action.target_ref,
            message="Upload verification requires manual confirmation",
        )

    def _find_element(self, ref: str, state: PageState) -> "ElementState | None":
        """Find element by ref in PageState."""
        for el in state.elements:
            if el.ref == ref:
                return el
        return None
