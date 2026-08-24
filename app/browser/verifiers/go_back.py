"""Go-back action verifier — checks navigation occurred.

Audit B4: go_back changes the URL and can discard unsaved form state,
so it should be verified, not silently skipped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    VerificationResult, make_failure, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from app.models.actions import BrowserAction
    from app.models.page_state import PageState

logger = logging.getLogger(__name__)


async def verify_go_back(
    page: Page, action: BrowserAction, prev: PageState, curr: PageState,
) -> VerificationResult:
    """Verify a go-back action navigated to a different page.

    The primary expectation is that the URL changed.
    If the URL is the same, the back navigation likely failed.
    """
    url_changed = curr.url != prev.url

    if url_changed:
        return make_success(
            "go_back", None,
            message=f"Navigated back: {prev.url} → {curr.url}",
        )

    # URL didn't change — back navigation likely failed or was at history start
    return make_failure(
        "go_back", None,
        message=f"URL did not change after go_back (still at {curr.url})",
    )
