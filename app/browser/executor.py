"""Browser action executor — typed Playwright operations.

Updated per audit findings:
- #9: Supports value_ref via ValueResolver (sensitive values resolved locally)
- #10: Supports document_ref via DocumentResolver
- #11+#12: Verification wired into core execution loop
- #14: Added scroll_to(target_ref) semantic scrolling
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.browser.locator import LocatorResolver
from app.browser.verification import ActionVerifier, VerificationResult, VerificationStatus
from app.models.actions import BrowserAction
from app.models.page_state import PageState
from app.vault.resolver import DocumentResolver, DocumentRegistry, UserVault, ValueResolver

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of executing a browser action."""

    action: BrowserAction
    success: bool
    message: str = ""
    verification: VerificationResult | None = None


class BrowserExecutor:
    """Executes typed browser actions using Playwright.

    After every state-changing action, verification is performed.
    """

    def __init__(
        self,
        vault: UserVault | None = None,
        document_registry: DocumentRegistry | None = None,
    ) -> None:
        self.locator_resolver = LocatorResolver()
        self.verifier = ActionVerifier()
        self.value_resolver = ValueResolver(vault or UserVault())
        self.document_resolver = DocumentResolver(document_registry or DocumentRegistry())

    def set_vault(self, vault: UserVault) -> None:
        """Update the user vault for value resolution."""
        self.value_resolver = ValueResolver(vault)

    def set_document_registry(self, registry: DocumentRegistry) -> None:
        """Update the document registry."""
        self.document_resolver = DocumentResolver(registry)

    async def execute(
        self,
        page: Page,
        action: BrowserAction,
        page_state: PageState,
    ) -> ActionResult:
        """Execute a browser action, verify, and return the result.

        Core loop per audit #12:
        action -> execute -> verify -> return result
        """
        logger.info("Executing action: %s (target=%s)", action.action, action.target_ref)

        # Capture pre-state for verification
        previous_state = page_state

        try:
            # Execute the action
            result = await self._do_execute(page, action, page_state)

            if not result.success:
                return result

            # Re-observe after state-changing action (#12)
            from app.browser.observer import PageObserver

            observer = PageObserver()
            new_observation = await observer.observe(page)
            current_state = new_observation.page_state

            # Verify the action had the intended effect (#11)
            verification = await self.verifier.verify(
                page=page,
                action=action,
                previous_state=previous_state,
                current_state=current_state,
            )

            result.verification = verification

            if verification.status == VerificationStatus.FAILURE:
                logger.warning(
                    "Verification FAILED for %s: %s",
                    action.action,
                    verification.message,
                )
                result.success = False
                result.message = f"Verified FAILED: {verification.message}"
            elif verification.status == VerificationStatus.UNCERTAIN:
                logger.info(
                    "Verification UNCERTAIN for %s: %s",
                    action.action,
                    verification.message,
                )
                # UNCERTAIN is still treated as success (may be expected)
            else:
                logger.info("Verification SUCCESS for %s", action.action)

            return result

        except Exception as e:
            logger.error("Action execution failed: %s", e, exc_info=True)
            return ActionResult(
                action=action,
                success=False,
                message=f"Execution error: {e}",
            )

    async def _do_execute(
        self,
        page: Page,
        action: BrowserAction,
        page_state: PageState,
    ) -> ActionResult:
        """Execute the raw Playwright action (without verification)."""
        try:
            if action.action == "open":
                return await self._execute_open(page, action)
            elif action.action == "click":
                return await self._execute_click(page, action, page_state)
            elif action.action == "fill":
                return await self._execute_fill(page, action, page_state)
            elif action.action == "select":
                return await self._execute_select(page, action, page_state)
            elif action.action == "check":
                return await self._execute_check(page, action, page_state, True)
            elif action.action == "uncheck":
                return await self._execute_check(page, action, page_state, False)
            elif action.action == "scroll":
                return await self._execute_scroll(page, action)
            elif action.action == "scroll_to":
                return await self._execute_scroll_to(page, action, page_state)
            elif action.action == "press":
                return await self._execute_press(page, action, page_state)
            elif action.action == "wait":
                return await self._execute_wait(page, action)
            elif action.action == "go_back":
                return await self._execute_go_back(page, action)
            elif action.action == "upload":
                return await self._execute_upload(page, action, page_state)
            elif action.action == "request_user_action":
                return ActionResult(
                    action=action,
                    success=True,
                    message=f"User action requested: {action.reason}",
                )
            elif action.action == "stop":
                return ActionResult(
                    action=action,
                    success=True,
                    message="Agent stopped",
                )
            else:
                return ActionResult(
                    action=action,
                    success=False,
                    message=f"Unknown action type: {action.action}",
                )
        except Exception as e:
            logger.error("Raw execution failed: %s", e, exc_info=True)
            return ActionResult(
                action=action,
                success=False,
                message=f"Execution error: {e}",
            )

    def _resolve_value(self, action: BrowserAction) -> str | None:
        """Resolve the value for a fill action (#9).

        Priority: value_ref (resolved locally) > literal_value
        """
        if action.value_ref:
            value = self.value_resolver.resolve(action.value_ref)
            if value is None:
                logger.warning("Could not resolve value_ref: %s", action.value_ref)
            return value
        return action.literal_value

    def _resolve_document_path(self, action: BrowserAction) -> str | None:
        """Resolve the file path for an upload action (#10).

        Priority: document_ref (resolved locally) > literal_value (file path)
        """
        if action.document_ref:
            doc = self.document_resolver.resolve(action.document_ref)
            if doc is None:
                logger.warning("Could not resolve document_ref: %s", action.document_ref)
                return None
            return doc.path
        return action.literal_value

    async def _execute_open(self, page: Page, action: BrowserAction) -> ActionResult:
        url = action.literal_value
        if not url:
            return ActionResult(action=action, success=False, message="No URL provided")
        await page.goto(url, wait_until="domcontentloaded")
        return ActionResult(action=action, success=True, message=f"Navigated to {url}")

    async def _execute_click(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")
        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )
        await locator.click()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return ActionResult(action=action, success=True, message=f"Clicked {action.target_ref}")

    async def _execute_fill(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        # Resolve value via ValueResolver (#9)
        value = self._resolve_value(action)
        if value is None:
            return ActionResult(
                action=action, success=False,
                message="No value provided (value_ref unresolved or literal_value missing)",
            )

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.click()
        await locator.fill(value)
        return ActionResult(action=action, success=True, message=f"Filled {action.target_ref}")

    async def _execute_select(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")
        if not action.option:
            return ActionResult(action=action, success=False, message="No option provided")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.select_option(label=action.option)
        return ActionResult(
            action=action, success=True,
            message=f"Selected '{action.option}' in {action.target_ref}",
        )

    async def _execute_check(
        self, page: Page, action: BrowserAction, page_state: PageState, check: bool
    ) -> ActionResult:
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        if check:
            await locator.check()
        else:
            await locator.uncheck()
        return ActionResult(
            action=action, success=True,
            message=f"{'Checked' if check else 'Unchecked'} {action.target_ref}",
        )

    async def _execute_scroll(self, page: Page, action: BrowserAction) -> ActionResult:
        direction = action.direction or "down"
        delta = {"up": -500, "down": 500, "left": -500, "right": 500}
        await page.mouse.wheel(0, delta.get(direction, 500))
        return ActionResult(action=action, success=True, message=f"Scrolled {direction}")

    async def _execute_scroll_to(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Scroll an element into view (#14)."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.scroll_into_view_if_needed()
        return ActionResult(
            action=action, success=True,
            message=f"Scrolled to {action.target_ref}",
        )

    async def _execute_press(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        key = action.key
        if not key:
            return ActionResult(action=action, success=False, message="No key specified")

        if action.target_ref:
            locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
            if locator:
                await locator.press(key)
                return ActionResult(
                    action=action, success=True,
                    message=f"Pressed '{key}' on {action.target_ref}",
                )

        await page.keyboard.press(key)
        return ActionResult(action=action, success=True, message=f"Pressed '{key}'")

    async def _execute_wait(self, page: Page, action: BrowserAction) -> ActionResult:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        return ActionResult(action=action, success=True, message="Waited for page load")

    async def _execute_go_back(self, page: Page, action: BrowserAction) -> ActionResult:
        await page.go_back()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return ActionResult(action=action, success=True, message="Navigated back")

    async def _execute_upload(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        # Resolve file path via DocumentResolver (#10)
        file_path = self._resolve_document_path(action)
        if not file_path:
            return ActionResult(
                action=action, success=False,
                message="No file path (document_ref unresolved or literal_value missing)",
            )

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.set_input_files(file_path)
        return ActionResult(
            action=action, success=True,
            message=f"Uploaded file to {action.target_ref}",
        )
