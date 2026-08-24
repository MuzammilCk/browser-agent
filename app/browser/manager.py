"""Playwright browser lifecycle manager."""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Playwright

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class DomainAccessError(Exception):
    """Raised when navigation targets a domain not in the trusted registry."""
    pass


class BrowserManager:
    """Manages Playwright browser lifecycle.

    Audit B5 fix: open() now validates against TrustedDomainRegistry
    before navigating, unless domain-trust checking is disabled.

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
        self._domain_registry: Any = None  # lazy-loaded TrustedDomainRegistry

    @property
    def page(self) -> Page:
        """Get the current page. Raises if browser not started."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """Get the browser context. Raises if browser not started."""
        if self._context is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context

    async def start(self) -> None:
        """Launch Playwright and open a Chromium browser."""
        logger.info("Starting Playwright...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._settings.headless,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
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
