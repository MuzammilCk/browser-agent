"""Browser action executor — Phase 3.5 hardened.

- #1: UNCERTAIN verification stops progression (not silently continues)
- #2+#23: ActionResult includes post_observation, recovery_required, user_action_required
- #4: Frame-aware locator dispatch
- #6: Removed open from LLM actions
- #7: Upload requires document_ref only
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.browser.locator import LocatorResolver
from app.browser.verification import ActionVerifier, VerificationResult, VerificationStatus
from app.models.actions import BrowserAction
from app.models.page_state import PageObservation, PageState
from app.vault.resolver import DocumentResolver, DocumentRegistry, UserVault, ValueResolver

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of executing a browser action — the contract for the future agent.

    #2+#23: Includes post_observation so the next iteration uses fresh state.
    """

    action: BrowserAction
    success: bool
    message: str = ""
    verification: VerificationResult | None = None
    post_observation: PageObservation | None = None
    recovery_required: bool = False
    user_action_required: bool = False


class BrowserExecutor:
    """Executes typed browser actions using Playwright.

    Phase 3.5 hardened:
    - UNCERTAIN stops progression
    - Post-observation returned to caller
    - Frame-aware resolution
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
        self.value_resolver = ValueResolver(vault)

    def set_document_registry(self, registry: DocumentRegistry) -> None:
        self.document_resolver = DocumentResolver(registry)

    async def execute(
        self,
        page: Page,
        action: BrowserAction,
        observation: PageObservation,
    ) -> ActionResult:
        """Execute a browser action with full verification loop.

        Flow:
        1. Check observation staleness (#3)
        2. Execute raw Playwright action
        3. Re-observe page
        4. Verify action result
        5. Handle UNCERTAIN (#1)
        6. Return ActionResult with post_observation (#2)
        """
        logger.info("Executing action: %s (target=%s)", action.action, action.target_ref)

        page_state = observation.page_state

        # Check observation staleness (#3)
        if action.observation_id and action.observation_id != observation.observation_id:
            return ActionResult(
                action=action,
                success=False,
                message=f"Stale reference: action targets observation {action.observation_id} "
                        f"but current observation is {observation.observation_id}",
                recovery_required=True,
            )

        try:
            # Execute the raw action
            result = await self._do_execute(page, action, page_state)

            if not result.success:
                return result

            # Re-observe after state-changing action
            from app.browser.observer import PageObserver
            observer = PageObserver()
            new_observation = await observer.observe(page)
            current_state = new_observation.page_state

            # Verify the action had the intended effect
            verification = await self.verifier.verify(
                page=page,
                action=action,
                previous_state=page_state,
                current_state=current_state,
            )

            result.verification = verification
            result.post_observation = new_observation

            # #1: UNCERTAIN handling — stop progression
            if verification.status == VerificationStatus.FAILURE:
                logger.warning(
                    "Verification FAILED for %s: %s", action.action, verification.message
                )
                result.success = False
                result.message = f"Verified FAILED: {verification.message}"
                result.recovery_required = True
            elif verification.status == VerificationStatus.UNCERTAIN:
                logger.warning(
                    "Verification UNCERTAIN for %s: %s — stopping progression",
                    action.action,
                    verification.message,
                )
                result.success = False
                result.message = f"UNCERTAIN: {verification.message}"
                result.recovery_required = True
            else:
                logger.info("Verification SUCCESS for %s", action.action)

            return result

        except Exception as e:
            logger.error("Action execution failed: %s", e, exc_info=True)
            return ActionResult(
                action=action,
                success=False,
                message=f"Execution error: {e}",
                recovery_required=True,
            )

    async def _do_execute(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Execute the raw Playwright action (without verification)."""
        try:
            if action.action == "click":
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
                    action=action, success=True,
                    message=f"User action requested: {action.reason}",
                    user_action_required=True,
                )
            elif action.action == "stop":
                return ActionResult(action=action, success=True, message="Agent stopped")
            else:
                return ActionResult(
                    action=action, success=False,
                    message=f"Unknown action type: {action.action}",
                )
        except Exception as e:
            logger.error("Raw execution failed: %s", e, exc_info=True)
            return ActionResult(action=action, success=False, message=f"Execution error: {e}")

    def _resolve_value(self, action: BrowserAction) -> str | None:
        if action.value_ref:
            value = self.value_resolver.resolve(action.value_ref)
            if value is None:
                logger.warning("Could not resolve value_ref: %s", action.value_ref)
            return value
        return action.literal_value

    def _resolve_document_path(self, action: BrowserAction) -> str | None:
        if action.document_ref:
            doc = self.document_resolver.resolve(action.document_ref)
            if doc is None:
                logger.warning("Could not resolve document_ref: %s", action.document_ref)
                return None
            return doc.path
        return None

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
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")
        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action, success=False,
                message=f"Could not locate element {action.target_ref}",
            )
        await locator.scroll_into_view_if_needed()
        return ActionResult(action=action, success=True, message=f"Scrolled to {action.target_ref}")

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
        file_path = self._resolve_document_path(action)
        if not file_path:
            return ActionResult(
                action=action, success=False,
                message="Could not resolve document_ref to file path",
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
