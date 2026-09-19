"""Browser tools — Phase 3 adapters over the EXISTING browser foundation.

Every mutating tool delegates to BrowserExecutor.execute(), which already
runs: stale-ref check → PolicyEngine → document policy → Playwright →
re-observe → ActionVerifier. This module intentionally contains NO policy
logic, NO verification logic, and NO Playwright calls of its own
(reuse, don't replace — AGENTS.md). Read tools reuse PageObserver and
BrowserManager (trusted-domain gate).

Invariants encoded here:
- Tools never touch Playwright directly; execution goes through the
  executor so policy + verification cannot be bypassed by construction.
- Mutating tools return the executor's fresh post_observation so the next
  decision targets current browser state (AGENTS.md rule 10).
- ToolResults carry safe metadata only — never resolved secret values
  (the executor's resolved_value audit field is not copied into payloads).
- A REFRESHED failure (verification failed after the page actually
  changed) still updates the context observation: the page state changed
  even though the goal failed, and pretending otherwise poisons the next
  decision (AGENTS.md rule 4: browser state is the source of truth).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.agent.tools.base import (
    Concurrency,
    GoBackOutput,
    InspectFieldOutput,
    InspectOptionsOutput,
    NavigateOutput,
    ObservePageOutput,
    PolicyClass,
    Tool,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolResult,
)
from app.browser.executor import ActionResult
from app.browser.manager import DomainAccessError
from app.models.actions import BrowserAction
from app.models.page_state import ElementState, PageObservation

logger = logging.getLogger(__name__)


# ============================================================
# Input schemas (strict, model-facing)
# ============================================================


class ObservePageInput(BaseModel):
    """observe_page takes no arguments — observing is always safe."""


class InspectFieldInput(BaseModel):
    ref: str = Field(min_length=1, description="Element ref from the observation")


class InspectOptionsInput(BaseModel):
    ref: str = Field(min_length=1, description="Select element ref")


class NavigateInput(BaseModel):
    url: str = Field(min_length=1, description="Full URL on a trusted government domain")


class ClickInput(BaseModel):
    """Arguments are descriptive; the authoritative target lives in the
    typed BrowserAction (target_ref + observation_id)."""


class FillFieldInput(BaseModel):
    """value_ref/literal_value choice is validated by BrowserAction itself
    (including the sensitive-literal policy)."""


class SelectOptionInput(BaseModel):
    option_note: str = Field(
        default="", description="Why this option was chosen (audit trail)",
    )


class CheckControlInput(BaseModel):
    pass


class UploadDocumentInput(BaseModel):
    document_ref: str = Field(
        min_length=1,
        description="Semantic document reference (e.g. 'DOCUMENT.aadhaar')",
    )


class ScrollInput(BaseModel):
    direction: str = Field(
        default="down", description="up | down | left | right",
    )


class PressKeyInput(BaseModel):
    key_note: str = Field(default="", description="Why this key press is needed")


class WaitForStateInput(BaseModel):
    reason: str = Field(default="", description="What the agent is waiting for")


class GoBackInput(BaseModel):
    pass


# ============================================================
# Shared adapter plumbing
# ============================================================


def _element_summary(el: ElementState) -> dict:
    return {
        "ref": el.ref,
        "role": el.role,
        "name": el.name,
        "value": el.value,
        "input_type": el.input_type,
        "required": el.required,
        "disabled": el.disabled,
        "checked": el.checked,
        "selected_options": list(el.selected_options),
        "frame_id": el.frame_id,
    }


def _validate_ref_in_observation(ref: str, ctx: ToolContext) -> str | None:
    """Fail closed on refs that are not in the fresh observation."""
    for el in ctx.page_state.elements:
        if el.ref == ref:
            return None
    return f"Element {ref} not in current observation — re-observe first"


def _same_page(prev: PageObservation, post: PageObservation) -> bool:
    """True when the post-action observation still describes the same
    in-page context (same URL, same element refs). Only then does the
    pre-action observation remain valid for the next decision."""
    a, b = prev.page_state, post.page_state
    if a.url != b.url:
        return False
    if {e.ref for e in a.elements} != {e.ref for e in b.elements}:
        return False
    return True


class _BrowserTool(Tool):
    """Shared behavior for executor-backed tools."""

    family = "browser"

    def _error(self, call: ToolCall, ctx: ToolContext, code: str, message: str) -> ToolResult:
        return self.error(call, code, message, ctx=ctx)

    def _from_action_result(
        self, call: ToolCall, ctx: ToolContext, result: ActionResult, ok_message: str,
    ) -> ToolResult:
        """Normalize an ActionResult into a ToolResult.

        The raw executor message is carried in payload (it may mention the
        action/target — safe metadata), while the ToolResult.message is a
        short stable summary. Policy + verification facts are promoted to
        first-class fields because the Phase 4 reasoner must see them.
        """
        policy = result.policy_result
        verification = result.verification
        if result.success:
            payload = {
                "executor_message": result.message,
                "tab_switched": result.tab_switch is not None,
            }
            if ctx.observation is not None and result.post_observation is not None:
                payload["refreshed_observation"] = not _same_page(
                    ctx.observation, result.post_observation,
                )
            return ToolResult(
                tool_name=self.metadata.name,
                success=True,
                message=ok_message,
                payload=payload,
                observation_id=(
                    result.post_observation.observation_id
                    if result.post_observation is not None
                    else ctx.observation.observation_id
                ),
                post_observation=result.post_observation,
                policy_allowed=policy.allowed if policy else None,
                verification_status=(
                    verification.status.value if verification else None
                ),
            )
        # Failure path: classify machine-readable error codes.
        message = result.message
        if result.user_action_required or (policy and policy.needs_user):
            code = "USER_ACTION_REQUIRED"
        elif policy and policy.needs_confirmation and not ctx.user_confirmed:
            code = "CONFIRMATION_REQUIRED"
        elif policy and policy.blocked:
            code = "POLICY_DENIED"
        elif result.verification is not None:
            code = "VERIFICATION_FAILED"
        elif result.recovery_required:
            code = "EXECUTION_FAILED"
        else:
            code = "EXECUTION_FAILED"
        return ToolResult(
            tool_name=self.metadata.name,
            success=False,
            error_code=code,
            message=message,
            payload={"executor_message": result.message},
            observation_id=ctx.observation.observation_id,
            post_observation=result.post_observation,
            policy_allowed=(not policy.blocked) if policy else None,
            verification_status=(
                verification.status.value if verification else None
            ),
        )


class _MutatingBrowserTool(_BrowserTool):
    """Executes a typed BrowserAction through the shared executor path."""

    action_type: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Executor-backed tools consume the decision's typed action.
        if cls.metadata is not None and getattr(cls.metadata, "family", "") == "browser":
            cls.metadata = cls.metadata.model_copy(
                update={"accepts_browser_action": True},
            )

    action_type: str = ""

    def _validate(self, call: ToolCall, ctx: ToolContext) -> str | None:
        action = call.action
        if action is None:  # registry enforces this; belt and suspenders
            return "missing typed BrowserAction"
        if action.action != self.action_type:
            return (
                f"action type mismatch: tool {self.metadata.name} "
                f"expects action='{self.action_type}', got '{action.action}'"
            )
        if action.target_ref:
            if not action.observation_id:
                return "action carries no observation_id (stale-ref guard)"
            if action.observation_id != ctx.observation.observation_id:
                return (
                    f"stale reference: action targets observation "
                    f"{action.observation_id}, context holds "
                    f"{ctx.observation.observation_id}"
                )
            return _validate_ref_in_observation(action.target_ref, ctx)
        return None

    async def run(self, args, call: ToolCall, ctx: ToolContext) -> ToolResult:
        invalid = self._validate(call, ctx)
        if invalid:
            return self._error(call, ctx, "STALE_OR_INVALID_TARGET", invalid)
        executor = ctx.require_executor()
        page = ctx.require_page()
        try:
            result = await executor.execute(
                page, call.action, ctx.observation,
                user_confirmed=ctx.user_confirmed,
            )
        except Exception as e:  # executor already converts its own errors
            return self._error(call, ctx, "EXECUTION_FAILED", f"Execution error: {e}")
        # Keep the context's observation current for the NEXT tool call.
        if result.post_observation is not None:
            ctx.observation = result.post_observation
        return self._from_action_result(call, ctx, result, ok_message=result.message)


# ============================================================
# Read-only browser tools
# ============================================================


class ObservePageTool(_BrowserTool):
    """Fresh observation of the current page (safe, repeatable)."""

    metadata = ToolMetadata(
        name="observe_page",
        description=(
            "Observe the current browser page: interactive elements with "
            "ephemeral refs, validation errors, alerts, tabs, and auth "
            "challenge state. Use before acting and after any page change."
        ),
        family="browser",
        input_schema=ObservePageInput,
        output_schema=ObservePageOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.EXCLUSIVE,
    )

    async def run(self, args, call: ToolCall, ctx: ToolContext) -> ToolResult:
        observer = ctx.observer
        page = ctx.require_page()
        if observer is None:
            return self._error(call, ctx, "MISSING_CONTEXT", "ToolContext has no observer")
        try:
            fresh = await observer.observe(page)
        except Exception as e:
            return self._error(call, ctx, "OBSERVATION_FAILED", f"Observation failed: {e}")
        ctx.observation = fresh
        return self._observe_payload(call, ctx, fresh)

    def _observe_payload(
        self, call: ToolCall, ctx: ToolContext, obs: PageObservation,
    ) -> ToolResult:
        ps = obs.page_state
        output = ObservePageOutput(
            url=ps.url,
            title=ps.title,
            page_type=ps.page_type,
            observation_id=obs.observation_id,
            elements=[_element_summary(e) for e in ps.elements if e.visible],
            validation_errors=[
                f"{v.target_ref}: {v.message}" for v in ps.validation_errors if v.visible
            ],
            alerts=[a.text or a.name or a.ref for a in ps.alerts if a.visible],
            open_tabs=ps.tabs.total,
            auth_detected=ps.authentication.detected,
            auth_challenge_type=ps.authentication.challenge_type,
        )
        return self.success(call, output, f"Observed {ps.page_type} page ({ps.url})", ctx=ctx)


class InspectFieldTool(_BrowserTool):
    """Detailed view of one element from the current observation."""

    metadata = ToolMetadata(
        name="inspect_field",
        description=(
            "Inspect one element in depth: role, names, value, required, "
            "disabled, checked state, selected options, frame, and any "
            "validation errors attached to it. Read-only."
        ),
        family="browser",
        input_schema=InspectFieldInput,
        output_schema=InspectFieldOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.EXCLUSIVE,
    )

    async def run(self, args: InspectFieldInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        invalid = _validate_ref_in_observation(args.ref, ctx)
        if invalid:
            return self._error(call, ctx, "STALE_OR_INVALID_TARGET", invalid)
        el = next(e for e in ctx.page_state.elements if e.ref == args.ref)
        errors = [
            v.message or "validation error"
            for v in ctx.page_state.validation_errors
            if v.target_ref == args.ref and v.visible
        ]
        output = InspectFieldOutput(found=True, element=_element_summary(el), validation_errors=errors)
        return self.success(call, output, f"Inspected {args.ref} ({el.role})", ctx=ctx)


class InspectOptionsTool(_BrowserTool):
    """Options of one select element, read from the live DOM."""

    metadata = ToolMetadata(
        name="inspect_options",
        description=(
            "List the options of a select/dropdown element (reads the live "
            "DOM: value + label per option) with the currently selected "
            "ones. Read-only."
        ),
        family="browser",
        input_schema=InspectOptionsInput,
        output_schema=InspectOptionsOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.EXCLUSIVE,
    )

    async def run(self, args: InspectOptionsInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        invalid = _validate_ref_in_observation(args.ref, ctx)
        if invalid:
            return self._error(call, ctx, "STALE_OR_INVALID_TARGET", invalid)
        el = next(e for e in ctx.page_state.elements if e.ref == args.ref)
        page = ctx.require_page()
        options, selected = await self._read_options(page, ctx, el)
        if options is None:
            return self._error(
                call, ctx, "EXECUTION_FAILED",
                f"Element {args.ref} is not a select (role={el.role})",
            )
        output = InspectOptionsOutput(found=True, options=options, selected=selected)
        return self.success(call, output, f"{len(options)} options for {args.ref}", ctx=ctx)

    async def _read_options(self, page, ctx: ToolContext, el: ElementState):
        """DOM-read the options; returns (options, selected) or (None, None)."""
        js = """
        (el) => {
            if (!el || el.tagName !== 'SELECT') return null;
            return {
                options: Array.from(el.options).map(o => ({
                    value: o.value, text: o.textContent.trim(),
                    selected: o.selected, disabled: o.disabled,
                })),
            };
        }
        """
        try:
            locator = await ctx.require_executor().locator_resolver.resolve(
                page, el.ref, ctx.page_state,
            )
            if locator is None:
                return None, None
            data = await locator.evaluate(js)
        except Exception as e:
            logger.debug("inspect_options read failed for %s: %s", el.ref, e)
            return None, None
        if data is None:
            return None, None
        options = [
            f"{o['text']}" + (f" [value={o['value']}]" if o["value"] != o["text"] else "")
            for o in data["options"]
        ]
        selected = [o["text"] for o in data["options"] if o["selected"]]
        return options, selected


class WaitForStateTool(_BrowserTool):
    """Bounded wait for page load; observation is refreshed afterwards."""

    metadata = ToolMetadata(
        name="wait_for_state",
        description=(
            "Wait briefly for the page to finish loading/navigation, then "
            "return a fresh observation. Use after navigation or dynamic "
            "updates. Read-only (no state change of its own)."
        ),
        family="browser",
        input_schema=WaitForStateInput,
        output_schema=ObservePageOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.EXCLUSIVE,
    )

    async def run(self, args: WaitForStateInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        page = ctx.require_page()
        observer = ctx.observer
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception as e:
            logger.debug("wait_for_state timeout: %s", e)
        if observer is None:
            return self._error(call, ctx, "MISSING_CONTEXT", "ToolContext has no observer")
        fresh = await observer.observe(page)
        ctx.observation = fresh
        result = self._observe_payload(call, ctx, fresh)
        result.tool_name = self.metadata.name
        result.message = f"Waited; page is {fresh.page_state.page_type}"
        return result


class NavigateTool(_BrowserTool):
    """Navigate to a trusted government URL via BrowserManager's gate."""

    metadata = ToolMetadata(
        name="navigate",
        description=(
            "Navigate the current tab to a URL on a trusted government "
            "domain. Untrusted domains are rejected by the trusted-domain "
            "registry — navigation cannot bypass it."
        ),
        family="browser",
        input_schema=NavigateInput,
        output_schema=NavigateOutput,
        read_only=False,
        policy_class=PolicyClass.LOW,
        concurrency=Concurrency.EXCLUSIVE,
    )

    async def run(self, args: NavigateInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        parsed = urlparse(args.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self._error(call, ctx, "INVALID_URL", f"Not a valid http(s) URL: {args.url}")
        manager = ctx.metadata.get("browser_manager")
        if manager is None:
            return self._error(
                call, ctx, "MISSING_CONTEXT",
                "No BrowserManager in ToolContext metadata — navigation unavailable",
            )
        try:
            page = await manager.open(args.url)
        except DomainAccessError as e:
            return self._error(call, ctx, "UNTRUSTED_DOMAIN", str(e))
        except Exception as e:
            return self._error(call, ctx, "NAVIGATION_FAILED", f"Navigation failed: {e}")
        ctx.page = page
        observer = ctx.observer
        if observer is None:
            return self._error(call, ctx, "MISSING_CONTEXT", "ToolContext has no observer")
        fresh = await observer.observe(page)
        ctx.observation = fresh
        ps = fresh.page_state
        output = NavigateOutput(url=ps.url, page_type=ps.page_type)
        result = self.success(call, output, f"Navigated to {ps.url}", ctx=ctx)
        result.observation_id = fresh.observation_id
        result.post_observation = fresh
        return result


# ============================================================
# Mutating browser tools
# ============================================================


class ClickTool(_MutatingBrowserTool):
    action_type = "click"
    metadata = ToolMetadata(
        name="click",
        description=(
            "Click the element with the given ref (button, link, control). "
            "The page is re-observed and the click verified afterwards."
        ),
        family="browser",
        input_schema=ClickInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class FillFieldTool(_MutatingBrowserTool):
    action_type = "fill"
    metadata = ToolMetadata(
        name="fill_field",
        description=(
            "Fill the field with the given ref. Provide value_ref for "
            "vault-backed semantic references (sensitive data never passes "
            "through the model) or literal_value for non-sensitive values. "
            "The fill is verified against the live DOM afterwards."
        ),
        family="browser",
        input_schema=FillFieldInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.SENSITIVE,
    )


class SelectOptionTool(_MutatingBrowserTool):
    action_type = "select"
    metadata = ToolMetadata(
        name="select_option",
        description=(
            "Select an option in the dropdown with the given ref. The "
            "match is label/value/fuzzy-robust; verified afterwards."
        ),
        family="browser",
        input_schema=SelectOptionInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class CheckControlTool(_MutatingBrowserTool):
    action_type = "check"
    metadata = ToolMetadata(
        name="check_control",
        description="Check a checkbox or radio control with the given ref.",
        family="browser",
        input_schema=CheckControlInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class UncheckControlTool(_MutatingBrowserTool):
    action_type = "uncheck"
    metadata = ToolMetadata(
        name="uncheck_control",
        description="Uncheck a checkbox with the given ref.",
        family="browser",
        input_schema=CheckControlInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class UploadDocumentTool(_MutatingBrowserTool):
    action_type = "upload"
    metadata = ToolMetadata(
        name="upload_document",
        description=(
            "Upload a document resolved locally from a semantic "
            "document_ref (raw filesystem paths are not accepted; "
            "document policy validates the file before upload)."
        ),
        family="browser",
        input_schema=UploadDocumentInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.SENSITIVE,
    )


class ScrollTool(_MutatingBrowserTool):
    action_type = "scroll"
    metadata = ToolMetadata(
        name="scroll",
        description="Scroll the page one step in a direction (up/down/left/right).",
        family="browser",
        input_schema=ScrollInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class PressKeyTool(_MutatingBrowserTool):
    action_type = "press"
    metadata = ToolMetadata(
        name="press_key",
        description="Press a keyboard key (optionally focused on an element ref).",
        family="browser",
        input_schema=PressKeyInput,
        output_schema=ObservePageOutput,
        policy_class=PolicyClass.LOW,
    )


class GoBackTool(_BrowserTool):
    """go_back delegates to the executor and refreshes the observation."""

    metadata = ToolMetadata(
        name="go_back",
        description="Navigate back in the browser history, then re-observe.",
        family="browser",
        input_schema=GoBackInput,
        output_schema=GoBackOutput,
        policy_class=PolicyClass.LOW,
    )

    async def run(self, args: GoBackInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        action = BrowserAction(action="go_back")
        executor = ctx.require_executor()
        page = ctx.require_page()
        try:
            result = await executor.execute(page, action, ctx.observation)
        except Exception as e:
            return self._error(call, ctx, "EXECUTION_FAILED", f"Execution error: {e}")
        if result.post_observation is not None:
            ctx.observation = result.post_observation
        normalized = self._from_action_result(call, ctx, result, ok_message=result.message)
        if result.success and result.post_observation is not None:
            normalized.payload["url"] = result.post_observation.page_state.url
        return normalized


BROWSER_TOOL_CLASSES = [
    ObservePageTool,
    InspectFieldTool,
    InspectOptionsTool,
    NavigateTool,
    WaitForStateTool,
    ClickTool,
    FillFieldTool,
    SelectOptionTool,
    CheckControlTool,
    UncheckControlTool,
    UploadDocumentTool,
    ScrollTool,
    PressKeyTool,
    GoBackTool,
]
