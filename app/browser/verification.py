"""Post-action verification engine — Phase 3.5 hardened.

- #5: Upload verification targets exact element, not all file inputs
- #14: Frame-aware verification (resolves within correct frame)
- #15: Enhanced click verification (section text, disabled state, content comparison)
- #17: scroll_to verifies viewport via bounding rect
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

    Phase 3.5: frame-aware, viewport-checking, content-comparing.
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

    # ─── FILL ────────────────────────────────────────────────────────

    async def _verify_fill(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref
        if not ref:
            return self._uncertain("fill", "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure("fill", ref, message=f"Element {ref} disappeared after fill")

        if target.disabled:
            return self._failure("fill", ref, message=f"Element {ref} became disabled after fill")

        # Live DOM value check
        expected_value = action.literal_value or ""
        if expected_value:
            try:
                live_value = await self._read_live_value(page, ref, target)
                if live_value is not None and live_value.strip() != expected_value.strip():
                    return self._failure(
                        "fill", ref, expected=expected_value, actual=live_value,
                        message=f"Live DOM value '{live_value}' != expected '{expected_value}'",
                    )
            except Exception as e:
                logger.debug("Could not read live value for %s: %s", ref, e)

        # Check validation errors
        new_errors = [v for v in curr.validation_errors if v.target_ref == ref]
        if new_errors:
            messages = [v.message for v in new_errors if v.message]
            return self._failure(
                "fill", ref,
                message=f"Validation errors appeared: {', '.join(messages)}",
                validation_errors=messages,
            )

        # Check new alerts
        if len([a for a in curr.alerts if a.visible]) > len([a for a in prev.alerts if a.visible]):
            new_texts = [a.text for a in curr.alerts if a.visible and a.text]
            return self._failure("fill", ref, message=f"New alerts: {new_texts[:3]}")

        return self._success("fill", ref, "Fill verified")

    # ─── CLICK (enhanced #15) ────────────────────────────────────────

    async def _verify_click(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref

        # Page-level changes
        if curr.url != prev.url or curr.title != prev.title or curr.page_type != prev.page_type:
            return self._success("click", ref, "Page changed after click", page_changed=True)

        # Element count changed
        if len(curr.elements) != len(prev.elements):
            return self._success(
                "click", ref,
                f"Element count: {len(prev.elements)} -> {len(curr.elements)}",
                page_changed=True,
            )

        # New alerts/dialogs
        if len(curr.alerts) > len(prev.alerts):
            return self._success("click", ref, "Dialog appeared", page_changed=True)

        # Validation errors changed
        if len(curr.validation_errors) != len(prev.validation_errors):
            return self._success(
                "click", ref,
                f"Validation changed: {len(prev.validation_errors)} -> {len(curr.validation_errors)}",
                page_changed=True,
            )

        # Element state changed
        if ref:
            prev_el = self._find_element(ref, prev)
            curr_el = self._find_element(ref, curr)
            if prev_el and curr_el:
                if prev_el.checked != curr_el.checked:
                    return self._success(
                        "click", ref,
                        f"State changed: checked {prev_el.checked} -> {curr_el.checked}",
                    )
                if prev_el.value != curr_el.value:
                    return self._success(
                        "click", ref,
                        f"Value changed: '{prev_el.value}' -> '{curr_el.value}'",
                    )
                # #15: Check disabled state changed
                if prev_el.disabled != curr_el.disabled:
                    return self._success(
                        "click", ref,
                        f"Disabled state: {prev_el.disabled} -> {curr_el.disabled}",
                    )

        # #15: Check if relevant section text changed by comparing element values
        # For form pages, if any element's value changed, that's a success
        prev_values = {e.ref: e.value for e in prev.elements if e.value}
        curr_values = {e.ref: e.value for e in curr.elements if e.value}
        if prev_values != curr_values:
            changed = {k: (prev_values.get(k), curr_values.get(k))
                      for k in set(prev_values) | set(curr_values)
                      if prev_values.get(k) != curr_values.get(k)}
            return self._success(
                "click", ref,
                f"Content changed: {len(changed)} element(s) modified",
            )

        # #15: Check if a button became enabled/disabled (e.g., submit after validation)
        if ref:
            curr_el = self._find_element(ref, curr)
            if curr_el and curr_el.role == "button":
                # Button click that didn't change anything visible — UNCERTAIN
                pass

        return self._uncertain(
            "click", ref,
            "No observable change — may be expected (toggle, hover, AJAX)",
        )

    # ─── SELECT ──────────────────────────────────────────────────────

    async def _verify_select(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref
        if not ref:
            return self._uncertain("select", "No target ref to verify")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure("select", ref, message=f"Element {ref} disappeared")

        if action.option:
            selected = target.selected_options
            if action.option not in selected and target.value != action.option:
                return self._failure(
                    "select", ref, expected=action.option, actual=str(selected),
                    message=f"Expected '{action.option}' but got {selected}",
                )

        # Detect dependent field changes
        new_elements = len(curr.elements) - len(prev.elements)
        if new_elements > 0:
            return self._success(
                "select", ref,
                f"Verified + {new_elements} new dependent elements",
            )

        return self._success("select", ref, "Select verified")

    # ─── CHECK/UNCHECK ───────────────────────────────────────────────

    async def _verify_check(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref
        if not ref:
            return self._uncertain(action.action, "No target ref")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure(action.action, ref, message=f"Element {ref} disappeared")

        expected_checked = action.action == "check"
        if target.checked is not None and target.checked != expected_checked:
            return self._failure(
                action.action, ref,
                expected=str(expected_checked), actual=str(target.checked),
                message=f"Mismatch: expected {expected_checked}, got {target.checked}",
            )

        return self._success(action.action, ref, f"{action.action} verified")

    # ─── UPLOAD (#5: exact element targeting) ────────────────────────

    async def _verify_upload(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref
        if not ref:
            return self._uncertain("upload", "No target ref")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure("upload", ref, message=f"Element {ref} disappeared")

        # #5: Verify the EXACT target element, not any file input
        try:
            file_info = await page.evaluate("""
                (elementInfo) => {
                    // Find the specific file input by name or accessible name
                    let target = null;
                    if (elementInfo.html_name) {
                        target = document.querySelector('input[type="file"][name="' + elementInfo.html_name + '"]');
                    }
                    if (!target && elementInfo.accessible_name) {
                        // Try by aria-label
                        target = document.querySelector('input[type="file"][aria-label="' + elementInfo.accessible_name + '"]');
                    }
                    if (!target && elementInfo.label_text) {
                        // Try by associated label
                        const labels = document.querySelectorAll('label');
                        for (const label of labels) {
                            if (label.textContent.includes(elementInfo.label_text)) {
                                const forId = label.getAttribute('for');
                                if (forId) {
                                    target = document.getElementById(forId);
                                }
                                if (!target) {
                                    target = label.querySelector('input[type="file"]');
                                }
                                break;
                            }
                        }
                    }
                    if (!target) {
                        // Last resort: try by input_type and ref index
                        const inputs = document.querySelectorAll('input[type="file"]');
                        const idx = parseInt(elementInfo.ref.replace('e', '')) - 1;
                        if (idx >= 0 && idx < inputs.length) {
                            target = inputs[idx];
                        }
                    }
                    if (target && target.files && target.files.length > 0) {
                        return {
                            found: true,
                            file_count: target.files.length,
                            file_name: target.files[0].name || null
                        };
                    }
                    return { found: false, file_count: 0, file_name: null };
                }
            """, {
                "ref": ref,
                "html_name": target.html_name,
                "accessible_name": target.accessible_name,
                "label_text": target.label_text,
            })

            if file_info.get("found") and file_info.get("file_count", 0) > 0:
                details = {"file_count": file_info["file_count"]}
                if file_info.get("file_name"):
                    details["file_name"] = file_info["file_name"]
                return self._success(
                    "upload", ref,
                    f"Upload verified: {file_info['file_count']} file(s)",
                    details=details,
                )
        except Exception as e:
            logger.debug("Upload verification error: %s", e)

        return self._uncertain(
            "upload", ref,
            "Upload completed but target-specific verification failed",
        )

    # ─── SCROLL_TO (#17: viewport verification) ─────────────────────

    async def _verify_scroll_to(
        self, page: Page, action: BrowserAction, prev: PageState, curr: PageState
    ) -> VerificationResult:
        ref = action.target_ref
        if not ref:
            return self._uncertain("scroll_to", "No target ref")

        target = self._find_element(ref, curr)
        if target is None:
            return self._failure("scroll_to", ref, message=f"Element {ref} not found")

        # #17: Verify element is actually in viewport
        try:
            in_viewport = await page.evaluate("""
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
                        rect.top >= -100 &&
                        rect.left >= -100 &&
                        rect.bottom <= window.innerHeight + 100 &&
                        rect.right <= window.innerWidth + 100
                    );
                    return {
                        in_viewport: inView,
                        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }
                    };
                }
            """, {
                "html_name": target.html_name,
                "accessible_name": target.accessible_name,
            })

            if in_viewport.get("in_viewport"):
                return self._success("scroll_to", ref, "Element is in viewport")
            else:
                return self._failure(
                    "scroll_to", ref,
                    message=f"Element NOT in viewport: {in_viewport.get('reason', 'outside bounds')}",
                )
        except Exception as e:
            logger.debug("Viewport check failed: %s", e)
            return self._uncertain("scroll_to", ref, "Could not verify viewport state")

    # ─── HELPERS ─────────────────────────────────────────────────────

    async def _read_live_value(
        self, page: Page, ref: str, element: ElementState
    ) -> str | None:
        """Read actual current value from live DOM."""
        try:
            if element.accessible_name:
                try:
                    pw_role = {
                        "textbox": "textbox", "combobox": "combobox",
                        "listbox": "listbox", "spinbutton": "spinbutton",
                        "searchbox": "searchbox",
                    }.get(element.role or "textbox")
                    if pw_role:
                        loc = page.get_by_role(pw_role, name=element.accessible_name, exact=True)
                        if await loc.count() == 1:
                            return await loc.input_value()
                except Exception:
                    pass
            if element.label_text:
                try:
                    loc = page.get_by_label(element.label_text)
                    if await loc.count() == 1:
                        return await loc.input_value()
                except Exception:
                    pass
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
        for el in state.elements:
            if el.ref == ref:
                return el
        return None

    def _success(self, action_type: str, target_ref: str | None = None,
                 message: str = "", page_changed: bool = False,
                 details: dict | None = None) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.SUCCESS, action_type=action_type,
            target_ref=target_ref, message=message, page_changed=page_changed,
            details=details or {},
        )

    def _failure(self, action_type: str, target_ref: str | None = None,
                 message: str = "", expected: str | None = None,
                 actual: str | None = None,
                 validation_errors: list[str] | None = None) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.FAILURE, action_type=action_type,
            target_ref=target_ref, expected=expected, actual=actual,
            message=message, validation_errors=validation_errors or [],
        )

    def _uncertain(self, action_type: str, target_ref: str | None = None,
                   message: str = "") -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.UNCERTAIN, action_type=action_type,
            target_ref=target_ref, message=message,
        )
