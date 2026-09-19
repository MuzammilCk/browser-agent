"""Deterministic success-criterion evaluation — Phase 5.

Criteria are explicit and testable (user instruction, Phase 5): each is
a typed predicate evaluated against a ``Snapshot`` of verified state
derived from the AUTHORITATIVE sources (WorkflowState for semantic task
state, PageObservation for the page). No model, no confidence, no
natural-language success.

Phase 6 note: the Snapshot is deliberately a thin projection of the
sources Phase 6's AgentWorldState will own — swapping its inputs for
WorldState later does not change the criterion contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.browser.observer import PageObservation
from app.models.workflow_state import WorkflowState

UNCERTAIN = "uncertain"


@dataclass
class Snapshot:
    """Verified-state projection criteria are evaluated against.

    ``completed_bindings``: refs/binding keys with VERIFIED success
    (from WorkflowState.actions_taken / completed_bindings).
    ``validation_errors``: visible page validation errors.
    """

    workflow: WorkflowState
    current_url: str = ""
    page_type: str = "unknown"
    validation_errors: list[str] = field(default_factory=list)

    @classmethod
    def from_sources(
        cls,
        workflow: WorkflowState,
        observation: PageObservation | None = None,
    ) -> Snapshot:
        ps = observation.page_state if observation is not None else None
        return cls(
            workflow=workflow,
            current_url=(ps.url if ps else workflow.current_url),
            page_type=(ps.page_type if ps else workflow.current_page_type),
            validation_errors=(
                [
                    f"{v.target_ref}: {v.message}"
                    for v in ps.validation_errors if v.visible
                ]
                if ps else []
            ),
        )


@dataclass(frozen=True)
class CriterionOutcome:
    """One criterion's deterministic verdict."""

    criterion_id: str
    kind: str
    satisfied: bool
    uncertain: bool = False
    detail: str = ""


def evaluate_criteria(
    criteria: list,
    snapshot: Snapshot,
) -> list[CriterionOutcome]:
    """Evaluate every criterion deterministically.

    ``never`` criteria are always unsatisfied (used for explicit
    placeholders/blocked conditions). Unknown kinds fail CLOSED as
    uncertain — a criterion the evaluator does not understand must never
    be reported as satisfied.
    """
    outcomes: list[CriterionOutcome] = []
    for criterion in criteria:
        kind = criterion.kind
        params = criterion.params or {}

        if kind == "never":
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind, satisfied=False,
                detail="explicit never-criterion",
            ))

        elif kind == "no_pending_fields":
            pending = snapshot.workflow.pending_fields
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=len(pending) == 0,
                detail=f"{len(pending)} pending fields",
            ))

        elif kind == "no_unmapped_fields":
            unmapped = snapshot.workflow.unmapped_fields
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=len(unmapped) == 0,
                detail=f"{len(unmapped)} unmapped fields",
            ))

        elif kind == "no_ambiguous_fields":
            ambiguous = snapshot.workflow.ambiguous_fields
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=len(ambiguous) == 0,
                detail=f"{len(ambiguous)} ambiguous fields",
            ))

        elif kind == "no_validation_errors":
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=len(snapshot.validation_errors) == 0,
                uncertain=False,
                detail=f"{len(snapshot.validation_errors)} visible errors",
            ))

        elif kind == "page_type_reached":
            target = str(params.get("page_type", ""))
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=bool(target) and snapshot.page_type == target,
                detail=f"page_type={snapshot.page_type} target={target!r}",
            ))

        elif kind == "url_reached":
            prefix = str(params.get("url", ""))
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=bool(prefix) and snapshot.current_url.startswith(prefix),
                detail=f"url={snapshot.current_url!r} prefix={prefix!r}",
            ))

        elif kind == "field_value_bound":
            binding = str(params.get("binding", ""))
            satisfied = binding in snapshot.workflow.completed_bindings
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=satisfied,
                detail=f"binding={binding!r} "
                       f"completed={len(snapshot.workflow.completed_bindings)}",
            ))

        elif kind == "auth_state_satisfied":
            target = str(params.get("state", ""))
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=bool(target)
                and snapshot.workflow.authentication_state == target,
                detail=f"auth={snapshot.workflow.authentication_state!r} "
                       f"target={target!r}",
            ))

        elif kind == "documents_resolved":
            refs = [str(r) for r in params.get("refs", [])]
            missing = [r for r in refs if r not in snapshot.workflow.completed_bindings]
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=bool(refs) and not missing,
                detail=f"missing={missing}" if missing else "all resolved",
            ))

        else:
            # Unknown criterion kind → fail closed as uncertain.
            outcomes.append(CriterionOutcome(
                criterion_id=criterion.id, kind=kind,
                satisfied=False, uncertain=True,
                detail=f"unknown criterion kind: {kind!r}",
            ))

    return outcomes


def criteria_verdict(
    criteria: list,
    outcomes: list[CriterionOutcome],
) -> tuple[bool, bool, list[str]]:
    """Aggregate outcomes → (all_required_satisfied, has_failure, failures).

    Verdict semantics (three-valued, never confidence):
    - all required satisfied            → (True, False, [])
    - a required criterion deterministically unsatisfied → FAILURE
      (has_failure=True). Uncertain is NOT failure — it means 'not yet
      decidable' (e.g. fields still pending mid-step).
    - optional (required=False) criteria never fail the verdict.
    """
    by_id = {c.id: c for c in criteria}
    failures: list[str] = []
    has_failure = False
    for outcome in outcomes:
        criterion = by_id.get(outcome.criterion_id)
        required = criterion.required if criterion is not None else True
        if outcome.satisfied or not required or outcome.uncertain:
            continue
        has_failure = True
        failures.append(f"{outcome.kind}: {outcome.detail}")
    all_satisfied = all(
        outcome.satisfied
        for outcome in outcomes
        if by_id.get(outcome.criterion_id) is None
        or by_id[outcome.criterion_id].required
    )
    return all_satisfied, has_failure, failures
