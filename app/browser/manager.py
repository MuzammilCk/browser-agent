"""Playwright browser lifecycle manager."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Playwright

from app.browser.tabs import TabTracker
from app.config.settings import Settings, get_settings
from app.models.page_state import TabsState

logger = logging.getLogger(__name__)


class DomainAccessError(Exception):
    """Raised when navigation targets a domain not in the trusted registry."""
    pass


class BrowserManager:
    """Manages Playwright browser lifecycle.

    Audit B5 fix: open() now validates against TrustedDomainRegistry
    before navigating, unless domain-trust checking is disabled.

    Audit Phase 8: a TabTracker is registered on the context at start(),
    so a tab opened by the site (target="_blank", window.open) is known
    from the moment it opens rather than discovered by accident. `page`
    returns the ACTIVE tab, which is the newest one — the same rule the
    executor applies after an action, so the two never disagree.

    Note: browser_mode='user' forces a headed window and therefore
    overrides the HEADLESS setting.

    Usage:
        async with BrowserManager() as manager:
            page = await manager.open("https://uidai.gov.in")
            await page.screenshot(path="screenshot.png")
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._tabs: TabTracker | None = None
        self._domain_registry: Any = None  # lazy-loaded TrustedDomainRegistry

    @property
    def page(self) -> Page:
        """Get the ACTIVE page (newest tab). Raises if browser not started."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        if self._tabs is not None:
            active = self._tabs.active_page
            if active is not None:
                return active
        return self._page

    @property
    def initial_page(self) -> Page:
        """The first page opened at start(), regardless of later tabs."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    @property
    def tabs(self) -> TabsState:
        """Explicit snapshot of every open tab and which one is active."""
        if self._tabs is None:
            return TabsState()
        return self._tabs.snapshot()

    @property
    def tab_tracker(self) -> TabTracker | None:
        """The context's tab tracker (None before start())."""
        return self._tabs

    @property
    def context(self) -> BrowserContext:
        """Get the browser context. Raises if browser not started."""
        if self._context is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context

    @staticmethod
    def _check_subprocess_support() -> None:
        """Verify the event loop supports subprocesses (required by Playwright).

        On Windows, SelectorEventLoop does not support subprocesses.
        This is common when uvicorn runs with reload=True, which forces
        SelectorEventLoop on Windows (see uvicorn docs on event loops).
        
        Previously this tried to monkey-patch the loop, but that cannot work:
        ProactorEventLoop._make_subprocess_transport requires IOCP internals
        that don't exist on a SelectorEventLoop instance.
        
        Raises RuntimeError with actionable guidance if unsupported.
        """
        import sys
        if sys.platform != "win32":
            return

        import asyncio
        loop = asyncio.get_running_loop()
        from asyncio import base_events
        
        if type(loop)._make_subprocess_transport is base_events.BaseEventLoop._make_subprocess_transport:
            raise RuntimeError(
                "Playwright requires subprocess support, but the current event loop is "
                f"{type(loop).__name__} which does not support subprocesses on Windows.\n\n"
                "This typically happens when uvicorn runs with reload=True or multiple workers,\n"
                "because uvicorn uses SelectorEventLoop for those modes on Windows.\n\n"
                "Fix: run without --reload (e.g. 'python run.py' without reload enabled),\n"
                "or use a production server like gunicorn with uvicorn workers."
            )

    async def start(self) -> None:
        """Launch Playwright and open a Chromium browser.

        browser_mode='user' → headed, resizable window (user controls size).
            NOTE: this overrides HEADLESS — a headed window is the point.
        browser_mode='test' → headless (per HEADLESS), fixed 1280×720 viewport
        """
        user_mode = self._settings.browser_mode == "user"
        headless = self._settings.headless if not user_mode else False
        if user_mode and self._settings.headless:
            logger.info(
                "browser_mode='user' overrides HEADLESS=true — running headed.",
            )

        logger.info("Starting Playwright (mode=%s)...", "user" if user_mode else "test")
        self._check_subprocess_support()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
        )

        ctx_kwargs: dict[str, object] = {
            "ignore_https_errors": True,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        # In user mode, skip fixed viewport so the user can resize freely
        if not user_mode:
            ctx_kwargs["viewport"] = {"width": 1280, "height": 720}

        self._context = await self._browser.new_context(**ctx_kwargs)
        self._page = await self._context.new_page()
        # Phase 8: track every tab from the moment it opens, so a
        # target="_blank" click can never navigate a page nobody watches.
        self._tabs = TabTracker(self._context, self._page)
        logger.info("Browser started successfully.")

    async def stop(self) -> None:
        """Close browser and clean up Playwright."""
        logger.info("Stopping browser...")
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._tabs = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser stopped.")

    def _get_domain_registry(self) -> Any:
        """Lazy-load the trusted domain registry."""
        if self._domain_registry is None:
            try:
                from app.sites.registry import TrustedDomainRegistry
                self._domain_registry = TrustedDomainRegistry()
            except Exception as e:
                logger.warning("Could not load TrustedDomainRegistry: %s", e)
                self._domain_registry = False  # sentinel: registry unavailable
        return self._domain_registry if self._domain_registry is not False else None

    def _extract_domain(self, url: str) -> str | None:
        """Extract bare domain from a URL for registry lookup.

        Returns None for non-http schemes (data:, file:, about:) which
        are not subject to domain-trust checks.
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # Skip non-http schemes (used for testing, local files, etc.)
        if parsed.scheme not in ("http", "https", ""):
            return None
        domain = parsed.netloc or parsed.path
        if not domain:
            return None
        # Strip www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()

    async def open(self, url: str) -> Page:
        """Navigate to a URL and return the page.

        Audit B5 fix: validates URL against TrustedDomainRegistry.
        Raises DomainAccessError if domain is not trusted.
        """
        # Audit B5: check domain against trusted registry
        registry = self._get_domain_registry()
        if registry is not None:
            domain = self._extract_domain(url)
            if domain is not None:  # None means non-http scheme, skip check
                entry = registry.get_entry(domain)
                if entry is None:
                    raise DomainAccessError(
                        f"Domain '{domain}' is not in the trusted government registry. "
                        f"Navigation blocked. Add it to TrustedDomainRegistry to allow."
                    )
                if not entry.allowed:
                    raise DomainAccessError(
                        f"Automation is not allowed on '{domain}' (entry.disabled). "
                        f"Set allowed=True in the registry to permit."
                    )
                logger.info("Domain trust check passed: %s (%s)", domain, entry.official_name)

        logger.info("Navigating to %s", url)
        await self.page.goto(url, wait_until="domcontentloaded")
        logger.info("Page loaded: %s", await self.page.title())
        return self.page

    async def screenshot(self, path: str | Path | None = None, full_page: bool = False) -> bytes:
        """Take a screenshot. Returns raw PNG bytes."""
        if path:
            await self.page.screenshot(path=str(path), full_page=full_page)
            logger.info("Screenshot saved to %s", path)
        return await self.page.screenshot(full_page=full_page)

    async def new_page(self) -> Page:
        """Create a new page in the same context."""
        return await self._context.new_page()

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
