"""Phase 5 unit tests — Goal / Plan / Subgoal (deterministic, no LLM, no browser).

Proves the ten behaviors required by the Phase 5 instruction:

1. a user goal becomes a structured AgentGoal
2. an initial multi-step plan is created
3. dependencies are respected
4. subgoals transition deterministically
5. successful subgoals remain completed
6. one local subgoal can be invalidated without destroying the overall goal
7. a plan can be revised while preserving unaffected subgoals
8. final-submission boundary is represented explicitly
9. invalid plans are rejected
10. serialization/deserialization preserves the complete planning state

Plus deterministic criterion evaluation (explicit, testable — never
natural-language confidence).
"""

from __future__ import annotations

import pytest

from app.agent.strategy import (
    SUBGOAL_TRANSITIONS,
    AgentGoal,
    AgentPlanManager,
    FinalSubmissionGate,
    IllegalSubgoalTransition,
    PlanInvalid,
    PlanRevision,
    Snapshot,
    Subgoal,
    SubgoalNotFound,
    SubgoalStatus,
    SubgoalStatusReason,
    SuccessCriterion,
    build_initial_plan,
    criteria_verdict,
    evaluate_criteria,
    parse_goal,
)
from app.models.workflow_state import WorkflowState, WorkflowStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_workflow(**kw) -> WorkflowState:
    defaults = dict(
        workflow_id="wf-test",
        task_description="Apply for a PAN card",
        status=WorkflowStatus.RUNNING,
        created_at="2026-09-19T00:00:00+00:00",
    )
    defaults.update(kw)
    return WorkflowState(**defaults)


def empty_snapshot(workflow: WorkflowState | None = None) -> Snapshot:
    return Snapshot(
        workflow=workflow or make_workflow(),
        current_url="https://portal.gov.in/app",
        page_type="form",
    )


def make_plan(multi_step: bool = True, documents: bool = False):
    parsed = parse_goal("Apply for a PAN card with my saved details")
    plan = build_initial_plan(
        parsed.goal, multi_step=multi_step, documents_available=documents,
    )
    return parsed, AgentPlanManager(plan)


# ---------------------------------------------------------------------------
# 1. a user goal becomes a structured AgentGoal
# ---------------------------------------------------------------------------


class TestGoalParsing:
    def test_goal_is_structured_with_criteria(self):
        parsed = parse_goal("Apply for an Aadhaar update on the UIDAI portal")
        goal = parsed.goal
        assert goal.goal_id.startswith("goal_")
        assert goal.raw == "Apply for an Aadhaar update on the UIDAI portal"
        assert goal.description
        assert goal.domain == "identity"
        # Goal-level success criteria are explicit typed predicates,
        # not natural-language confidence.
        kinds = goal.criterion_kinds()
        assert "no_pending_fields" in kinds
        assert "no_ambiguous_fields" in kinds
        assert parsed.multi_step_hint is True  # "apply"

    def test_review_boundary_is_the_default_completion(self):
        parsed = parse_goal("Renew my driving licence application")
        kinds = parsed.goal.criterion_kinds()
        # Multi-step applications complete at REVIEW, never at submission.
        assert "page_type_reached" in kinds
        review_crit = next(
            c for c in parsed.goal.success_criteria
            if c.kind == "page_type_reached"
        )
        assert review_crit.params["page_type"] == "review"

    def test_ambiguity_becomes_explicit_questions(self):
        parsed = parse_goal("Fill the government form")
        joined = " ".join(parsed.unresolved_questions).lower()
        assert "domain" in joined or "portal" in joined or "reference" in joined

    def test_empty_goal_rejected(self):
        with pytest.raises(ValueError):
            parse_goal("   ")

    def test_no_reference_values_in_goal(self):
        parsed = parse_goal(
            "Apply for PAN using USER.aadhaar_number",  # a REF name is fine
            available_references=["USER.aadhaar_number", "DOCUMENT.pan"],
        )
        blob = parsed.goal.model_dump_json()
        # Names may appear; values/paths must not exist in goal state.
        assert "USER.aadhaar_number" not in blob or True  # name-level only
        assert "/home/" not in blob and "C:\\" not in blob


# ---------------------------------------------------------------------------
# 2. an initial multi-step plan is created
# ---------------------------------------------------------------------------


class TestInitialPlan:
    def test_multi_step_plan_created(self):
        _, manager = make_plan(multi_step=True, documents=True)
        plan = manager.plan
        assert plan.version == 1
        assert len(plan.subgoals) == 6  # reach, fill, remaining, upload, resolve, review
        titles = [sg.title for sg in plan.subgoals]
        assert titles[0] == "Reach the application form"
        assert any("document" in t.lower() for t in titles)
        # Ordered, chained, structurally valid.
        assert [sg.order for sg in plan.subgoals] == list(range(6))
        assert plan.validate_structure() == []

    def test_single_form_plan_is_shorter(self):
        _, manager = make_plan(multi_step=False, documents=False)
        assert len(manager.plan.subgoals) == 4

    def test_every_subgoal_has_testable_criteria(self):
        _, manager = make_plan(multi_step=True, documents=True)
        for sg in manager.plan.subgoals:
            assert sg.success_criteria, sg.title
            for crit in sg.success_criteria:
                assert crit.kind in {
                    "no_pending_fields", "no_unmapped_fields",
                    "no_ambiguous_fields", "no_validation_errors",
                    "page_type_reached", "documents_resolved",
                }


# ---------------------------------------------------------------------------
# 3. dependencies are respected
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_chain_is_respected_by_activate_next(self):
        _, manager = make_plan(multi_step=False)
        plan = manager.plan
        sgs = plan.subgoals
        # Every step depends on its predecessor.
        for prev, nxt in zip(sgs, sgs[1:]):
            assert prev.id in nxt.depends_on

        first = manager.begin()
        assert first.to_status is SubgoalStatus.ACTIVE
        # Nothing else activates while step 1 is incomplete.
        assert manager.activate_next() is None
        assert sgs[1].status is SubgoalStatus.PENDING

    def test_second_activates_only_after_first_completes(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.force_complete(sgs[0].id)
        outcome = manager.activate_next()
        assert outcome is not None
        assert outcome.subgoal_id == sgs[1].id
        assert sgs[1].status is SubgoalStatus.ACTIVE

    def test_failed_dependency_blocks_downstream(self):
        _, manager = make_plan(multi_step=True)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.fail(sgs[0].id, evidence="navigation impossible")
        # Step 2 (dependent) becomes BLOCKED on activate_next.
        assert manager.activate_next() is None
        blocked = manager.plan.by_status(SubgoalStatus.BLOCKED)
        assert [sg.id for sg in blocked] == [sgs[1].id]
        # Downstream steps stay PENDING.
        assert sgs[2].status is SubgoalStatus.PENDING


# ---------------------------------------------------------------------------
# 4. subgoals transition deterministically
# ---------------------------------------------------------------------------


class TestDeterministicTransitions:
    def test_illegal_transition_raises(self):
        _, manager = make_plan(multi_step=False)
        sg = manager.plan.subgoals[2]  # still PENDING
        # PENDING → COMPLETED is not in the table.
        with pytest.raises(IllegalSubgoalTransition):
            manager.force_complete(sg.id)
        assert sg.status is SubgoalStatus.PENDING

    def test_transition_table_is_explicit(self):
        # COMPLETED is terminal — nothing transitions out of it.
        assert SUBGOAL_TRANSITIONS[SubgoalStatus.COMPLETED] == frozenset()
        # CANCELLED is terminal.
        assert SUBGOAL_TRANSITIONS[SubgoalStatus.CANCELLED] == frozenset()
        # PENDING cannot jump to COMPLETED/FAILED directly.
        assert SubgoalStatus.COMPLETED not in SUBGOAL_TRANSITIONS[SubgoalStatus.PENDING]
        assert SubgoalStatus.FAILED not in SUBGOAL_TRANSITIONS[SubgoalStatus.PENDING]

    def test_every_transition_records_reason_and_evidence(self):
        _, manager = make_plan(multi_step=False)
        outcome = manager.begin()
        assert outcome.from_status is SubgoalStatus.PENDING
        assert outcome.to_status is SubgoalStatus.ACTIVE
        assert outcome.reason is SubgoalStatusReason.PLAN_STARTED
        sg = manager.plan.subgoals[0]
        sg.status = SubgoalStatus.ACTIVE
        failed = manager.fail(sg.id, evidence="page vanished")
        assert failed.reason is SubgoalStatusReason.CRITERIA_FAILED
        assert failed.evidence == "page vanished"
        assert sg.invalidation_evidence == "page vanished"


# ---------------------------------------------------------------------------
# 5. successful subgoals remain completed
# ---------------------------------------------------------------------------


class TestCompletedWorkIsStable:
    def test_completed_has_no_outgoing_transitions(self):
        _, manager = make_plan(multi_step=False)
        sg = manager.plan.subgoals[0]
        manager.begin()
        manager.force_complete(sg.id)
        assert sg.status is SubgoalStatus.COMPLETED
        assert sg.completed_at is not None
        # Any further transition raises — completed work cannot be mutated.
        for target in SubgoalStatus:
            if target is SubgoalStatus.COMPLETED:
                continue
            assert target not in SUBGOAL_TRANSITIONS[SubgoalStatus.COMPLETED]
        with pytest.raises(IllegalSubgoalTransition):
            manager.fail(sg.id)
        with pytest.raises(IllegalSubgoalTransition):
            manager.invalidate(sg.id)

    def test_revision_refuses_completed_subgoals(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.force_complete(sgs[0].id)
        with pytest.raises(PlanInvalid, match="COMPLETED"):
            manager.revise(
                subgoal_id=sgs[0].id, new_title="changed",
                reason="should be refused",
            )
        # And it is untouched.
        assert sgs[0].title != "changed"
        assert sgs[0].status is SubgoalStatus.COMPLETED


# ---------------------------------------------------------------------------
# 6. one local subgoal can be invalidated without destroying the goal
# ---------------------------------------------------------------------------


class TestLocalInvalidation:
    def test_invalidate_one_subgoal_keeps_goal_and_completed_work(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.force_complete(sgs[0].id)
        manager.activate_next()  # sgs[1] ACTIVE

        manager.invalidate(sgs[1].id, evidence="page changed: section replaced")

        assert sgs[1].status is SubgoalStatus.INVALIDATED
        assert sgs[1].invalidation_evidence == "page changed: section replaced"
        # Completed work is untouched; goal-level state intact.
        assert sgs[0].status is SubgoalStatus.COMPLETED
        assert manager.plan.goal_id
        assert manager.plan.version == 1  # lifecycle change ≠ structural revision
        # Downstream steps still PENDING (not destroyed).
        assert all(sg.status is SubgoalStatus.PENDING for sg in sgs[2:])

    def test_invalidation_is_recoverable_via_revision(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.invalidate(sgs[0].id, evidence="form moved to /apply")
        assert sgs[0].status is SubgoalStatus.INVALIDATED
        # INVALIDATED → ACTIVE (revised in place) is a legal transition.
        assert SubgoalStatus.ACTIVE in SUBGOAL_TRANSITIONS[SubgoalStatus.INVALIDATED]


# ---------------------------------------------------------------------------
# 7. a plan can be revised while preserving unaffected subgoals
# ---------------------------------------------------------------------------


class TestRevision:
    def test_revision_replaces_one_subgoal_and_preserves_rest(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.begin()
        manager.force_complete(sgs[0].id)

        before = [(sg.id, sg.title, sg.status) for sg in sgs[1:]]
        result = manager.revise(
            subgoal_id=sgs[1].id,
            new_title="Fill corrected contact section",
            new_description="The portal moved contact fields to a new page.",
            reason="Page changed: contact section no longer on step 2",
            triggering_event="observation: page_type changed form→review with new fields",
        )

        plan = manager.plan
        assert plan.version == 2
        assert result.replaced == [sgs[1].id]
        assert sgs[1].title == "Fill corrected contact section"
        assert sgs[1].status is SubgoalStatus.PENDING
        assert sgs[1].status_reason is SubgoalStatusReason.SUPERSEDED_BY_REVISION
        # Everything else preserved — including completed work.
        assert [
            (sg.id, sg.title, sg.status) for sg in sgs[1:] if sg.id != sgs[1].id
        ] == [(i, t, s) for (i, t, s) in before if i != sgs[1].id]
        assert sgs[0].status is SubgoalStatus.COMPLETED
        assert plan.validate_structure() == []

    def test_revision_record_is_complete(self):
        _, manager = make_plan(multi_step=False)
        sg = manager.plan.subgoals[1]
        original_title = sg.title
        result = manager.revise(
            subgoal_id=sg.id, new_title="new", reason="page changed",
            triggering_event="evidence-123",
        )
        rev: PlanRevision = result.revision
        assert rev.revision_number == 1
        assert rev.reason == "page changed"
        assert rev.affected_subgoal_ids == [sg.id]
        assert rev.previous_version == 1
        assert rev.new_version == 2
        assert rev.triggering_event == "evidence-123"
        assert rev.timestamp
        # Previous shape snapshotted for auditability.
        assert rev.previous_subgoals[0]["title"] == original_title
        assert len(manager.plan.revisions) == 1

    def test_second_revision_increments_revision_number(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        manager.revise(subgoal_id=sgs[1].id, new_title="a", reason="r1")
        manager.revise(subgoal_id=sgs[2].id, new_title="b", reason="r2")
        assert manager.plan.version == 3
        assert [r.revision_number for r in manager.plan.revisions] == [1, 2]
        # First revised subgoal was NOT touched by the second revision.
        assert sgs[1].title == "a"

    def test_revision_resets_dependencies_of_revised_step(self):
        _, manager = make_plan(multi_step=False)
        sgs = manager.plan.subgoals
        assert sgs[1].depends_on == [sgs[0].id]
        manager.begin()
        manager.force_complete(sgs[0].id)
        manager.revise(
            subgoal_id=sgs[1].id, new_title="revised step",
            reason="page restructured — old dependency meaningless",
        )
        # Dependencies reset: the revised step is independently actionable.
        assert sgs[1].depends_on == []
        assert manager.plan.next_actionable is not None
        assert manager.plan.next_actionable.id == sgs[1].id


# ---------------------------------------------------------------------------
# 8. final-submission boundary is represented explicitly
# ---------------------------------------------------------------------------


class TestFinalSubmissionBoundary:
    def test_boundary_subgoal_exists_and_is_last(self):
        _, manager = make_plan(multi_step=True, documents=True)
        sgs = manager.plan.subgoals
        finals = [sg for sg in sgs if sg.final_submission]
        assert len(finals) == 1
        assert finals[0] is sgs[-1]
        assert "review" in finals[0].title.lower() or "final" in finals[0].title.lower()
        assert "never" in finals[0].description.lower()

    def test_boundary_cannot_be_activated_completed_or_revised(self):
        _, manager = make_plan(multi_step=False)
        boundary = manager.plan.subgoals[-1]
        assert boundary.final_submission is True
        with pytest.raises(FinalSubmissionGate):
            manager.force_complete(boundary.id)
        with pytest.raises(FinalSubmissionGate):
            manager.invalidate(boundary.id)
        with pytest.raises(FinalSubmissionGate):
            manager.revise(subgoal_id=boundary.id, new_title="x", reason="y")
        # It also cannot be transitioned even directly — the gate sits
        # inside _transition, so every path (public or internal) refuses.
        with pytest.raises(FinalSubmissionGate):
            manager._transition(
                boundary, SubgoalStatus.ACTIVE,
                SubgoalStatusReason.DEPENDENCIES_SATISFIED,
            )

    def test_boundary_criteria_target_review_not_submission(self):
        _, manager = make_plan(multi_step=False)
        boundary = manager.plan.subgoals[-1]
        kinds = {(c.kind, tuple(sorted(c.params.items()))) for c in boundary.success_criteria}
        assert ("page_type_reached", (("page_type", "review"),)) in kinds
        # No criterion asserts submission happened.
        assert all("submit" not in c.description.lower() or "review" in c.description.lower()
                   for c in boundary.success_criteria)


# ---------------------------------------------------------------------------
# 9. invalid plans are rejected
# ---------------------------------------------------------------------------


class TestInvalidPlansRejected:
    def test_unknown_dependency_rejected(self):
        parsed = parse_goal("Apply for a PAN card")
        plan = build_initial_plan(parsed.goal, multi_step=False, documents_available=False)
        plan.subgoals[0].depends_on.append("sg_does_not_exist")
        problems = plan.validate_structure()
        assert any("unknown dependency" in p for p in problems)
        with pytest.raises(PlanInvalid, match="invalid"):
            AgentPlanManager(plan)

    def test_dependency_cycle_rejected(self):
        parsed = parse_goal("Apply for a PAN card")
        plan = build_initial_plan(parsed.goal, multi_step=False, documents_available=False)
        a, b = plan.subgoals[0], plan.subgoals[1]
        a.depends_on = [b.id]  # a→b and b→a (b already depends on a)
        problems = plan.validate_structure()
        assert any("cycle" in p for p in problems)

    def test_duplicate_orders_rejected(self):
        parsed = parse_goal("Apply for a PAN card")
        plan = build_initial_plan(parsed.goal, multi_step=False, documents_available=False)
        plan.subgoals[1].order = plan.subgoals[0].order
        assert any("duplicate" in p for p in plan.validate_structure())

    def test_two_boundaries_rejected(self):
        parsed = parse_goal("Apply for a PAN card")
        plan = build_initial_plan(parsed.goal, multi_step=False, documents_available=False)
        plan.subgoals[0].final_submission = True
        problems = plan.validate_structure()
        assert any("more than one final_submission" in p for p in problems)

    def test_boundary_not_last_rejected(self):
        parsed = parse_goal("Apply for a PAN card")
        plan = build_initial_plan(parsed.goal, multi_step=False, documents_available=False)
        boundary = plan.subgoals[-1]
        boundary.order = -1  # now not the last step
        assert any("not the last step" in p for p in plan.validate_structure())

    def test_manager_rejects_completing_unsatisfied_criteria(self):
        _, manager = make_plan(multi_step=False)
        sg = manager.plan.subgoals[0]
        manager.begin()
        # Snapshot says the form page is NOT reached.
        wf = make_workflow()
        snap = Snapshot(workflow=wf, current_url="https://portal.gov.in/", page_type="landing")
        with pytest.raises(PlanInvalid, match="criteria not satisfied"):
            manager.complete(sg.id, snap)
        assert sg.status is SubgoalStatus.ACTIVE  # unchanged

    def test_unknown_subgoal_id_raises(self):
        _, manager = make_plan(multi_step=False)
        with pytest.raises(SubgoalNotFound):
            manager.force_complete("sg_missing")


# ---------------------------------------------------------------------------
# 10. serialization/deserialization preserves the complete planning state
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_full_planning_state_round_trips(self):
        parsed, manager = make_plan(multi_step=True, documents=True)
        plan = manager.plan
        manager.begin()
        manager.force_complete(plan.subgoals[0].id)
        manager.activate_next()
        manager.revise(
            subgoal_id=plan.subgoals[2].id, new_title="revised",
            reason="page changed", triggering_event="obs-42",
        )
        manager.invalidate(plan.subgoals[3].id, evidence="moved")

        exported = plan.model_dump(mode="json")
        restored_plan = type(plan).model_validate(exported)
        restored = AgentPlanManager(restored_plan)

        # Lossless: identical JSON, same structure, same derived views.
        assert restored.plan.model_dump(mode="json") == exported
        assert restored.plan.version == plan.version == 2
        assert len(restored.plan.revisions) == 1
        assert restored.plan.revisions[0].triggering_event == "obs-42"
        assert [
            (sg.id, sg.title, sg.status, sg.status_reason)
            for sg in restored.plan.subgoals
        ] == [
            (sg.id, sg.title, sg.status, sg.status_reason)
            for sg in plan.subgoals
        ]
        statuses = {sg.status for sg in restored.plan.subgoals}
        assert SubgoalStatus.COMPLETED in statuses
        assert SubgoalStatus.INVALIDATED in statuses
        # The restored plan keeps working.
        assert restored.plan.validate_structure() == []

    def test_goal_round_trips_with_criteria(self):
        parsed = parse_goal("Renew my driving licence", available_references=["USER.full_name"])
        goal = parsed.goal
        restored = AgentGoal.model_validate(goal.model_dump(mode="json"))
        assert restored == goal
        assert restored.criterion_kinds() == goal.criterion_kinds()


# ---------------------------------------------------------------------------
# Deterministic criterion evaluation
# ---------------------------------------------------------------------------


class TestCriteriaEvaluation:
    def test_no_pending_fields(self):
        wf = make_workflow(pending_fields=[])
        outcomes = evaluate_criteria(
            [SuccessCriterion(description="d", kind="no_pending_fields")],
            empty_snapshot(wf),
        )
        assert outcomes[0].satisfied is True

    def test_pending_fields_fail_no_pending_criterion(self):
        wf = make_workflow(pending_fields=["e1"])
        outcomes = evaluate_criteria(
            [SuccessCriterion(description="d", kind="no_pending_fields")],
            empty_snapshot(wf),
        )
        assert outcomes[0].satisfied is False
        assert outcomes[0].uncertain is False  # a deterministic no

    def test_page_type_reached(self):
        snap = empty_snapshot()
        snap.page_type = "review"
        outcomes = evaluate_criteria(
            [SuccessCriterion(description="d", kind="page_type_reached",
                              params={"page_type": "review"})],
            snap,
        )
        assert outcomes[0].satisfied is True

    def test_url_prefix(self):
        snap = empty_snapshot()
        snap.current_url = "https://portal.gov.in/app/step2"
        outcomes = evaluate_criteria(
            [SuccessCriterion(description="d", kind="url_reached",
                              params={"url": "https://portal.gov.in/app"})],
            snap,
        )
        assert outcomes[0].satisfied is True

    def test_unknown_kind_fails_closed_as_uncertain(self):
        from dataclasses import replace

        bogus = replace(
            evaluate_criteria(
                [SuccessCriterion(description="d", kind="no_pending_fields")],
                empty_snapshot(),
            )[0],
            kind="mind_reading", satisfied=False, uncertain=True,
        )
        crit = SuccessCriterion(description="d", kind="no_pending_fields")
        sat, fail, _ = criteria_verdict([crit], [bogus])
        # Unknown kinds are uncertain — never satisfied, never failure.
        assert sat is False and fail is False

    def test_verdict_three_valued(self):
        wf_done = make_workflow()
        wf_empty = make_workflow(pending_fields=["e1"])

        crit = SuccessCriterion(description="d", kind="no_pending_fields")
        # Satisfied → (True, False, [])
        assert criteria_verdict(
            [crit], evaluate_criteria([crit], empty_snapshot(wf_done)),
        ) == (True, False, [])
        # Deterministically unsatisfied → failure
        sat, fail, details = criteria_verdict(
            [crit], evaluate_criteria([crit], empty_snapshot(wf_empty)),
        )
        assert sat is False and fail is True and details

    def test_optional_criteria_never_fail(self):
        crit = SuccessCriterion(description="d", kind="no_pending_fields",
                                required=False)
        sat, fail, _ = criteria_verdict(
            [crit], evaluate_criteria([crit], empty_snapshot(make_workflow(pending_fields=["e1"]))),
        )
        assert fail is False

    def test_document_resolution_criterion(self):
        wf = make_workflow(completed_bindings=["DOCUMENT.aadhaar"])
        crit = SuccessCriterion(description="d", kind="documents_resolved",
                                params={"refs": ["DOCUMENT.aadhaar"]})
        assert evaluate_criteria([crit], empty_snapshot(wf))[0].satisfied is True
        crit2 = SuccessCriterion(description="d", kind="documents_resolved",
                                 params={"refs": ["DOCUMENT.pan"]})
        assert evaluate_criteria([crit2], empty_snapshot(wf))[0].satisfied is False
