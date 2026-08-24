"""Locator engine — resolves element refs to Playwright locators.

Locator resolution priority:
1. Stable current observation reference (from ARIA snapshot)
2. Accessible role + accessible name
3. Associated label
4. Placeholder
5. Title / accessible description
6. Stable semantic DOM attributes (id, name)
7. Scoped text relationship
8. CSS/XPath only as controlled last resort
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models.page_state import ElementState, PageState

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


class LocatorResolver:
    """Resolves element refs to Playwright locators."""

    async def resolve(self, page: Page, ref: str, page_state: PageState) -> Locator | None:
        """Resolve a ref from the current PageState to a Playwright Locator.

        Tries multiple strategies in priority order.
        Returns None if the element cannot be located.
        """
        element = self._find_element(ref, page_state)
        if element is None:
            logger.warning("Element ref '%s' not found in PageState", ref)
            return None

        # Strategy 1: ARIA snapshot ref (if available)
        locator = await self._try_snapshot_ref(page, ref)
        if locator:
            return locator

        # Strategy 2: Role + accessible name
        locator = await self._try_role_name(page, element)
        if locator:
            return locator

        # Strategy 3: Label text
        locator = await self._try_label(page, element)
        if locator:
            return locator

        # Strategy 4: Placeholder
        locator = await self._try_placeholder(page, element)
        if locator:
            return locator

        # Strategy 5: Semantic DOM attributes (id, name)
        locator = await self._try_semantic_attributes(page, element)
        if locator:
            return locator

        # Strategy 6: Text content
        locator = await self._try_text(page, element)
        if locator:
            return locator

        logger.warning("Could not resolve locator for ref '%s' (role=%s, name=%s)", ref, element.role, element.name)
        return None

    def _find_element(self, ref: str, page_state: PageState) -> ElementState | None:
        """Find element by ref in PageState."""
        for el in page_state.elements:
            if el.ref == ref:
                return el
        return None

    async def _try_snapshot_ref(self, page: Page, ref: str) -> Locator | None:
        """Try to use Playwright's snapshot ref directly."""
        try:
            locator = page.locator(f"[ref='{ref}']")
            if await locator.count() > 0:
                logger.debug("Resolved via snapshot ref: %s", ref)
                return locator
        except Exception:
            pass
        return None

    async def _try_role_name(self, page: Page, element: ElementState) -> Locator | None:
        """Try role + accessible name."""
        if not element.role:
            return None

        # Build name candidates
        names = []
        if element.name:
            names.append(element.name)
        if element.label:
            names.append(element.label)

        # Map our role names to Playwright role names
        role_map = {
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

        pw_role = role_map.get(element.role)
        if not pw_role:
            return None

        for name in names:
            if not name:
                continue
            try:
                # Try exact match first
                locator = page.get_by_role(pw_role, name=name, exact=True)
                if await locator.count() > 0:
                    logger.debug("Resolved via role+name (exact): %s / %s", pw_role, name)
                    return locator
            except Exception:
                pass
            try:
                # Fallback to substring match
                locator = page.get_by_role(pw_role, name=name)
                if await locator.count() == 1:
                    logger.debug("Resolved via role+name: %s / %s", pw_role, name)
                    return locator
            except Exception:
                continue

        # Try without name (role only)
        try:
            locator = page.get_by_role(pw_role)
            if await locator.count() == 1:
                logger.debug("Resolved via role only: %s", pw_role)
                return locator
        except Exception:
            pass

        return None

    async def _try_label(self, page: Page, element: ElementState) -> Locator | None:
        """Try to locate by associated label text."""
        if not element.label:
            return None

        try:
            locator = page.get_by_label(element.label)
            if await locator.count() > 0:
                logger.debug("Resolved via label: %s", element.label)
                return locator
        except Exception:
            pass
        return None

    async def _try_placeholder(self, page: Page, element: ElementState) -> Locator | None:
        """Try to locate by placeholder text."""
        if not element.placeholder:
            return None

        try:
            locator = page.get_by_placeholder(element.placeholder)
            if await locator.count() > 0:
                logger.debug("Resolved via placeholder: %s", element.placeholder)
                return locator
        except Exception:
            pass
        return None

    async def _try_semantic_attributes(self, page: Page, element: ElementState) -> Locator | None:
        """Try id, name, or aria-label attributes."""
        # Try by name attribute
        if element.name:
            try:
                locator = page.locator(f"[name='{element.name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via name attribute: %s", element.name)
                    return locator
            except Exception:
                pass

        # Try by aria-label
        if element.name:
            try:
                locator = page.locator(f"[aria-label='{element.name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via aria-label: %s", element.name)
                    return locator
            except Exception:
                pass

        return None

    async def _try_text(self, page: Page, element: ElementState) -> Locator | None:
        """Try to locate by visible text (for buttons, links)."""
        if element.role not in ("button", "link"):
            return None
        if not element.name:
            return None

        try:
            locator = page.get_by_text(element.name, exact=True)
            if await locator.count() == 1:
                logger.debug("Resolved via text: %s", element.name)
                return locator
        except Exception:
            pass
        return None
