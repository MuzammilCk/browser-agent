"""Memory domain models — Phase 9.

Implements the four clearly separated memory layers:
1. Working Memory: Short-lived bounded state for the current run/turn.
2. Episodic Memory: Meaningful milestone events from completed/ongoing workflows.
3. Semantic Memory: Durable facts and stable domain knowledge with temporal validity and conflict tracking.
4. Experience Memory: Reusable operational lessons from execution and recovery.

Core invariants:
- Memory is supporting context, never browser truth:
  Current Browser Observation > Verified WorldState > Current Runtime State > Current User Input > Durable Semantic Memory > Episodic/Experience Memory > Model Inference.
- Epistemic hierarchy: VERIFIED > OBSERVED > INFERRED > STALE.
- Provenance is mandatory for all persisted items.
- Secrets (passwords, OTPs, PINs, auth credentials, raw document bytes) are strictly prohibited.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "mem") -> str:
    """Generate a prefixed unique identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class MemoryType(str, Enum):
    """The four distinct memory layers."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    EXPERIENCE = "experience"


class EpistemicStatus(str, Enum):
    """Trust level of a memory item.

    VERIFIED: Confirmed by deterministic runtime execution/verification or explicit user profile.
    OBSERVED: Extracted directly from live page state during execution.
    INFERRED: Proposed by model inference or heuristic (unconfirmed).
    STALE: Previously valid or observed, but superseded or no longer active.
    """

    VERIFIED = "verified"
    OBSERVED = "observed"
    INFERRED = "inferred"
    STALE = "stale"


class AuthorType(str, Enum):
    """Origin/creator of a memory proposal or item."""

    USER_EXPLICIT = "user_explicit"
    RUNTIME_VERIFIED = "runtime_verified"
    MODEL_INFERRED = "model_inferred"
    UNTRUSTED_PAGE = "untrusted_page"


class EpisodeOutcome(str, Enum):
    """Execution outcome of a workflow episode."""

    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    ABORTED = "aborted"


class MemoryProvenance(BaseModel):
    """Immutable audit trail for memory items."""

    source: str = Field(description="Origin source (e.g. 'user_dialogue', 'runtime_verification', 'tool_result')")
    author_type: AuthorType = Field(default=AuthorType.RUNTIME_VERIFIED)
    run_id: str = Field(default="", description="Associated agent run ID")
    observation_id: str = Field(default="", description="Observation ID if derived from browser state")
    tool_name: str = Field(default="", description="Tool name if derived from tool execution")
    state_version: int = Field(default=0, description="WorldState version at time of creation")
    timestamp: str = Field(default_factory=utc_now_iso, description="ISO-8601 UTC timestamp")
    details: dict[str, Any] = Field(default_factory=dict, description="Safe audit metadata")


# ── 1. Working Memory ──────────────────────────────────────────────────────────

class WorkingMemory(BaseModel):
    """Short-lived, bounded state needed for the current run/turn.

    Must NOT accumulate unlimited history. Bounded by strict caps.
    """

    goal: str = Field(default="", description="Current primary user goal")
    subgoal: str = Field(default="", description="Current active subgoal")
    verified_facts: dict[str, Any] = Field(
        default_factory=dict,
        description="Key verified facts from AgentWorldState",
    )
    semantic_fields: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Active semantic form fields (summary only)",
    )
    recent_tool_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bounded list of recent sanitized tool results (max 5)",
    )
    recent_failures: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bounded list of recent recovery attempts/failures (max 5)",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="Pending unresolved questions or ambiguities",
    )
    active_interrupt: dict[str, Any] | None = Field(
        default=None,
        description="Current HumanInterrupt state if paused",
    )
    active_approval: dict[str, Any] | None = Field(
        default=None,
        description="Current ApprovalBinding if present",
    )
    conversation_context: list[dict[str, str]] = Field(
        default_factory=list,
        description="Bounded near-term conversation turns (max 10)",
    )
    compacted_summary: str = Field(
        default="",
        description="Compacted summary of prior historical context",
    )
    is_compacted: bool = Field(
        default=False,
        description="True if historical context has undergone compaction",
    )

    # Caps
    max_tool_results: int = Field(default=5)
    max_failures: int = Field(default=5)
    max_conversation_turns: int = Field(default=10)

    def add_tool_result(self, result: dict[str, Any]) -> None:
        """Add a sanitized tool result, keeping the list bounded."""
        self.recent_tool_results.append(result)
        if len(self.recent_tool_results) > self.max_tool_results:
            self.recent_tool_results = self.recent_tool_results[-self.max_tool_results:]

    def add_failure(self, failure: dict[str, Any]) -> None:
        """Add a failure/recovery record, keeping the list bounded."""
        self.recent_failures.append(failure)
        if len(self.recent_failures) > self.max_failures:
            self.recent_failures = self.recent_failures[-self.max_failures:]

    def add_conversation_turn(self, role: str, content: str) -> None:
        """Add a dialogue turn, keeping the list bounded."""
        self.conversation_context.append({"role": role, "content": content})
        if len(self.conversation_context) > self.max_conversation_turns:
            self.conversation_context = self.conversation_context[-self.max_conversation_turns:]

    def total_items_count(self) -> int:
        """Return total active items count to evaluate compaction triggers."""
        return (
            len(self.recent_tool_results)
            + len(self.recent_failures)
            + len(self.conversation_context)
            + len(self.unresolved_questions)
        )


# ── 2. Episodic Memory ─────────────────────────────────────────────────────────

class EpisodicMemory(BaseModel):
    """Record meaningful events from completed/ongoing workflows.

    Captures workflow trajectory milestones rather than raw full transcripts.
    """

    episode_id: str = Field(default_factory=lambda: new_id("ep"))
    run_id: str = Field(description="Run ID that generated this episode")
    portal: str = Field(default="", description="Portal URL or domain")
    goal: str = Field(default="", description="High-level goal of the workflow")
    subgoal: str = Field(default="", description="Specific subgoal or phase")
    summary: str = Field(description="Concise factual narrative of what occurred")
    key_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured key milestones (e.g. form progress, auth challenges, failures)",
    )
    outcome: EpisodeOutcome = Field(default=EpisodeOutcome.SUCCESS)
    provenance: MemoryProvenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── 3. Semantic Memory ─────────────────────────────────────────────────────────

class SemanticMemoryItem(BaseModel):
    """Durable facts and stable knowledge.

    Distinguishes epistemic status (VERIFIED, OBSERVED, INFERRED, STALE) and preserves
    lineage and validity intervals during updates rather than silently overwriting.
    """

    memory_id: str = Field(default_factory=lambda: new_id("sem"))
    subject: str = Field(description="Entity or context identifier (e.g. 'USER.address', 'PORTAL.scholarship')")
    predicate: str = Field(description="Relationship or property (e.g. 'residence_state', 'requires_otp')")
    value: Any = Field(description="Factual value or semantic reference identifier")
    portal: str = Field(default="", description="Portal domain if portal-specific, empty for global user facts")
    user_session_id: str = Field(default="", description="User or session identifier for access scoping")
    provenance: MemoryProvenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    epistemic_status: EpistemicStatus = Field(default=EpistemicStatus.VERIFIED)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    valid_from: str = Field(default_factory=utc_now_iso)
    valid_until: str | None = Field(default=None, description="Expiration or supersession timestamp")
    is_current: bool = Field(default=True, description="False if superseded or invalidated")
    superseded_by: str | None = Field(default=None, description="Memory ID of newer superseding fact")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── 4. Experience Memory ───────────────────────────────────────────────────────

class ExperienceMemory(BaseModel):
    """Reusable lessons from execution and recovery.

    Context-sensitive operational knowledge. Requires repeated verification
    to achieve high confidence; never generalizes an unverified one-off anecdote.
    """

    experience_id: str = Field(default_factory=lambda: new_id("exp"))
    run_id: str = Field(default="", description="Run where lesson was learned")
    portal: str = Field(default="", description="Portal URL or domain")
    task_type: str = Field(default="", description="Task or form category (e.g. 'scholarship_application')")
    trigger_condition: str = Field(
        description="Condition triggering this lesson (e.g. 'stale_reference_on_dropdown_change')",
    )
    recovery_strategy: str = Field(
        description="Effective recovery strategy (e.g. 'reobserve_and_rederive_target')",
    )
    context_features: dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic features (e.g. error code, failure type, layout indicators)",
    )
    outcome: str = Field(default="success", description="Result of applying this strategy")
    success_count: int = Field(default=1, ge=1)
    failure_count: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    provenance: MemoryProvenance
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Proposals & Compaction Audit ───────────────────────────────────────────────

class MemoryCandidate(BaseModel):
    """Memory write proposal prior to deterministic MemoryWritePolicy validation."""

    memory_type: MemoryType
    subject: str = ""
    predicate: str = ""
    value: Any = None
    summary: str = ""
    portal: str = ""
    user_session_id: str = ""
    author_type: AuthorType = AuthorType.MODEL_INFERRED
    source: str = "model_proposal"
    proposed_status: EpistemicStatus = EpistemicStatus.INFERRED
    confidence: float = 0.5
    run_id: str = ""
    observation_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class CompactionRecord(BaseModel):
    """Audit log of a working memory compaction event."""

    compaction_id: str = Field(default_factory=lambda: new_id("cmp"))
    run_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    pre_items_count: int
    post_items_count: int
    preserved_keys: list[str] = Field(default_factory=list)
    compacted_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
