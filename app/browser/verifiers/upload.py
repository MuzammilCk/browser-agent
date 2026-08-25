"""Upload action verifier — targets exact file input element."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.browser.verifiers.base import (
    find_element, make_success, make_uncertain,
)

if TYPE_CHECKING:
    from app.models.actions import BrowserAction
    from app.models.page_state import PageState

logger = logging.getLogger(__name__)


async def verify_upload(
    page, action: BrowserAction, prev: PageState, curr: PageState,
):
    """Verify upload targets the exact element, not any file input."""
    ref = action.target_ref
    if not ref:
        return make_uncertain("upload", message="No target ref")

    target = find_element(ref, curr)
    if target is None:
        from app.browser.verifiers.base import make_failure
        return make_failure("upload", ref, message=f"Element {ref} disappeared")

    try:
        file_info = await page.evaluate(
            _VERIFY_JS, {
                "ref": ref,
                "html_name": target.html_name,
                "accessible_name": target.accessible_name,
                "label_text": target.label_text,
            }
        )

        if file_info.get("found") and file_info.get("file_count", 0) > 0:
            details = {"file_count": file_info["file_count"]}
            if file_info.get("file_name"):
                details["file_name"] = file_info["file_name"]
            return make_success(
                "upload", ref,
                f"Upload verified: {file_info['file_count']} file(s)",
                details=details,
            )
    except Exception as e:
        logger.debug("Upload verification error: %s", e)

    return make_uncertain("upload", ref, "Upload completed but verification failed")


_VERIFY_JS = """
(elementInfo) => {
    let target = null;
    if (elementInfo.html_name) {
        target = document.querySelector('input[type="file"][name="' + elementInfo.html_name + '"]');
    }
    if (!target && elementInfo.accessible_name) {
        target = document.querySelector('input[type="file"][aria-label="' + elementInfo.accessible_name + '"]');
    }
    if (!target && elementInfo.label_text) {
        const labels = document.querySelectorAll('label');
        for (const label of labels) {
            if (label.textContent.includes(elementInfo.label_text)) {
                const forId = label.getAttribute('for');
                if (forId) target = document.getElementById(forId);
                if (!target) target = label.querySelector('input[type="file"]');
                break;
            }
        }
    }
    // Audit #16 / C12: no index-based guessing. Matching "some file input"
    // by ordinal can attribute a different input's file to this upload.
    // If the exact target cannot be identified, report not-found and the
    // verifier returns UNCERTAIN instead of a false pass.
    if (target && target.files && target.files.length > 0) {
        return { found: true, file_count: target.files.length, file_name: target.files[0].name || null };
    }
    return { found: false, file_count: 0, file_name: null };
}
"""
