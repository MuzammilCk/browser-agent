"""Post-action verification engine — Phase 3.5 hardened.

Delegates to per-action verifiers in app/browser/verifiers/.
Each verifier is a focused module (< 100 lines).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import VerificationResult, VerificationStatus
from app.browser.verifiers.check import verify_check
from app.browser.verifiers.click import verify_click
from app.browser.verifiers.fill import verify_fill
from app.browser.verifiers.go_back import verify_go_back
from app.browser.verifiers.press import verify_press
from app.browser.verifiers.scroll import verify_scroll_to
from app.browser.verifiers.select import verify_select
from app.browser.verifiers.upload import verify_upload
from app.models.actions import BrowserAction
from app.models.page_state import PageState

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Dispatch table: action_type → verifier function
_VERIFIERS = {
    "fill": verify_fill,
    "click": verify_click,
    "select": verify_select,
    "check": verify_check,
    "uncheck": verify_check,
    "upload": verify_upload,
    "scroll_to": verify_scroll_to,
    "press": verify_press,
    "go_back": verify_go_back,
}


class ActionVerifier:
    """Verifies that browser actions had the intended effect.

    Delegates to per-action verifier modules.
    """

    async def verify(
        self,
        page: Page,
        action: BrowserAction,
        previous_state: PageState,
        current_state: PageState,
        resolved_value: str | None = None,
    ) -> VerificationResult:
        """Verify an action's result by comparing page states and live DOM.

        Audit B3: resolved_value threads the vault-resolved string through
        so verify_fill can check sensitive-data fills (value_ref path).
        """
        verifier = _VERIFIERS.get(action.action)
        if verifier is None:
            return VerificationResult(
                status=VerificationStatus.SUCCESS,
                action_type=action.action,
                message="Non-state-changing action, no verification needed",
            )
        # Only fill verifier needs resolved_value (others ignore it)
        if action.action == "fill":
            return await verifier(page, action, previous_state, current_state, resolved_value=resolved_value)
        return await verifier(page, action, previous_state, current_state)
