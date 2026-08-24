"""Integration tests for browser executor actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.actions import BrowserAction

SYNTHETIC_PAGES_DIR = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
SYNTHETIC_BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.fixture
def executor() -> BrowserExecutor:
    return BrowserExecutor()


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


class TestFillAction:
    """Test fill browser action."""

    @pytest.mark.asyncio
    async def test_fill_text_input(self, settings, executor, observer) -> None:
        """Fill a text input and verify the value."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            name_field = next(
                e for e in state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )

            action = BrowserAction(
                action="fill",
                target_ref=name_field.ref,
                literal_value="Rahul Sharma",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True
            # Verification should have been called
            assert result.verification is not None

    @pytest.mark.asyncio
    async def test_fill_email_field(self, settings, executor, observer) -> None:
        """Fill an email input."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            email_field = next(e for e in state.elements if e.input_type == "email")
            action = BrowserAction(
                action="fill",
                target_ref=email_field.ref,
                literal_value="rahul@example.gov.in",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_fill_no_value_fails(self, settings, executor, observer) -> None:
        """Fill without value fails validation."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            name_field = next(
                e for e in state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )
            # This should fail at Pydantic validation level
            with pytest.raises(ValueError, match="fill requires either"):
                BrowserAction(action="fill", target_ref=name_field.ref)


class TestClickAction:
    """Test click browser action."""

    @pytest.mark.asyncio
    async def test_click_button(self, settings, executor, observer) -> None:
        """Click a button."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            submit_btn = next(e for e in state.elements if e.role == "button")
            action = BrowserAction(action="click", target_ref=submit_btn.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_click_navigates_multistep(self, settings, executor, observer) -> None:
        """Click Next in multi-step form advances to step 2."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/multistep.html")
            obs = await observer.observe(page)
            state = obs.page_state

            buttons = [e for e in state.elements if e.role == "button"]
            next_btn = buttons[0]
            action = BrowserAction(action="click", target_ref=next_btn.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True

            # Verify re-observation happened
            assert result.verification is not None


class TestSelectAction:
    """Test select dropdown action."""

    @pytest.mark.asyncio
    async def test_select_dropdown(self, settings, executor, observer) -> None:
        """Select an option from a dropdown."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            state_select = next(e for e in state.elements if e.role == "combobox")
            action = BrowserAction(
                action="select",
                target_ref=state_select.ref,
                option="Kerala",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_select_dependent_dropdown(self, settings, executor, observer) -> None:
        """Select state then district in dependent dropdown form."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/dropdowns.html")
            obs = await observer.observe(page)
            state = obs.page_state

            state_select = next(e for e in state.elements if e.role == "combobox")
            action = BrowserAction(action="select", target_ref=state_select.ref, option="Kerala")
            await executor.execute(page, action, state)

            # Re-observe
            obs2 = await observer.observe(page)
            selects = [e for e in obs2.page_state.elements if e.role == "combobox"]
            assert len(selects) >= 2


class TestCheckUncheckAction:
    """Test checkbox actions."""

    @pytest.mark.asyncio
    async def test_check_checkbox(self, settings, executor, observer) -> None:
        """Check a checkbox."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            obs = await observer.observe(page)
            state = obs.page_state

            terms_checkbox = next(
                e for e in state.elements
                if e.role == "checkbox" and e.name and "terms" in e.name.lower()
            )
            action = BrowserAction(action="check", target_ref=terms_checkbox.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_check_radio_button(self, settings, executor, observer) -> None:
        """Click a radio button."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            obs = await observer.observe(page)
            state = obs.page_state

            radios = [e for e in state.elements if e.role == "radio"]
            assert len(radios) > 0
            male_radio = radios[0]
            action = BrowserAction(action="click", target_ref=male_radio.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True


class TestScrollActions:
    """Test scroll actions."""

    @pytest.mark.asyncio
    async def test_scroll_down(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            action = BrowserAction(action="scroll", direction="down")
            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_scroll_to_element(self, settings, executor, observer) -> None:
        """Scroll to a specific element (#14)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            # Find submit button and scroll to it
            btn = next(e for e in state.elements if e.role == "button")
            action = BrowserAction(action="scroll_to", target_ref=btn.ref)
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestGoBackAction:
    """Test go_back action."""

    @pytest.mark.asyncio
    async def test_go_back(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            action = BrowserAction(action="go_back")
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestPressAction:
    """Test keyboard press action."""

    @pytest.mark.asyncio
    async def test_press_tab(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            action = BrowserAction(action="press", key="Tab")
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestOpenAction:
    """Test open URL action."""

    @pytest.mark.asyncio
    async def test_open_url(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open("about:blank")
            obs = await observer.observe(page)
            state = obs.page_state

            action = BrowserAction(action="open", literal_value=f"{SYNTHETIC_BASE}/simple.html")
            result = await executor.execute(page, action, state)
            assert result.success is True
            assert "simple.html" in page.url


class TestActionValidation:
    """Test action-specific validation (#16)."""

    def test_select_requires_option(self) -> None:
        with pytest.raises(ValueError, match="select requires option"):
            BrowserAction(action="select", target_ref="e1")

    def test_click_requires_target(self) -> None:
        with pytest.raises(ValueError, match="click requires target_ref"):
            BrowserAction(action="click")

    def test_upload_requires_target(self) -> None:
        with pytest.raises(ValueError, match="upload requires target_ref"):
            BrowserAction(action="upload", literal_value="/tmp/test.pdf")

    def test_press_requires_key(self) -> None:
        with pytest.raises(ValueError, match="press requires key"):
            BrowserAction(action="press")

    def test_request_user_action_requires_reason(self) -> None:
        with pytest.raises(ValueError, match="request_user_action requires reason"):
            BrowserAction(action="request_user_action")

    def test_valid_action_combinations(self) -> None:
        """Valid actions should not raise."""
        BrowserAction(action="fill", target_ref="e1", literal_value="test")
        BrowserAction(action="fill", target_ref="e1", value_ref="USER.full_name")
        BrowserAction(action="select", target_ref="e1", option="Kerala")
        BrowserAction(action="click", target_ref="e1")
        BrowserAction(action="check", target_ref="e1")
        BrowserAction(action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar")
        BrowserAction(action="upload", target_ref="e1", literal_value="/tmp/file.pdf")
        BrowserAction(action="scroll_to", target_ref="e1")
        BrowserAction(action="stop")
        BrowserAction(action="request_user_action", reason="OTP required")
