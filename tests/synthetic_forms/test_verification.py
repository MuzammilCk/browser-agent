"""Phase 3 failure injection tests — prove the verifier detects real failures.

Tests that the verification engine correctly identifies:
- Field disappears after fill
- Field becomes disabled after fill
- Validation appears after fill
- Click has no effect
- Click triggers dialog
- Click adds new elements
- Select changes dependent options
- Select with invalid option fails
"""

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


# ═══════════════════════════════════════════════════════════════
# FILL FAILURE TESTS
# ═══════════════════════════════════════════════════════════════

class TestFillFailureDetection:
    """Verify that fill failures are detected, not masked as success."""

    @pytest.mark.asyncio
    async def test_detects_field_disappeared(self, settings, executor, observer) -> None:
        """Field that disappears after typing 'REMOVE' is detected as failure."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            state = obs.page_state

            disappearing = next(e for e in state.elements if e.html_name == "disappearing")

            # Fill with "REMOVE" which triggers the field to disappear
            action = BrowserAction(
                action="fill",
                target_ref=disappearing.ref,
                literal_value="REMOVE",
            )
            result = await executor.execute(page, action, state)

            # The executor re-observes and verifies — field should be gone
            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE
            assert "disappeared" in result.verification.message.lower()

    @pytest.mark.asyncio
    async def test_detects_field_became_disabled(self, settings, executor, observer) -> None:
        """Field that becomes disabled after typing 'LOCK' is detected."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            state = obs.page_state

            locking = next(e for e in state.elements if e.html_name == "locking")

            action = BrowserAction(
                action="fill",
                target_ref=locking.ref,
                literal_value="LOCK",
            )
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE
            assert "disabled" in result.verification.message.lower()

    @pytest.mark.asyncio
    async def test_detects_validation_appeared(self, settings, executor, observer) -> None:
        """Validation error that appears after fill is detected."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            state = obs.page_state

            validating = next(e for e in state.elements if e.html_name == "validating")

            action = BrowserAction(
                action="fill",
                target_ref=validating.ref,
                literal_value="ERROR",
            )
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.FAILURE
            # Could be validation error or alert — both count as failure
            msg = result.verification.message.lower()
            assert "validation" in msg or "alert" in msg or "invalid" in msg

    @pytest.mark.asyncio
    async def test_normal_fill_succeeds(self, settings, executor, observer) -> None:
        """Normal fill without side effects is verified as success."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_fill.html")
            obs = await observer.observe(page)
            state = obs.page_state

            normal = next(e for e in state.elements if e.html_name == "normal")

            action = BrowserAction(
                action="fill",
                target_ref=normal.ref,
                literal_value="Hello World",
            )
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# CLICK FAILURE TESTS
# ═══════════════════════════════════════════════════════════════

class TestClickFailureDetection:
    """Verify that click results are correctly classified."""

    @pytest.mark.asyncio
    async def test_detects_noop_click(self, settings, executor, observer) -> None:
        """Click on a no-op button is classified as UNCERTAIN."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            state = obs.page_state

            noop_btn = next(e for e in state.elements if e.accessible_name and "no-op" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=noop_btn.ref)
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            # No-op should be UNCERTAIN (not FAILURE, since no-op is valid)
            assert result.verification.status == VerificationStatus.UNCERTAIN

    @pytest.mark.asyncio
    async def test_detects_new_elements_appeared(self, settings, executor, observer) -> None:
        """Click that adds new elements is detected as SUCCESS (page changed)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            state = obs.page_state

            add_btn = next(e for e in state.elements if e.accessible_name and "add new" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=add_btn.ref)
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_detects_title_change(self, settings, executor, observer) -> None:
        """Click that changes page title is detected."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            state = obs.page_state

            title_btn = next(e for e in state.elements if e.accessible_name and "change title" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=title_btn.ref)
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_detects_element_toggled(self, settings, executor, observer) -> None:
        """Click that toggles element class is detected."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_click.html")
            obs = await observer.observe(page)
            state = obs.page_state

            toggle_btn = next(e for e in state.elements if e.accessible_name and "toggle" in e.accessible_name.lower())
            action = BrowserAction(action="click", target_ref=toggle_btn.ref)
            result = await executor.execute(page, action, state)

            # Toggle may or may not change observable state
            assert result.verification is not None
            # Either SUCCESS (state changed) or UNCERTAIN (no observable change)
            assert result.verification.status in (
                VerificationStatus.SUCCESS,
                VerificationStatus.UNCERTAIN,
            )


# ═══════════════════════════════════════════════════════════════
# SELECT FAILURE TESTS
# ═══════════════════════════════════════════════════════════════

class TestSelectFailureDetection:
    """Verify that select results are correctly classified."""

    @pytest.mark.asyncio
    async def test_detects_dependent_field_appeared(self, settings, executor, observer) -> None:
        """Select that causes dependent dropdown to appear is detected."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_select.html")
            obs = await observer.observe(page)
            state = obs.page_state

            category = next(e for e in state.elements if e.html_name == "category")
            action = BrowserAction(action="select", target_ref=category.ref, option="Education")
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS
            assert "dependent" in result.verification.message.lower() or "new" in result.verification.message.lower()

    @pytest.mark.asyncio
    async def test_select_wrong_option_fails(self, settings, executor, observer) -> None:
        """Select with non-existent option is detected as failure."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_select.html")
            obs = await observer.observe(page)
            state = obs.page_state

            limited = next(e for e in state.elements if e.html_name == "limited")
            action = BrowserAction(action="select", target_ref=limited.ref, option="Option Z")
            # This will throw at Playwright level since Option Z doesn't exist
            result = await executor.execute(page, action, state)

            # Should fail because Playwright can't find "Option Z"
            assert result.success is False

    @pytest.mark.asyncio
    async def test_select_triggers_new_text_field(self, settings, executor, observer) -> None:
        """Select 'Other' triggers a new text field — verified as dependent change."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/failure_select.html")
            obs = await observer.observe(page)
            state = obs.page_state

            reason = next(e for e in state.elements if e.html_name == "reason")
            action = BrowserAction(action="select", target_ref=reason.ref, option="Other (specify)")
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════
# RE-OBSERVATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestReObservation:
    """Verify that the executor re-observes after every action."""

    @pytest.mark.asyncio
    async def test_executor_re_observes_after_fill(self, settings, executor, observer) -> None:
        """After fill, executor produces fresh verification with current state."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            name_field = next(
                e for e in state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )

            action = BrowserAction(
                action="fill",
                target_ref=name_field.ref,
                literal_value="Test User",
            )
            result = await executor.execute(page, action, state)

            # Verification should exist and use fresh state
            assert result.verification is not None
            assert result.verification.action_type == "fill"
            assert result.verification.target_ref == name_field.ref

    @pytest.mark.asyncio
    async def test_executor_re_observes_after_select(self, settings, executor, observer) -> None:
        """After select, executor produces fresh verification."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            state_select = next(e for e in state.elements if e.role == "combobox")
            action = BrowserAction(
                action="select",
                target_ref=state_select.ref,
                option="Kerala",
            )
            result = await executor.execute(page, action, state)

            assert result.verification is not None
            assert result.verification.status == VerificationStatus.SUCCESS
