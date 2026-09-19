"""Agent-as-Tool adapter — Phase 10 (implementation_plan.md).

CRITICAL INVARIANTS (Rule 1, 13):
1. Specialists are ADVISORS, never authorities.
2. SpecialistToolAdapter CANNOT set:
   - browser mutation (post_observation is ALWAYS None)
   - authoritative verification (verification_status is ALWAYS None)
   - policy approval (policy_allowed is ALWAYS None)
   - WorldState mutation (WorldState is NOT reachable or mutated)
3. accepts_browser_action is ALWAYS False (rejects any stray BrowserAction fail-closed).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent.specialists.base import SpecialistAgent, get_specialist_audit_log
from app.agent.specialists.context_builder import build_specialist_context
from app.agent.specialists.models import (
    ResultKind,
    SpecialistOutcome,
    SpecialistType,
)
from app.agent.specialists.registry import SpecialistRegistry, get_specialist_registry
from app.agent.tools.base import (
    Concurrency,
    InterruptBehavior,
    PolicyClass,
    Tool,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolResult,
)
from app.agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ==============================================================================
# Specialist Output Wrapper for ToolResult Payload (Rule 2)
# ==============================================================================


class SpecialistToolOutputPayload(BaseModel):
    """Schema-validated payload container for specialist tool results."""

    result_kind: str = Field(default="specialist_analysis")
    specialist_type: str
    permission: str
    outcome: str
    confidence: float
    epistemic_status: str = "inferred"
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


# ==============================================================================
# SpecialistToolAdapter (Agent-as-Tool)
# ==============================================================================


class SpecialistToolAdapter(Tool):
    """Adapts a SpecialistAgent into the standard ToolRegistry interface.

    CRITICAL INVARIANTS:
    - accepts_browser_action = False (rejects any browser mutation attempt).
    - read_only = True.
    - Result normalization explicitly clears post_observation, policy_allowed,
      and verification_status (Rule 13).
    """

    def __init__(self, specialist: SpecialistAgent) -> None:
        self._specialist = specialist
        self.metadata = ToolMetadata(
            name=f"call_{specialist.specialist_type.value}",
            description=(
                f"Consult the isolated {specialist.specialist_type.value} specialist "
                f"({specialist.permission.value}). Returns structured advisory analysis; "
                f"does NOT execute browser mutations or alter state directly."
            ),
            family="agent",
            input_schema=specialist.input_schema,
            output_schema=SpecialistToolOutputPayload,
            read_only=True,
            destructive=False,
            requires_user_interaction=False,
            interrupt_behavior=InterruptBehavior.NONE,
            policy_class=PolicyClass.READ_ONLY,
            concurrency=Concurrency.SHARED,
            accepts_browser_action=False,
        )

    @property
    def specialist(self) -> SpecialistAgent:
        return self._specialist

    async def run(
        self,
        args: BaseModel,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute the adapted specialist within an allowlisted, isolated context.

        Rule 3 & 13:
        1. Context is created via build_specialist_context from allowlisted projections only.
        2. Live ToolContext handles (page, executor) are NOT passed to the specialist.
        3. Normalized ToolResult strictly enforces non-mutating, non-authoritative bounds.
        """
        # Extract safe metadata from ToolContext
        parent_run_id = str(ctx.metadata.get("run_id", ""))
        goal = ctx.metadata.get("goal")
        subgoal = ctx.metadata.get("subgoal")
        world_state = ctx.metadata.get("world_state")
        failure_evidence = ctx.metadata.get("failure_evidence")
        memory_items = ctx.metadata.get("memory_items")
        document_references = ctx.metadata.get("document_references")

        # Build isolated projection context
        spec_context = build_specialist_context(
            parent_run_id=parent_run_id,
            specialist_type=self._specialist.specialist_type,
            parameters=args.model_dump(),
            goal=goal,
            subgoal=subgoal,
            observation=ctx.observation,
            world_state=world_state,
            failure_evidence=failure_evidence,
            memory_items=memory_items,
            document_references=document_references,
            timeout_seconds=self._specialist.default_timeout,
        )

        # Execute isolated specialist
        spec_result = await self._specialist.execute(spec_context)

        # Normalize to ToolResult (Rule 13: cannot set mutation or verification)
        payload = SpecialistToolOutputPayload(
            result_kind=spec_result.result_kind.value,
            specialist_type=spec_result.specialist_type.value,
            permission=spec_result.permission.value,
            outcome=spec_result.outcome.value,
            confidence=spec_result.confidence,
            epistemic_status=spec_result.epistemic_status,
            data=spec_result.data,
            evidence=spec_result.evidence,
            ambiguities=spec_result.ambiguities,
            error_code=spec_result.error_code,
            error_message=spec_result.error_message,
        )

        is_success = spec_result.outcome == SpecialistOutcome.SUCCESS
        msg = (
            f"Specialist {self._specialist.specialist_type.value} completed analysis "
            f"({len(spec_result.evidence)} evidence items)"
            if is_success
            else f"Specialist {self._specialist.specialist_type.value} failed: {spec_result.error_message}"
        )

        tool_result = ToolResult(
            tool_name=self.metadata.name,
            success=is_success,
            error_code=spec_result.error_code,
            message=msg,
            payload=payload.model_dump(),
            observation_id=ctx.observation.observation_id if ctx.observation else "",
            # RULE 13 ENFORCEMENT:
            post_observation=None,      # Never a browser mutation
            policy_allowed=None,        # Never policy authorization
            verification_status=None,   # Never authoritative verification
        )

        return tool_result


# ==============================================================================
# Unified CallSpecialistTool (Dynamic Dispatch)
# ==============================================================================


class CallSpecialistInput(BaseModel):
    """Input parameters for the unified call_specialist tool."""

    specialist_type: str = Field(
        description=(
            "Type of specialist to invoke: 'portal_research', 'form_semantics', "
            "'document', 'recovery', 'verification'"
        ),
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Specialist-specific input parameters",
    )


class CallSpecialistTool(Tool):
    """Unified tool dispatching to registered specialists in SpecialistRegistry.

    Enforces Rule 5 (Authoritative Registry):
    The model may select a registered specialist by type, but CANNOT
    create or modify its permission class or capabilities.
    """

    def __init__(self, registry: SpecialistRegistry | None = None) -> None:
        self._registry = registry or get_specialist_registry()
        self.metadata = ToolMetadata(
            name="call_specialist",
            description=(
                "Invoke a registered specialist advisor agent (portal_research, "
                "form_semantics, document, recovery, verification). Returns structured "
                "advisory analysis; does NOT execute browser mutations or alter state directly."
            ),
            family="agent",
            input_schema=CallSpecialistInput,
            output_schema=SpecialistToolOutputPayload,
            read_only=True,
            destructive=False,
            requires_user_interaction=False,
            interrupt_behavior=InterruptBehavior.NONE,
            policy_class=PolicyClass.READ_ONLY,
            concurrency=Concurrency.SHARED,
            accepts_browser_action=False,
        )

    async def run(
        self,
        args: BaseModel,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        inp = CallSpecialistInput.model_validate(call.arguments or {})
        stype_str = inp.specialist_type

        # Look up registered specialist
        specialist = self._registry.get(stype_str)
        if specialist is None:
            return ToolResult(
                tool_name=self.metadata.name,
                success=False,
                error_code="UNKNOWN_SPECIALIST",
                message=f"Specialist '{stype_str}' is not registered. Available: {[s.value for s in self._registry.list_specialists()]}",
                payload=SpecialistToolOutputPayload(
                    result_kind="specialist_analysis",
                    specialist_type=stype_str,
                    permission="unknown",
                    outcome="failure",
                    confidence=0.0,
                    error_code="UNKNOWN_SPECIALIST",
                    error_message=f"Unknown specialist '{stype_str}'",
                ).model_dump(),
                observation_id=ctx.observation.observation_id if ctx.observation else "",
                post_observation=None,
                policy_allowed=None,
                verification_status=None,
            )

        # Delegate execution through an adapter
        adapter = SpecialistToolAdapter(specialist)
        try:
            param_obj = specialist.input_schema.model_validate(inp.parameters)
        except Exception as e:
            return ToolResult(
                tool_name=self.metadata.name,
                success=False,
                error_code="INPUT_SCHEMA_INVALID",
                message=f"Parameters for specialist '{stype_str}' failed schema validation: {e}",
                payload=SpecialistToolOutputPayload(
                    result_kind="specialist_analysis",
                    specialist_type=stype_str,
                    permission=specialist.permission.value,
                    outcome="validation_failed",
                    confidence=0.0,
                    error_code="INPUT_SCHEMA_INVALID",
                    error_message=str(e),
                ).model_dump(),
                observation_id=ctx.observation.observation_id if ctx.observation else "",
                post_observation=None,
                policy_allowed=None,
                verification_status=None,
            )

        return await adapter.run(param_obj, call, ctx)


# ==============================================================================
# Registry Registration Helper
# ==============================================================================


def register_specialists_in_tool_registry(
    tool_registry: ToolRegistry,
    specialist_registry: SpecialistRegistry | None = None,
) -> None:
    """Register all standard specialist tools into a ToolRegistry.

    Registers:
    - call_specialist (unified dispatcher)
    - call_portal_research
    - call_form_semantics
    - call_document
    - call_recovery
    - call_verification
    """
    from app.agent.specialists.implementations import (
        DocumentAgent,
        FormSemanticsAgent,
        PortalResearchAgent,
        RecoveryAgent,
        VerificationAgent,
    )

    spec_reg = specialist_registry or get_specialist_registry()

    # Ensure canonical specialists are in the SpecialistRegistry
    canonical_agents = [
        PortalResearchAgent(),
        FormSemanticsAgent(),
        DocumentAgent(),
        RecoveryAgent(),
        VerificationAgent(),
    ]

    for agent in canonical_agents:
        if not spec_reg.is_registered(agent.specialist_type):
            spec_reg.register(agent)

    # Register the unified call_specialist tool
    if not tool_registry.get("call_specialist"):
        tool_registry.register(CallSpecialistTool(spec_reg))

    # Register each specialist's dedicated tool adapter
    for stype in spec_reg.list_specialists():
        spec = spec_reg.get(stype)
        if spec is not None:
            tool_name = f"call_{stype.value}"
            if not tool_registry.get(tool_name):
                tool_registry.register(SpecialistToolAdapter(spec))
