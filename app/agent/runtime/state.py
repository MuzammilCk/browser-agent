"""Agent run state — Phase 2 persistent runtime state model.

Phase 2 establishes the persistent AgentRuntime without the LLM reasoning
loop (implementation_plan.md Phase 2). ``AgentRunState`` is the durable
logical state of one agent run; the browser remains the source of truth
for browser state (AGENTS.md rule 4), so this model carries handles and
metadata only — never DOM refs, never raw secrets.

Design constraints (AGENTS.md Phase 2 rules):
- DOM refs are ephemeral; nothing here stores them as durable state (D005).
- Browser/session/memory are represented as serializable HANDLES, not
  live objects, so a paused run can be fully serialized (Phase 2 exit).
- Transitions are deterministic and validated against an explicit table.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.interrupts.models import ApprovalBinding, HumanInterrupt
from app.agent.world.models import AgentWorldState
from app.models.workflow_state import WorkflowState


class AgentLifecycle(str, Enum):
    """Runtime lifecycle states (implementation_plan.md Phase 2).

    WAITING_FOR_USER covers the existing WorkflowStatus checkpoint states
    (WAITING_FOR_USER / WAITING_FOR_AUTH / WAITING_FOR_CAPTCHA) — the
    distinct causes live in the pending interrupt and workflow state.
    """

    INITIALIZING = "initializing"
    OBSERVING = "observing"
    REASONING = "reasoning"
    ACTING = "acting"
    VERIFYING = "verifying"
    REFLECTING = "reflecting"
    WAITING_FOR_USER = "waiting_for_user"
    READY_FOR_REVIEW = "ready_for_review"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


TERMINAL_LIFECYCLE_STATES = frozenset({
    AgentLifecycle.COMPLETED,
    AgentLifecycle.FAILED,
    AgentLifecycle.ABORTED,
})


# Deterministic transition table: from → set of legal targets.
# Any transition not listed is rejected by AgentRuntime.set_lifecycle.
LIFECYCLE_TRANSITIONS: dict[AgentLifecycle, frozenset[AgentLifecycle]] = {
    AgentLifecycle.INITIALIZING: frozenset({
        AgentLifecycle.OBSERVING,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.OBSERVING: frozenset({
        AgentLifecycle.REASONING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_REVIEW,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.REASONING: frozenset({
        AgentLifecycle.ACTING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_REVIEW,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.REFLECTING,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.ACTING: frozenset({
        AgentLifecycle.VERIFYING,
        AgentLifecycle.REFLECTING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.VERIFYING: frozenset({
        AgentLifecycle.REFLECTING,
        AgentLifecycle.OBSERVING,
        AgentLifecycle.REASONING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_REVIEW,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.REFLECTING: frozenset({
        AgentLifecycle.OBSERVING,
        AgentLifecycle.REASONING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_REVIEW,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    # Paused states resume back into the working loop; any paused state
    # may also be abandoned into a terminal state.
    AgentLifecycle.WAITING_FOR_USER: frozenset({
        AgentLifecycle.OBSERVING,
        AgentLifecycle.REASONING,
        AgentLifecycle.REFLECTING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.READY_FOR_REVIEW: frozenset({
        AgentLifecycle.OBSERVING,
        AgentLifecycle.REASONING,
        AgentLifecycle.REFLECTING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.READY_FOR_CONFIRMATION,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    AgentLifecycle.READY_FOR_CONFIRMATION: frozenset({
        AgentLifecycle.OBSERVING,
        AgentLifecycle.REASONING,
        AgentLifecycle.ACTING,
        AgentLifecycle.WAITING_FOR_USER,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.FAILED,
        AgentLifecycle.ABORTED,
    }),
    # Terminal states are final. A new run, not a transition, restarts.
    AgentLifecycle.COMPLETED: frozenset(),
    AgentLifecycle.FAILED: frozenset(),
    AgentLifecycle.ABORTED: frozenset(),
}


def can_transition(current: AgentLifecycle, target: AgentLifecycle) -> bool:
    """True when the transition is legal. Self-transitions in paused
    states are allowed (WAITING_FOR_USER → WAITING_FOR_USER) because a
    re-issued interrupt replaces the previous one in place."""
    return target in LIFECYCLE_TRANSITIONS[current]


class BrowserHandle(BaseModel):
    """Serializable pointer to the browser session owning this run.

    Metadata only. The live Playwright objects stay in BrowserManager;
    the browser is the source of truth for browser state, and a restored
    run re-attaches via session_id.
    """

    session_id: str = Field(default="", description="BrowserManager session id")
    trusted_domain: str = Field(
        default="", description="Domain the run was opened against"
    )
    current_url: str = Field(
        default="", description="Last observed URL (metadata, not authority)"
    )


class MemoryHandles(BaseModel):
    """Opaque handles to memory layers. Phase 2 stores handles only —
    no memory implementation, no vector DB (AGENTS.md rule 18)."""

    working_ref: str = Field(
        default="", description="Working-memory handle (Phase 9)"
    )
    episodic_event_log_id: str = Field(
        default="",
        description="Episodic memory = AgentEventLog id (event-backed, Phase 9)",
    )
    semantic_ref: str = Field(
        default="", description="Semantic memory handle (Phase 9)"
    )
    experience_ref: str = Field(
        default="", description="Experience memory handle (Phase 9)"
    )


class PendingInterrupt(BaseModel):
    """A durable, resumable human interrupt (AGENTS.md rule 14).

    Describes WHY the run paused. Resumption materializes as a user
    decision event; the interrupt itself is cleared by the runtime.
    """

    kind: Literal[
        "user_input",
        "authentication",
        "captcha",
        "confirmation",
        "review",
        "stall",
        "error",
        "unknown",
    ] = "unknown"
    reason: str = Field(default="", description="Human-readable cause")
    raised_at_iteration: int = Field(default=0)
    observation_id: str = Field(
        default="",
        description="Observation the interrupt was raised against (stale-ref guard)",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe metadata (never raw secrets/document contents)",
    )


class AgentIdentity(BaseModel):
    """Parent/child agent metadata for the future hierarchical agent
    (specialists are Phase 10; this is the durable identity slot)."""

    role: Literal["primary", "specialist"] = "primary"
    parent_run_id: str | None = Field(
        default=None, description="Set for specialist agents"
    )
    specialist_kind: str | None = Field(
        default=None,
        description="e.g. 'portal_research' — Phase 10 reserves the slot",
    )


class UsageCounters(BaseModel):
    """Cost/usage counters. Tokens/cost are recorded by later phases;
    the structure is part of the durable state contract now."""

    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    actions_executed: int = 0
    observations_made: int = 0


class AgentRunState(BaseModel):
    """Durable logical state of one agent run.

    Everything here serializes losslessly with model_dump(mode="json").
    The run references the WorkflowState (the semantic task state that
    already exists) plus handles to everything that is NOT serializable.
    """

    # Identity
    run_id: str = Field(default="", description="Unique run id")
    created_at: str = Field(default="", description="ISO-8601 UTC")
    updated_at: str = Field(default="", description="ISO-8601 UTC")

    # Goal / plan / subgoal. Plan stays as structured dicts until Phase 5
    # introduces the typed AgentPlan/Subgoal models; dicts serialize and
    # round-trip without inventing an abstraction early.
    goal: str = Field(default="", description="User goal for this run")
    plan: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Current plan (Phase 5 replaces dicts with typed models)",
    )
    current_subgoal: str = Field(
        default="", description="Subgoal currently being pursued"
    )

    # Lifecycle
    lifecycle: AgentLifecycle = Field(default=AgentLifecycle.INITIALIZING)
    iteration: int = Field(
        default=0, description="Completed loop iterations (0 before first)"
    )

    # Handles — never live objects
    world_state: WorkflowState = Field(
        default_factory=WorkflowState,
        description="Semantic workflow state (the real logical task state)",
    )
    browser: BrowserHandle = Field(
        default_factory=BrowserHandle,
        description="Browser session handle (metadata only)",
    )
    memory: MemoryHandles = Field(
        default_factory=MemoryHandles,
        description="Memory layer handles (unimplemented until Phase 9)",
    )

    # Interrupts
    pending_interrupt: PendingInterrupt | None = Field(
        default=None, description="Active human interrupt, if paused"
    )
    human_interrupt: HumanInterrupt | None = Field(
        default=None, description="Durable human interrupt (Phase 8)"
    )
    approval_binding: ApprovalBinding | None = Field(
        default=None, description="Durable human approval binding (Phase 8)"
    )
    agent_world_state: AgentWorldState | None = Field(
        default=None, description="Durable semantic world state (Phase 6/8)"
    )

    # Cost / usage
    usage: UsageCounters = Field(default_factory=UsageCounters)

    # Hierarchy metadata
    agent: AgentIdentity = Field(default_factory=AgentIdentity)

    def is_terminal(self) -> bool:
        return self.lifecycle in TERMINAL_LIFECYCLE_STATES

    def is_paused(self) -> bool:
        return self.lifecycle in (
            AgentLifecycle.WAITING_FOR_USER,
            AgentLifecycle.READY_FOR_REVIEW,
            AgentLifecycle.READY_FOR_CONFIRMATION,
        )

    def summary(self) -> str:
        """One-line human summary for logs."""
        subgoal = f" subgoal={self.current_subgoal!r}" if self.current_subgoal else ""
        return (
            f"run={self.run_id} {self.lifecycle.value} iter={self.iteration}"
            f"{subgoal}"
        )
