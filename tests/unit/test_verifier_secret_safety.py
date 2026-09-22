"""Phase 15 H1 regression tests — verifier failure messages must never echo values.

Secret-safety: fill/select verifiers compare resolved (possibly vault-sourced)
values against live page values. Before Phase 15, a mismatch formatted both
values into the VerificationResult message, which flows into ToolResult.message
→ model context and traces. These tests lock the shape-only reporting.
"""

from __future__ import annotations

from app.browser.verifiers.base import describe_value_mismatch
from app.browser.verifiers.fill import verify_fill
from app.browser.verifiers.select import verify_select
from app.models.actions import BrowserAction
from app.models.page_state import ElementState, PageState

SECRET = "S3cret-Aadhaar-1234"
OTHER = "wrong-value-on-page"


def _state(target: ElementState) -> PageState:
    return PageState(url="https://portal.test/form", title="t", elements=[target])


def _textbox(ref: str = "e1", value: str | None = None) -> ElementState:
    return ElementState(
        ref=ref, role="textbox", accessible_name="Aadhaar",
        html_name="aadhaar", label_text="Aadhaar", value=value,
        input_type="text",
    )


class TestDescribeValueMismatch:
    def test_message_contains_no_values(self) -> None:
        msg = describe_value_mismatch(SECRET, OTHER)
        assert SECRET not in msg
        assert OTHER not in msg

    def test_message_reports_shape(self) -> None:
        msg = describe_value_mismatch("abcd", "abcdef")
        assert "4 chars" in msg and "6 chars" in msg

    def test_message_handles_unreadable_live_value(self) -> None:
        msg = describe_value_mismatch(SECRET, None)
        assert SECRET not in msg
        assert "unreadable" in msg

    def test_subject_is_included(self) -> None:
        msg = describe_value_mismatch(SECRET, OTHER, subject="Selected option")
        assert "Selected option" in msg
        assert SECRET not in msg


class TestFillVerifierSecretSafety:
    async def test_mismatch_message_withholds_both_values(self, monkeypatch) -> None:
        """The live DOM returns a value different from the resolved secret —
        the failure message must not contain either string."""
        target = _textbox(value=OTHER)
        state = _state(target)

        async def fake_read(page, ref, element):  # noqa: ANN001
            return OTHER

        monkeypatch.setattr("app.browser.verifiers.fill._read_live_value", fake_read)

        action = BrowserAction(
            action="fill", target_ref="e1", literal_value="irrelevant-model-guard",
        )
        result = await verify_fill(
            page=None, action=action, prev=state, curr=state,
            resolved_value=SECRET,
        )
        assert result.status.value == "failure"
        assert SECRET not in result.message
        assert OTHER not in result.message
        assert "withheld" in result.message

    async def test_mismatch_message_withholds_literal_value(self, monkeypatch) -> None:
        """literal_value path (non-vault) is equally withheld — shape only."""
        target = _textbox(value="page-echo")
        state = _state(target)

        async def fake_read(page, ref, element):  # noqa: ANN001
            return "page-echo"

        monkeypatch.setattr("app.browser.verifiers.fill._read_live_value", fake_read)

        action = BrowserAction(action="fill", target_ref="e1", literal_value="expected-text")
        result = await verify_fill(
            page=None, action=action, prev=state, curr=state,
        )
        assert result.status.value == "failure"
        assert "expected-text" not in result.message
        assert "page-echo" not in result.message

    async def test_matching_value_still_succeeds(self, monkeypatch) -> None:
        target = _textbox(value=SECRET)
        state = _state(target)

        async def fake_read(page, ref, element):  # noqa: ANN001
            return SECRET

        monkeypatch.setattr("app.browser.verifiers.fill._read_live_value", fake_read)

        action = BrowserAction(action="fill", target_ref="e1", literal_value="x")
        result = await verify_fill(
            page=None, action=action, prev=state, curr=state,
            resolved_value=SECRET,
        )
        assert result.status.value == "success"
        assert SECRET not in result.message


class TestSelectVerifierSecretSafety:
    async def test_mismatch_message_withholds_option_and_selected(self) -> None:
        target = _textbox(ref="e2", value="leaked-selected")
        target = target.model_copy(update={"selected_options": ["leaked-selected"]})
        state = _state(target)

        action = BrowserAction(action="select", target_ref="e2", option=SECRET)
        result = await verify_select(
            page=None, action=action, prev=state, curr=state,
        )
        assert result.status.value == "failure"
        assert SECRET not in result.message
        assert "leaked-selected" not in result.message
