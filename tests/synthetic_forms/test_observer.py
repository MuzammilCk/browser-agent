"""Integration tests for PageObserver against synthetic form pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings

SYNTHETIC_PAGES_DIR = Path(__file__).parent / "pages"
SYNTHETIC_SERVER_BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


class TestSimpleForm:
    """Tests against simple.html — text inputs, labels, required fields."""

    @pytest.mark.asyncio
    async def test_observes_text_inputs(self, settings: Settings, observer: PageObserver) -> None:
        """Observer detects text input fields with correct labels."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            assert state.url.endswith("simple.html")
            assert state.page_type == "form"

            refs = [e.ref for e in state.elements]
            assert len(refs) >= 6

            # Check fullName field uses split name fields
            name_fields = [e for e in state.elements if e.name and "name" in e.name.lower()]
            assert len(name_fields) >= 1
            name_field = name_fields[0]
            assert name_field.required is True
            assert name_field.input_type == "text"
            # Verify split fields exist
            assert name_field.accessible_name is not None or name_field.label_text is not None

    @pytest.mark.asyncio
    async def test_observes_required_fields(self, settings: Settings, observer: PageObserver) -> None:
        """Observer correctly identifies required fields."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            required = [e for e in state.elements if e.required]
            assert len(required) >= 3

    @pytest.mark.asyncio
    async def test_observes_select_dropdown(self, settings: Settings, observer: PageObserver) -> None:
        """Observer detects select dropdown."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            selects = [e for e in state.elements if e.role == "combobox"]
            assert len(selects) >= 1

    @pytest.mark.asyncio
    async def test_observes_button(self, settings: Settings, observer: PageObserver) -> None:
        """Observer detects submit button."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            buttons = [e for e in state.elements if e.role == "button"]
            assert len(buttons) >= 1

    @pytest.mark.asyncio
    async def test_element_refs_are_unique(self, settings: Settings, observer: PageObserver) -> None:
        """Every element has a unique ref."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            refs = [e.ref for e in state.elements]
            assert len(refs) == len(set(refs))

    @pytest.mark.asyncio
    async def test_page_observation_has_aria_snapshot(self, settings: Settings, observer: PageObserver) -> None:
        """PageObservation includes ARIA snapshot per audit #2."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)

            assert obs.aria_snapshot is not None
            assert len(obs.aria_snapshot) > 0
            assert obs.observation_id != ""

    @pytest.mark.asyncio
    async def test_element_has_split_name_fields(self, settings: Settings, observer: PageObserver) -> None:
        """Elements have split name fields per audit #3."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            # All elements should have the new fields (even if None)
            for el in state.elements:
                assert hasattr(el, "accessible_name")
                assert hasattr(el, "html_name")
                assert hasattr(el, "label_text")

    @pytest.mark.asyncio
    async def test_element_has_context_fields(self, settings: Settings, observer: PageObserver) -> None:
        """Elements have context fields per audit #8."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/simple.html")
            obs = await observer.observe(page)
            state = obs.page_state

            for el in state.elements:
                assert hasattr(el, "section_heading")
                assert hasattr(el, "group_label")
                assert hasattr(el, "help_text")


class TestDropdownForm:
    """Tests against dropdowns.html — dependent dropdowns."""

    @pytest.mark.asyncio
    async def test_observes_hidden_elements(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/dropdowns.html")
            obs = await observer.observe(page)
            state = obs.page_state

            selects = [e for e in state.elements if e.role == "combobox"]
            assert len(selects) >= 1

    @pytest.mark.asyncio
    async def test_dependent_dropdown_appears(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/dropdowns.html")
            await page.locator("#state").select_option("kerala")

            obs = await observer.observe(page)
            state = obs.page_state
            selects = [e for e in state.elements if e.role == "combobox"]
            assert len(selects) >= 2


class TestCheckboxesRadios:
    """Tests against checks.html — checkboxes and radio buttons."""

    @pytest.mark.asyncio
    async def test_observes_radios(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/checks.html")
            obs = await observer.observe(page)
            state = obs.page_state

            radios = [e for e in state.elements if e.role == "radio"]
            assert len(radios) >= 4

    @pytest.mark.asyncio
    async def test_observes_checkboxes(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/checks.html")
            obs = await observer.observe(page)
            state = obs.page_state

            checkboxes = [e for e in state.elements if e.role == "checkbox"]
            assert len(checkboxes) >= 4


class TestValidationForm:
    """Tests against validation.html — validation errors."""

    @pytest.mark.asyncio
    async def test_observes_validation_errors(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/validation.html")
            obs = await observer.observe(page)
            state = obs.page_state

            assert len(state.validation_errors) >= 2

    @pytest.mark.asyncio
    async def test_validation_messages_captured(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/validation.html")
            obs = await observer.observe(page)
            state = obs.page_state

            messages = [v.message for v in state.validation_errors if v.message]
            assert len(messages) >= 2
            assert any("12 digits" in m for m in messages)


class TestMultiStep:
    """Tests against multistep.html — multi-step wizard."""

    @pytest.mark.asyncio
    async def test_observes_step1(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/multistep.html")
            obs = await observer.observe(page)
            state = obs.page_state

            visible_elements = [e for e in state.elements if e.visible]
            buttons = [e for e in visible_elements if e.role == "button"]
            assert len(buttons) >= 1

    @pytest.mark.asyncio
    async def test_navigate_to_step2(self, settings: Settings, observer: PageObserver) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_SERVER_BASE}/multistep.html")
            await page.get_by_role("button", name="Next").click()

            obs = await observer.observe(page)
            state = obs.page_state
            all_names = " ".join(e.name or "" for e in state.elements).lower()
            assert "email" in all_names or "phone" in all_names
