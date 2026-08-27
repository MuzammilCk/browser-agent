"""Unit tests for explicit multi-tab state — audit Phase 8.

Covers the parts of `app/browser/tabs.py` that must behave correctly
without a browser: the mock-safe accessors (they must never invent tab
state), the observation snapshot, the TabSwitch trace text, and the
narrowing that keeps a mocked ActionResult from hijacking the tracked page.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.browser.tabs import (
    TabSwitch,
    TabSyncResult,
    build_tabs_state,
    context_of,
    is_closed,
    live_pages,
    pages_for,
    resolve_active_page,
    safe_url,
    switch_from_result,
    sync_active_page,
)
from app.models.page_state import TabsState


class FakePage:
    """Minimal stand-in for a Playwright Page."""

    def __init__(self, url: str, context: "FakeContext | None" = None) -> None:
        self.url = url
        self.context = context
        self._closed = False
        self.close_calls = 0

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True
        self.close_calls += 1

    async def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        return None


class FakeContext:
    def __init__(self) -> None:
        self._pages: list[FakePage] = []

    @property
    def pages(self) -> list[FakePage]:
        return [p for p in self._pages if not p.is_closed()]

    def open(self, url: str) -> FakePage:
        page = FakePage(url, self)
        self._pages.append(page)
        return page


def _context_with(*urls: str) -> tuple[FakeContext, list[FakePage]]:
    ctx = FakeContext()
    return ctx, [ctx.open(u) for u in urls]


class TestMockSafeAccessors:
    """Tab state must degrade to 'unknown', never to invented values."""

    def test_context_of_missing(self) -> None:
        assert context_of(object()) is None

    def test_live_pages_of_none(self) -> None:
        assert live_pages(None) == []

    def test_live_pages_of_magicmock_context(self) -> None:
        """A MagicMock's .pages is not a list — that means 'unknown', not a tab."""
        assert live_pages(MagicMock()) == []

    def test_pages_for_magicmock_page(self) -> None:
        assert pages_for(MagicMock()) == []

    def test_safe_url_of_broken_page(self) -> None:
        broken = MagicMock()
        type(broken).url = property(lambda self: (_ for _ in ()).throw(RuntimeError("gone")))
        assert safe_url(broken) == ""

    def test_safe_url_non_string(self) -> None:
        assert safe_url(MagicMock()) == ""

    def test_is_closed_unknown_is_false(self) -> None:
        assert is_closed(object()) is False

    def test_live_pages_excludes_closed(self) -> None:
        ctx, pages = _context_with("a", "b")
        pages[0]._closed = True
        assert live_pages(ctx) == [pages[1]]


class TestBuildTabsState:
    def test_unknown_context_reports_single_tab(self) -> None:
        state = build_tabs_state(MagicMock())
        assert state == TabsState(total=1, active_index=0, tabs=[])

    def test_active_index_tracks_the_observed_page(self) -> None:
        ctx, pages = _context_with("https://a.gov.in", "https://b.gov.in")
        state = build_tabs_state(pages[1])
        assert state.total == 2
        assert state.active_index == 1
        assert [t.url for t in state.tabs] == ["https://a.gov.in", "https://b.gov.in"]
        assert [t.active for t in state.tabs] == [False, True]

    def test_describe_single_and_multi(self) -> None:
        ctx, pages = _context_with("https://a.gov.in")
        assert "1 browser tab open" in build_tabs_state(pages[0]).describe()
        other = ctx.open("https://b.gov.in")
        multi = build_tabs_state(pages[0])
        assert multi.describe().startswith("2 browser tabs open")
        assert "https://b.gov.in" in multi.describe()


class TestTabSwitchTrace:
    def test_describe_new_tab_is_explicit(self) -> None:
        switch = TabSwitch(
            from_url="https://portal.gov.in",
            to_url="https://myaadhaar.gov.in",
            total_tabs=1,
            closed_tabs=1,
        )
        text = switch.describe()
        assert "opened a new tab: https://myaadhaar.gov.in" in text
        assert "switching context to it" in text
        assert "closed 1 orphaned tab(s)" in text
        assert "https://portal.gov.in" in text

    def test_describe_closed_by_site(self) -> None:
        switch = TabSwitch(
            from_url="", to_url="https://b.gov.in", total_tabs=1,
            reason="closed_by_site",
        )
        assert "closed_by_site" in switch.describe()
        assert "https://b.gov.in" in switch.describe()


class TestSyncActivePage:
    @pytest.mark.asyncio
    async def test_new_tab_becomes_active_and_orphan_closed(self) -> None:
        ctx, pages = _context_with("https://portal.gov.in")
        before = list(ctx.pages)
        popup = ctx.open("https://myaadhaar.gov.in")

        result = await sync_active_page(pages[0], before)

        assert result.active_page is popup
        assert result.switch is not None
        assert result.switch.to_url == "https://myaadhaar.gov.in"
        assert result.switch.closed_tabs == 1
        assert pages[0].is_closed() is True
        assert ctx.pages == [popup]

    @pytest.mark.asyncio
    async def test_orphan_kept_when_policy_disabled(self) -> None:
        ctx, pages = _context_with("https://portal.gov.in")
        before = list(ctx.pages)
        popup = ctx.open("https://myaadhaar.gov.in")

        result = await sync_active_page(pages[0], before, close_orphans=False)

        assert result.active_page is popup
        assert pages[0].is_closed() is False
        assert result.switch.closed_tabs == 0

    @pytest.mark.asyncio
    async def test_duplicate_new_tabs_collapse_to_newest(self) -> None:
        """One action opening two tabs must not leave a pile behind."""
        ctx, pages = _context_with("https://portal.gov.in")
        before = list(ctx.pages)
        first_popup = ctx.open("https://myaadhaar.gov.in")
        second_popup = ctx.open("https://myaadhaar.gov.in")

        result = await sync_active_page(pages[0], before)

        assert result.active_page is second_popup
        assert first_popup.is_closed() is True
        assert result.switch.closed_tabs == 2
        assert ctx.pages == [second_popup]

    @pytest.mark.asyncio
    async def test_no_new_tab_reports_no_switch(self) -> None:
        ctx, pages = _context_with("https://portal.gov.in")
        result = await sync_active_page(pages[0], list(ctx.pages), wait_for_tabs=False)
        assert result.switch is None
        assert result.active_page is pages[0]

    @pytest.mark.asyncio
    async def test_unknown_tab_state_changes_nothing(self) -> None:
        page = MagicMock()
        result = await sync_active_page(page, [], wait_for_tabs=True)
        assert result.active_page is page
        assert result.switch is None

    @pytest.mark.asyncio
    async def test_tracked_page_closed_falls_forward(self) -> None:
        ctx, pages = _context_with("https://portal.gov.in", "https://other.gov.in")
        pages[0]._closed = True
        result = await sync_active_page(pages[0], list(ctx.pages), wait_for_tabs=False)
        assert result.active_page is pages[1]
        assert result.switch is not None
        assert result.switch.reason == "closed_by_site"


class TestResolveActivePage:
    def test_live_page_is_left_alone(self) -> None:
        ctx, pages = _context_with("https://a.gov.in", "https://b.gov.in")
        result = resolve_active_page(pages[0])
        # Extra tabs are reported to the model, not seized silently.
        assert result.active_page is pages[0]
        assert result.switch is None

    def test_dead_page_is_replaced(self) -> None:
        ctx, pages = _context_with("https://a.gov.in", "https://b.gov.in")
        pages[0]._closed = True
        result = resolve_active_page(pages[0])
        assert result.active_page is pages[1]
        assert result.switch is not None

    def test_unknown_context_is_left_alone(self) -> None:
        page = object()
        assert resolve_active_page(page).active_page is page


class TestSwitchFromResult:
    def test_real_switch_is_adopted(self) -> None:
        current, target = FakePage("a"), FakePage("b")
        result = MagicMock()
        result.tab_switch = TabSwitch(from_url="a", to_url="b", total_tabs=1)
        result.active_page = target
        sync = switch_from_result(current, result)
        assert sync.active_page is target
        assert sync.switch is not None

    def test_mocked_result_cannot_hijack_the_page(self) -> None:
        """A MagicMock attribute is not a TabSwitch — leave the page alone."""
        current = FakePage("a")
        sync = switch_from_result(current, MagicMock())
        assert sync.active_page is current
        assert sync.switch is None

    def test_missing_active_page_keeps_current(self) -> None:
        current = FakePage("a")
        result = MagicMock()
        result.tab_switch = TabSwitch(from_url="a", to_url="b", total_tabs=1)
        result.active_page = None
        sync = switch_from_result(current, result)
        assert sync.active_page is current
        assert isinstance(sync, TabSyncResult)
