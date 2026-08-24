"""Tests for Playwright browser manager."""

import pytest

from app.browser.manager import BrowserManager
from app.config.settings import Settings


@pytest.mark.integration
async def test_browser_starts_and_stops() -> None:
    """Browser manager can start and stop cleanly."""
    settings = Settings(headless=True)
    manager = BrowserManager(settings)
    await manager.start()
    assert manager.page is not None
    assert not manager.page.is_closed()
    await manager.stop()
    assert manager._page is None


@pytest.mark.integration
async def test_browser_opens_url() -> None:
    """Browser can navigate to a URL."""
    settings = Settings(headless=True)
    async with BrowserManager(settings) as manager:
        page = await manager.open("data:text/html,<h1>Test Page</h1>")
        title = await page.title()
        content = await page.content()
        assert "Test Page" in content


@pytest.mark.integration
async def test_browser_screenshot() -> None:
    """Browser can capture a screenshot."""
    settings = Settings(headless=True)
    async with BrowserManager(settings) as manager:
        await manager.open("data:text/html,<h1>Screenshot Test</h1>")
        screenshot = await manager.screenshot()
        assert isinstance(screenshot, bytes)
        assert len(screenshot) > 0
        # PNG magic bytes
        assert screenshot[:4] == b"\x89PNG"


@pytest.mark.integration
async def test_browser_context() -> None:
    """Browser context is available after start."""
    settings = Settings(headless=True)
    manager = BrowserManager(settings)
    await manager.start()
    ctx = manager.context
    assert ctx is not None
    await manager.stop()


@pytest.mark.integration
async def test_browser_no_page_raises() -> None:
    """Accessing page before start raises RuntimeError."""
    manager = BrowserManager()
    with pytest.raises(RuntimeError, match="Browser not started"):
        _ = manager.page
