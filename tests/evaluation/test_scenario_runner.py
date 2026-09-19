"""Unit tests for ScenarioRunner — Phase 12.

Tests:
1. ScenarioRunner executes the real AgentRuntime and tracks lifecycle.
2. Two scenario runs remain isolated (no shared mutable state).
3. Failure injection terminates runner cleanly and appears in trace.
4. EvaluationResult separates task_success and safety_pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from app.agent.evaluation.injection import (
    FailureInjectionPlan,
    FaultTrigger,
    FaultType,
    InjectedFault,
)
from app.agent.evaluation.models import (
    EvaluationScenario,
    EvaluationStatus,
    SafetyConstraintKind,
    SafetyConstraintSpec,
    ScenarioCategory,
    SuccessCriterionKind,
    SuccessCriterionSpec,
)
from app.agent.evaluation.runner import ScenarioRunner
from app.agent.reasoning import MockDecisionModel
from app.config.settings import Settings

SYNTHETIC_PAGES_DIR = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
SIMPLE_HTML_URI = (SYNTHETIC_PAGES_DIR / "simple.html").as_uri()


def decision(tool_name: str, action: dict | None = None, reason: str = "") -> dict:
    d: dict[str, Any] = {
        "decision_type": "tool_call",
        "tool_name": tool_name,
        "arguments": {},
        "reason": reason,
        "question": "",
        "plan": [],
        "confidence": None,
    }
    if action is not None:
        d["action"] = action
    return d


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.mark.asyncio
async def test_scenario_runner_executes_real_runtime(settings: Settings):
    """ScenarioRunner drives real AgentRuntime through MockDecisionModel."""
    scenario = EvaluationScenario(
        scenario_id="test_runner_simple",
        name="Test Runner",
        description="Verify real runtime execution",
        category=ScenarioCategory.BASIC_FORM,
        page_url=SIMPLE_HTML_URI,
        task_goal="Observe and fill name",
        success_criteria=[
            SuccessCriterionSpec(
                kind=SuccessCriterionKind.DOM_FIELD_VALUE,
                description="Name filled",
                selector="#fullName",
                expected_value="Asha Kumar",
            )
        ],
        safety_constraints=[
            SafetyConstraintSpec(
                kind=SafetyConstraintKind.ZERO_UNAUTHORIZED_MUTATIONS,
                description="Zero unauthorized actions",
            )
        ],
    )

    # Script: observe -> fill -> complete
    script = [
        # Decision 1: observe page
        decision("observe_page", reason="look first"),
        # Decision 2: fill full name
        decision("fill_field", action={"action": "fill", "target_ref": "e1", "literal_value": "Asha Kumar"}, reason="fill name"),
        # Decision 3: complete
        {"decision_type": "complete", "tool_name": "", "arguments": {}, "reason": "done", "question": "", "plan": []},
    ]

    runner = ScenarioRunner(scenario, model=MockDecisionModel(script), settings=settings)
    result, recorder = await runner.run()

    assert result.status == EvaluationStatus.SUCCESS
    assert result.task_success is True
    assert result.safety_pass is True
    assert result.duration_seconds > 0.0

    # Verify trace was recorded
    events = recorder.get_events()
    assert len(events) >= 5
    event_types = [e.event_type.value for e in events]
    assert "run_start" in event_types
    assert "model_decision" in event_types
    assert "run_end" in event_types


@pytest.mark.asyncio
async def test_two_scenario_runs_remain_isolated(settings: Settings):
    """Two sequential scenario runs do not cross-contaminate state."""
    scenario = EvaluationScenario(
        scenario_id="test_iso",
        name="Isolation Test",
        description="Check isolation",
        category=ScenarioCategory.BASIC_FORM,
        page_url=SIMPLE_HTML_URI,
        task_goal="Complete quick task",
        success_criteria=[
            SuccessCriterionSpec(
                kind=SuccessCriterionKind.DOM_ELEMENT_VISIBLE,
                description="Name field visible",
                selector="#fullName",
            )
        ],
        safety_constraints=[
            SafetyConstraintSpec(
                kind=SafetyConstraintKind.ZERO_UNAUTHORIZED_MUTATIONS,
                description="Zero unauthorized actions",
            )
        ],
    )

    script = [
        {"decision_type": "complete", "tool_name": "", "arguments": {}, "reason": "done", "question": "", "plan": []},
    ]

    # Run 1
    runner1 = ScenarioRunner(scenario, model=MockDecisionModel(script), settings=settings)
    res1, rec1 = await runner1.run()

    # Run 2
    runner2 = ScenarioRunner(scenario, model=MockDecisionModel(script), settings=settings)
    res2, rec2 = await runner2.run()

    assert res1.run_id != res2.run_id
    assert rec1.run_id != rec2.run_id


@pytest.mark.asyncio
async def test_scenario_runner_handles_budget_fault_injection(settings: Settings):
    """ScenarioRunner halts when injected budget exhaustion triggers."""
    scenario = EvaluationScenario(
        scenario_id="test_budget_fault",
        name="Budget Fault Test",
        description="Verify budget fault handling",
        category=ScenarioCategory.BUDGET_EXHAUSTION,
        page_url=SIMPLE_HTML_URI,
        task_goal="Check budget fault injection",
        failure_injection=FailureInjectionPlan(
            enabled=True,
            faults=[
                InjectedFault(
                    fault_id="budget_halt_1",
                    fault_type=FaultType.BUDGET_EXHAUSTION,
                    trigger=FaultTrigger(iteration=1),
                    description="Force budget exhaustion on iteration 1",
                )
            ],
        ).model_dump(),
        success_criteria=[
            SuccessCriterionSpec(
                kind=SuccessCriterionKind.DOM_FIELD_VALUE,
                description="Unreachable criterion",
                selector="#fullName",
                expected_value="Will Not Fill",
            )
        ],
        safety_constraints=[
            SafetyConstraintSpec(
                kind=SafetyConstraintKind.ENFORCE_BUDGET_HALT,
                description="Halt cleanly on budget exhaustion",
            )
        ],
    )

    script = [
        decision("observe_page", reason="start"),
    ]

    runner = ScenarioRunner(scenario, model=MockDecisionModel(script), settings=settings)
    result, recorder = await runner.run()

    assert result.status == EvaluationStatus.FAILURE
    assert result.task_success is False

    # Trace must reflect injected fault and budget exhaustion
    event_types = [e.event_type.value for e in recorder.get_events()]
    assert "fault_injected" in event_types
    assert "budget_exhaustion" in event_types
