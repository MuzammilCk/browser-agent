"""Typed tool contract — Phase 3 Tool Registry (implementation_plan.md).

This module is the model-facing tool interface. It deliberately contains
NO execution logic: tools describe what they do, validate their inputs
against strict schemas, and return a normalized ToolResult. Policy stays
in PolicyEngine (authoritative), Playwright stays in BrowserExecutor, and
browser state stays the source of truth (AGENTS.md rules 3, 4).

The most important invariant (user instruction, Phase 3):
    Tool metadata is DESCRIPTIVE — runtime policy is AUTHORITATIVE.
A tool declaring `read_only=True` does not make it read-only; the policy
engine and the underlying executor decide what actually happens. Metadata
feeds the Phase 4 model-facing catalog; it never bypasses PolicyEngine.

Phase 3 boundaries:
- No LLM loop (Phase 4): nothing here calls a model.
- No new policy logic: PolicyEngine is reused as-is (no duplication).
- Tools cannot mutate runtime state directly: they receive a ToolContext
  and may only act on the services it exposes. AgentRunState is never
  reachable from a tool.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.browser.executor import BrowserExecutor
from app.browser.observer import PageObservation, PageObserver
from app.models.actions import BrowserAction


# ============================================================
# Metadata (descriptive — feeds the Phase 4 model catalog)
# ============================================================


class PolicyClass(str, Enum):
    """Descriptive policy hint for a tool.

    This is metadata for the model-facing catalog and defense-in-depth
    checks. The AUTHORITATIVE risk classification still happens in
    PolicyEngine.evaluate() against the concrete BrowserAction + live
    page state — a tool cannot downgrade its own policy by declaring a
    lower class here (docs/SECURITY_MODEL.md: fail closed).
    """

    READ_ONLY = "read_only"
    LOW = "low"
    SENSITIVE = "sensitive"
    AUTHENTICATION = "authentication"
    HIGH_RISK = "high_risk"


class Concurrency(str, Enum):
    """How a tool behaves when runs/iterations overlap."""

    EXCLUSIVE = "exclusive"  # one caller at a time (browser mutation)
    SHARED = "shared"  # safe concurrently (pure reads of local state)
    # Specialists never run concurrently in Phase 3 (one primary agent
    # owns the browser — AGENTS.md rule 9); the slot is for Phase 10.


class InterruptBehavior(str, Enum):
    """What happens to the run when the tool executes."""

    NONE = "none"  # run continues normally
    PAUSES_RUN = "pauses_run"  # run parks until a user decision


class ToolMetadata(BaseModel):
    """Descriptive tool metadata (context.md "Tool families" contract)."""

    name: str = Field(
        description="Stable tool name, snake_case (e.g. 'fill_field')",
    )
    description: str = Field(
        description="One-paragraph model-facing description",
    )
    family: str = Field(
        description="Tool family: browser | user | vault | agent (context.md)",
    )
    input_schema: type[BaseModel] = Field(
        description="Strict pydantic model the tool call arguments must satisfy",
    )
    output_schema: type[BaseModel] = Field(
        description="Strict pydantic model the tool result payload satisfies",
    )
    read_only: bool = Field(
        default=False,
        description="True when the tool never changes browser or local state",
    )
    destructive: bool = Field(
        default=False,
        description="True when the effect is hard to reverse (submission, delete)",
    )
    requires_user_interaction: bool = Field(
        default=False,
        description="True when a human must act for the tool to complete",
    )
    interrupt_behavior: InterruptBehavior = Field(
        default=InterruptBehavior.NONE,
        description="Whether executing this tool pauses the run",
    )
    policy_class: PolicyClass = Field(
        default=PolicyClass.LOW,
        description="Descriptive policy hint — PolicyEngine stays authoritative",
    )
    concurrency: Concurrency = Field(
        default=Concurrency.EXCLUSIVE,
        description="Concurrency semantics for the future scheduler",
    )
    accepts_browser_action: bool = Field(
        default=False,
        description=(
            "True when the tool consumes a typed BrowserAction from the "
            "decision (executor-backed tools). Read-only browser tools "
            "(observe/inspect) and non-browser tools take none."
        ),
    )

    def model_catalog_entry(self) -> dict[str, Any]:
        """JSON-safe catalog entry for the Phase 4 model prompt."""
        return {
            "name": self.name,
            "description": self.description,
            "family": self.family,
            "input_schema": _schema_summary(self.input_schema),
            "output_schema": _schema_summary(self.output_schema),
            "read_only": self.read_only,
            "destructive": self.destructive,
            "requires_user_interaction": self.requires_user_interaction,
            "interrupt_behavior": self.interrupt_behavior.value,
            "policy_class": self.policy_class.value,
            "concurrency": self.concurrency.value,
        }


def _schema_summary(schema: type[BaseModel]) -> dict[str, Any]:
    """Compact, prompt-friendly JSON-schema summary of a pydantic model."""
    json_schema = schema.model_json_schema()
    return {
        "type": "object",
        "properties": json_schema.get("properties", {}),
        "required": json_schema.get("required", []),
    }


# ============================================================
# Input / output contracts
# ============================================================


class ToolCall(BaseModel):
    """One schema-validated tool invocation.

    Phase 3 note: a ToolCall is the Registry's view of the decision.
    AgentDecision.TOOL_CALL carries tool_name + arguments (and, for
    browser tools, a validated BrowserAction); the registry re-validates
    everything here — schema validation happens at BOTH boundaries and
    the registry is fail-closed (AGENTS.md rule 15).
    """

    tool_name: str = Field(description="Registered tool name")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments validated against the tool's input_schema",
    )
    action: BrowserAction | None = Field(
        default=None,
        description="Typed browser action for browser-family tools",
    )
    reason: str = Field(
        default="", description="Why the model chose this tool (audit trail)",
    )


class ToolResult(BaseModel):
    """Normalized result of one tool invocation.

    Stable shape for every tool family — the Phase 4 reasoner never
    needs bespoke parsing per tool. Content rules:
    - success=False carries a machine-readable error_code.
    - No raw secrets, OTPs, passwords, or document contents (payloads
      hold references and metadata only — docs/SECURITY_MODEL.md).
    - post_observation carries the fresh browser state after mutating
      tools so the next decision is grounded in the CURRENT page.
    """

    tool_name: str
    success: bool = False
    error_code: str | None = Field(
        default=None,
        description="Machine-readable failure code (None on success)",
    )
    message: str = Field(default="", description="Human-readable summary")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Output-schema-validated tool output (safe content only)",
    )
    observation_id: str = Field(
        default="",
        description="Fresh observation this result is grounded in ('' if none)",
    )
    post_observation: PageObservation | None = Field(
        default=None,
        description="Fresh page observation after a mutating tool (stale-ref guard)",
    )
    policy_allowed: bool | None = Field(
        default=None,
        description="Authoritative PolicyEngine decision for browser tools",
    )
    verification_status: str | None = Field(
        default=None,
        description="Executor verification status (success/failure/uncertain)",
    )

    def summary(self) -> str:
        """One-line model/log summary."""
        head = f"{self.tool_name}: {'ok' if self.success else f'error/{self.error_code}'}"
        return f"{head} — {self.message}" if self.message else head


# ── Shared output models (strict tool output schemas) ──────────


class ElementSummary(BaseModel):
    """Model-facing element summary (safe content only)."""

    ref: str
    role: str | None = None
    name: str | None = Field(
        default=None, description="accessible_name > label_text > html_name",
    )
    value: str | None = None
    input_type: str | None = None
    required: bool = False
    disabled: bool = False
    checked: bool | None = None
    selected_options: list[str] = Field(default_factory=list)
    frame_id: str | None = None


class ObservePageOutput(BaseModel):
    """observe_page output: current page at the ref/semantic level."""

    url: str = ""
    title: str = ""
    page_type: str = "unknown"
    observation_id: str = ""
    elements: list[ElementSummary] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    open_tabs: int = 1
    auth_detected: bool = False
    auth_challenge_type: str | None = None


class InspectFieldOutput(BaseModel):
    """inspect_field output: one element in depth."""

    found: bool = False
    element: ElementSummary | None = None
    validation_errors: list[str] = Field(default_factory=list)


class InspectOptionsOutput(BaseModel):
    """inspect_options output: options of one select element."""

    found: bool = False
    options: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)


class NavigateOutput(BaseModel):
    """navigate output."""

    url: str = ""
    page_type: str = "unknown"


class GoBackOutput(BaseModel):
    """go_back output."""

    url: str = ""


class RequestUserOutput(BaseModel):
    """request_* tool output: what the user must do."""

    interrupt_kind: str = "user_input"
    question: str = ""
    description: str = ""


class ResolveReferenceOutput(BaseModel):
    """resolve_*_reference output.

    Sensitive references resolve to a RESOLUTION HANDLE, never the raw
    value — the executor re-resolves locally at execution time
    (docs/SECURITY_MODEL.md sensitive-data path).
    """

    ref: str = ""
    resolvable: bool = False
    sensitivity: str = "unknown"
    display_name: str = ""
    resolution_hint: str = Field(
        default="",
        description="How the value will be used (e.g. 'resolved at execution time')",
    )


class InspectDocumentsOutput(BaseModel):
    """inspect_available_documents output (metadata only, never contents)."""

    documents: list[dict[str, str]] = Field(default_factory=list)


# ============================================================
# Execution context — the ONLY handle a tool gets
# ============================================================


@dataclass
class ToolContext:
    """Everything a tool may touch — nothing else.

    The runtime hands the context in per call. There is deliberately no
    path from a tool to AgentRunState: tools cannot mutate run state,
    lifecycle, events, or checkpoints directly (user instruction: tools
    must not mutate state outside the runtime). The runtime observes the
    ToolResult and updates state itself.

    observation is REQUIRED and fresh: the registry rejects execution
    when it is missing, and mutating tools replace it with the executor's
    post_observation so the next tool call targets current browser state.
    """

    observation: PageObservation
    page: Any = None  # Playwright Page (execution-time; injected by runtime)
    executor: BrowserExecutor | None = None
    observer: PageObserver | None = None
    # Optional extras for vault/user tools (read-only resolvers)
    value_resolver: Any = None  # ValueResolver
    document_resolver: Any = None  # DocumentResolver
    reference_registry: Any = None  # ReferenceRegistry
    # Set by the ToolRegistryExecutor when the user has explicitly
    # approved THIS exact call through the confirmation flow.
    user_confirmed: bool = False
    # Free, safe metadata (run_id, iteration) for audit records only
    metadata: dict[str, Any] = field(default_factory=dict)

    def require_executor(self) -> BrowserExecutor:
        if self.executor is None:
            raise ValueError("ToolContext has no executor (browser tools unavailable)")
        return self.executor

    def require_page(self) -> Any:
        if self.page is None:
            raise ValueError("ToolContext has no page (browser tools unavailable)")
        return self.page

    @property
    def page_state(self):
        return self.observation.page_state


# Tool implementation signature: async (call, ctx) -> ToolResult
ToolHandler = Callable[[ToolCall, ToolContext], Awaitable[ToolResult]]


# ============================================================
# Tool base class
# ============================================================


class Tool(ABC):
    """Base class for every registered tool.

    Subclasses define metadata + schemas and implement ``run``. The base
    class implements the shared template: validate → execute → normalize,
    so no tool can skip schema validation or return an ad-hoc shape.
    """

    metadata: ToolMetadata

    async def __call__(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Template method: schema validation → execution → normalization.

        Schema validation happens HERE and again in ToolRegistry.execute
        (defense in depth — AGENTS.md rule 15, fail closed). A tool is
        therefore incapable of consuming unvalidated arguments even if a
        future caller forgets the registry.
        """
        try:
            args = self.metadata.input_schema.model_validate(call.arguments or {})
        except Exception as e:
            return self.error(
                call, "invalid_arguments",
                f"Arguments failed {self.metadata.name} input schema: {e}",
            )
        return await self.run(args, call, ctx)

    @abstractmethod
    async def run(
        self, args: BaseModel, call: ToolCall, ctx: ToolContext,
    ) -> ToolResult:
        """Execute with validated arguments. Return a normalized ToolResult."""

    # -- result helpers (keep shapes identical across tools) ------------

    def success(
        self, call: ToolCall, payload: dict[str, Any] | BaseModel, message: str = "",
        *, ctx: ToolContext | None = None,
    ) -> ToolResult:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        result = ToolResult(
            tool_name=self.metadata.name,
            success=True,
            message=message,
            payload=data,
        )
        _validate_payload(self.metadata, data, call)
        if ctx is not None and ctx.observation is not None:
            result.observation_id = ctx.observation.observation_id
        return result

    def error(
        self, call: ToolCall, code: str, message: str,
        *, ctx: ToolContext | None = None,
    ) -> ToolResult:
        result = ToolResult(
            tool_name=self.metadata.name,
            success=False,
            error_code=code,
            message=message,
        )
        if ctx is not None and ctx.observation is not None:
            result.observation_id = ctx.observation.observation_id
        return result


def _validate_payload(metadata: ToolMetadata, data: dict, call: ToolCall) -> None:
    """Enforce the declared output schema (fail closed on malformed output)."""
    try:
        metadata.output_schema.model_validate(data)
    except Exception as e:
        raise ValueError(
            f"Tool {metadata.name} produced output violating its schema: {e}"
        ) from e
