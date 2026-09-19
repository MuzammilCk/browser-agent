"""Deterministic initial plan builder — Phase 5 (requirement 2).

Creates an AgentPlan from a parsed AgentGoal WITHOUT any LLM call. The
builder is deterministic: same goal shape → same plan structure. It
never hard-codes government portals (AGENTS.md rule 17) — steps are
derived from the goal's own shape (multi-step vs single-form, references
available vs not) and are generic to any portal.

Step templates are generic application shapes:
    navigate → fill personal details → [fill contact] → [upload documents]
    → resolve ambiguities → review (the explicit final-submission
    boundary subgoal, gated, never auto-executed).

Dependencies encode a strict chain; the manager enforces them.
"""

from __future__ import annotations

from app.agent.strategy.models import (
    AgentGoal,
    AgentPlan,
    PlanInvalid,
    Subgoal,
    SubgoalStatus,
    SuccessCriterion,
)


def _crit(description: str, kind: str, **params) -> SuccessCriterion:
    return SuccessCriterion(description=description, kind=kind, params=params)


def _step(
    order: int,
    title: str,
    description: str,
    depends_on: list[str],
    criteria: list[SuccessCriterion],
    *,
    final_submission: bool = False,
) -> Subgoal:
    return Subgoal(
        title=title,
        description=description,
        order=order,
        depends_on=depends_on,
        success_criteria=criteria,
        final_submission=final_submission,
    )


def build_initial_plan(
    goal: AgentGoal,
    *,
    multi_step: bool,
    documents_available: bool,
) -> AgentPlan:
    """Build the initial ordered plan for the goal.

    Deterministic and portal-agnostic. ``multi_step`` (from the goal
    parser) selects the multi-page application shape; ``documents_available``
    (from the vault/reference layer) adds the upload subgoal.
    """
    subgoals: list[Subgoal] = []
    order = 0
    prev_id: str | None = None

    def _add(
        title: str, description: str, criteria: list[SuccessCriterion],
        *, final_submission: bool = False,
    ) -> Subgoal:
        nonlocal order, prev_id
        sg = _step(
            order=order,
            title=title,
            description=description,
            depends_on=[prev_id] if prev_id else [],
            criteria=criteria,
            final_submission=final_submission,
        )
        subgoals.append(sg)
        prev_id = sg.id
        order += 1
        return sg

    # 1. Reach the form/start of the application.
    _add(
        title="Reach the application form",
        description=(
            "Navigate/observe until the entry form of the application is "
            "on screen."
        ),
        criteria=[_crit(
            "A form page is on screen", "page_type_reached", page_type="form",
        )],
    )

    # 2. Fill the primary (personal-details) section.
    _add(
        title="Fill primary details",
        description=(
            "Complete the first required section of the form using "
            "semantic references where available."
        ),
        criteria=[
            _crit("Primary section has no pending required fields",
                  "no_pending_fields"),
            _crit("No visible validation errors remain",
                  "no_validation_errors"),
        ],
    )

    if multi_step:
        # 3. Complete remaining sections (contact/etc.) on later pages.
        _add(
            title="Complete remaining sections",
            description=(
                "Fill later form sections after progressing past the "
                "first page."
            ),
            criteria=[
                _crit("No pending fields remain anywhere",
                      "no_pending_fields"),
                _crit("No visible validation errors remain",
                      "no_validation_errors"),
            ],
        )

    if documents_available:
        _add(
            title="Resolve and upload documents",
            description=(
                "Upload required documents via semantic document "
                "references (paths never pass through the model)."
            ),
            criteria=[_crit(
                "Required document refs are resolved and bound",
                "documents_resolved", refs=["DOCUMENT.REQUIRED"],
            )],
        )

    # Penultimate: resolve ambiguities before review.
    _add(
        title="Resolve ambiguities",
        description=(
            "Ensure every field is mapped and nothing is ambiguous "
            "before review."
        ),
        criteria=[
            _crit("No unmapped fields remain", "no_unmapped_fields"),
            _crit("No ambiguous fields remain", "no_ambiguous_fields"),
        ],
    )

    # FINAL: the explicit final-submission boundary. Represented and
    # tracked, gated by FinalSubmissionGate on activation — never
    # autonomously executed (execution stays gated by PolicyEngine and
    # the Phase 4 runtime constraints).
    _add(
        title="Review and human confirmation (final boundary)",
        description=(
            "Bring the application to the review state and hand over to "
            "the human for the irreversible submission decision. The "
            "agent never performs the final submission autonomously."
        ),
        criteria=[
            _crit("Review page reached", "page_type_reached", page_type="review"),
            _crit("No validation errors before handover", "no_validation_errors"),
        ],
        final_submission=True,
    )

    plan = AgentPlan(goal_id=goal.goal_id, subgoals=subgoals)

    problems = plan.validate_structure()
    if problems:
        raise PlanInvalid(f"built plan is structurally invalid: {problems}")
    return plan
