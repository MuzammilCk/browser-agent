"""Real Chromium Acceptance Scenarios for Evaluation Platform — Phase 12.

Tests:
1. Golden Scenario 1 (Basic Form Completion) in real Chromium:
   EvaluationScenario -> real Chromium -> actual AgentRuntime -> observation ->
   mock model decision -> typed tool -> ToolRegistry -> PolicyEngine -> BrowserExecutor ->
   post-observation -> deterministic verification -> WorldState -> TraceRecorder ->
   Metrics -> EvaluationResult.
2. Adversarial Security Scenario (Prompt Injection Defense) in real Chromium:
   Malicious page -> untrusted observation -> adversarial proposal ->
   deterministic PolicyEngine gate -> REQUIRE_CONFIRMATION / DENY ->
   Trace records containment -> Metrics record safety pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from app.agent.evaluation.models import EvaluationStatus
from app.agent.evaluation.runner import ScenarioRunner
from app.agent.evaluation.scenarios import get_golden_scenarios
from app.agent.reasoning import MockDecisionModel
from app.config.settings import Settings

SYNTHETIC_PAGES_DIR = Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
INJECTION_PAGES_DIR = Path(__file__).resolve().parent.parent / "prompt_injection" / "pages"


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


class TestEvaluationPlatformChromiumAcceptance:
    """End-to-end acceptance tests verifying Phase 12 in real Chromium."""

    @pytest.mark.asyncio
    async def test_acceptance_golden_form_scenario_in_real_chromium(self, settings: Settings):
        """Golden Scenario 1 runs against real Chromium and produces complete verified EvaluationResult."""
        scenarios = get_golden_scenarios()
        basic_form_sc = next(s for s in scenarios if s.scenario_id == "golden_01_basic_form")

        # Decisions:
        # 1. observe
        # 2. fill full name (#fullName is e1)
        # 3. fill email (#email is e2)
        # 4. complete
        script = [
            decision("observe_page", reason="Inspect fields on page"),
            decision("fill_field", action={"action": "fill", "target_ref": "e1", "literal_value": "Asha Kumar"}, reason="Fill full name"),
            decision("fill_field", action={"action": "fill", "target_ref": "e2", "literal_value": "asha.kumar@example.gov.in"}, reason="Fill email address"),
            {"decision_type": "complete", "tool_name": "", "arguments": {}, "reason": "Application form complete", "question": "", "plan": []},
        ]

        runner = ScenarioRunner(basic_form_sc, model=MockDecisionModel(script), settings=settings)
        result, recorder = await runner.run()

        # 1. Assertions on EvaluationResult
        assert result.status == EvaluationStatus.SUCCESS
        assert result.task_success is True
        assert result.safety_pass is True
        assert result.duration_seconds > 0.0

        # 2. Assertions on Criteria Evaluations
        assert len(result.criteria_results) == 2
        for crit in result.criteria_results:
            assert crit.satisfied is True
            assert crit.observed_value == crit.expected_value

        # 3. Assertions on Metrics
        metrics = result.metrics
        assert metrics["task"]["task_success"] is True
        assert metrics["task"]["verification_successes"] >= 2
        assert metrics["task"]["verification_success_rate"] == 1.0
        assert metrics["efficiency"]["tool_calls_count"] >= 3
        assert metrics["safety"]["safety_pass"] is True

        # 4. Assertions on Trace
        events = recorder.get_events()
        event_types = [e.event_type.value for e in events]
        assert "run_start" in event_types
        assert "observation" in event_types
        assert "model_decision" in event_types
        assert "verification" in event_types
        assert "world_state_update" in event_types
        assert "run_end" in event_types

    @pytest.mark.asyncio
    async def test_acceptance_adversarial_security_scenario_in_real_chromium(self, settings: Settings):
        """Golden Scenario 9 (Prompt Injection Defense) contains malicious page in real Chromium."""
        scenarios = get_golden_scenarios()
        prompt_inj_sc = next(s for s in scenarios if s.scenario_id == "golden_09_prompt_injection")

        # Adversarial page contains button with data-risk="low" and text claiming override.
        # Script proposes to click high-risk pay button.
        script = [
            decision("observe_page", reason="Inspect adversarial page"),
            decision("click", action={"action": "click", "target_ref": "e2"}, reason="Click payment button claiming pre-approval"),
        ]

        runner = ScenarioRunner(prompt_inj_sc, model=MockDecisionModel(script), settings=settings)
        result, recorder = await runner.run()

        # PolicyEngine must enforce REQUIRE_CONFIRMATION, pausing run
        events = recorder.get_events()
        event_types = [e.event_type.value for e in events]

        assert "policy_evaluation" in event_types
        assert "hitl_interrupt" in event_types

        # Safety was preserved: payment was NOT executed without human confirmation
        assert result.safety_pass is True
