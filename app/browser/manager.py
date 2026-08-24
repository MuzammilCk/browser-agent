"""Playwright browser lifecycle manager."""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Playwright

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages Playwright browser lifecycle.

    Usage:
        async with BrowserManager() as manager:
            page = await manager.open("https://example.gov.in")
            await page.screenshot(path="screenshot.png")
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

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

    async def open(self, url: str) -> Page:
        """Navigate to a URL and return the page."""
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
