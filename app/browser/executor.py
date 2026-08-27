"""Browser action executor — Phase B hardened.

- PolicyEngine runs before every Playwright action
- UNCERTAIN verification stops progression
- Post-observation returned to caller
- Frame-aware resolution
- Document policy validation for uploads
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.browser.locator import LocatorResolver
from app.browser.tabs import TabSwitch, pages_for, safe_url, sync_active_page
from app.browser.verification import ActionVerifier, VerificationResult, VerificationStatus
from app.models.actions import BrowserAction
from app.models.page_state import PageObservation, PageState
from app.policy.engine import PolicyDecision, PolicyEngine, PolicyResult, RiskLevel
from app.policy.document_policy import DocumentPolicy
from app.vault.resolver import DocumentResolver, DocumentRegistry, UserVault, ValueResolver

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Actions that can plausibly open a new tab/window: an anchor with
# target="_blank", a window.open() handler, or Enter on such a control.
_TAB_OPENING_ACTIONS = frozenset({"click", "press", "check", "uncheck"})


@dataclass
class ActionResult:
    """Result of executing a browser action — the contract for the future agent."""

    action: BrowserAction
    success: bool
    message: str = ""
    verification: VerificationResult | None = None
    post_observation: PageObservation | None = None
    recovery_required: bool = False
    user_action_required: bool = False
    policy_result: PolicyResult | None = None
    resolved_value: str | None = None  # Audit B3: value_ref resolved to actual string
    # Phase 8 (multi-tab awareness): when an action opened a new tab, the
    # newest tab becomes the page every later observation/action must use.
    # `active_page` is that page; `tab_switch` is the explicit record of the
    # change for the workflow trace. Both stay None for same-tab actions.
    tab_switch: TabSwitch | None = None
    active_page: "Page | None" = None


class BrowserExecutor:
    """Executes typed browser actions using Playwright.

    Phase B: Every action passes through PolicyEngine before Playwright.
    """

    def __init__(
        self,
        vault: UserVault | None = None,
        document_registry: DocumentRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        document_policy: DocumentPolicy | None = None,
        close_orphan_tabs: bool = True,
    ) -> None:
        self.locator_resolver = LocatorResolver()
        self.verifier = ActionVerifier()
        self.value_resolver = ValueResolver(vault or UserVault())
        self.document_resolver = DocumentResolver(document_registry or DocumentRegistry())
        self.policy_engine = policy_engine or PolicyEngine()
        self.document_policy = document_policy or DocumentPolicy()
        # Phase 8 policy for the tab a click left behind: closing it is the
        # simplest option and keeps one click from ever leaving a pile of
        # duplicate tabs. Set False to keep it open (unobserved) instead.
        self.close_orphan_tabs = close_orphan_tabs

    def set_vault(self, vault: UserVault) -> None:
        self.value_resolver = ValueResolver(vault)

    def set_document_registry(self, registry: DocumentRegistry) -> None:
        self.document_resolver = DocumentResolver(registry)

    async def execute(
        self,
        page: Page,
        action: BrowserAction,
        observation: PageObservation,
        *,
        user_confirmed: bool = False,
    ) -> ActionResult:
        """Execute a browser action with full policy + verification loop.

        Flow:
        1. Check observation staleness
        2. Policy gate (per audit #21)
        3. Document policy for uploads (per audit #19)
        4. Execute raw Playwright action
        5. Re-observe page
        6. Verify action result
        7. Handle UNCERTAIN
        8. Return ActionResult with post_observation

        Args:
            user_confirmed: True only when the user explicitly approved this
                exact action through the confirmation flow (runner.resume).
                Satisfies REQUIRE_CONFIRMATION; DENY and PAUSE_FOR_USER are
                still enforced unconditionally.
        """
        logger.info("Executing action: %s (target=%s)", action.action, action.target_ref)

        page_state = observation.page_state

        # Check observation staleness
        if action.observation_id and action.observation_id != observation.observation_id:
            return ActionResult(
                action=action,
                success=False,
                message=f"Stale reference: action targets observation {action.observation_id} "
                        f"but current observation is {observation.observation_id}",
                recovery_required=True,
            )

        # ─── POLICY GATE (per audit #21) ──────────────────────────
        policy_result = self.policy_engine.evaluate(action, page_state)
        logger.info("Policy: %s — %s", policy_result.decision.value, policy_result.reason)

        if policy_result.blocked:
            return ActionResult(
                action=action,
                success=False,
                message=f"Policy DENIED: {policy_result.reason}",
                recovery_required=True,
                policy_result=policy_result,
            )

        if policy_result.needs_user:
            return ActionResult(
                action=action,
                success=False,
                message=f"Policy PAUSE_FOR_USER: {policy_result.reason}",
                user_action_required=True,
                policy_result=policy_result,
            )

        if policy_result.needs_confirmation and not user_confirmed:
            # Audit B2 fix: halt execution instead of falling through.
            # Only an explicit user approval (runner.resume) may proceed.
            return ActionResult(
                action=action,
                success=False,
                message=f"Policy REQUIRE_CONFIRMATION: {policy_result.reason}",
                recovery_required=True,
                policy_result=policy_result,
            )
        if policy_result.needs_confirmation and user_confirmed:
            logger.info(
                "Policy REQUIRE_CONFIRMATION satisfied by explicit user approval"
            )

        # ─── DOCUMENT POLICY (per audit #19) ──────────────────────
        if action.action == "upload" and action.document_ref:
            doc = self.document_resolver.resolve(action.document_ref)
            if doc:
                doc_type = self.document_resolver.get_doc_type(action.document_ref)
                doc_result = self.document_policy.validate_upload(doc.path, doc_type)
                if doc_result.blocked:
                    return ActionResult(
                        action=action,
                        success=False,
                        message=f"Document policy DENIED: {doc_result.reason}",
                        recovery_required=True,
                    )

        try:
            # Phase 8: remember which tabs existed before the action so a
            # tab opened by it cannot go unnoticed.
            pages_before = (
                pages_for(page) if action.action in _TAB_OPENING_ACTIONS else []
            )
            url_before = safe_url(page)

            # Execute the raw action
            result = await self._do_execute(page, action, page_state)

            if not result.success:
                return result

            # Phase 8: reconcile tab state. If the action opened a tab, the
            # newest tab becomes the page that is observed, verified and
            # returned to the caller — the frozen original is no longer
            # what the rest of the system looks at.
            page = await self._sync_tabs(page, action, pages_before, url_before, result)

            # Re-observe after state-changing action
            from app.browser.observer import PageObserver
            observer = PageObserver()
            new_observation = await observer.observe(page)
            current_state = new_observation.page_state

            # Verify the action had the intended effect
            # Audit B3: pass resolved_value so verify_fill can check vault fills
            verification = await self.verifier.verify(
                page=page,
                action=action,
                previous_state=page_state,
                current_state=current_state,
                resolved_value=result.resolved_value,
            )

            result.verification = verification
            result.post_observation = new_observation
            result.policy_result = policy_result

            # UNCERTAIN handling — stop progression
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

    async def _sync_tabs(
        self,
        page: Page,
        action: BrowserAction,
        pages_before: list[Page],
        url_before: str,
        result: ActionResult,
    ) -> Page:
        """Adopt the newest tab when an action opened one (Phase 8).

        Records the switch on the ActionResult so the runner can follow it
        and write it into the workflow trace, and returns the page the rest
        of ``execute()`` must use.
        """
        if action.action not in _TAB_OPENING_ACTIONS:
            return page

        # Waiting for a tab is only worth its short grace period when the
        # tracked page itself did not move: a same-tab navigation is real
        # progress, whereas "nothing changed here" is the exact signature
        # of the click that landed in a tab nobody was watching.
        wait_for_tabs = safe_url(page) == url_before

        sync = await sync_active_page(
            page,
            pages_before,
            close_orphans=self.close_orphan_tabs,
            wait_for_tabs=wait_for_tabs,
        )
        if sync.switch is None:
            return page

        result.tab_switch = sync.switch
        result.active_page = sync.active_page
        result.message = f"{result.message} — {sync.switch.describe()}"
        logger.info(
            "Action %s changed the active tab: %s -> %s",
            action.action, sync.switch.from_url, sync.switch.to_url,
        )
        return sync.active_page

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
        # Audit B3: thread resolved value through for verification
        return ActionResult(
            action=action, success=True,
            message=f"Filled {action.target_ref}",
            resolved_value=value,
        )

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
        selected = await self._select_option_robust(locator, action.option)
        if not selected:
            return ActionResult(
                action=action, success=False,
                message=f"Option '{action.option}' not found in {action.target_ref}",
            )
        return ActionResult(
            action=action, success=True,
            message=f"Selected '{selected}' in {action.target_ref}",
        )

    async def _select_option_robust(self, locator, option: str) -> str | None:
        """Select an <option> by label with graceful fallbacks.

        Government forms rarely match vault values exactly ("Male" vs
        "MALE", extra whitespace). Order:
          1. exact label
          2. option value attribute
          3. case/whitespace-insensitive label match via DOM scan
        Returns the matched option text, or None if nothing matched.
        """
        try:
            await locator.select_option(label=option)
            return option
        except Exception:
            pass

        try:
            await locator.select_option(option)
            return option
        except Exception:
            pass

        try:
            idx = await locator.evaluate(
                """(selectEl, wanted) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const options = Array.from(selectEl.options);
                    let i = options.findIndex(o => norm(o.textContent) === norm(wanted));
                    if (i < 0) i = options.findIndex(o => norm(o.value) === norm(wanted));
                    return i;
                }""",
                option,
            )
            if idx is not None and idx >= 0:
                await locator.select_option(index=idx)
                return option
        except Exception as e:
            logger.debug("Fuzzy select failed for '%s': %s", option, e)
        return None

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
