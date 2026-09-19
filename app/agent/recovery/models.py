"""Phase 7 recovery data models and failure taxonomy (implementation_plan.md).

Defines the structured contracts for:
- Failure taxonomy (13 required failure types)
- Evidence capture
- Bounded recovery budgets
- Reflection result
- Recovery decisions & strategies
- Recovery attempt auditing
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools.base import ToolCall


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FailureType(str, Enum):
    """The 13 canonical failure types required by Phase 7."""

    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    AMBIGUOUS_FIELD = "AMBIGUOUS_FIELD"
    INVALID_OPTION = "INVALID_OPTION"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    STALE_REFERENCE = "STALE_REFERENCE"
    PAGE_CHANGED = "PAGE_CHANGED"
    NAVIGATION_FAILURE = "NAVIGATION_FAILURE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    TOOL_FAILURE = "TOOL_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    TIMEOUT = "TIMEOUT"
    POLICY_DENIED = "POLICY_DENIED"


class RecoveryStrategy(str, Enum):
    """Actions recommended by reflection.

    Reflection NEVER executes tools directly; it chooses a strategy
    that the runtime or caller executes via the standard gates.
    """

    ACQUIRE_FRESH_REF = "acquire_fresh_ref"
    RE_OBSERVE_AND_RETRY = "re_observe_and_retry"
    REVISE_INPUT = "revise_input"
    REPLAN_SUBGOAL = "replan_subgoal"
    REQUEST_USER_INPUT = "request_user_input"
    SURFACE_DENIAL = "surface_denial"
    FAIL_CLOSED = "fail_closed"
    TERMINAL_FAILURE = "terminal_failure"


class FailureEvidence(BaseModel):
    """Safe, structured evidence that triggered the failure."""

    error_code: str = Field(description="Machine-readable error code")
    message: str = Field(default="", description="Safe failure description")
    target_ref: str | None = Field(default=None, description="Ephemeral target element ref")
    semantic_id: str | None = Field(default=None, description="Stable semantic id if known")
    observation_id: str | None = Field(default=None, description="Observation id during failure")
    details: dict[str, Any] = Field(default_factory=dict, description="Safe details (no raw secrets)")


class FailureClassification(BaseModel):
    """Outcome of FailureClassifier analysis."""

    failure_type: FailureType
    evidence: FailureEvidence
    is_retryable: bool = False
    suggested_strategy: RecoveryStrategy


class RecoveryBudget(BaseModel):
    """Configurable boundaries for recovery attempts to prevent runaway loops."""

    max_attempts_per_type: dict[FailureType, int] = Field(
        default_factory=lambda: {
            FailureType.STALE_REFERENCE: 2,
            FailureType.VALIDATION_FAILURE: 2,
            FailureType.TARGET_NOT_FOUND: 2,
            FailureType.INVALID_OPTION: 1,
            FailureType.PAGE_CHANGED: 2,
            FailureType.NAVIGATION_FAILURE: 1,
            FailureType.TIMEOUT: 1,
            FailureType.TOOL_FAILURE: 1,
            FailureType.MODEL_FAILURE: 1,
            FailureType.POLICY_DENIED: 0,
            FailureType.PROMPT_INJECTION: 0,
            FailureType.AMBIGUOUS_FIELD: 0,
            FailureType.AUTHENTICATION_REQUIRED: 0,
        }
    )
    max_attempts_per_subgoal: int = 3
    max_total_attempts: int = 10

    def limit_for(self, failure_type: FailureType) -> int:
        return self.max_attempts_per_type.get(failure_type, 1)


class RecoveryDecision(BaseModel):
    """Concrete next action recommended by reflection.

    Crucial rule: Reflection produces this decision; it does NOT execute tools.
    """

    strategy: RecoveryStrategy
    action_required: str = Field(
        description="One of: re_observe, execute_tool, replan, user_interrupt, stop",
    )
    recommended_tool_call: ToolCall | None = Field(
        default=None,
        description="Fresh typed tool call to execute via ToolRegistry if strategy is retry/fresh ref",
    )
    recommended_subgoal_id: str | None = Field(
        default=None,
        description="Subgoal id to invalidate or revise if strategy is replan",
    )
    pause_for_user: bool = False
    user_interrupt_kind: str | None = None
    user_question: str | None = None
    reason: str = Field(default="", description="Explanation of recovery rationale")
    is_terminal: bool = False


class ReflectionResult(BaseModel):
    """Total result of bounded reflection analysis."""

    failure_type: FailureType
    root_cause: str
    can_recover: bool
    attempt_number: int
    budget_remaining: int
    decision: RecoveryDecision


class RecoveryAttemptRecord(BaseModel):
    """Audit record capturing every recovery attempt.

    Required fields from specification:
    - failure type
    - triggering evidence
    - attempted strategy
    - attempt count
    - resulting ToolResult
    - resulting WorldState change
    """

    attempt_id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:8]}")
    timestamp: str = Field(default_factory=utc_now_iso)
    failure_type: FailureType
    triggering_evidence: dict[str, Any]
    attempted_strategy: RecoveryStrategy
    attempt_count: int
    resulting_tool_result_summary: str | None = None
    resulting_world_state_version_change: tuple[int, int] = (0, 0)
