"""Phase 3 failure injection tests — updated for Phase 3.5 hardened API."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.browser.verification import VerificationStatus
from app.config.settings import Settings
from app.models.actions import BrowserAction

SYNTHETIC_PAGES_DIR = Path(__file__).parent / "pages"
BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.fixture
def executor() -> BrowserExecutor:
    return BrowserExecutor()


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


class TestFillFailureDetection:
    @pytest.mark.asyncio
    async def test_detects_field_disappeared(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            disappearing = next(e for e in obs.page_state.elements if e.html_name == "disappearing")
            action = BrowserAction(action="fill", target_ref=disappearing.ref, literal_value="REMOVE")
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE

    @pytest.mark.asyncio
    async def test_detects_field_became_disabled(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            locking = next(e for e in obs.page_state.elements if e.html_name == "locking")
            action = BrowserAction(action="fill", target_ref=locking.ref, literal_value="LOCK")
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE

    @pytest.mark.asyncio
    async def test_detects_validation_appeared(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            validating = next(e for e in obs.page_state.elements if e.html_name == "validating")
            action = BrowserAction(action="fill", target_ref=validating.ref, literal_value="ERROR")
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE
            msg = result.verification.message.lower()
            assert "validation" in msg or "alert" in msg or "invalid" in msg

    @pytest.mark.asyncio
    async def test_normal_fill_succeeds(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            normal = next(e for e in obs.page_state.elements if e.html_name == "normal")
            action = BrowserAction(action="fill", target_ref=normal.ref, literal_value="Hello World")
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS


class TestClickFailureDetection:
    @pytest.mark.asyncio
    async def test_detects_noop_click(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            noop_btn = next(e for e in obs.page_state.elements if e.accessible_name and "no-op" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=noop_btn.ref)
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            # UNCERTAIN now stops progression (#1)
            assert result.verification.status == VerificationStatus.UNCERTAIN
            assert result.recovery_required is True

    @pytest.mark.asyncio
    async def test_detects_new_elements_appeared(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            add_btn = next(e for e in obs.page_state.elements if e.accessible_name and "add new" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=add_btn.ref)
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_detects_title_change(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            title_btn = next(e for e in obs.page_state.elements if e.accessible_name and "change title" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=title_btn.ref)
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS


class TestSelectFailureDetection:
    @pytest.mark.asyncio
    async def test_detects_dependent_field_appeared(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_select.html")
            obs = await observer.observe(page)
            category = next(e for e in obs.page_state.elements if e.html_name == "category")
            action = BrowserAction(action="select", target_ref=category.ref, option="Education")
            result = await executor.execute(page, action, obs)
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_select_wrong_option_fails(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_select.html")
            obs = await observer.observe(page)
            limited = next(e for e in obs.page_state.elements if e.html_name == "limited")
            action = BrowserAction(action="select", target_ref=limited.ref, option="Option Z")
            result = await executor.execute(page, action, obs)
            assert result.success is False


class TestReObservation:
    @pytest.mark.asyncio
    async def test_executor_returns_post_observation(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/simple.html")
            obs = await observer.observe(page)
            name_field = next(
                e for e in obs.page_state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )
            action = BrowserAction(action="fill", target_ref=name_field.ref, literal_value="Test User")
            result = await executor.execute(page, action, obs)
            assert result.post_observation is not None
            assert result.post_observation.observation_id != obs.observation_id

    @pytest.mark.asyncio
    async def test_uncertain_stops_progression(self, settings, executor, observer) -> None:
        """UNCERTAIN verification now causes recovery_required=True (#1)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            noop_btn = next(e for e in obs.page_state.elements if e.accessible_name and "no-op" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=noop_btn.ref)
            result = await executor.execute(page, action, obs)
            assert result.recovery_required is True
            assert result.success is False
