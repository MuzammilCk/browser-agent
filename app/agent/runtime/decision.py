"""AgentDecision — Phase 2 typed decision contract.

Phase 2 implements the DECISION RECORD only: the schema-validated shape
every future LLM decision must take (AGENTS.md rule 15: every LLM
decision must be schema validated). No reasoning loop, no LLM calls —
the OpenRouter reasoner arrives in Phase 4 and must emit this exact
contract, with the runtime staying authoritative over authorization
(AGENTS.md rule 3: the model proposes; deterministic policy authorizes).

Decision types follow context.md ("Decision types"):
TOOL_CALL, REPLAN, REFLECT, ASK_USER, HANDOFF, COMPLETE.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.actions import BrowserAction


class AgentDecisionType(str, Enum):
    """Decision types the reasoner may emit (context.md)."""

    TOOL_CALL = "tool_call"
    REPLAN = "replan"
    REFLECT = "reflect"
    ASK_USER = "ask_user"
    HANDOFF = "handoff"
    COMPLETE = "complete"


class AgentDecision(BaseModel):
    """One schema-validated decision.

    ``tool_call`` decisions embed a BrowserAction, which carries its own
    validators (stale-ref observation_id, sensitive-value policy), so a
    malformed tool decision fails validation at the contract boundary —
    before any policy or execution layer sees it.

    Phase 2 boundaries:
    - No HANDOFF: specialist agents are Phase 10; accepting one now would
      authorize a concept the runtime cannot yet scope.
    - ``tool_name`` is reserved for Phase 3's Tool Registry; tool_call
      decisions currently carry a BrowserAction, which is what the
      existing executor consumes.
    """

    decision_type: AgentDecisionType
    run_id: str = Field(default="", description="Run this decision belongs to")
    iteration: int = Field(default=0)

    # TOOL_CALL
    action: BrowserAction | None = Field(
        default=None,
        description="Browser action for tool_call decisions (Phase 3 widens to tools)",
    )

    # REPLAN
    plan: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Proposed plan for replan decisions",
    )

    # REFLECT / REPLAN / ASK_USER / COMPLETE
    reason: str = Field(
        default="", description="Why this decision was made or requested"
    )

    # ASK_USER
    question: str = Field(
        default="", description="What the user is being asked"
    )
    interrupt_kind: Literal[
        "user_input", "authentication", "captcha", "confirmation",
        "review", "stall", "error", "unknown",
    ] = Field(
        default="user_input",
        description="Interrupt kind for ask_user decisions",
    )

    # HANDOFF — reserved for Phase 10, deliberately not settable yet.

    # Observability metadata (schema-validated, safe content only)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_id: str = Field(
        default="", description="Unique id assigned by the runtime when recorded"
    )

    @model_validator(mode="after")
    def validate_decision_fields(self) -> AgentDecision:
        """Decision-type-specific required fields (fail closed)."""
        if self.decision_type == AgentDecisionType.TOOL_CALL and self.action is None:
            raise ValueError("tool_call decisions require an action")
        if self.decision_type == AgentDecisionType.ASK_USER and not self.question:
            raise ValueError("ask_user decisions require a question")
        if self.decision_type in (
            AgentDecisionType.REPLAN, AgentDecisionType.REFLECT,
            AgentDecisionType.COMPLETE,
        ) and not self.reason:
            raise ValueError(f"{self.decision_type.value} decisions require a reason")
        return self
