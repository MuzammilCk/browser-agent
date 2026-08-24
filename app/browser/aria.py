"""ARIA/accessibility snapshot extraction from Playwright pages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def extract_aria_snapshot(page: Page) -> str:
    """Extract the ARIA accessibility snapshot from the page body.

    Uses Playwright's AI-oriented aria_snapshot() to get a structured
    accessibility representation with element references.
    """
    try:
        body = page.locator("body")
        snapshot = await body.aria_snapshot(mode="ai")
        logger.debug("ARIA snapshot extracted (%d chars)", len(snapshot))
        return snapshot
    except Exception:
        logger.warning("Failed to extract ARIA snapshot", exc_info=True)
        return ""


async def extract_aria_snapshot_with_refs(page: Page) -> str:
    """Extract ARIA snapshot including element references for action targets.

    This snapshot is used by the LLM to identify which elements can be
    interacted with and their reference IDs.
    """
    try:
        body = page.locator("body")
        snapshot = await body.aria_snapshot(mode="ai", refs=True)
        logger.debug("ARIA snapshot with refs extracted (%d chars)", len(snapshot))
        return snapshot
    except Exception:
        logger.warning("Failed to extract ARIA snapshot with refs", exc_info=True)
        return ""


async def extract_frame_snapshots(page: Page) -> list[dict[str, str]]:
    """Extract ARIA snapshots from all frames/iframes on the page."""
    frame_snapshots = []
    frames = page.frames

    for frame in frames:
        if frame == page.main_frame:
            continue
        try:
            body = frame.locator("body")
            snapshot = await body.aria_snapshot(mode="ai", refs=True)
            frame_snapshots.append({
                "frame_url": frame.url,
                "frame_name": frame.name,
                "snapshot": snapshot,
            })
        except Exception:
            logger.debug("Could not snapshot frame: %s", frame.url)

    return frame_snapshots
