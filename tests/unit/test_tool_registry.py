"""Phase 3 Tool Registry unit tests — protocol, gates, metadata, normalization.

All tests run without a browser: tools that need execution get a stub
executor recording calls and returning canned ActionResults. The point
here is the CONTRACT: fail-closed validation, descriptive metadata,
authoritative policy passthrough, normalized results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pydantic import BaseModel

from app.agent.tools import (
    BROWSER_TOOL_CLASSES,
    USER_TOOL_CLASSES,
    VAULT_TOOL_CLASSES,
    ClickTool,
    FillFieldTool,
    InspectAvailableDocumentsTool,
    ObservePageOutput,
    ObservePageTool,
    PolicyClass,
    RequestConfirmationTool,
    ResolveUserReferenceTool,
    Tool,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    build_registry,
)
from app.browser.executor import ActionResult
from app.browser.verifiers.base import VerificationResult, VerificationStatus
from app.models.actions import BrowserAction
from app.models.page_state import (
    AuthenticationState,
    ElementState,
    PageObservation,
    PageState,
)

# ---------------------------------------------------------------------------
# Fixtures: fake observation + stub executor
# ---------------------------------------------------------------------------


def make_observation(
    *, ref="e1", role="textbox", name="Full Name", observation_id="obs-1",
    auth_detected=False,
) -> PageObservation:
    ps = PageState(
        url="https://uidai.gov.in/form",
        title="Form",
        page_id=observation_id,
        page_type="form",
        elements=[
            ElementState(ref=ref, role=role, accessible_name=name, input_type="text"),
            ElementState(ref="e2", role="button", accessible_name="Next"),
        ],
        authentication=AuthenticationState(detected=auth_detected, challenge_type="otp" if auth_detected else None),
    )
    return PageObservation(page_state=ps, observation_id=observation_id)


def make_ctx(observation=None, **kw) -> ToolContext:
    return ToolContext(
        observation=observation or make_observation(),
        page=kw.get("page", object()),  # stub executor never touches it
        executor=kw.get("executor"),
        observer=kw.get("observer"),
        metadata=kw.get("metadata", {}),
        user_confirmed=kw.get("user_confirmed", False),
    )


@dataclass
class StubExecutor:
    """Records actions and returns canned ActionResults (no Playwright)."""

    result: ActionResult | None = None
    calls: list = field(default_factory=list)

    async def execute(self, page, action, observation, *, user_confirmed=False):
        # Signature must match BrowserExecutor.execute keyword-only tail;
        # positional misroutes would silently return the wrong arity.
        self.calls.append((action, observation.observation_id, user_confirmed))
        if self.result is not None:
            return self.result
        return ActionResult(
            action=action,
            success=True,
            message="ok",
            verification=VerificationResult(
                status=VerificationStatus.SUCCESS, action_type=action.action,
            ),
        )


def ok_result(action, post=None) -> ActionResult:
    return ActionResult(
        action=action,
        success=True,
        message="ok",
        verification=VerificationResult(
            status=VerificationStatus.SUCCESS, action_type=action.action,
        ),
        post_observation=post,
    )


def policy_blocked_result(action, decision_holder: dict | None = None) -> ActionResult:
    from app.policy.engine import PolicyDecision, PolicyResult, RiskLevel

    pr = PolicyResult(
        decision=PolicyDecision.DENY, risk_level=RiskLevel.HIGH_RISK, reason="nope",
    )
    if decision_holder is not None:
        decision_holder["policy"] = pr
    return ActionResult(
        action=action, success=False, message=f"Policy DENIED: {pr.reason}",
        recovery_required=True, policy_result=pr,
    )


def confirmation_result(action) -> ActionResult:
    from app.policy.engine import PolicyDecision, PolicyResult, RiskLevel

    return ActionResult(
        action=action, success=False,
        message="Policy REQUIRE_CONFIRMATION: sensitive",
        recovery_required=True,
        policy_result=PolicyResult(
            decision=PolicyDecision.REQUIRE_CONFIRMATION,
            risk_level=RiskLevel.SENSITIVE, reason="sensitive",
        ),
    )


# ---------------------------------------------------------------------------
# Protocol / base contract
# ---------------------------------------------------------------------------


class _EchoInput(BaseModel):
    text: str


class _EchoOutput(BaseModel):
    echoed: str


class EchoTool(Tool):
    metadata = ToolMetadata(
        name="echo",
        description="test tool",
        family="agent",
        input_schema=_EchoInput,
        output_schema=_EchoOutput,
    )

    async def run(self, args: _EchoInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return self.success(call, _EchoOutput(echoed=args.text), "echoed", ctx=ctx)


class _BrokenOutput(Tool):
    metadata = ToolMetadata(
        name="broken_output",
        description="violates its own output schema",
        family="agent",
        input_schema=_EchoInput,
        output_schema=_EchoOutput,
    )

    async def run(self, args, call, ctx):
        return self.success(call, {"unexpected": "shape"}, "bad")


class TestToolProtocol:
    async def test_validates_arguments_before_run(self):
        tool = EchoTool()
        result = await tool(ToolCall(tool_name="echo", arguments={}), make_ctx())
        assert result.success is False
        assert result.error_code == "invalid_arguments"

    async def test_runs_with_validated_arguments(self):
        tool = EchoTool()
        result = await tool(
            ToolCall(tool_name="echo", arguments={"text": "hi"}), make_ctx(),
        )
        assert result.success is True
        assert result.payload == {"echoed": "hi"}
        assert result.observation_id == "obs-1"

    async def test_output_schema_enforced(self):
        tool = _BrokenOutput()
        with pytest.raises(ValueError, match="output"):
            await tool(ToolCall(tool_name="broken_output", arguments={"text": "x"}), make_ctx())

    def test_metadata_catalog_entry_is_json_safe(self):
        entry = EchoTool().metadata.model_catalog_entry()
        assert entry["name"] == "echo"
        assert "properties" in entry["input_schema"]
        assert entry["policy_class"] == "low"


# ---------------------------------------------------------------------------
# Registry gates
# ---------------------------------------------------------------------------


class TestRegistryGates:
    async def test_unknown_tool_fails_closed(self):
        reg = ToolRegistry()
        result = await reg.execute(ToolCall(tool_name="nope"), make_ctx())
        assert result.success is False
        assert result.error_code == "TOOL_NOT_FOUND"

    def test_duplicate_registration_raises(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(EchoTool())

    async def test_browser_tool_without_action_rejected(self):
        reg = ToolRegistry()
        reg.register(ClickTool())
        result = await reg.execute(ToolCall(tool_name="click", arguments={}), make_ctx())
        assert result.error_code == "TOOL_SCHEMA_INVALID"

    async def test_non_browser_tool_with_action_rejected(self):
        reg = ToolRegistry()
        reg.register(ResolveUserReferenceTool())
        call = ToolCall(
            tool_name="resolve_user_reference",
            arguments={"ref": "USER.full_name"},
            action=BrowserAction(action="click", target_ref="e1"),
        )
        result = await reg.execute(call, make_ctx())
        assert result.error_code == "INVALID_TOOL_CALL"

    async def test_missing_observation_rejected(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        ctx = make_ctx()
        ctx.observation = None
        result = await reg.execute(
            ToolCall(tool_name="echo", arguments={"text": "x"}), ctx,
        )
        assert result.error_code == "MISSING_CONTEXT"

    async def test_schema_invalid_arguments_rejected(self):
        reg = ToolRegistry()
        reg.register(ResolveUserReferenceTool())
        result = await reg.execute(
            ToolCall(tool_name="resolve_user_reference", arguments={}), make_ctx(),
        )
        assert result.error_code == "TOOL_SCHEMA_INVALID"

    def test_catalog_lists_all_registered(self):
        reg = build_registry()
        names = reg.list_names()
        assert "observe_page" in names
        assert "fill_field" in names
        assert "request_confirmation" in names
        assert len(reg.catalog()) == len(names)


# ---------------------------------------------------------------------------
# Browser tool adapters (stub executor — policy/verification passthrough)
# ---------------------------------------------------------------------------


class TestBrowserToolAdapters:
    def _click_tool_call(self, observation_id="obs-1") -> ToolCall:
        return ToolCall(
            tool_name="click",
            arguments={},
            action=BrowserAction(
                action="click", target_ref="e2", observation_id=observation_id,
            ),
        )

    async def test_click_happy_path_normalizes_result(self):
        executor = StubExecutor()
        reg = ToolRegistry()
        reg.register(ClickTool())
        ctx = make_ctx(executor=executor)
        result = await reg.execute(self._click_tool_call(), ctx)
        assert result.success is True
        assert result.verification_status == "success"
        assert result.policy_allowed is None  # stub result had no policy info
        # executor received the typed action + fresh observation id
        assert executor.calls[0][0].action == "click"
        assert executor.calls[0][1] == "obs-1"

    async def test_stale_action_rejected_before_executor(self):
        executor = StubExecutor()
        reg = ToolRegistry()
        reg.register(ClickTool())
        ctx = make_ctx(executor=executor)
        result = await reg.execute(self._click_tool_call(observation_id="obs-OLD"), ctx)
        assert result.success is False
        assert result.error_code == "STALE_OR_INVALID_TARGET"
        assert executor.calls == []  # never reached the browser

    async def test_unknown_ref_rejected_before_executor(self):
        executor = StubExecutor()
        reg = ToolRegistry()
        reg.register(ClickTool())
        ctx = make_ctx(executor=executor)
        call = ToolCall(
            tool_name="click",
            arguments={},
            action=BrowserAction(action="click", target_ref="e999", observation_id="obs-1"),
        )
        result = await reg.execute(call, ctx)
        assert result.error_code == "STALE_OR_INVALID_TARGET"
        assert executor.calls == []

    async def test_action_type_mismatch_rejected(self):
        reg = ToolRegistry()
        reg.register(ClickTool())
        call = ToolCall(
            tool_name="click",
            arguments={},
            action=BrowserAction(action="fill", target_ref="e1", observation_id="obs-1",
                                 literal_value="x"),
        )
        result = await reg.execute(call, make_ctx())
        assert result.error_code == "STALE_OR_INVALID_TARGET"
        assert "mismatch" in result.message

    async def test_policy_denied_maps_to_error_code(self):
        holder: dict = {}
        executor = StubExecutor(result=policy_blocked_result(
            BrowserAction(action="click", target_ref="e2"), holder,
        ))
        reg = ToolRegistry()
        reg.register(ClickTool())
        result = await reg.execute(self._click_tool_call(), make_ctx(executor=executor))
        assert result.success is False
        assert result.error_code == "POLICY_DENIED"
        assert result.policy_allowed is False

    async def test_confirmation_required_surfaces_without_bypass(self):
        executor = StubExecutor(result=confirmation_result(
            BrowserAction(action="fill", target_ref="e1", literal_value="x"),
        ))
        reg = ToolRegistry()
        reg.register(FillFieldTool())
        call = ToolCall(
            tool_name="fill_field",
            arguments={},
            action=BrowserAction(
                action="fill", target_ref="e1", literal_value="x",
                observation_id="obs-1",
            ),
        )
        # Not confirmed → CONFIRMATION_REQUIRED, executor was consulted
        # (the executor owns policy; the tool only normalizes).
        result = await reg.execute(call, make_ctx(executor=executor))
        assert result.error_code == "CONFIRMATION_REQUIRED"
        assert result.success is False

    async def test_mutating_success_requires_post_observation(self):
        post = make_observation(observation_id="obs-2")
        executor = StubExecutor(
            result=ok_result(BrowserAction(action="click", target_ref="e2"), post=post),
        )
        reg = ToolRegistry()
        reg.register(ClickTool())
        ctx = make_ctx(executor=executor)
        result = await reg.execute(self._click_tool_call(), ctx)
        assert result.success is True
        assert result.observation_id == "obs-2"
        assert result.post_observation.observation_id == "obs-2"
        # context observation advanced for the next call
        assert ctx.observation.observation_id == "obs-2"


# ---------------------------------------------------------------------------
# Metadata / permission model
# ---------------------------------------------------------------------------


class TestMetadataPermissionModel:
    def test_every_browser_tool_declares_full_metadata(self):
        for cls in BROWSER_TOOL_CLASSES:
            meta = cls().metadata
            assert meta.name
            assert meta.description
            assert meta.family == "browser"
            assert issubclass(meta.input_schema, BaseModel)
            assert issubclass(meta.output_schema, BaseModel)
            assert isinstance(meta.read_only, bool)
            assert isinstance(meta.destructive, bool)
            assert isinstance(meta.requires_user_interaction, bool)
            assert meta.interrupt_behavior is not None
            assert meta.policy_class is not None
            assert meta.concurrency is not None

    def test_read_only_tools_declared_read_only(self):
        read_only_names = {
            cls().metadata.name
            for cls in BROWSER_TOOL_CLASSES if cls().metadata.read_only
        }
        assert {"observe_page", "inspect_field", "inspect_options",
                "wait_for_state"} <= read_only_names
        # mutating ones must NOT claim read-only
        for mutating in ("click", "fill_field", "select_option", "upload_document",
                         "navigate", "go_back", "scroll", "press_key",
                         "check_control", "uncheck_control"):
            assert mutating not in read_only_names

    def test_user_tools_pause_runs_and_require_interaction(self):
        for cls in USER_TOOL_CLASSES:
            meta = cls().metadata
            assert meta.interrupt_behavior.value == "pauses_run"
            assert meta.requires_user_interaction is True
            assert meta.family == "user"

    def test_sensitive_tools_declare_higher_policy_class(self):
        assert FillFieldTool().metadata.policy_class == PolicyClass.SENSITIVE
        assert RequestConfirmationTool().metadata.policy_class == PolicyClass.HIGH_RISK
        assert ObservePageTool().metadata.policy_class == PolicyClass.READ_ONLY

    def test_vault_tools_are_read_only_and_shared(self):
        for cls in VAULT_TOOL_CLASSES:
            meta = cls().metadata
            assert meta.read_only is True
            assert meta.policy_class == PolicyClass.READ_ONLY
            assert meta.concurrency.value == "shared"

    def test_every_registered_tool_has_unique_name(self):
        reg = build_registry()
        names = reg.list_names()
        assert len(names) == len(set(names))
        # tool count: 14 browser + 3 user + 3 vault
        assert len(names) == 20


# ---------------------------------------------------------------------------
# Vault tools (masked sensitive data)
# ---------------------------------------------------------------------------


class TestVaultTools:
    class _FakeValueResolver:
        def __init__(self, values: dict[str, str]):
            self._values = values

        def resolve(self, ref: str) -> str | None:
            return self._values.get(ref)

    async def test_public_reference_resolves_without_value_leak(self):
        reg = ToolRegistry()
        reg.register(ResolveUserReferenceTool(
            value_resolver=self._FakeValueResolver({"USER.full_name": "Rahul"}),
        ))
        result = await reg.execute(
            ToolCall(tool_name="resolve_user_reference",
                     arguments={"ref": "USER.full_name"}),
            make_ctx(),
        )
        assert result.success is True
        assert result.payload["resolvable"] is True
        assert result.payload["sensitivity"] == "public"
        # The raw value never appears anywhere in the result
        assert "Rahul" not in result.model_dump_json()

    async def test_sensitive_reference_is_masked(self):
        reg = ToolRegistry()
        reg.register(ResolveUserReferenceTool(
            value_resolver=self._FakeValueResolver({"USER.aadhaar_number": "1234"}),
        ))
        result = await reg.execute(
            ToolCall(tool_name="resolve_user_reference",
                     arguments={"ref": "USER.aadhaar_number"}),
            make_ctx(),
        )
        assert result.payload["sensitivity"] == "masked"
        assert result.payload["resolvable"] is True
        assert "1234" not in result.model_dump_json()

    async def test_unknown_reference_fails_closed(self):
        reg = ToolRegistry()
        reg.register(ResolveUserReferenceTool())
        result = await reg.execute(
            ToolCall(tool_name="resolve_user_reference",
                     arguments={"ref": "USER.not_a_field"}),
            make_ctx(),
        )
        assert result.success is False
        assert result.error_code == "UNKNOWN_REFERENCE"

    async def test_document_listing_never_exposes_paths(self, tmp_path):
        from app.vault.resolver import DocumentRef, DocumentRegistry, DocumentResolver

        real_file = tmp_path / "aadhaar.pdf"
        real_file.write_bytes(b"%PDF-1.4 test")
        registry = DocumentRegistry()
        registry.register(DocumentRef(
            id="aadhaar", type="aadhaar", path=str(real_file),
        ))
        reg = ToolRegistry()
        reg.register(InspectAvailableDocumentsTool(
            document_resolver=DocumentResolver(registry),
        ))
        result = await reg.execute(
            ToolCall(tool_name="inspect_available_documents", arguments={}),
            make_ctx(),
        )
        assert result.success is True
        dumped = result.model_dump_json()
        assert str(tmp_path) not in dumped
        assert any(d["ref"] == "DOCUMENT.aadhaar" for d in result.payload["documents"])


# ---------------------------------------------------------------------------
# ToolResult shape stability
# ---------------------------------------------------------------------------


class TestToolResultShape:
    def test_result_fields_are_stable(self):
        fields = set(ToolResult.model_fields.keys())
        assert fields == {
            "tool_name", "success", "error_code", "message", "payload",
            "observation_id", "post_observation", "policy_allowed",
            "verification_status",
        }

    def test_error_result_serializes_without_observation(self):
        r = ToolResult(tool_name="x", success=False, error_code="E", message="m")
        data = r.model_dump(mode="json")
        assert data["post_observation"] is None
        assert data["error_code"] == "E"

    async def test_observe_output_schema_round_trips(self):
        out = ObservePageOutput(url="u", elements=[{"ref": "e1", "role": "textbox"}])
        assert out.model_dump(mode="json")["elements"][0]["ref"] == "e1"
