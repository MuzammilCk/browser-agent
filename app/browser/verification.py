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
    ) -> VerificationResult:
        """Verify an action's result by comparing page states and live DOM."""
        verifier = _VERIFIERS.get(action.action)
        if verifier is None:
            return VerificationResult(
                status=VerificationStatus.SUCCESS,
                action_type=action.action,
                message="Non-state-changing action, no verification needed",
            )
        return await verifier(page, action, previous_state, current_state)
