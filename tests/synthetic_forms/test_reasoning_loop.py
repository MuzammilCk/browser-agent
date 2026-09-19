"""Phase 4 exit criterion — mock decision model drives a real form.

Exit criterion (implementation_plan.md Phase 4):
    "The model chooses among multiple tools over multiple iterations
     while deterministic runtime rules remain authoritative."

The AgentReasoner is the decision-making controller: each iteration
assembles the bounded reasoning context from the AUTHORITATIVE
observation, the mock model emits ONE decision, it is schema-validated
into an AgentDecision, and executed through the REAL ToolRegistry →
BrowserExecutor path (PolicyEngine + verification intact — Phase 3
code, unchanged). The mock proves the loop; no LLM API is involved.

Also proven on this page:
- tool failure handling: the model's first fill targets a stale ref,
  receives STALE_OR_INVALID_TARGET in the next context's
  recent_tool_results, and recovers by re-observing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
from app.agent.tools import ToolContext, ToolRegistry, build_registry
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.workflow_state import WorkflowState, WorkflowStatus

SYNTHETIC_PAGES_DIR = Path(__file__).parent / "pages"
BASE = SYNTHETIC_PAGES_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


def _find_by_name(payload: dict, html_name: str) -> dict | None:
    """Deterministic mock-model perception: find an element by its
    html_name attribute in the context's page_observation (as an LLM
    would pick a field by its form name)."""
    for el in payload.get("page_observation", {}).get("elements", []):
        if el.get("html_name") == html_name:
            return el
    return None


def _find_button(payload: dict, *keywords: str) -> dict | None:
    for el in payload.get("page_observation", {}).get("elements", []):
        if el.get("role") == "button" and el.get("name"):
            if all(k in el["name"].lower() for k in keywords):
                return el
    return None


def decision(
    tool_name: str, action: dict | None = None,
    reason: str = "", arguments: dict | None = None,
) -> dict:
    d: dict[str, Any] = {
        "decision_type": "tool_call", "tool_name": tool_name,
        "arguments": arguments or {}, "reason": reason,
        "question": "", "plan": [], "confidence": None,
    }
    if action is not None:
        d["action"] = action
    return d


def fill_decision(html_name: str, value: str) -> Any:
    async def _decide(*, system: str, context: str) -> dict:
        payload = json.loads(context)
        el = _find_by_name(payload, html_name)
        assert el is not None, f"mock model: {html_name} not visible"
        return decision("fill_field", action={
            "action": "fill", "target_ref": el["ref"],
            "literal_value": value,
        }, reason=f"fill {html_name}")
    return _decide


def select_decision(html_name: str, option: str) -> Any:
    async def _decide(*, system: str, context: str) -> dict:
        payload = json.loads(context)
        el = _find_by_name(payload, html_name)
        assert el is not None, f"mock model: {html_name} not visible"
        return decision("select_option", action={
            "action": "select", "target_ref": el["ref"], "option": option,
        }, reason=f"select {option}")
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


async def run_mock_model_loop(
    page,
    script: list[Any],
    *,
    registry: ToolRegistry,
    manager: BrowserManager,
) -> dict:
    """Run the full Phase 4 loop: assemble → reason → decide → execute.

    Returns a recording of decisions, results, prompts and lifecycle.
    """
    observer = PageObserver()
    executor = BrowserExecutor()
    observation = await observer.observe(page)
    ctx = ToolContext(
        observation=observation, page=page,
        executor=executor, observer=observer,
        metadata={"browser_manager": manager},
    )
    registry = registry  # real Phase 3 registry
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
        workflow_id="phase4-exit",
        task_description="Complete the application wizard",
        status=WorkflowStatus.RUNNING,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    from app.agent.runtime.decision import AgentDecisionType

    recording: dict[str, Any] = {
        "decisions": [], "results": [], "prompts": [],
        "model_failure": None,
    }
    for step in script:
        context = build_reasoning_context(
            goal="Complete the application wizard",
            subgoal="current step",
            observation=ctx.observation,
            tool_metadata=[
                registry.metadata(name) for name in registry.list_names()
            ],
            recent_results=recording["results"][-5:],
            unresolved_questions=[],
        )
        recording["prompts"].append(context.render())
        outcome = await reasoner.reason(
            context, observation_id=ctx.observation.observation_id,
        )
        if not outcome.decided:
            recording["model_failure"] = {
                "code": outcome.model_failure_code, "reason": outcome.reason,
            }
            break
        d = outcome.decision
        assert d is not None
        recording["decisions"].append({
            "type": d.decision_type.value,
            "tool": d.tool_name,
        })
        if d.decision_type is not AgentDecisionType.TOOL_CALL:
            continue
        result = await registry.execute(decision_to_tool_call(d), ctx)
        recording["results"].append(result)
    # The context observation is the AUTHORITATIVE final browser state
    # (read tools update it in place; mutating tools via post_observation).
    recording["final_observation"] = ctx.observation
    return recording


class TestMockModelCompletesWizard:
    @pytest.mark.asyncio
    async def test_model_chooses_multiple_tools_over_multiple_iterations(
        self, settings: Settings,
    ):
        """EXIT CRITERION: the model (mock) chooses among multiple tools
        (observe_page, fill_field, select_option, click) over multiple
        iterations while deterministic runtime rules (ToolRegistry →
        PolicyEngine → executor) remain authoritative."""
        registry = build_registry()
        script: list[Any] = [
            observe_decision(),
            fill_decision("name", "Rahul Sharma"),
            fill_decision("dob", "1994-06-15"),
            select_decision("gender", "Male"),
            click_decision("next"),
            observe_decision(),
            fill_decision("email", "rahul@example.com"),
            fill_decision("phone", "9876543210"),
            click_decision("next"),
            observe_decision(),
        ]
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            recording = await run_mock_model_loop(
                page, script, registry=registry, manager=manager,
            )

        assert recording["model_failure"] is None
        chosen_tools = [d["tool"] for d in recording["decisions"]]
        # Multiple DIFFERENT tools over multiple iterations:
        assert chosen_tools == [
            "observe_page", "fill_field", "fill_field", "select_option",
            "click", "observe_page", "fill_field", "fill_field", "click",
            "observe_page",
        ]
        assert len(set(chosen_tools)) == 4
        # Every result succeeded through the real registry+executor path.
        assert len(recording["results"]) == 10
        assert all(r.success for r in recording["results"])
        # The mock model READ the authoritative observation: refs it used
        # were validated against the live page (any stale ref would have
        # failed at the registry/executor with STALE_OR_INVALID_TARGET).

        # Deterministic runtime remained authoritative end-to-end: the
        # final observation is the review step — a page the mock model
        # only knows because the executor reported it.
        review_elements = [
            el for el in recording["final_observation"].page_state.elements
            if el.visible
        ]
        assert any(
            el.role == "button" and "submit" in (el.accessible_name or "").lower()
            for el in review_elements
        )

    @pytest.mark.asyncio
    async def test_model_handles_tool_failure_and_recovers(
        self, settings: Settings,
    ):
        """The scripted first fill targets a stale ref (obs-ancient). The
        runtime binds actions to the CURRENT observation, so the registry
        rejects it; the next context carries the failure in
        recent_tool_results and the mock model recovers by re-observing."""
        registry = build_registry()

        async def bogus_ref_fill(*, system: str, context: str) -> dict:
            payload = json.loads(context)
            el = _find_by_name(payload, "name")
            assert el is not None
            # Model "misremembers" the ref: it names a ref that does not
            # exist in the CURRENT observation. The parser stamps the
            # current observation_id (the model cannot smuggle a stale
            # binding), but the unknown ref fails at the registry/tool:
            return decision("fill_field", action={
                "action": "fill", "target_ref": "e999",
                "literal_value": "Rahul Sharma",
            }, reason="fill from memory")

        script: list[Any] = [
            bogus_ref_fill,
            observe_decision(),
            fill_decision("name", "Rahul Sharma"),
        ]
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            recording = await run_mock_model_loop(
                page, script, registry=registry, manager=manager,
            )

        assert recording["model_failure"] is None
        # First call failed with the stale/invalid-target error...
        assert recording["results"][0].success is False
        assert recording["results"][0].error_code == "STALE_OR_INVALID_TARGET"
        # ...the recovery decisions followed, and the fill then succeeded.
        assert recording["decisions"][1]["tool"] == "observe_page"
        assert recording["results"][-1].success is True

        # The failure was surfaced to the model in the NEXT context.
        second_prompt = json.loads(recording["prompts"][1])
        recent = second_prompt["recent_tool_results"]
        assert recent and recent[0]["error_code"] == "STALE_OR_INVALID_TARGET"

    @pytest.mark.asyncio
    async def test_parser_overrides_model_supplied_observation_id(self):
        """Off-browser proof: the runtime binds every action to the CURRENT
        observation id — a stale one in the model's action dict is
        overwritten, never trusted."""
        from app.agent.reasoning import parse_model_decision

        decision_obj, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {
                    "action": "fill", "target_ref": "e1",
                    "literal_value": "x",
                    "observation_id": "obs-STALE",
                },
            },
            known_tools={"fill_field"}, action_tools={"fill_field"},
            observation_id="obs-CURRENT",
        )
        assert failure is None and decision_obj is not None
        assert decision_obj.action is not None
        assert decision_obj.action.observation_id == "obs-CURRENT"

    @pytest.mark.asyncio
    async def test_model_failure_is_explicit_in_loop(
        self, settings: Settings,
    ):
        """A mock model that always returns garbage produces a visible
        MODEL_FAILURE in the loop recording — never a silent fallback."""
        registry = build_registry()
        garbage = {"decision_type": "nope"}
        script: list[Any] = [garbage, garbage, garbage]
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            recording = await run_mock_model_loop(
                page, script, registry=registry, manager=manager,
            )
        assert recording["model_failure"] is not None
        assert recording["model_failure"]["code"] == "DECISION_SCHEMA_INVALID"
        assert recording["model_failure"]["reason"].startswith("model_failure:")
        assert recording["decisions"] == []
