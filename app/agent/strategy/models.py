"""Typed planning models — Phase 5 (implementation_plan.md).

STRATEGIC STATE ONLY: these models carry no execution capability, no
browser handles, no policy authority. They are pydantic models so the
complete planning state serializes/round-trips losslessly (Phase 5
requirement 10), and they compose with the Phase 2 runtime state via
plain data (AgentRunState.plan stays ``list[dict]`` until wiring; the
typed models dump to JSON-compatible dicts).

Key invariants encoded here:

- Subgoal lifecycle is an explicit, table-validated state machine —
  mirroring the Phase 2 runtime's approach (D014): deterministic
  transitions, illegal ones rejected, never coerced.
- Completion is EVIDENCE-BASED: a subgoal completes only against named
  SuccessCriteria that are explicit and testable (never vague natural-
  language confidence).
- The FINAL-SUBMISSION BOUNDARY is explicit: a subgoal with
  ``final_submission=True`` is a hard gate — activating it raises, and
  it can never be auto-completed by the manager. Execution-time gating
  stays where it already is (PolicyEngine + runtime constraints).
- Revisions preserve history: every AgentPlan revision records reason,
  affected subgoals, previous version and triggering evidence, and
  completed subgoals are carried over untouched (Phase 5 requirement 7).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Errors (fail closed — never coerce invalid planning state)
# ---------------------------------------------------------------------------


class SubgoalNotFound(Exception):
    """Referenced subgoal id does not exist in the plan."""


class PlanInvalid(Exception):
    """Plan structure is invalid (cycles, unknown deps, bad boundary)."""


class IllegalSubgoalTransition(Exception):
    """A subgoal status change is not in the transition table."""


class FinalSubmissionGate(Exception):
    """Raised when anything tries to ACTIVATE the final-submission
    boundary subgoal. The boundary is represented and tracked — never
    autonomously executed (AGENTS.md rule 7; the runtime + PolicyEngine
    gate the action itself regardless)."""


# ---------------------------------------------------------------------------
# Success criteria
# ---------------------------------------------------------------------------


class SuccessCriterion(BaseModel):
    """One explicit, testable success condition.

    NOT natural-language confidence: a criterion is a typed predicate the
    deterministic evaluator (criteria.py) can decide True/False/uncertain
    against a Snapshot of verified state. ``description`` is for humans
    and prompts only — the ``kind`` + ``params`` decide the outcome.
    """

    id: str = Field(default_factory=lambda: _new_id("crit"))
    description: str = Field(
        description="Human/model-facing description (not the test itself)",
    )
    kind: Literal[
        "no_pending_fields",       # WorkflowState.pending_fields is empty
        "no_unmapped_fields",      # WorkflowState.unmapped_fields is empty
        "no_ambiguous_fields",     # WorkflowState.ambiguous_fields is empty
        "no_validation_errors",    # page observation has no visible errors
        "page_type_reached",       # observed page_type == params.page_type
        "url_reached",             # current URL startswith params.url
        "field_value_bound",       # binding in params.binding ∈ completed_bindings
        "auth_state_satisfied",    # authentication_state == params.state
        "documents_resolved",      # params.refs all in completed bindings
        "never",                   # always False (blocked/placeholder criteria)
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = Field(
        default=True,
        description="False only for optional/telemetry criteria",
    )

    def snapshot_target(self) -> str:
        return f"{self.kind}:{self.params or ''}"


# ---------------------------------------------------------------------------
# Subgoal
# ---------------------------------------------------------------------------


class SubgoalStatus(str, Enum):
    """Explicit subgoal lifecycle (user instruction, Phase 5)."""

    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"
    CANCELLED = "cancelled"


class SubgoalStatusReason(str, Enum):
    """Machine-readable WHY for every status change (audit + replay)."""

    PLAN_STARTED = "plan_started"
    DEPENDENCIES_SATISFIED = "dependencies_satisfied"
    DEPENDENCIES_INCOMPLETE = "dependencies_incomplete"
    DEPENDENCY_FAILED = "dependency_failed"
    DEPENDENCY_INVALIDATED = "dependency_invalidated"
    CRITERIA_SATISFIED = "criteria_satisfied"
    CRITERIA_FAILED = "criteria_failed"
    CRITERIA_UNCERTAIN = "criteria_uncertain"
    NO_LONGER_APPLICABLE = "no_longer_applicable"   # page changed under it
    TARGET_CHANGED = "target_changed"
    SUPERSEDED_BY_REVISION = "superseded_by_revision"
    MANUAL_CANCEL = "manual_cancel"


class Subgoal(BaseModel):
    """One ordered step of the plan with an explicit lifecycle.

    ``depends_on`` holds subgoal ids that must be COMPLETED before this
    one may activate (dependencies are respected by the manager, never
    by convention). ``final_submission=True`` marks the irreversible
    boundary subgoal — it is represented, tracked, and gated, never
    autonomously executed.
    """

    id: str = Field(default_factory=lambda: _new_id("sg"))
    title: str = Field(description="Short stable title (e.g. 'Fill personal details')")
    description: str = Field(default="")
    status: SubgoalStatus = SubgoalStatus.PENDING
    order: int = Field(description="Position in the plan (0-based)")
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    final_submission: bool = Field(
        default=False,
        description="True only for the explicit final-submission boundary subgoal",
    )
    # Evidence (filled by the manager when criteria are evaluated)
    status_reason: SubgoalStatusReason | None = None
    completed_at: str | None = None
    invalidation_evidence: str = Field(default="")

    def is_terminal(self) -> bool:
        return self.status in (
            SubgoalStatus.COMPLETED,
            SubgoalStatus.FAILED,
            SubgoalStatus.INVALIDATED,
            SubgoalStatus.CANCELLED,
        )


# ---------------------------------------------------------------------------
# Plan revision
# ---------------------------------------------------------------------------


class PlanRevision(BaseModel):
    """Immutable record of one plan revision.

    Every revision carries: revision id, reason, affected subgoals, the
    previous plan (version + the affected subgoals' prior shapes), the
    new version, timestamp, and the triggering event/evidence
    (user instruction, Phase 5). Revisions never rewrite history —
    completed subgoals carry over and the trail stays auditable.
    """

    revision_id: str = Field(default_factory=lambda: _new_id("rev"))
    revision_number: int = Field(description="1-based sequence within the plan")
    reason: str = Field(description="Why the plan was revised")
    affected_subgoal_ids: list[str] = Field(default_factory=list)
    previous_version: int = Field(description="Plan version before this revision")
    new_version: int = Field(description="Plan version after this revision")
    timestamp: str = Field(default_factory=utc_now_iso)
    triggering_event: str = Field(
        default="",
        description="Evidence/event that triggered the revision (e.g. page change)",
    )
    # Prior shapes of affected subgoals (serializable snapshots), so the
    # previous plan is reconstructible without referencing live objects.
    previous_subgoals: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------


class AgentGoal(BaseModel):
    """The user's goal as structured, durable strategic state.

    ``raw`` preserves the user's words verbatim (provenance);
    ``description`` is the normalized form the planner works with.
    Success criteria at goal level define WHEN THE WHOLE GOAL is done —
    they are evaluated exactly like subgoal criteria (deterministic,
    evidence-based), never as confidence.
    """

    goal_id: str = Field(default_factory=lambda: _new_id("goal"))
    raw: str = Field(default="", description="The user's verbatim task text")
    description: str = Field(
        description="Normalized goal statement used by the planner",
    )
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    domain: str = Field(
        default="",
        description="Target domain/site class if known (informational)",
    )
    created_at: str = Field(default_factory=utc_now_iso)

    def criterion_kinds(self) -> list[str]:
        return [c.kind for c in self.success_criteria]


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class AgentPlan(BaseModel):
    """Versioned ordered plan over subgoals.

    The manager mutates subgoal statuses; ``version`` increments on every
    structural change (revisions, not lifecycle transitions). All state
    serializes losslessly (pydantic, mode="json").
    """

    plan_id: str = Field(default_factory=lambda: _new_id("plan"))
    goal_id: str = Field(description="Owning goal")
    version: int = Field(default=1, description="Incremented by every revision")
    subgoals: list[Subgoal] = Field(default_factory=list)
    revisions: list[PlanRevision] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    # -- lookups -------------------------------------------------------

    def get(self, subgoal_id: str) -> Subgoal:
        for sg in self.subgoals:
            if sg.id == subgoal_id:
                return sg
        raise SubgoalNotFound(f"unknown subgoal: {subgoal_id}")

    def by_status(self, *statuses: SubgoalStatus) -> list[Subgoal]:
        wanted = set(statuses)
        return [sg for sg in self.subgoals if sg.status in wanted]

    # -- derived views ---------------------------------------------------

    @property
    def next_actionable(self) -> Subgoal | None:
        """Lowest-order subgoal whose dependencies are all COMPLETED and
        which is still PENDING. Deterministic: order, then plan order.

        The final-submission boundary subgoal is NEVER actionable by the
        planner: when only it remains, this returns None and the runtime
        parks the run at the human gate (see AgentPlanManager
        .at_final_boundary)."""
        completed = {sg.id for sg in self.by_status(SubgoalStatus.COMPLETED)}
        for sg in sorted(self.subgoals, key=lambda s: s.order):
            if sg.final_submission:
                continue
            if sg.status is SubgoalStatus.PENDING and all(
                dep in completed for dep in sg.depends_on
            ):
                return sg
        return None

    @property
    def at_final_boundary(self) -> bool:
        """True when every non-boundary subgoal is terminal and only the
        human-gated boundary remains — the run is ready for review/
        confirmation handover, not for further planner actions."""
        boundary = [sg for sg in self.subgoals if sg.final_submission]
        if not boundary:
            return False
        others = [sg for sg in self.subgoals if not sg.final_submission]
        return all(sg.is_terminal() for sg in others) and any(
            sg.status is SubgoalStatus.PENDING for sg in boundary
        )

    def dependencies_satisfied(self, subgoal: Subgoal) -> bool:
        completed = {sg.id for sg in self.by_status(COMPLETED_STATUS)}
        return all(dep in completed for dep in subgoal.depends_on)

    def validate_structure(self) -> list[str]:
        """Structural validation; returns problems (empty = valid).

        Rejects: unknown dependency ids, dependency cycles, duplicate
        orders, final_submission not on the last effective step, more
        than one final-submission subgoal.
        """
        problems: list[str] = []
        ids = [sg.id for sg in self.subgoals]
        if len(ids) != len(set(ids)):
            problems.append("duplicate subgoal ids")
        orders = [sg.order for sg in self.subgoals]
        if len(orders) != len(set(orders)):
            problems.append("duplicate subgoal orders")
        id_set = set(ids)
        for sg in self.subgoals:
            for dep in sg.depends_on:
                if dep not in id_set:
                    problems.append(f"{sg.id}: unknown dependency {dep}")
        # Cycle check (DFS with coloring)
        state: dict[str, int] = {}
        for start in ids:
            if state.get(start, 0) == 2:
                continue
            stack = [(start, iter(self.get(start).depends_on))]
            state[start] = 1
            while stack:
                node, it = stack[-1]
                advanced = False
                found_cycle = False
                for dep in it:
                    if dep not in id_set:
                        continue  # unknown deps already recorded above
                    if state.get(dep, 0) == 1:
                        problems.append(f"dependency cycle through {dep}")
                        found_cycle = True
                        break
                    if state.get(dep, 0) == 0:
                        state[dep] = 1
                        stack.append((dep, iter(self.get(dep).depends_on)))
                        advanced = True
                        break
                if found_cycle:
                    break  # stack already abandoned; report from next start
                if not advanced:
                    state[node] = 2
                    stack.pop()
        finals = [sg for sg in self.subgoals if sg.final_submission]
        if len(finals) > 1:
            problems.append("more than one final_submission subgoal")
        if finals:
            # The boundary must be a sink: nothing may depend on anything
            # ordered after it, i.e. it must have the highest order.
            boundary = max(sg.order for sg in finals)
            if any(sg.order > boundary for sg in self.subgoals):
                problems.append(
                    "final_submission subgoal is not the last step"
                )
        return problems

    def summary(self) -> str:
        counts = {status.value: 0 for status in SubgoalStatus}
        for sg in self.subgoals:
            counts[sg.status.value] += 1
        return (
            f"plan v{self.version} goal={self.goal_id} "
            f"{len(self.subgoals)} subgoals: {counts}"
        )


# Status alias used by the dependency view (kept as a module constant so
# the table above stays readable).
COMPLETED_STATUS = SubgoalStatus.COMPLETED
