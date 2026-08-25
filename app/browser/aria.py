"""ARIA/accessibility snapshot extraction from Playwright pages.

Fix for audit B1: aria_snapshot(mode="ai") throws TypeError on Playwright
>=1.50 which doesn't accept `mode`. We introspect the installed driver's
actual signature once at import time and only pass supported kwargs.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ── Introspect Playwright's actual aria_snapshot signature once ─────────
_supported_snapshot_kwargs: set[str] = set()

def _probe_snapshot_kwargs() -> None:
    """Detect which kwargs the installed Playwright's aria_snapshot accepts."""
    global _supported_snapshot_kwargs
    try:
        from playwright.async_api import Locator
        sig = inspect.signature(Locator.aria_snapshot)
        _supported_snapshot_kwargs = set(sig.parameters.keys()) - {"self"}
        logger.debug("aria_snapshot supported kwargs: %s", _supported_snapshot_kwargs)
    except Exception:
        # If introspection fails, assume minimal (no kwargs beyond default)
        _supported_snapshot_kwargs = set()
        logger.warning("Could not introspect aria_snapshot signature; assuming no extra kwargs")

_probe_snapshot_kwargs()


# Values to use when a kwarg is supported. Playwright's aria_snapshot
# validates mode against {"ai", "default"} server-side; passing any other
# value (e.g. a bare bool) is rejected by the driver even though Python's
# signature accepts it.
_KWARG_VALUES: dict[str, object] = {
    "mode": "ai",
    "refs": True,
}


def _build_snapshot_kwargs(**hints: bool) -> dict:
    """Build kwargs dict with proper values for params the driver accepts."""
    return {
        k: _KWARG_VALUES[k]
        for k in ("mode", "refs")
        if hints.get(k, False) and k in _supported_snapshot_kwargs and k in _KWARG_VALUES
    }


async def extract_aria_snapshot(page: Page) -> str:
    """Extract the ARIA accessibility snapshot from the page body.

    Uses Playwright's aria_snapshot() to get a structured
    accessibility representation. Only passes kwargs the installed
    driver actually accepts (audit B1 fix).
    """
    try:
        body = page.locator("body")
        kwargs = _build_snapshot_kwargs(mode=True)
        snapshot = await body.aria_snapshot(**kwargs)
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
        kwargs = _build_snapshot_kwargs(mode=True, refs=True)
        # Fallback: if refs was not in supported kwargs, try without it
        try:
            snapshot = await body.aria_snapshot(**kwargs)
        except TypeError:
            kwargs_no_refs = _build_snapshot_kwargs(mode=True)
            snapshot = await body.aria_snapshot(**kwargs_no_refs)
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
            kwargs = _build_snapshot_kwargs(mode=True, refs=True)
            try:
                snapshot = await body.aria_snapshot(**kwargs)
            except TypeError:
                kwargs_no_refs = _build_snapshot_kwargs(mode=True)
                snapshot = await body.aria_snapshot(**kwargs_no_refs)
            frame_snapshots.append({
                "frame_url": frame.url,
                "frame_name": frame.name,
                "snapshot": snapshot,
            })
        except Exception:
            logger.debug("Could not snapshot frame: %s", frame.url)

    return frame_snapshots
