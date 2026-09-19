"""Phase 5 acceptance test — local page change invalidates ONE subgoal.

Most important acceptance test (user instruction, Phase 5):

- Goal contains multiple steps.
- Plan contains multiple subgoals.
- One subgoal completes successfully.
- A later page change invalidates another subgoal.
- The planner revises that subgoal.
- Previously completed work remains completed.
- The overall goal remains active.
- The agent continues from the revised subgoal instead of restarting.

The strategic layer (AgentGoal/AgentPlan/AgentPlanManager) is the REAL
Phase 5 code; the tactical loop is the REAL Phase 4 reasoning loop; the
browser boundary is REAL Chromium via the Phase 1–3 stack. The decision
model is the deterministic mock (same rationale as Phase 4's exit test:
prove the runtime behavior, not model quality).

Scenario (tests/synthetic_forms/pages/dynamic_step_change.html):
  Stage 1: full_name + email  →  Continue
  Stage 2: REPLACED contact layout (phone + address; email section gone)
  Stage 3: review

Plan (portal-agnostic): reach-form → fill-primary → fill-contact →
resolve-ambiguities → [review boundary]. The mock model fills the
primary fields and clicks Continue (page change). The deterministic
invalidation check finds the active subgoal's expected fields gone,
invalidates it, the model proposes a REPLAN, the MANAGER applies the
revision, and the loop continues from the revised subgoal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.reasoning import (
    AgentReasoner,
    MockDecisionModel,
    ReasonerConfig,
    build_reasoning_context,
    decision_to_tool_call,
)
from app.agent.strategy import (
    AgentPlanManager,
    Snapshot,
    SubgoalStatus,
    build_initial_plan,
    parse_goal,
)
from app.agent.tools import ToolContext, ToolRegistry, build_registry
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.workflow_state import ActionRecord, WorkflowState, WorkflowStatus

SYNTHETIC_PAGES_DIR = Path(__file__).parent / "pages"
BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


# ---------------------------------------------------------------------------
# Mock-model perception helpers (deterministic, same style as Phase 4)
# ---------------------------------------------------------------------------


def _elements(payload: dict) -> list[dict]:
    return payload.get("page_observation", {}).get("elements", []) or []


def _find_by_name(payload: dict, html_name: str) -> dict | None:
    for el in _elements(payload):
        if el.get("html_name") == html_name:
            return el
    return None


def _find_button(payload: dict, *keywords: str) -> dict | None:
    for el in _elements(payload):
        if el.get("role") == "button" and el.get("name"):
            if all(k in el["name"].lower() for k in keywords):
                return el
    return None


def decision(tool_name: str, action: dict | None = None, reason: str = "") -> dict:
    d: dict[str, Any] = {
        "decision_type": "tool_call", "tool_name": tool_name,
        "arguments": {}, "reason": reason,
        "question": "", "plan": [], "confidence": None,
    }
    if action is not None:
        d["action"] = action
    return d


def replan_decision(steps: list[dict], reason: str) -> dict:
    return {
        "decision_type": "replan", "tool_name": None,
        "arguments": {}, "reason": reason, "question": "",
        "plan": steps, "confidence": None,
    }


def fill_decision(html_name: str, value: str) -> Any:
    async def _decide(*, system: str, context: str) -> dict:
        payload = json.loads(context)
        el = _find_by_name(payload, html_name)
        assert el is not None, f"mock model: {html_name} not visible"
        return decision("fill_field", action={
            "action": "fill", "target_ref": el["ref"], "literal_value": value,
        }, reason=f"fill {html_name}")
    return _decide


def click_decision(*keywords: str) -> Any:
    async def _decide(*, system: str, context: str) -> dict:
        payload = json.loads(context)
        el = _find_button(payload, *keywords)
        assert el is not None, f"mock model: button {keywords} not visible"
        return decision("click", action={
            "action": "click", "target_ref": el["ref"],
        }, reason=f"click {keywords}")
    return _decide


def observe_decision() -> dict:
    return decision("observe_page", reason="look before acting")


# ---------------------------------------------------------------------------
# Strategic-loop machinery
# ---------------------------------------------------------------------------

# Subgoal title → the html_names its premise assumes exist on the page.
SUBGOAL_FIELD_EXPECTATIONS: dict[str, list[str]] = {
    "Fill primary details": ["full_name", "email"],
    "Complete remaining sections": ["email"],  # premise: email section ahead
}


def _invalidate_stale_subgoals(manager: AgentPlanManager, payload: dict) -> list[str]:
    """Deterministic invalidation check: if the ACTIVE subgoal expects
    fields that no longer exist in the CURRENT observation, its premise
    vanished — invalidate it with the page-change evidence.

    Returns the ids of invalidated subgoals.
    """
    invalidated: list[str] = []
    for sg in manager.plan.by_status(SubgoalStatus.ACTIVE):
        expected = SUBGOAL_FIELD_EXPECTATIONS.get(sg.title, [])
        if not expected:
            continue
        present = {el.get("html_name") for el in _elements(payload)}
        missing = [f for f in expected if f not in present]
        if missing:
            manager.invalidate(
                sg.id,
                evidence=(
                    f"page changed: expected field(s) {missing} no longer "
                    "present on the current page"
                ),
            )
            invalidated.append(sg.id)
    return invalidated


async def run_strategic_loop(page, manager: AgentPlanManager, script: list) -> dict:
    """Drive the full loop: plan subgoal context → reason → execute.

    Strategic state advances ONLY through the AgentPlanManager against
    real observations. REPLAN decisions from the model are applied by
    the MANAGER (the model proposes; the deterministic layer authorizes
    plan structure). The mock model behaves exactly like the Phase 4
    loop: one decision per iteration, executed through ToolRegistry.
    """
    observer = PageObserver()
    executor = BrowserExecutor()
    observation = await observer.observe(page)
    ctx = ToolContext(
        observation=observation, page=page,
        executor=executor, observer=observer,
        metadata={"browser_manager": None},  # no navigation in this scenario
    )
    registry = build_registry()
    known_tools = frozenset(registry.list_names())
    action_tools = frozenset(
        name for name in registry.list_names()
        if registry.metadata(name) is not None
        and registry.metadata(name).accepts_browser_action
    )
    model = MockDecisionModel(script)
    reasoner = AgentReasoner(
        model, known_tools=known_tools, action_tools=action_tools,
        config=ReasonerConfig(max_attempts=3),
    )

    workflow = WorkflowState(
        workflow_id="phase5-accept",
        task_description="Complete the dynamic application",
        status=WorkflowStatus.RUNNING,
        created_at="2026-09-19T00:00:00+00:00",
    )

    recording: dict[str, Any] = {
        "decisions": [], "results": [], "subgoal_history": [],
        "revisions": [], "model_failure": None,
    }
    # Subgoals invalidated but not yet revised (the REPLAN decision that
    # resolves them arrives on a LATER iteration — observe first, then
    # propose the revised step).
    pending_invalidated: list[str] = []

    def _history() -> list[dict]:
        return [
            {"id": sg.id[-6:], "title": sg.title, "status": sg.status.value}
            for sg in manager.plan.subgoals
        ]

    manager.begin()
    recording["subgoal_history"].append(("begin", _history()))

    for step_index in range(len(script)):
        # Stop before the human-gated boundary: never planner-actionable.
        if manager.plan.at_final_boundary:
            recording["subgoal_history"].append((f"boundary@{step_index}", _history()))
            break

        # 1. Advance plan state from the CURRENT authoritative observation.
        payload = json.loads(build_reasoning_context(
            goal=manager.plan.goal_id,
            observation=ctx.observation,
            tool_metadata=[
                registry.metadata(name) for name in registry.list_names()
            ],
        ).render())
        # Per-observation pending-field tracking (the runner's normal
        # job): required, visible, still-empty inputs on the CURRENT page.
        workflow.pending_fields = [
            el["ref"] for el in _elements(payload)
            if el.get("required") and not el.get("value")
        ]
        snapshot = Snapshot.from_sources(workflow, ctx.observation)
        manager.evaluate_active(snapshot)

        # 2. Deterministic invalidation: did the page change under the
        #    active subgoal?
        pending_invalidated.extend(
            _invalidate_stale_subgoals(manager, payload)
        )

        # 3. Activate the next subgoal when nothing is active.
        if not manager.plan.by_status(SubgoalStatus.ACTIVE):
            manager.recover_blocked()
            if manager.plan.next_actionable is not None:
                manager.activate_next()
        recording["subgoal_history"].append((f"plan@{step_index}", _history()))

        active = manager.plan.by_status(SubgoalStatus.ACTIVE)
        active_title = active[0].title if active else "(none)"

        context = build_reasoning_context(
            goal=manager.plan.goal_id,
            subgoal=active_title,
            plan=[sg.model_dump(mode="json") for sg in manager.plan.subgoals],
            workflow=workflow,
            observation=ctx.observation,
            tool_metadata=[
                registry.metadata(name) for name in registry.list_names()
            ],
            recent_results=recording["results"][-5:],
            unresolved_questions=[],
        )
        outcome = await reasoner.reason(
            context, observation_id=ctx.observation.observation_id,
        )
        if not outcome.decided:
            recording["model_failure"] = {
                "code": outcome.model_failure_code, "reason": outcome.reason,
            }
            break
        d = outcome.decision
        recording["decisions"].append({
            "type": d.decision_type.value,
            "tool": d.tool_name, "subgoal": active_title,
        })

        # 4. REPLAN: the model proposes a revised subgoal; the MANAGER
        #    applies it deterministically (id/order/dependents preserved;
        #    completed work untouched). Revision targets the OLDEST still-
        #    unrevised invalidated subgoal (carried across iterations).
        if d.decision_type.value == "replan" and d.plan:
            if pending_invalidated:
                proposed = d.plan[0]
                result_rev = manager.revise(
                    subgoal_id=pending_invalidated.pop(0),
                    new_title=proposed.get("title", "revised step"),
                    new_description=proposed.get("description", ""),
                    reason=proposed.get("reason", d.reason),
                    triggering_event=d.reason,
                )
                recording["revisions"].append(result_rev.revision)
            continue

        if d.tool_name is None:
            continue
        result = await registry.execute(decision_to_tool_call(d), ctx)
        recording["results"].append(result)
        workflow.record_action(ActionRecord(
            action_type=result.tool_name, success=result.success,
            message=result.message,
            observation_id=result.observation_id,
            timestamp="2026-09-19T00:00:0%d+00:00" % (step_index % 10),
        ))
        # Clicks change the page → adopt the fresh observation.
        if result.post_observation is not None:
            ctx.observation = result.post_observation

    recording["final_observation"] = ctx.observation
    recording["workflow"] = workflow
    return recording


# ---------------------------------------------------------------------------
# The acceptance test
# ---------------------------------------------------------------------------


class TestDynamicFormInvalidation:
    @pytest.mark.asyncio
    async def test_page_change_invalidates_one_subgoal_goal_survives(
        self, settings,
    ):
        # ---- Goal + plan (multiple steps, multiple subgoals) ----
        parsed = parse_goal(
            "Apply for the service using my saved details and stop at review",
            available_references=["USER.full_name"],
        )
        assert parsed.multi_step_hint is True
        plan = build_initial_plan(
            parsed.goal, multi_step=True, documents_available=False,
        )
        manager = AgentPlanManager(plan)
        assert len(plan.subgoals) == 5
        primary = plan.subgoals[1]   # fill primary details
        contact = plan.subgoals[2]   # fill remaining/contact sections
        boundary = plan.subgoals[-1]
        assert boundary.final_submission is True

        # ---- Scripted mock model: fills, Continue (page change), observe,
        #      REPLAN (model proposes revised contact step), fills of the
        #      NEW fields, Review, observe ----
        script: list = [
            observe_decision(),
            fill_decision("full_name", "Rahul Sharma"),
            fill_decision("email", "rahul@example.com"),
            click_decision("continue"),          # → REPLACED contact layout
            observe_decision(),                  # observe the new layout
            replan_decision(
                [{
                    "title": "Fill updated contact section",
                    "description": "Portal replaced email section with "
                                   "phone + address fields.",
                    "reason": "Page changed: contact layout replaced after "
                              "Continue; email fields gone, phone/address "
                              "fields present",
                }],
                reason="Page changed: contact layout replaced after Continue",
            ),
            fill_decision("phone", "9876543210"),
            fill_decision("address", "MG Road, Bengaluru"),
            click_decision("review"),
            observe_decision(),
        ]

        async with BrowserManager(settings) as browser_manager:
            page = await browser_manager.open(f"{BASE}/dynamic_step_change.html")
            recording = await run_strategic_loop(page, manager, script)

        assert recording["model_failure"] is None, recording["model_failure"]

        # ---- One subgoal completed successfully (primary details) ----
        assert primary.status is SubgoalStatus.COMPLETED
        assert primary.completed_at is not None

        # ---- The page change invalidated the contact subgoal ----
        # (visible in the recorded plan history at invalidation time)
        assert any(
            entry["id"] == contact.id[-6:] and entry["status"] == "invalidated"
            for _label, snap in recording["subgoal_history"] for entry in snap
        )
        # The deterministic causal evidence is preserved on the subgoal.
        assert "expected field(s)" in contact.invalidation_evidence

        # ---- The planner revised that subgoal (not the whole plan) ----
        assert plan.version == 2
        assert len(plan.revisions) == 1
        revision = plan.revisions[0]
        assert revision.affected_subgoal_ids == [contact.id]
        assert revision.previous_version == 1 and revision.new_version == 2
        assert revision.triggering_event
        assert contact.title == "Fill updated contact section"
        # The revised subgoal keeps its identity slot in the plan.
        assert plan.subgoals[2] is contact
        # End state: the agent continued from the REVISED subgoal and
        # completed it (mid-run ACTIVE state is proven by the decision
        # labels below; completion here is the outcome of that work).
        assert contact.status is SubgoalStatus.COMPLETED

        # ---- Previously completed work remains completed ----
        assert primary.status is SubgoalStatus.COMPLETED
        assert plan.subgoals[0].status is SubgoalStatus.COMPLETED

        # ---- The overall goal remains active ----
        assert plan.goal_id == parsed.goal.goal_id
        assert plan.validate_structure() == []
        non_terminal = [sg for sg in plan.subgoals if not sg.is_terminal()]
        assert non_terminal, "goal must still have active work"

        # ---- The agent continued from the revised subgoal ----
        # It filled the NEW fields (phone/address) instead of restarting.
        fill_calls = [
            d for d in recording["decisions"] if d["tool"] == "fill_field"
        ]
        assert len(fill_calls) == 4  # name, email, phone, address
        assert all(r.success for r in recording["results"])
        # The fills after the revision happened under the REVISED subgoal.
        post_revision_fills = [
            d["subgoal"] for d in recording["decisions"]
            if d["tool"] == "fill_field"
        ]
        assert "Fill updated contact section" in post_revision_fills

        # ---- Review reached; boundary untouched (human decision) ----
        review_elements = [
            el for el in recording["final_observation"].page_state.elements
            if el.visible
        ]
        assert any(
            el.role == "button" and "submit" in (el.accessible_name or "").lower()
            for el in review_elements
        )
        assert boundary.status is SubgoalStatus.PENDING
        # The plan is parked AT the boundary: every non-boundary subgoal
        # is terminal, the boundary awaiting the HUMAN decision.
        assert plan.at_final_boundary is True
