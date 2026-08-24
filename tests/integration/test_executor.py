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
            state = await observer.observe(page)

            # Find the fullName field
            name_field = next(e for e in state.elements if e.name and "name" in e.name.lower() and e.input_type == "text")

            action = BrowserAction(
                action="fill",
                target_ref=name_field.ref,
                literal_value="Rahul Sharma",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True

            # Verify the value was filled via observer
            new_state = await observer.observe(page)
            filled_field = next(e for e in new_state.elements if e.ref == name_field.ref)
            assert filled_field.value == "Rahul Sharma"

    @pytest.mark.asyncio
    async def test_fill_email_field(self, settings, executor, observer) -> None:
        """Fill an email input."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            email_field = next(e for e in state.elements if e.input_type == "email")
            action = BrowserAction(
                action="fill",
                target_ref=email_field.ref,
                literal_value="rahul@example.gov.in",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True


class TestClickAction:
    """Test click browser action."""

    @pytest.mark.asyncio
    async def test_click_button(self, settings, executor, observer) -> None:
        """Click a button."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            submit_btn = next(e for e in state.elements if e.role == "button")
            action = BrowserAction(
                action="click",
                target_ref=submit_btn.ref,
            )

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_click_navigates_multistep(self, settings, executor, observer) -> None:
        """Click Next in multi-step form advances to step 2."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/multistep.html")
            state = await observer.observe(page)

            # Find the Next button by role
            buttons = [e for e in state.elements if e.role == "button"]
            next_btn = buttons[0]  # First button is "Next →"
            action = BrowserAction(action="click", target_ref=next_btn.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True

            # Observe new state — step 2 should have different elements
            new_state = await observer.observe(page)
            all_names = " ".join(e.name or e.label or "" for e in new_state.elements).lower()
            # Step 2 has email and phone fields
            assert "email" in all_names or "phone" in all_names


class TestSelectAction:
    """Test select dropdown action."""

    @pytest.mark.asyncio
    async def test_select_dropdown(self, settings, executor, observer) -> None:
        """Select an option from a dropdown."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            state_select = next(e for e in state.elements if e.role == "combobox")
            action = BrowserAction(
                action="select",
                target_ref=state_select.ref,
                option="Kerala",
            )

            result = await executor.execute(page, action, state)
            assert result.success is True

            # Verify selection
            new_state = await observer.observe(page)
            selected = next(e for e in new_state.elements if e.ref == state_select.ref)
            assert "Kerala" in (selected.selected_options or [])

    @pytest.mark.asyncio
    async def test_select_dependent_dropdown(self, settings, executor, observer) -> None:
        """Select state then district in dependent dropdown form."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/dropdowns.html")
            state = await observer.observe(page)

            # Select state
            state_select = next(e for e in state.elements if e.role == "combobox")
            action = BrowserAction(action="select", target_ref=state_select.ref, option="Kerala")
            await executor.execute(page, action, state)

            # Re-observe to see district dropdown
            new_state = await observer.observe(page)
            selects = [e for e in new_state.elements if e.role == "combobox"]
            assert len(selects) >= 2

            # Select district
            district_select = selects[1]
            action = BrowserAction(action="select", target_ref=district_select.ref, option="Thiruvananthapuram")
            result = await executor.execute(page, action, new_state)
            assert result.success is True


class TestCheckUncheckAction:
    """Test checkbox actions."""

    @pytest.mark.asyncio
    async def test_check_checkbox(self, settings, executor, observer) -> None:
        """Check a checkbox."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            state = await observer.observe(page)

            terms_checkbox = next(
                e for e in state.elements
                if e.role == "checkbox" and e.name and "terms" in e.name.lower()
            )
            action = BrowserAction(action="check", target_ref=terms_checkbox.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_check_radio_button(self, settings, executor, observer) -> None:
        """Click a radio button (via click action)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            state = await observer.observe(page)

            # Find radio buttons — use first radio (Male)
            radios = [e for e in state.elements if e.role == "radio"]
            assert len(radios) > 0, f"No radios found. Elements: {[(e.ref, e.role, e.name) for e in state.elements]}"
            male_radio = radios[0]  # First radio is Male
            action = BrowserAction(action="click", target_ref=male_radio.ref)

            result = await executor.execute(page, action, state)
            assert result.success is True


class TestScrollAction:
    """Test scroll action."""

    @pytest.mark.asyncio
    async def test_scroll_down(self, settings, executor, observer) -> None:
        """Scroll the page down."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            action = BrowserAction(action="scroll", direction="down")
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestGoBackAction:
    """Test go_back action."""

    @pytest.mark.asyncio
    async def test_go_back(self, settings, executor, observer) -> None:
        """Navigate back."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            action = BrowserAction(action="go_back")
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestPressAction:
    """Test keyboard press action."""

    @pytest.mark.asyncio
    async def test_press_tab(self, settings, executor, observer) -> None:
        """Press Tab key."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            action = BrowserAction(action="press", key="Tab")
            result = await executor.execute(page, action, state)
            assert result.success is True


class TestOpenAction:
    """Test open URL action."""

    @pytest.mark.asyncio
    async def test_open_url(self, settings, executor, observer) -> None:
        """Navigate to a URL."""
        async with BrowserManager(settings) as manager:
            page = await manager.open("about:blank")
            state = await observer.observe(page)

            action = BrowserAction(
                action="open",
                literal_value=f"{SYNTHETIC_BASE}/simple.html",
            )
            result = await executor.execute(page, action, state)
            assert result.success is True
            assert "simple.html" in page.url


class TestInvalidAction:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_fill_no_value(self, settings, executor, observer) -> None:
        """Fill without value fails gracefully."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            name_field = next(e for e in state.elements if e.name and "name" in e.name.lower() and e.input_type == "text")
            action = BrowserAction(action="fill", target_ref=name_field.ref)

            result = await executor.execute(page, action, state)
            assert result.success is False
            assert "No value" in result.message

    @pytest.mark.asyncio
    async def test_click_nonexistent_ref(self, settings, executor, observer) -> None:
        """Click a nonexistent ref fails gracefully."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            state = await observer.observe(page)

            action = BrowserAction(action="click", target_ref="e999")
            result = await executor.execute(page, action, state)
            assert result.success is False
