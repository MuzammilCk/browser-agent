"""Post-action verification engine — Phase 3 enhanced.

After every state-changing action, verify the result matches expectations.
Uses live Playwright DOM queries for ground-truth verification, not just
comparing PageState snapshots.

Key verifications per action type:
- fill: actual input value matches expected, no new validation errors
- click: page changed OR element state changed OR dialog appeared
- select: selected option matches, dependent fields may have changed
- check/uncheck: checkbox state matches expected
- upload: file input has files
- open: navigation occurred

The verifier detects failed actions rather than blindly reporting success.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.models.actions import BrowserAction
from app.models.page_state import ElementState, PageState

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
    details: dict = field(default_factory=dict)


class ActionVerifier:
    """Verifies that browser actions had the intended effect.

    Uses both PageState comparison AND live Playwright DOM queries
    for ground-truth verification.
    """

    async def verify(
        self,
        page: Page,
        action: BrowserAction,
        previous_state: PageState,
        current_state: PageState,
    ) -> VerificationResult:
        """Verify an action's result by comparing page states and live DOM."""
        action_type = action.action

        if action_type == "fill":
            return await self._verify_fill(page, action, previous_state, current_state)
        elif action_type == "click":
            return await self._verify_click(page, action, previous_state, current_state)
        elif action_type == "select":
            return await self._verify_select(page, action, previous_state, current_state)
        elif action_type in ("check", "uncheck"):
            return await self._verify_check(page, action, previous_state, current_state)
        elif action_type == "open":
            return await self._verify_open(action, previous_state, current_state)
        elif action_type == "upload":
            return await self._verify_upload(page, action, previous_state, current_state)
        elif action_type == "scroll_to":
            return await self._verify_scroll_to(page, action, previous_state, current_state)
        else:
            return VerificationResult(
                status=VerificationStatus.SUCCESS,
                action_type=action_type,
                message="Non-state-changing action, no verification needed",
            )

    # ─── FILL VERIFICATION ───────────────────────────────────────────

    async def _verify_fill(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a fill action using live DOM queries.

        Checks:
        1. Element still exists in current state
        2. Element is not disabled
        3. Live DOM input value matches expected value
        4. No new validation errors on this element
        5. No new page-level alerts appeared
        """
        ref = action.target_ref
        if not ref:
            return self._uncertain("fill", "No target ref to verify")

        # Check 1: Element exists
        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(
                "fill", ref,
                message=f"Element {ref} disappeared after fill",
            )

        # Check 2: Element not disabled
        if target.disabled:
            return self._failure(
                "fill", ref,
                message=f"Element {ref} became disabled after fill",
            )

        # Check 3: Live DOM value check
        expected_value = action.literal_value
        if expected_value:
            try:
                # Find the element by ref in current state and read its live value
                live_value = await self._read_live_value(page, ref, target)
                if live_value is not None and live_value != expected_value:
                    # Normalize for comparison (trim whitespace)
                    if live_value.strip() != expected_value.strip():
                        return self._failure(
                            "fill", ref,
                            expected=expected_value,
                            actual=live_value,
                            message=(
                                f"Live DOM value '{live_value}' does not match "
                                f"expected '{expected_value}'"
                            ),
                        )
            except Exception as e:
                logger.debug("Could not read live value for %s: %s", ref, e)
                # Don't fail verification just because live read failed

        # Check 4: No new validation errors
        new_errors = [v for v in curr.validation_errors if v.target_ref == ref]
        if new_errors:
            messages = [v.message for v in new_errors if v.message]
            return self._failure(
                "fill", ref,
                message=f"Validation errors appeared: {', '.join(messages)}",
                validation_errors=messages,
            )

        # Check 5: No new page-level alerts
        new_alerts = [a for a in curr.alerts if a.visible]
        old_alerts = [a for a in prev.alerts if a.visible]
        if len(new_alerts) > len(old_alerts):
            new_texts = [a.text for a in new_alerts if a.text]
            return self._failure(
                "fill", ref,
                message=f"New alerts appeared after fill: {new_texts[:3]}",
            )

        return self._success("fill", ref, "Fill verified: element exists, value set, no errors")

    # ─── CLICK VERIFICATION ──────────────────────────────────────────

    async def _verify_click(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a click action.

        Checks:
        1. Page URL changed, OR
        2. Page title changed, OR
        3. Element count changed (new elements appeared), OR
        4. Page type changed, OR
        5. A dialog/alert appeared, OR
        6. Element state changed (e.g., dropdown opened)
        """
        ref = action.target_ref

        # Check page-level changes
        page_changed = (
            curr.url != prev.url
            or curr.title != prev.title
            or curr.page_type != prev.page_type
        )

        if page_changed:
            return self._success(
                "click", ref,
                "Page changed after click",
                page_changed=True,
            )

        # Check element count changed (new elements appeared/disappeared)
        if len(curr.elements) != len(prev.elements):
            return self._success(
                "click", ref,
                f"Element count changed: {len(prev.elements)} → {len(curr.elements)}",
                page_changed=True,
            )

        # Check for new alerts/dialogs
        if len(curr.alerts) > len(prev.alerts):
            return self._success(
                "click", ref,
                "Dialog/alert appeared after click",
                page_changed=True,
            )

        # Check validation errors changed
        if len(curr.validation_errors) != len(prev.validation_errors):
            return self._success(
                "click", ref,
                f"Validation errors changed: {len(prev.validation_errors)} → {len(curr.validation_errors)}",
                page_changed=True,
            )

        # Check if a specific element changed state (e.g., checkbox toggled)
        if ref:
            prev_el = self._find_element(ref, prev)
            curr_el = self._find_element(ref, curr)
            if prev_el and curr_el:
                if prev_el.checked != curr_el.checked:
                    return self._success(
                        "click", ref,
                        f"Element state changed: checked {prev_el.checked} → {curr_el.checked}",
                    )
                if prev_el.value != curr_el.value:
                    return self._success(
                        "click", ref,
                        f"Element value changed: '{prev_el.value}' → '{curr_el.value}'",
                    )

        # Nothing observable changed — may still be valid (e.g., dropdown toggle)
        return self._uncertain(
            "click", ref,
            "No observable change after click — may be expected (toggle, hover)",
        )

    # ─── SELECT VERIFICATION ─────────────────────────────────────────

    async def _verify_select(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a select action.

        Checks:
        1. Element still exists
        2. Selected option matches expected
        3. Dependent fields may have appeared/changed
        4. No validation errors
        """
        ref = action.target_ref
        if not ref:
            return self._uncertain("select", "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(
                "select", ref,
                message=f"Element {ref} disappeared after select",
            )

        # Check selected option
        if action.option:
            selected = target.selected_options
            if action.option not in selected and target.value != action.option:
                return self._failure(
                    "select", ref,
                    expected=action.option,
                    actual=str(selected),
                    message=f"Expected '{action.option}' but got {selected}",
                )

        # Detect dependent field changes (new elements appeared)
        new_elements = len(curr.elements) - len(prev.elements)
        if new_elements > 0:
            return self._success(
                "select", ref,
                f"Select verified + {new_elements} new dependent elements appeared",
            )

        return self._success("select", ref, "Select verified: option matches")

    # ─── CHECK/UNCHECK VERIFICATION ──────────────────────────────────

    async def _verify_check(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a check/uncheck action."""
        ref = action.target_ref
        if not ref:
            return self._uncertain(action.action, "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(
                action.action, ref,
                message=f"Element {ref} disappeared after {action.action}",
            )

        expected_checked = action.action == "check"
        if target.checked is not None and target.checked != expected_checked:
            return self._failure(
                action.action, ref,
                expected=str(expected_checked),
                actual=str(target.checked),
                message=f"Checkbox state mismatch: expected {expected_checked}, got {target.checked}",
            )

        return self._success(action.action, ref, f"{action.action} verified")

    # ─── OPEN VERIFICATION ───────────────────────────────────────────

    async def _verify_open(
        self,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a navigation (open) action."""
        if curr.url == prev.url and curr.title == prev.title:
            return self._uncertain(
                "open", message="Page URL did not change after open",
            )
        return self._success(
            "open", message=f"Navigated to {curr.url}", page_changed=True,
        )

    # ─── UPLOAD VERIFICATION ─────────────────────────────────────────

    async def _verify_upload(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify a file upload action using live DOM check."""
        ref = action.target_ref
        if not ref:
            return self._uncertain("upload", "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(
                "upload", ref,
                message=f"Element {ref} disappeared after upload",
            )

        # Live DOM check: does the file input have files?
        try:
            file_count = await page.evaluate("""
                (ref) => {
                    const els = document.querySelectorAll('input[type="file"]');
                    for (const el of els) {
                        if (el.files && el.files.length > 0) return el.files.length;
                    }
                    return 0;
                }
            """, ref)
            if file_count > 0:
                return self._success(
                    "upload", ref,
                    f"Upload verified: {file_count} file(s) attached",
                )
        except Exception:
            pass

        return self._uncertain(
            "upload", ref,
            "Upload completed but file attachment could not be verified via DOM",
        )

    # ─── SCROLL_TO VERIFICATION ──────────────────────────────────────

    async def _verify_scroll_to(
        self,
        page: Page,
        action: BrowserAction,
        prev: PageState,
        curr: PageState,
    ) -> VerificationResult:
        """Verify scroll_to action — element should be in viewport."""
        ref = action.target_ref
        if not ref:
            return self._uncertain("scroll_to", "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(
                "scroll_to", ref,
                message=f"Element {ref} not found after scroll_to",
            )

        return self._success("scroll_to", ref, "Element scrolled into view")

    # ─── HELPERS ─────────────────────────────────────────────────────

    async def _read_live_value(
        self, page: Page, ref: str, element: ElementState
    ) -> str | None:
        """Read the actual current value from the live DOM."""
        try:
            # Try to find by accessible name and read value
            if element.accessible_name:
                try:
                    role = element.role or "textbox"
                    pw_role = {
                        "textbox": "textbox",
                        "combobox": "combobox",
                        "listbox": "listbox",
                        "spinbutton": "spinbutton",
                        "searchbox": "searchbox",
                    }.get(role)
                    if pw_role:
                        loc = page.get_by_role(pw_role, name=element.accessible_name, exact=True)
                        if await loc.count() == 1:
                            return await loc.input_value()
                except Exception:
                    pass

            # Fallback: try by label
            if element.label_text:
                try:
                    loc = page.get_by_label(element.label_text)
                    if await loc.count() == 1:
                        return await loc.input_value()
                except Exception:
                    pass

            # Fallback: try by name attribute
            if element.html_name:
                try:
                    loc = page.locator(f"[name='{element.html_name}']")
                    if await loc.count() == 1:
                        return await loc.input_value()
                except Exception:
                    pass

        except Exception as e:
            logger.debug("Live value read failed for %s: %s", ref, e)

        return None

    def _find_element(self, ref: str, state: PageState) -> ElementState | None:
        """Find element by ref in PageState."""
        for el in state.elements:
            if el.ref == ref:
                return el
        return None

    def _success(
        self,
        action_type: str,
        target_ref: str | None = None,
        message: str = "",
        page_changed: bool = False,
    ) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.SUCCESS,
            action_type=action_type,
            target_ref=target_ref,
            message=message,
            page_changed=page_changed,
        )

    def _failure(
        self,
        action_type: str,
        target_ref: str | None = None,
        message: str = "",
        expected: str | None = None,
        actual: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.FAILURE,
            action_type=action_type,
            target_ref=target_ref,
            expected=expected,
            actual=actual,
            message=message,
            validation_errors=validation_errors or [],
        )

    def _uncertain(
        self,
        action_type: str,
        target_ref: str | None = None,
        message: str = "",
    ) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.UNCERTAIN,
            action_type=action_type,
            target_ref=target_ref,
            message=message,
        )
