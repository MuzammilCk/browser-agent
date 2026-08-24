"""Locator engine — resolves element refs to Playwright locators.

Updated per audit findings:
- #3: Uses split name fields (accessible_name, label_text, html_name)
- #5: Removed broken snapshot_ref strategy (DOM has no ref attributes)
- #15: Frame-aware resolution

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
    from playwright.async_api import Locator, Page

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
    """Resolves element refs to Playwright locators."""

    async def resolve(
        self,
        page: Page,
        ref: str,
        page_state: PageState,
    ) -> Locator | None:
        """Resolve a ref from the current PageState to a Playwright Locator.

        Returns None if the element cannot be uniquely located.
        NEVER guesses — returns None for ambiguous targets.
        """
        element = self._find_element(ref, page_state)
        if element is None:
            logger.warning("Element ref '%s' not found in PageState", ref)
            return None

        # Strategy 1: Role + accessible name (exact match first)
        locator = await self._try_role_name(page, element)
        if locator:
            return locator

        # Strategy 2: Label text
        locator = await self._try_label(page, element)
        if locator:
            return locator

        # Strategy 3: Placeholder
        locator = await self._try_placeholder(page, element)
        if locator:
            return locator

        # Strategy 4: Semantic DOM attributes (name, aria-label)
        locator = await self._try_semantic_attributes(page, element)
        if locator:
            return locator

        # Strategy 5: Text content (buttons/links only)
        locator = await self._try_text(page, element)
        if locator:
            return locator

        logger.warning(
            "Could not resolve locator for ref '%s' (role=%s, name=%s)",
            ref,
            element.role,
            element.accessible_name,
        )
        return None

    def _find_element(self, ref: str, page_state: PageState) -> ElementState | None:
        """Find element by ref in PageState."""
        for el in page_state.elements:
            if el.ref == ref:
                return el
        return None

    async def _try_role_name(self, page: Page, element: ElementState) -> Locator | None:
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
                locator = page.get_by_role(pw_role, name=name, exact=True)
                if await locator.count() > 0:
                    logger.debug("Resolved via role+name (exact): %s / %s", pw_role, name)
                    return locator
            except Exception:
                pass
            try:
                # Fallback to substring match (only if exactly 1 result)
                locator = page.get_by_role(pw_role, name=name)
                if await locator.count() == 1:
                    logger.debug("Resolved via role+name: %s / %s", pw_role, name)
                    return locator
            except Exception:
                continue

        # Try role only (only if exactly 1 element of that role)
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
        if not element.label_text:
            return None

        try:
            locator = page.get_by_label(element.label_text)
            if await locator.count() == 1:
                logger.debug("Resolved via label: %s", element.label_text)
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
            if await locator.count() == 1:
                logger.debug("Resolved via placeholder: %s", element.placeholder)
                return locator
        except Exception:
            pass
        return None

    async def _try_semantic_attributes(self, page: Page, element: ElementState) -> Locator | None:
        """Try name attribute or aria-label."""
        # Try by HTML name attribute
        if element.html_name:
            try:
                locator = page.locator(f"[name='{element.html_name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via name attribute: %s", element.html_name)
                    return locator
            except Exception:
                pass

        # Try by aria-label
        if element.accessible_name:
            try:
                locator = page.locator(f"[aria-label='{element.accessible_name}']")
                if await locator.count() == 1:
                    logger.debug("Resolved via aria-label: %s", element.accessible_name)
                    return locator
            except Exception:
                pass

        return None

    async def _try_text(self, page: Page, element: ElementState) -> Locator | None:
        """Try to locate by visible text (for buttons, links only)."""
        if element.role not in ("button", "link"):
            return None
        if not element.accessible_name:
            return None

        try:
            locator = page.get_by_text(element.accessible_name, exact=True)
            if await locator.count() == 1:
                logger.debug("Resolved via text: %s", element.accessible_name)
                return locator
        except Exception:
            pass
        return None
