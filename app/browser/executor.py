"""Browser action executor — typed Playwright operations.

All browser actions are deterministic and do not involve the LLM.
Each action takes the current page, resolves the target, and executes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.browser.locator import LocatorResolver
from app.browser.verification import ActionVerifier, VerificationResult
from app.models.actions import BrowserAction
from app.models.page_state import PageState

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
    """Executes typed browser actions using Playwright."""

    def __init__(self) -> None:
        self.locator_resolver = LocatorResolver()
        self.verifier = ActionVerifier()

    async def execute(
        self,
        page: Page,
        action: BrowserAction,
        page_state: PageState,
    ) -> ActionResult:
        """Execute a browser action and return the result."""
        logger.info("Executing action: %s (target=%s)", action.action, action.target_ref)

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
            elif action.action == "press":
                return await self._execute_press(page, action, page_state)
            elif action.action == "wait":
                return await self._execute_wait(page, action)
            elif action.action == "go_back":
                return await self._execute_go_back(page, action)
            elif action.action == "upload":
                return await self._execute_upload(page, action, page_state)
            else:
                return ActionResult(
                    action=action,
                    success=False,
                    message=f"Unknown action type: {action.action}",
                )
        except Exception as e:
            logger.error("Action execution failed: %s", e, exc_info=True)
            return ActionResult(
                action=action,
                success=False,
                message=f"Execution error: {e}",
            )

    async def _execute_open(self, page: Page, action: BrowserAction) -> ActionResult:
        """Navigate to a URL."""
        url = action.literal_value
        if not url:
            return ActionResult(action=action, success=False, message="No URL provided")

        await page.goto(url, wait_until="domcontentloaded")
        return ActionResult(
            action=action,
            success=True,
            message=f"Navigated to {url}",
        )

    async def _execute_click(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Click an element."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action,
                success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.click()
        # Wait for potential navigation
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        return ActionResult(
            action=action,
            success=True,
            message=f"Clicked element {action.target_ref}",
        )

    async def _execute_fill(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Fill a text input."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        value = action.literal_value
        if value is None:
            return ActionResult(
                action=action,
                success=False,
                message="No value provided for fill action",
            )

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action,
                success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        # Clear existing value and fill
        await locator.click()
        await locator.fill(value)

        return ActionResult(
            action=action,
            success=True,
            message=f"Filled element {action.target_ref}",
        )

    async def _execute_select(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Select a dropdown option."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")
        if not action.option:
            return ActionResult(action=action, success=False, message="No option provided")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action,
                success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.select_option(label=action.option)

        return ActionResult(
            action=action,
            success=True,
            message=f"Selected '{action.option}' in {action.target_ref}",
        )

    async def _execute_check(
        self,
        page: Page,
        action: BrowserAction,
        page_state: PageState,
        check: bool,
    ) -> ActionResult:
        """Check or uncheck a checkbox."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action,
                success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        if check:
            await locator.check()
        else:
            await locator.uncheck()

        return ActionResult(
            action=action,
            success=True,
            message=f"{'Checked' if check else 'Unchecked'} element {action.target_ref}",
        )

    async def _execute_scroll(self, page: Page, action: BrowserAction) -> ActionResult:
        """Scroll the page."""
        direction = action.direction or "down"
        delta = {"up": -500, "down": 500, "left": -500, "right": 500}
        await page.mouse.wheel(0, delta.get(direction, 500))
        return ActionResult(
            action=action,
            success=True,
            message=f"Scrolled {direction}",
        )

    async def _execute_press(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Press a keyboard key."""
        key = action.key
        if not key:
            return ActionResult(action=action, success=False, message="No key specified")

        # If target_ref is provided, press on that element
        if action.target_ref:
            locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
            if locator:
                await locator.press(key)
                return ActionResult(
                    action=action,
                    success=True,
                    message=f"Pressed '{key}' on {action.target_ref}",
                )

        # Otherwise press on the page
        await page.keyboard.press(key)
        return ActionResult(
            action=action,
            success=True,
            message=f"Pressed '{key}'",
        )

    async def _execute_wait(self, page: Page, action: BrowserAction) -> ActionResult:
        """Wait for a condition."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        return ActionResult(
            action=action,
            success=True,
            message="Waited for page load",
        )

    async def _execute_go_back(self, page: Page, action: BrowserAction) -> ActionResult:
        """Navigate back."""
        await page.go_back()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return ActionResult(
            action=action,
            success=True,
            message="Navigated back",
        )

    async def _execute_upload(
        self, page: Page, action: BrowserAction, page_state: PageState
    ) -> ActionResult:
        """Upload a file."""
        if not action.target_ref:
            return ActionResult(action=action, success=False, message="No target ref")
        if not action.literal_value:
            return ActionResult(action=action, success=False, message="No file path provided")

        locator = await self.locator_resolver.resolve(page, action.target_ref, page_state)
        if locator is None:
            return ActionResult(
                action=action,
                success=False,
                message=f"Could not locate element {action.target_ref}",
            )

        await locator.set_input_files(action.literal_value)
        return ActionResult(
            action=action,
            success=True,
            message=f"Uploaded file to {action.target_ref}",
        )
