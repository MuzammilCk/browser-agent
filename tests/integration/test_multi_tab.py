"""Multi-tab awareness — Phase 8 acceptance tests.

Reproduces the audit §3 failure with a real browser, real
``BrowserExecutor`` and a real ``target="_blank"`` link:

    BEFORE: click → the tracked Page never navigates, the new tab is
    invisible to the whole stack, success=True is reported anyway, and the
    next iteration re-clicks the same link → one duplicate tab per retry.

    AFTER:  the newest tab becomes the active page for every subsequent
    observation and action, the switch is explicit in the result, and the
    orphaned tab does not accumulate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.runner import AgentRunner
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.browser.tabs import TabSwitch
from app.config.settings import Settings
from app.models.actions import BrowserAction
from app.vault.resolver import UserVault

SYNTHETIC_PAGES_DIR = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
SYNTHETIC_BASE = SYNTHETIC_PAGES_DIR.as_uri()

LANDING = f"{SYNTHETIC_BASE}/portal_landing.html"


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True, browser_mode="test")


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


@pytest.fixture
def executor() -> BrowserExecutor:
    return BrowserExecutor()


def _link_ref(observation, name: str) -> str:
    element = next(
        e for e in observation.page_state.elements
        if e.role == "link" and (e.name or "").strip() == name
    )
    return element.ref


class TestTargetBlankClick:
    """The exact repro from the audit (§3)."""

    @pytest.mark.asyncio
    async def test_tracked_page_follows_new_tab(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)

            action = BrowserAction(
                action="click", target_ref=_link_ref(obs, "Download Aadhaar"),
            )
            result = await executor.execute(page, action, obs)

            assert result.success is True
            # The tab switch is explicit, not silent.
            assert isinstance(result.tab_switch, TabSwitch)
            assert "portal_subportal.html" in result.tab_switch.to_url
            # The ACTIVE page — the one every later observation/action uses —
            # is the sub-portal, not the frozen landing page.
            assert result.active_page is not None
            assert "portal_subportal.html" in result.active_page.url
            # Post-observation describes the new tab, not the old page.
            assert "portal_subportal.html" in result.post_observation.page_state.url
            # One click must never leave more than the old + new tab behind.
            assert len(manager.context.pages) <= 2

    @pytest.mark.asyncio
    async def test_window_open_click_also_switches(self, settings, executor, observer) -> None:
        """``window.open(..., '_blank')`` behaves the same as target=_blank."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)

            action = BrowserAction(
                action="click",
                target_ref=_link_ref(obs, "Open Sub-Portal (window.open)"),
            )
            result = await executor.execute(page, action, obs)

            assert result.tab_switch is not None
            assert "portal_subportal.html" in result.active_page.url
            assert len(manager.context.pages) <= 2

    @pytest.mark.asyncio
    async def test_orphaned_tab_does_not_accumulate(self, settings, executor, observer) -> None:
        """Policy: the orphaned old tab is closed once a newer tab is active."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)
            action = BrowserAction(
                action="click", target_ref=_link_ref(obs, "Download Aadhaar"),
            )
            result = await executor.execute(page, action, obs)

            assert result.tab_switch.closed_tabs == 1
            assert page.is_closed() is True
            live = [p for p in manager.context.pages if not p.is_closed()]
            assert len(live) == 1
            assert "portal_subportal.html" in live[0].url

    @pytest.mark.asyncio
    async def test_no_duplicate_tab_on_next_iteration(self, settings, executor, observer) -> None:
        """The stale-page re-click that produced duplicate tabs is gone.

        After the switch, re-observing the ACTIVE page shows the sub-portal,
        so the planner never sees the unclicked-looking link again.
        """
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)
            result = await executor.execute(
                page,
                BrowserAction(action="click", target_ref=_link_ref(obs, "Download Aadhaar")),
                obs,
            )

            next_obs = await observer.observe(result.active_page)
            assert "portal_subportal.html" in next_obs.page_state.url
            link_names = [
                (e.name or "") for e in next_obs.page_state.elements if e.role == "link"
            ]
            assert "Download Aadhaar" not in link_names
            assert len([p for p in manager.context.pages if not p.is_closed()]) == 1

    @pytest.mark.asyncio
    async def test_same_page_navigation_reports_no_switch(
        self, settings, executor, observer,
    ) -> None:
        """A normal same-tab link must not be reported as a tab switch."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)
            result = await executor.execute(
                page,
                BrowserAction(action="click", target_ref=_link_ref(obs, "Reload this page")),
                obs,
            )

            assert result.tab_switch is None
            assert len([p for p in manager.context.pages if not p.is_closed()]) == 1


class TestObservationReportsTabs:
    """Multi-tab state is part of what the model observes."""

    @pytest.mark.asyncio
    async def test_single_tab_state(self, settings, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await observer.observe(page)
            tabs = obs.page_state.tabs
            assert tabs.total == 1
            assert tabs.active_index == 0
            assert len(tabs.tabs) == 1
            assert tabs.tabs[0].active is True

    @pytest.mark.asyncio
    async def test_second_tab_is_visible_in_observation(self, settings, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            other = await manager.context.new_page()
            await other.goto(f"{SYNTHETIC_BASE}/portal_subportal.html")

            obs = await observer.observe(page)
            tabs = obs.page_state.tabs
            assert tabs.total == 2
            assert tabs.active_index == 0
            assert any("portal_subportal.html" in t.url for t in tabs.tabs)
            assert tabs.describe().startswith("2 browser tabs open")


class TestManagerTabTracking:
    """BrowserManager tracks tabs from the moment they open."""

    @pytest.mark.asyncio
    async def test_new_page_event_adopts_active_page(self, settings) -> None:
        async with BrowserManager(settings) as manager:
            first = await manager.open(LANDING)
            second = await manager.context.new_page()
            await second.goto(f"{SYNTHETIC_BASE}/portal_subportal.html")

            # The listener registered in start() saw the tab open.
            assert manager.page is second
            assert manager.tabs.total == 2
            assert first is not manager.page

    @pytest.mark.asyncio
    async def test_active_page_falls_back_when_closed(self, settings) -> None:
        async with BrowserManager(settings) as manager:
            first = await manager.open(LANDING)
            second = await manager.context.new_page()
            await second.close()
            # Closing the adopted tab must fall back to a live one.
            assert manager.page is first
            assert manager.page.is_closed() is False


class TestRunnerTabSwitchTrace:
    """The switch is visible in the workflow trace, not handled silently."""

    @pytest.mark.asyncio
    async def test_workflow_records_tab_switch_and_follows_it(self, settings) -> None:
        from app.agent.planner import ACTION_SCHEMA

        plan_responses = [
            {"action": "click", "target_ref": None, "confidence": 0.9},
            {"action": "stop", "reason": "sub-portal reached"},
        ]
        plan_calls = 0

        async with BrowserManager(settings) as manager:
            page = await manager.open(LANDING)
            obs = await PageObserver().observe(page)
            plan_responses[0]["target_ref"] = _link_ref(obs, "Download Aadhaar")

            async def mock_complete(**kwargs):
                """Answer planner calls only; field-mapper calls get nothing."""
                nonlocal plan_calls
                resp = MagicMock()
                if kwargs.get("schema") is not ACTION_SCHEMA:
                    resp.parsed = {"mappings": []}
                    return resp
                resp.parsed = plan_responses[min(plan_calls, len(plan_responses) - 1)]
                plan_calls += 1
                return resp

            mock_llm = MagicMock()
            mock_llm.model_name = "test/mock"
            mock_llm.complete = AsyncMock(side_effect=mock_complete)

            runner = AgentRunner(
                llm=mock_llm, max_iterations=4,
                vault=UserVault(full_name="Test User"),
            )
            workflow = await runner.run(
                page=page, task="Click Download Aadhaar", domain="uidai.gov.in",
            )

            assert workflow.tab_switches, "tab switch missing from workflow trace"
            assert "portal_subportal.html" in workflow.tab_switches[0]
            assert any("new tab" in cp.lower() for cp in workflow.checkpoints)
            # The workflow followed the new tab instead of re-observing the
            # frozen landing page.
            assert "portal_subportal.html" in workflow.current_url
            assert workflow.open_tab_count >= 1
            # Exactly one click — no duplicate tabs from repeated attempts.
            clicks = [a for a in workflow.actions_taken if a.action_type == "click"]
            assert len(clicks) == 1
