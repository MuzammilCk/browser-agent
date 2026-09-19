"""ToolRegistry — Phase 3 model-facing tool catalog + validation gate.

The registry is the ONLY path from a decision to a tool:
    AgentDecision (TOOL_CALL) → ToolRegistry.execute() → ToolResult

Fail-closed guarantees (docs/SECURITY_MODEL.md):
- unknown tool name → TOOL_NOT_FOUND error, never a guess;
- non-browser tool carrying a BrowserAction → INVALID_TOOL errors;
- browser tool without a typed BrowserAction → TOOL_SCHEMA_INVALID;
- missing/stale-context ToolContext → MISSING_CONTEXT error, never execution;
- arguments failing the tool's input schema → TOOL_SCHEMA_INVALID;
- duplicate tool names at registration → ValueError (build-time failure).

The registry never mutates run state and never calls a model: the runtime
owns state (Phase 2), the reasoner arrives in Phase 4.
"""

from __future__ import annotations

import logging
import threading

from app.agent.tools.base import (
    Tool,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Catalog of typed tools + the single fail-closed execution gate."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration / catalog
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool. Duplicate names raise (fail at build time)."""
        with self._lock:
            name = tool.metadata.name
            if name in self._tools:
                raise ValueError(f"Tool already registered: {name}")
            self._tools[name] = tool
            logger.debug("Registered tool: %s (%s)", name, tool.metadata.family)

    def get(self, name: str) -> Tool | None:
        with self._lock:
            return self._tools.get(name)

    def metadata(self, name: str) -> ToolMetadata | None:
        tool = self.get(name)
        return tool.metadata if tool else None

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def catalog(self) -> list[dict]:
        """Model-facing tool catalog (Phase 4 prompt input)."""
        with self._lock:
            return [t.metadata.model_catalog_entry() for t in self._tools.values()]

    def catalog_for_families(self, families: list[str]) -> list[dict]:
        """Catalog filtered to tool families (e.g. read-only specialists)."""
        wanted = set(families)
        with self._lock:
            return [
                t.metadata.model_catalog_entry()
                for t in self._tools.values()
                if t.metadata.family in wanted
            ]

    # ------------------------------------------------------------------
    # Execution — the one gate
    # ------------------------------------------------------------------

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Validate and execute one tool call. Fail closed at every step."""
        tool = self.get(call.tool_name)
        if tool is None:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error_code="TOOL_NOT_FOUND",
                message=f"Unknown tool: {call.tool_name}",
            )

        meta = tool.metadata

        # Only executor-backed tools consume a typed BrowserAction, and
        # for those it is REQUIRED. A stray action on any other tool
        # would smuggle an unvetted execution path past the tool's own
        # schema — rejected either way (fail closed).
        if meta.accepts_browser_action and call.action is None:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error_code="TOOL_SCHEMA_INVALID",
                message=f"Tool {call.tool_name} requires a typed BrowserAction",
            )
        if call.action is not None and not meta.accepts_browser_action:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error_code="INVALID_TOOL_CALL",
                message=f"Tool {call.tool_name} does not accept a BrowserAction",
            )

        # The context must carry a fresh observation for every tool call.
        if ctx.observation is None:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error_code="MISSING_CONTEXT",
                message="ToolContext has no fresh observation",
            )

        # Schema validation (second boundary — the Tool base validates too).
        try:
            schema_fields = set(meta.input_schema.model_fields.keys())
            actual_fields = set((call.arguments or {}).keys())
            extra = actual_fields - schema_fields
            if extra:
                return ToolResult(
                    tool_name=call.tool_name,
                    success=False,
                    error_code="TOOL_SCHEMA_INVALID",
                    message=f"Forbidden/unknown arguments for {call.tool_name}: {sorted(extra)}",
                )
            args = meta.input_schema.model_validate(call.arguments or {})
        except Exception as e:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error_code="TOOL_SCHEMA_INVALID",
                message=f"Arguments failed {call.tool_name} input schema: {e}",
            )

        result = await tool.run(args, call, ctx)

        # Mutating tools must hand back the fresh post-action
        # observation so the next decision targets current browser state.
        if (
            meta.accepts_browser_action
            and not meta.read_only
            and result.success
            and result.post_observation is None
        ):
            logger.warning(
                "Tool %s returned no post_observation for a successful "
                "mutating call — next decision may target stale state",
                call.tool_name,
            )
        return result
