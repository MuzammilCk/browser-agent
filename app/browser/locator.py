"""Locator engine — resolves element refs to Playwright locators.

Phase A fixes:
- #15: Frame-aware resolution — uses element.frame_id to resolve
  against the correct Playwright Frame, not just the main page.

Locator resolution priority:
1. Accessible role + accessible name (exact)
2. Associated label text
3. Placeholder
4. Stable semantic DOM attributes (id, name)
5. Scoped text relationship (buttons/links)
6. Returns None if ambiguous (never guesses)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models.page_state import ElementState, PageState

if TYPE_CHECKING:
    from playwright.async_api import Frame, Locator, Page

logger = logging.getLogger(__name__)

# Map our role names to Playwright role names
ROLE_MAP = {
    "textbox": "textbox",
    "combobox": "combobox",
    "listbox": "listbox",
    "checkbox": "checkbox",
    "radio": "radio",
    "button": "button",
    "link": "link",
    "switch": "switch",
    "slider": "slider",
    "spinbutton": "spinbutton",
    "searchbox": "searchbox",
    "option": "option",
}


class LocatorResolver:
    """Resolves element refs to Playwright locators.

    Phase A: Frame-aware — resolves within the correct Frame
    based on element.frame_id.
    """

    async def resolve(
        self,
        page: Page,
        ref: str,
        page_state: PageState,
    ) -> Locator | None:
        """Resolve a ref from the current PageState to a Playwright Locator.

        Returns None if the element cannot be uniquely located.
        NEVER guesses — returns None for ambiguous targets.

        Per audit #15: uses element.frame_id to resolve against
        the correct Playwright Frame.
        """
        element = self._find_element(ref, page_state)
        if element is None:
            logger.warning("Element ref '%s' not found in PageState", ref)
            return None

        # Get the correct resolution target (Page or Frame)
        target = await self._get_resolution_target(page, element, page_state)
        if target is None:
            logger.warning(
                "Could not find frame '%s' for element '%s'",
                element.frame_id, ref,
            )
            return None

        # Strategy 1: Role + accessible name (exact match first)
        locator = await self._try_role_name(target, element)
        if locator:
            return locator

        # Strategy 2: Label text
        locator = await self._try_label(target, element)
        if locator:
            return locator

        # Strategy 3: Placeholder
        locator = await self._try_placeholder(target, element)
        if locator:
            return locator

        # Strategy 4: Semantic DOM attributes (name, aria-label)
        locator = await self._try_semantic_attributes(target, element)
        if locator:
            return locator

        # Strategy 5: Text content (buttons/links only)
        locator = await self._try_text(target, element)
        if locator:
            return locator

        logger.warning(
            "Could not resolve locator for ref '%s' (role=%s, name=%s, frame=%s)",
            ref,
            element.role,
            element.accessible_name,
            element.frame_id or "main",
        )
        return None

    async def _get_resolution_target(
        self,
        page: Page,
        element: ElementState,
        page_state: PageState,
    ) -> Page | Frame | None:
        """Get the correct Playwright target (Page or Frame) for resolution.

        Per audit #15: if element.frame_id is set, resolve against
        the matching Frame. Otherwise resolve against the main Page.
        """
        if not element.frame_id or element.frame_id == "main":
            return page

        # Find the frame in PageState
        for frame_state in page_state.frames:
            if frame_state.frame_id == element.frame_id:
                # Get the actual Playwright Frame
                try:
                    frames = page.frames
                    for frame in frames:
                        if frame == page.main_frame:
                            continue
                        # Match by URL or name
                        if frame_state.url and frame.url == frame_state.url:
                            return frame
                        if frame_state.name and frame.name == frame_state.name:
                            return frame
                    logger.warning(
                        "Frame '%s' found in PageState but not in Playwright",
                        element.frame_id,
                    )
                    return None
                except Exception as e:
                    logger.warning("Error resolving frame: %s", e)
                    return None

        logger.warning("frame_id '%s' not found in PageState frames", element.frame_id)
        return None

    def _find_element(self, ref: str, page_state: PageState) -> ElementState | None:
        """Find element by ref in PageState."""
        for el in page_state.elements:
            if el.ref == ref:
                return el
        return None

    async def _try_role_name(
        self, target: Page | Frame, element: ElementState
    ) -> Locator | None:
        """Try role + accessible name with exact match first."""
        if not element.role:
            return None

        pw_role = ROLE_MAP.get(element.role)
        if not pw_role:
            return None

        # Build name candidates from split fields
        names = []
        if element.accessible_name:
            names.append(element.accessible_name)
        if element.label_text and element.label_text != element.accessible_name:
            names.append(element.label_text)

        for name in names:
            if not name:
                continue
            try:
                # Exact match first (prevents strict mode violations)
                locator = target.get_by_role(pw_role, name=name, exact=True)
                if await locator.count() > 0:
                    logger.debug("Resolved via role+name (exact): %s / %s", pw_role, name)
                    return locator
            except Exception:
                pass
            try:
                # Fallback to substring match (only if exactly 1 result)
                locator = target.get_by_role(pw_role, name=name)
                if await locator.count() == 1:
                    logger.debug("Resolved via role+name: %s / %s", pw_role, name)
                    return locator
            except Exception:
                continue

        # Try role only (only if exactly 1 element of that role)
        try:
            locator = target.get_by_role(pw_role)
            if await locator.count() == 1:
                logger.debug("Resolved via role only: %s", pw_role)
                return locator
        except Exception:
            pass

        return None

    async def _try_label(
        self, target: Page | Frame, element: ElementState
    ) -> Locator | None:
        """Try to locate by associated label text."""
        if not element.label_text:
            return None

        try:
            locator = target.get_by_label(element.label_text)
            if await locator.count() == 1:
                logger.debug("Resolved via label: %s", element.label_text)
                return locator
        except Exception:
            pass
        return None

    async def _try_placeholder(
        self, target: Page | Frame, element: ElementState
    ) -> Locator | None:
        """Try to locate by placeholder text."""
        if not element.placeholder:
            return None

        try:
            locator = target.get_by_placeholder(element.placeholder)
            if await locator.count() == 1:
                logger.debug("Resolved via placeholder: %s", element.placeholder)
                return locator
        except Exception:
            pass
        return None

    async def _try_semantic_attributes(
        self, target: Page | Frame, element: ElementState
    ) -> Locator | None:
        """Try name attribute or aria-label."""
        # Try by HTML name attribute
        if element.html_name:
            try:
                locator = target.locator(f"[name='{element.html_name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via name attribute: %s", element.html_name)
                    return locator
            except Exception:
                pass

        # Try by aria-label
        if element.accessible_name:
            try:
                locator = target.locator(f"[aria-label='{element.accessible_name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via aria-label: %s", element.accessible_name)
                    return locator
            except Exception:
                pass

        return None

    async def _try_text(
        self, target: Page | Frame, element: ElementState
    ) -> Locator | None:
        """Try to locate by visible text (for buttons, links only)."""
        if element.role not in ("button", "link"):
            return None
        if not element.accessible_name:
            return None

        try:
            locator = target.get_by_text(element.accessible_name, exact=True)
            if await locator.count() == 1:
                logger.debug("Resolved via text: %s", element.accessible_name)
                return locator
        except Exception:
            pass
        return None
