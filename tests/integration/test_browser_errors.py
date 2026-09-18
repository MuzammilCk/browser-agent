"""Phase 1 — Browser error visibility tests.

Verifies that browser errors (pageerror, requestfailed, responsefailed) are not
silently swallowed by the BrowserManager or PageObserver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings

SYNTHETIC_PAGES_DIR = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
SYNTHETIC_BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True, browser_mode="test")


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


class TestBrowserErrorVisibility:
    """Browser errors must be surfaced, not swallowed."""

    @pytest.mark.asyncio
    async def test_page_error_is_visible(self, settings: Settings) -> None:
        """A pageerror (unhandled JS exception) is not silently swallowed."""
        errors = []

        async with BrowserManager(settings) as manager:
            manager.page.on("pageerror", lambda exc: errors.append(str(exc)))
            await manager.page.goto("about:blank")
            await manager.page.set_content("<html><body><p>before</p></body></html>")
            # Inject a script that throws — Playwright's pageerror event
            # captures it in the browser, not the test process.
            await manager.page.add_script_tag(
                path=None,
                content="""
                window.__testPageError = new Error("Phase 1 test error");
                throw window.__testPageError;
                """
            )

        assert len(errors) >= 1, (
            f"Expected at least 1 pageerror, got {len(errors)} — browser errors may be swallowed"
        )
        assert any("Phase 1 test error" in e for e in errors), (
            f"Expected 'Phase 1 test error' in page errors, got: {errors}"
        )

    @pytest.mark.asyncio
    async def test_request_failure_is_visible(self, settings: Settings) -> None:
        """A failed network request (requestfailed) is not silently swallowed."""
        import asyncio

        failures = []

        async with BrowserManager(settings) as manager:
            manager.page.on("requestfailed", lambda req: failures.append(req.url))
            # Navigate to a data URL (no network needed) then trigger a fetch to a dead port
            await manager.page.goto("about:blank")
            await manager.page.set_content("<html><body><p>content</p></body></html>")
            await manager.page.evaluate("""() => {
                const req = new Request('http://127.0.0.1:1/nonexistent');
                fetch(req).catch(() => {});
            }""")
            # Wait for the request to fail
            await asyncio.sleep(1)

        assert len(failures) >= 1, (
            f"Expected at least 1 requestfailed event, got {len(failures)} — "
            "network errors may be swallowed"
        )
        assert failures[0].startswith("http://127.0.0.1:1/")

    @pytest.mark.asyncio
    async def test_observer_propagates_page_state_with_js_errors(self, settings: Settings, observer: PageObserver) -> None:
        """Observer produces a valid PageState even when page throws JS errors."""
        import urllib.parse

        async with BrowserManager(settings) as manager:
            html = """
            <html><body>
                <h1>Test Page</h1>
                <input type="text" id="name" placeholder="Enter name" />
                <script>throw new Error("onload error");</script>
            </body></html>
            """
            encoded = urllib.parse.quote(html.replace("\n", "").replace("  ", ""))
            page = await manager.open("data:text/html," + encoded)
            # Wait for page to settle
            await manager.page.wait_for_timeout(500)

            obs = await observer.observe(page)
            assert obs.page_state.elements is not None
            assert len(obs.page_state.elements) >= 1

            text_inputs = [e for e in obs.page_state.elements if e.input_type == "text"]
            assert len(text_inputs) >= 1
            assert text_inputs[0].placeholder == "Enter name"
