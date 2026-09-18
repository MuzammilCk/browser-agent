"""Integration tests for browser executor actions — Phase 3.5 hardened."""

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
    @pytest.mark.asyncio
    async def test_fill_text_input(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)

            name_field = next(
                e for e in obs.page_state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )
            action = BrowserAction(
                action="fill", target_ref=name_field.ref,
                literal_value="Rahul Sharma",
            )
            result = await executor.execute(page, action, obs)
            assert result.success is True
            assert result.verification is not None
            assert result.post_observation is not None

    @pytest.mark.asyncio
    async def test_fill_no_value_fails(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            name_field = next(
                e for e in obs.page_state.elements
                if e.name and "name" in e.name.lower() and e.input_type == "text"
            )
            with pytest.raises(ValueError, match="fill requires either"):
                BrowserAction(action="fill", target_ref=name_field.ref)


class TestClickAction:
    @pytest.mark.asyncio
    async def test_click_button(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            submit_btn = next(e for e in obs.page_state.elements if e.role == "button")
            action = BrowserAction(action="click", target_ref=submit_btn.ref)
            result = await executor.execute(page, action, obs)
            # "Submit Application" is HIGH_RISK → REQUIRE_CONFIRMATION.
            # Without explicit user approval the executor must refuse (audit B2).
            assert result.success is False
            assert "REQUIRE_CONFIRMATION" in result.message
            assert result.verification is None
            assert result.post_observation is None

    @pytest.mark.asyncio
    async def test_click_button_with_user_confirmation(self, settings, observer) -> None:
        """Audit C1: an explicitly user-confirmed high-risk action executes."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            submit_btn = next(e for e in obs.page_state.elements if e.role == "button")
            confirmed_executor = BrowserExecutor()
            action = BrowserAction(action="click", target_ref=submit_btn.ref)
            result = await confirmed_executor.execute(
                page, action, obs, user_confirmed=True,
            )
            # Submit button on data: URL may produce UNCERTAIN (no observable change)
            # This is correct behavior — UNCERTAIN stops progression
            assert result.verification is not None
            assert result.post_observation is not None

    @pytest.mark.asyncio
    async def test_click_navigates_multistep(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/multistep.html")
            obs = await observer.observe(page)
            buttons = [e for e in obs.page_state.elements if e.role == "button"]
            action = BrowserAction(action="click", target_ref=buttons[0].ref)
            result = await executor.execute(page, action, obs)
            assert result.success is True
            assert result.post_observation is not None


class TestSelectAction:
    @pytest.mark.asyncio
    async def test_select_dropdown(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            state_select = next(e for e in obs.page_state.elements if e.role == "combobox")
            action = BrowserAction(action="select", target_ref=state_select.ref, option="Kerala")
            result = await executor.execute(page, action, obs)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_select_dependent_dropdown(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/dropdowns.html")
            obs = await observer.observe(page)
            state_select = next(e for e in obs.page_state.elements if e.role == "combobox")
            action = BrowserAction(action="select", target_ref=state_select.ref, option="Kerala")
            await executor.execute(page, action, obs)
            # Re-observe using post_observation from previous result
            obs2 = await observer.observe(page)
            selects = [e for e in obs2.page_state.elements if e.role == "combobox"]
            assert len(selects) >= 2


class TestCheckUncheckAction:
    @pytest.mark.asyncio
    async def test_check_checkbox(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            obs = await observer.observe(page)
            terms_checkbox = next(
                e for e in obs.page_state.elements
                if e.role == "checkbox" and e.name and "terms" in e.name.lower()
            )
            action = BrowserAction(action="check", target_ref=terms_checkbox.ref)
            result = await executor.execute(page, action, obs)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_check_radio_button(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/checks.html")
            obs = await observer.observe(page)
            radios = [e for e in obs.page_state.elements if e.role == "radio"]
            assert len(radios) > 0
            action = BrowserAction(action="click", target_ref=radios[0].ref)
            result = await executor.execute(page, action, obs)
            assert result.success is True


class TestScrollActions:
    @pytest.mark.asyncio
    async def test_scroll_down(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            action = BrowserAction(action="scroll", direction="down")
            result = await executor.execute(page, action, obs)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_scroll_to_element(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            # Use a text input (has html_name) for reliable viewport check
            text_field = next(e for e in obs.page_state.elements if e.input_type == "text")
            action = BrowserAction(action="scroll_to", target_ref=text_field.ref)
            result = await executor.execute(page, action, obs)
            assert result.success is True


class TestGoBackAction:
    @pytest.mark.asyncio
    async def test_go_back(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            action = BrowserAction(action="go_back")
            result = await executor.execute(page, action, obs)
            assert result.success is True


class TestPressAction:
    @pytest.mark.asyncio
    async def test_press_tab(self, settings, executor, observer) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)
            action = BrowserAction(action="press", key="Tab")
            result = await executor.execute(page, action, obs)
            assert result.success is True


class TestActionValidation:
    def test_select_requires_option(self) -> None:
        with pytest.raises(ValueError, match="select requires option"):
            BrowserAction(action="select", target_ref="e1")

    def test_click_requires_target(self) -> None:
        with pytest.raises(ValueError, match="click requires target_ref"):
            BrowserAction(action="click")

    def test_upload_requires_document_ref(self) -> None:
        with pytest.raises(ValueError, match="upload requires document_ref"):
            BrowserAction(action="upload", target_ref="e1", literal_value="/tmp/test.pdf")

    def test_upload_with_document_ref_succeeds(self) -> None:
        action = BrowserAction(action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar")
        assert action.document_ref == "DOCUMENT.aadhaar"

    def test_press_requires_key(self) -> None:
        with pytest.raises(ValueError, match="press requires key"):
            BrowserAction(action="press")

    def test_request_user_action_requires_reason(self) -> None:
        with pytest.raises(ValueError, match="request_user_action requires reason"):
            BrowserAction(action="request_user_action")

    def test_open_not_in_action_set(self) -> None:
        """Open is no longer in the LLM action set (#6)."""
        with pytest.raises(Exception):
            BrowserAction(action="open", literal_value="https://example.com")

    def test_valid_action_combinations(self) -> None:
        BrowserAction(action="fill", target_ref="e1", literal_value="test")
        BrowserAction(action="fill", target_ref="e1", value_ref="USER.full_name")
        BrowserAction(action="select", target_ref="e1", option="Kerala")
        BrowserAction(action="click", target_ref="e1")
        BrowserAction(action="check", target_ref="e1")
        BrowserAction(action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar")
        BrowserAction(action="scroll_to", target_ref="e1")
        BrowserAction(action="stop")
        BrowserAction(action="request_user_action", reason="OTP required")

    def test_sensitive_pattern_rejected(self) -> None:
        """Sensitive numeric patterns in literal_value are rejected (#8)."""
        with pytest.raises(ValueError, match="Sensitive"):
            BrowserAction(action="fill", target_ref="e1", literal_value="123456789012")

    def test_pan_pattern_rejected(self) -> None:
        """PAN pattern in literal_value is rejected (#8)."""
        with pytest.raises(ValueError, match="PAN"):
            BrowserAction(action="fill", target_ref="e1", literal_value="ABCTS1234K")


class TestStaleRefRejection:
    @pytest.mark.asyncio
    async def test_stale_observation_rejected(self, settings, executor, observer) -> None:
        """Action with wrong observation_id is rejected (#3)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)

            # Create action with wrong observation_id
            action = BrowserAction(
                action="scroll", direction="down",
                observation_id="wrong_id_123",
            )
            result = await executor.execute(page, action, obs)
            assert result.success is False
            assert "Stale reference" in result.message
            assert result.recovery_required is True

    @pytest.mark.asyncio
    async def test_correct_observation_accepted(self, settings, executor, observer) -> None:
        """Action with correct observation_id is accepted (#3)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)

            action = BrowserAction(
                action="scroll", direction="down",
                observation_id=obs.observation_id,
            )
            result = await executor.execute(page, action, obs)
            assert result.success is True


class TestActionResultContract:
    @pytest.mark.asyncio
    async def test_action_result_has_post_observation(self, settings, executor, observer) -> None:
        """ActionResult includes post_observation (#2+#23)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)

            action = BrowserAction(action="scroll", direction="down")
            result = await executor.execute(page, action, obs)
            assert result.post_observation is not None
            assert result.post_observation.observation_id != obs.observation_id

    @pytest.mark.asyncio
    async def test_action_result_recovery_fields(self, settings, executor, observer) -> None:
        """ActionResult has recovery_required and user_action_required (#23)."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs = await observer.observe(page)

            action = BrowserAction(action="scroll", direction="down")
            result = await executor.execute(page, action, obs)
            assert hasattr(result, "recovery_required")
            assert hasattr(result, "user_action_required")


class TestUploadAction:
    """Phase 1 — file input coverage: observe → upload → verify."""

    @pytest.mark.asyncio
    async def test_upload_file_to_file_input(self, settings, executor, observer, tmp_path) -> None:
        """Actually perform a file upload and verify the file is set."""
        from app.vault.resolver import DocumentRef, DocumentRegistry

        # Create a temp file to upload
        upload_file = Path(__file__).parent / "fixtures" / "test_photo.jpg"

        doc_registry = DocumentRegistry()
        doc_registry.register(DocumentRef(
            id="photo", type="photo", path=str(upload_file),
            mime_type="image/jpeg",             original_filename="test_photo.jpg",
        ))
        executor.set_document_registry(doc_registry)

        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/file_upload.html")
            obs = await observer.observe(page)

            photo = next(
                e for e in obs.page_state.elements
                if e.input_type == "file" and e.html_name == "photo"
            )

            action = BrowserAction(
                action="upload",
                target_ref=photo.ref,
                document_ref="DOCUMENT.photo",
            )
            result = await executor.execute(page, action, obs, user_confirmed=True)
            assert result.success is True
            assert result.verification is not None
            assert result.verification.status.value == "success"

            # Verify the file is actually set in the DOM
            file_info = await page.evaluate("""(selector) => {
                const input = document.querySelector(selector);
                if (!input || !input.files || input.files.length === 0) return null;
                return { name: input.files[0].name, count: input.files.length };
            }""", f'input[name="{photo.html_name}"]')
            assert file_info is not None
            assert file_info["name"] == "test_photo.jpg"
            assert file_info["count"] == 1

    @pytest.mark.asyncio
    async def test_upload_to_wrong_element_fails(self, settings, executor, observer, tmp_path) -> None:
        """Upload to a file input must target the exact element, not any file input."""
        from app.vault.resolver import DocumentRef, DocumentRegistry

        upload_file = Path(__file__).parent / "fixtures" / "test_photo.jpg"

        doc_registry = DocumentRegistry()
        doc_registry.register(DocumentRef(
            id="photo", type="photo", path=str(upload_file),
            mime_type="image/jpeg",             original_filename="test_photo.jpg",
        ))
        executor.set_document_registry(doc_registry)

        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/file_upload.html")
            obs = await observer.observe(page)

            photo = next(
                e for e in obs.page_state.elements
                if e.input_type == "file" and e.html_name == "photo"
            )
            aadhaar = next(
                e for e in obs.page_state.elements
                if e.input_type == "file" and e.html_name == "aadhaar"
            )

            action = BrowserAction(
                action="upload", target_ref=photo.ref,
                document_ref="DOCUMENT.photo",
            )
            result = await executor.execute(page, action, obs, user_confirmed=True)
            assert result.success is True

            # Verify aadhaar input did NOT get the file
            aadhaar_files = await page.evaluate("""(selector) => {
                const input = document.querySelector(selector);
                if (!input || !input.files) return 0;
                return input.files.length;
            }""", f'input[name="{aadhaar.html_name}"]')
            assert aadhaar_files == 0


class TestIframeInteraction:
    """Phase 1 — iframe coverage: observe → interact with iframe content → verify."""

    @pytest.mark.asyncio
    async def test_click_button_inside_iframe(self, settings, executor, observer) -> None:
        """Interact with an element inside an iframe and verify the result."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/iframe.html")
            obs = await observer.observe(page)

            # The iframe content should be observable
            assert len(obs.page_state.frames) >= 1

            # Find and click the button inside the iframe
            frame = page.frames[1]  # First non-main-frame
            frame_btn = await frame.wait_for_selector("#frameButton")
            assert frame_btn is not None

            await frame_btn.click()

            # Verify the button click updated the iframe input
            frame_input_value = await frame.evaluate(
                "document.getElementById('frameInput').value"
            )
            assert frame_input_value == "frame was clicked"

    @pytest.mark.asyncio
    async def test_fill_input_inside_iframe(self, settings, executor, observer) -> None:
        """Fill a text input inside an iframe and verify the value."""
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/iframe.html")

            # Access iframe content directly
            frame = page.frames[1]
            await frame.fill("#frameInput", "Filled from parent")

            # Verify
            value = await frame.input_value("#frameInput")
            assert value == "Filled from parent"

    @pytest.mark.asyncio
    async def test_executor_fills_input_inside_iframe(self, settings, executor, observer) -> None:
        """BrowserExecutor resolves iframe elements via frame_id and fills them.

        This goes through the full BrowserAction + BrowserExecutor pipeline
        (policy → locator → Playwright → verify → re-observe), proving the
        frame-aware LocatorResolver resolves elements inside iframes.
        """
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/iframe.html")
            obs = await observer.observe(page)

            # The iframe input should be observed with frame_id set
            frame_input = next(
                e for e in obs.page_state.elements
                if e.html_name == "frameInput" and e.frame_id is not None
            )
            assert frame_input.frame_id == "f1"

            # Execute fill through the executor — this exercises
            # LocatorResolver._get_resolution_target which resolves
            # against the correct Playwright Frame by frame_id.
            action = BrowserAction(
                action="fill",
                target_ref=frame_input.ref,
                literal_value="Executor fill",
            )
            result = await executor.execute(page, action, obs)
            assert result.success is True
            assert result.verification is not None
            assert result.post_observation is not None

            # Verify the value was actually written into the iframe
            frame = page.frames[1]
            actual = await frame.input_value("#frameInput")
            assert actual == "Executor fill"
