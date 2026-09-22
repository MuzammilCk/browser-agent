"""Phase 15 H7 regression tests — password field values are masked.

Before H7, a page-rendered (or hostile-page echoed) password field value
flowed unmasked from the DOM extraction into ElementState.value → model
context element previews → world state → stall fingerprints → checkpoints.

Masking now happens at three layers:
1. DOM extraction JS returns '' for password inputs (main page + frames);
2. PageObserver masks any password-typed value in Python (defense in depth);
3. The reasoning context masks password-typed values again at prompt build.
"""

from __future__ import annotations

import pytest

from app.browser.observer import MASKED_PASSWORD_VALUE, PageObserver
from app.models.page_state import (
    ElementState,
    PageObservation,
    PageState,
)


def _raw_element(**overrides) -> dict:
    base = {
        "ref": "e1",
        "role": "textbox",
        "accessible_name": "Password",
        "html_name": "pwd",
        "label_text": "Password",
        "value": "S3cret!Value",
        "input_type": "password",
        "required": True,
        "disabled": False,
        "checked": None,
        "selected_options": [],
        "placeholder": None,
        "autocomplete": "current-password",
        "description": None,
        "visible": True,
        "frame_id": None,
    }
    base.update(overrides)
    return base


class TestObserverMasksPasswordValues:
    def test_password_value_masked_in_element_from_raw(self):
        observer = PageObserver()
        el = observer._element_from_raw(_raw_element())
        assert el.value == MASKED_PASSWORD_VALUE
        assert el.value != "S3cret!Value"

    def test_non_password_value_untouched(self):
        observer = PageObserver()
        el = observer._element_from_raw(
            _raw_element(input_type="text", value="Regular Name")
        )
        assert el.value == "Regular Name"

    def test_empty_password_value_stays_empty(self):
        observer = PageObserver()
        el = observer._element_from_raw(_raw_element(value=""))
        assert el.value == ""

    def test_case_insensitive_password_type(self):
        observer = PageObserver()
        el = observer._element_from_raw(_raw_element(input_type="PASSWORD"))
        assert el.value == MASKED_PASSWORD_VALUE

    def test_password_type_without_value_untouched(self):
        observer = PageObserver()
        el = observer._element_from_raw(_raw_element(value=None))
        assert el.value is None


class TestContextMasksPasswordValues:
    def _observation(self, el: ElementState) -> PageObservation:
        ps = PageState(
            url="https://portal.test/login",
            title="Login",
            elements=[el],
        )
        return PageObservation(page_state=ps, observation_id="obs-1")

    def test_context_masks_password_value_defense_in_depth(self):
        """Even if a value slipped past the observer (e.g. an old
        checkpoint or a hostile extraction path), the context build must
        not put it into the prompt."""
        from app.agent.reasoning.context import build_reasoning_context

        hostile = ElementState(
            ref="e1", role="textbox", accessible_name="Password",
            input_type="password", value="LEAKED-SECRET",
        )
        ctx = build_reasoning_context(
            goal="Log in",
            subgoal="enter credentials",
            observation=self._observation(hostile),
            tool_metadata=[],
            recent_results=[],
            unresolved_questions=[],
        )
        rendered = ctx.render()
        assert "LEAKED-SECRET" not in rendered
        assert "[MASKED]" in rendered

    def test_context_shows_normal_values(self):
        from app.agent.reasoning.context import build_reasoning_context

        normal = ElementState(
            ref="e2", role="textbox", accessible_name="Username",
            input_type="text", value="asha.kumar",
        )
        ctx = build_reasoning_context(
            goal="Log in",
            subgoal="enter credentials",
            observation=self._observation(normal),
            tool_metadata=[],
            recent_results=[],
            unresolved_questions=[],
        )
        assert "asha.kumar" in ctx.render()


class TestDomExtractionMasksPasswords:
    async def test_extraction_script_masks_password_input(self):
        """End-to-end through the real extraction script in local
        Chromium: a pre-filled password input is never extracted."""
        from pathlib import Path

        from app.browser.dom import extract_interactive_elements
        from app.browser.manager import BrowserManager
        from app.config.settings import Settings

        page_path = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
        login_uri = (page_path / "login.html").as_uri()
        if not (page_path / "login.html").exists():
            pytest.skip("login.html fixture not present")

        settings = Settings(headless=True)
        async with BrowserManager(settings) as manager:
            page = await manager.open(login_uri)
            raw_elements = await extract_interactive_elements(page)
        pwd = [
            e for e in raw_elements if e.get("input_type") == "password"
        ]
        assert pwd, "fixture must contain a password field"
        for e in pwd:
            assert e.get("value") in ("", None), e.get("value")
