"""AgentPlanManager — deterministic lifecycle + revision engine (Phase 5).

The manager owns subgoal lifecycle transitions and plan revisions. It is
STRICTLY DETERMINISTIC — no LLM, no execution capability:

- Transitions are table-validated (mirrors the Phase 2 runtime's
  approach, D014): illegal transitions raise, never coerced.
- Completion is EVIDENCE-BASED: a subgoal completes only when its
  required SuccessCriteria evaluate satisfied against a Snapshot of
  authoritative state; there is no force path that bypasses criteria
  except the explicit human decision entry point (force_complete,
  which itself refuses the boundary subgoal).
- The final-submission boundary subgoal can never be activated,
  auto-completed, force-completed, or revised here (FinalSubmissionGate).
- Revision replaces ONLY the affected subgoal; unaffected (and
  especially COMPLETED) subgoals carry over untouched, and every
  revision appends a PlanRevision record (reason, affected ids, previous
  version/shapes, new version, timestamp, triggering evidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.strategy.criteria import (
    Snapshot,
    criteria_verdict,
    evaluate_criteria,
)
from app.agent.strategy.models import (
    AgentPlan,
    FinalSubmissionGate,
    IllegalSubgoalTransition,
    PlanInvalid,
    PlanRevision,
    Subgoal,
    SubgoalNotFound,
    SubgoalStatus,
    SubgoalStatusReason,
    utc_now_iso,
)

# Explicit transition table (fail closed; mirrors LIFECYCLE_TRANSITIONS).
SUBGOAL_TRANSITIONS: dict[SubgoalStatus, frozenset[SubgoalStatus]] = {
    SubgoalStatus.PENDING: frozenset({
        SubgoalStatus.ACTIVE,
        SubgoalStatus.BLOCKED,
        SubgoalStatus.INVALIDATED,  # page changed before the step started
        SubgoalStatus.CANCELLED,
    }),
    SubgoalStatus.ACTIVE: frozenset({
        SubgoalStatus.COMPLETED,
        SubgoalStatus.FAILED,
        SubgoalStatus.INVALIDATED,
        SubgoalStatus.CANCELLED,
    }),
    SubgoalStatus.BLOCKED: frozenset({
        SubgoalStatus.ACTIVE,
        SubgoalStatus.PENDING,
        SubgoalStatus.CANCELLED,
        SubgoalStatus.INVALIDATED,
    }),
    SubgoalStatus.COMPLETED: frozenset(),  # completed work is stable
    SubgoalStatus.FAILED: frozenset({
        SubgoalStatus.ACTIVE,          # bounded retry of the same step
        SubgoalStatus.INVALIDATED,
        SubgoalStatus.CANCELLED,
    }),
    SubgoalStatus.INVALIDATED: frozenset({
        SubgoalStatus.PENDING,         # revised/re-created replacement
        SubgoalStatus.ACTIVE,          # revised in place
        SubgoalStatus.CANCELLED,
    }),
    SubgoalStatus.CANCELLED: frozenset(),
}

# Dependency statuses that block/propagate failure.
_FAILURE_STATUSES = frozenset({
    SubgoalStatus.FAILED, SubgoalStatus.INVALIDATED, SubgoalStatus.CANCELLED,
})


@dataclass
class RevisionResult:
    """What one revision changed (for events/tests/callers)."""

    plan: AgentPlan
    revision: PlanRevision
    carried_over: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    invalidated_by_revision: list[str] = field(default_factory=list)


@dataclass
class TransitionOutcome:
    """Result of one lifecycle transition (audit + tests)."""

    subgoal_id: str
    from_status: SubgoalStatus
    to_status: SubgoalStatus
    reason: SubgoalStatusReason
    evidence: str = ""


class AgentPlanManager:
    """Deterministic owner of subgoal lifecycle and plan revisions."""

    def __init__(self, plan: AgentPlan) -> None:
        problems = plan.validate_structure()
        if problems:
            raise PlanInvalid(f"cannot manage invalid plan: {problems}")
        self._plan = plan

    @property
    def plan(self) -> AgentPlan:
        return self._plan

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin(self) -> TransitionOutcome:
        """Start the plan: the first actionable subgoal becomes ACTIVE."""
        nxt = self._plan.next_actionable
        if nxt is None:
            if self._plan.at_final_boundary:
                raise FinalSubmissionGate(
                    "plan is at the final-submission boundary — "
                    "activation is a human decision"
                )
            raise PlanInvalid("plan has no actionable subgoal to begin")
        return self._transition(
            nxt, SubgoalStatus.ACTIVE, SubgoalStatusReason.PLAN_STARTED,
        )

    def activate_next(self) -> TransitionOutcome | None:
        """Activate the next actionable subgoal, if dependencies allow.

        Deterministic: lowest order first. Subgoals whose dependencies
        FAILED/INVALIDATED/CANCELLED are marked BLOCKED. Returns None
        when nothing is currently actionable.
        """
        completed = {
            sg.id for sg in self._plan.by_status(SubgoalStatus.COMPLETED)
        }
        for sg in sorted(self._plan.subgoals, key=lambda s: s.order):
            if sg.status is not SubgoalStatus.PENDING:
                continue
            if sg.final_submission:
                continue  # the boundary is never planner-actionable
            failed_deps = [
                dep for dep in sg.depends_on
                if self._plan.get(dep).status in _FAILURE_STATUSES
            ]
            if failed_deps:
                self._transition(
                    sg, SubgoalStatus.BLOCKED,
                    SubgoalStatusReason.DEPENDENCY_FAILED,
                    evidence=(
                        f"dependency {failed_deps[0]} is "
                        f"{self._plan.get(failed_deps[0]).status.value}"
                    ),
                )
                continue
            if all(dep in completed for dep in sg.depends_on):
                return self._transition(
                    sg, SubgoalStatus.ACTIVE,
                    SubgoalStatusReason.DEPENDENCIES_SATISFIED,
                )
        return None

    def recover_blocked(self) -> list[TransitionOutcome]:
        """Re-examine BLOCKED subgoals after a revision (their blocking
        dependency may have been replaced). BLOCKED → PENDING is legal;
        activate_next then re-decides deterministically."""
        outcomes: list[TransitionOutcome] = []
        for sg in sorted(self._plan.subgoals, key=lambda s: s.order):
            if sg.status is SubgoalStatus.BLOCKED:
                outcomes.append(self._transition(
                    sg, SubgoalStatus.PENDING,
                    SubgoalStatusReason.SUPERSEDED_BY_REVISION,
                    evidence="plan revision — re-evaluating dependencies",
                ))
        return outcomes

    def mark_blocked(
        self, subgoal_id: str, reason: SubgoalStatusReason,
        *, evidence: str = "",
    ) -> TransitionOutcome:
        sg = self._plan.get(subgoal_id)
        return self._transition(
            sg, SubgoalStatus.BLOCKED, reason, evidence=evidence,
        )

    def complete(self, subgoal_id: str, snapshot: Snapshot) -> TransitionOutcome:
        """Complete a subgoal ONLY if its required criteria evaluate
        satisfied against the snapshot (evidence-based, no bypass)."""
        sg = self._plan.get(subgoal_id)
        self._assert_not_boundary(sg, "auto-complete")
        satisfied, _has_failure, failures = self._evaluate(sg, snapshot)
        if not satisfied:
            raise PlanInvalid(
                f"subgoal {sg.id} cannot complete: criteria not satisfied "
                f"({'; '.join(failures) or 'undecided'})"
            )
        return self._transition(
            sg, SubgoalStatus.COMPLETED, SubgoalStatusReason.CRITERIA_SATISFIED,
            evidence="all criteria satisfied",
        )

    def force_complete(
        self, subgoal_id: str, *, evidence: str = "",
    ) -> TransitionOutcome:
        """Human-forced completion (durable user decision path).

        Refused for the final-submission boundary and terminal subgoals —
        the boundary's completion is a HUMAN decision recorded by the
        runtime, never something the planner grants itself.
        """
        sg = self._plan.get(subgoal_id)
        self._assert_not_boundary(sg, "force-complete")
        if sg.is_terminal():
            raise PlanInvalid(f"subgoal {sg.id} is already terminal")
        return self._transition(
            sg, SubgoalStatus.COMPLETED, SubgoalStatusReason.CRITERIA_SATISFIED,
            evidence=evidence or "human-forced completion",
        )

    def fail(
        self, subgoal_id: str, *, evidence: str = "",
    ) -> TransitionOutcome:
        sg = self._plan.get(subgoal_id)
        return self._transition(
            sg, SubgoalStatus.FAILED, SubgoalStatusReason.CRITERIA_FAILED,
            evidence=evidence,
        )

    def invalidate(
        self, subgoal_id: str, *, evidence: str = "",
    ) -> TransitionOutcome:
        """Mark a subgoal no-longer-applicable (e.g. the page changed
        under it). Preserves every other subgoal — the exit-criterion
        path."""
        sg = self._plan.get(subgoal_id)
        self._assert_not_boundary(sg, "invalidate")
        return self._transition(
            sg, SubgoalStatus.INVALIDATED,
            SubgoalStatusReason.NO_LONGER_APPLICABLE,
            evidence=evidence,
        )

    def cancel(self, subgoal_id: str, *, evidence: str = "") -> TransitionOutcome:
        sg = self._plan.get(subgoal_id)
        return self._transition(
            sg, SubgoalStatus.CANCELLED, SubgoalStatusReason.MANUAL_CANCEL,
            evidence=evidence,
        )

    def evaluate_active(
        self, snapshot: Snapshot,
    ) -> tuple[TransitionOutcome | None, list[str]]:
        """Evaluate the ACTIVE subgoal's criteria against the snapshot.

        Returns (completion_outcome_or_None, failure_details). A
        satisfied verdict COMPLETES the subgoal; a failure verdict only
        surfaces details (marking FAILED is the caller's explicit
        decision); uncertain keeps waiting.
        """
        active = self._plan.by_status(SubgoalStatus.ACTIVE)
        if not active:
            return None, []
        sg = active[0]
        satisfied, _has_failure, failures = self._evaluate(sg, snapshot)
        if satisfied:
            outcome = self._transition(
                sg, SubgoalStatus.COMPLETED,
                SubgoalStatusReason.CRITERIA_SATISFIED,
                evidence="all criteria satisfied",
            )
            return outcome, []
        return None, failures

    # ------------------------------------------------------------------
    # Revision
    # ------------------------------------------------------------------

    def revise(
        self,
        *,
        subgoal_id: str,
        new_title: str,
        new_description: str = "",
        new_criteria: list[SuccessCriterion] | None = None,
        reason: str,
        triggering_event: str = "",
        reset_dependencies: bool = True,
    ) -> RevisionResult:
        """Revise ONE subgoal in place; preserve everything else.

        The affected subgoal keeps its id, order and (unless
        ``reset_dependencies``) dependencies; its status resets to
        PENDING (ACTIVE if it was the active one) with
        SUPERSEDED_BY_REVISION evidence. Its previous shape is
        snapshotted into the PlanRevision. COMPLETED subgoals are
        refused — completed work is preserved (exit criterion).
        """
        plan = self._plan
        sg = plan.get(subgoal_id)
        self._assert_not_boundary(sg, "revise")
        if sg.status is SubgoalStatus.COMPLETED:
            raise PlanInvalid(
                f"refusing to revise COMPLETED subgoal {sg.id} — "
                "completed work is preserved"
            )
        # NOTE: dependents may keep depending on the revised subgoal — its
        # id, order and dependency slot are preserved, so the chain stays
        # intact. Only structural rewrites (not supported here) would break
        # dependents.

        was_active = sg.status is SubgoalStatus.ACTIVE
        previous_snapshot = sg.model_dump(mode="json")

        sg.title = new_title
        if new_description:
            sg.description = new_description
        if new_criteria is not None:
            sg.success_criteria = list(new_criteria)
        sg.status_reason = SubgoalStatusReason.SUPERSEDED_BY_REVISION

        if reset_dependencies and sg.depends_on:
            sg.depends_on = []

        sg.status = SubgoalStatus.ACTIVE if was_active else SubgoalStatus.PENDING
        # Preserve the ORIGINAL invalidation evidence (the causal record
        # of WHY this step needed revision); the triggering_event lives
        # on the PlanRevision.
        if not sg.invalidation_evidence:
            sg.invalidation_evidence = triggering_event or reason

        revision = PlanRevision(
            revision_number=len(plan.revisions) + 1,
            reason=reason,
            affected_subgoal_ids=[sg.id],
            previous_version=plan.version,
            new_version=plan.version + 1,
            triggering_event=triggering_event,
            previous_subgoals=[previous_snapshot],
        )
        plan.version += 1
        plan.updated_at = utc_now_iso()
        plan.revisions.append(revision)

        return RevisionResult(
            plan=plan,
            revision=revision,
            carried_over=[
                other.id for other in plan.subgoals if other.id != sg.id
            ],
            replaced=[sg.id],
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evaluate(
        self, sg: Subgoal, snapshot: Snapshot,
    ) -> tuple[bool, bool, list[str]]:
        outcomes = evaluate_criteria(sg.success_criteria, snapshot)
        return criteria_verdict(sg.success_criteria, outcomes)

    def _assert_not_boundary(self, sg: Subgoal, operation: str) -> None:
        if sg.final_submission:
            raise FinalSubmissionGate(
                f"{operation} on the final-submission boundary subgoal "
                f"{sg.id} is refused — it is a human decision"
            )

    def _transition(
        self,
        sg: Subgoal,
        target: SubgoalStatus,
        reason: SubgoalStatusReason,
        *,
        evidence: str = "",
    ) -> TransitionOutcome:
        # The final-submission boundary is hard-gated at the transition
        # level: no code path (public or internal) can move it anywhere.
        self._assert_not_boundary(sg, f"transition to {target.value}")
        if target not in SUBGOAL_TRANSITIONS[sg.status]:
            raise IllegalSubgoalTransition(
                f"subgoal {sg.id}: illegal transition "
                f"{sg.status.value} → {target.value}"
            )
        previous = sg.status
        sg.status = target
        sg.status_reason = reason
        if target is SubgoalStatus.COMPLETED:
            sg.completed_at = utc_now_iso()
        if target in (SubgoalStatus.INVALIDATED, SubgoalStatus.FAILED):
            sg.invalidation_evidence = evidence
        return TransitionOutcome(
            subgoal_id=sg.id, from_status=previous, to_status=target,
            reason=reason, evidence=evidence,
        )
