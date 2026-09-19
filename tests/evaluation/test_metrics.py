"""Unit tests for Multidimensional Metrics Engine — Phase 12.

Tests:
1. Metrics calculate accurately from trace events.
2. Metrics do not depend on model self-reported claims.
3. Multidimensional separation is strictly preserved (Task, Efficiency, Recovery, Safety, Reliability).
"""

from __future__ import annotations

from app.agent.evaluation.metrics import MetricsCalculator
from app.agent.evaluation.trace import TraceEventType, TraceRecorder
from app.agent.security.models import SecurityViolationCode


def test_metrics_calculation_from_trace_events():
    """All counter families compute correctly from discrete trace events."""
    recorder = TraceRecorder(run_id="run_metrics", scenario_id="golden_metrics")

    # Iteration 1
    recorder.set_iteration(1)
    recorder.record(
        TraceEventType.MODEL_DECISION,
        subsystem="reasoning",
        component="AgentReasoner",
        token_usage={"total_tokens": 1500},
        cost_usd=0.005,
    )
    recorder.record(TraceEventType.TOOL_PROPOSAL, subsystem="tools", component="ToolRegistry")
    recorder.record(
        TraceEventType.BROWSER_ACTION,
        subsystem="browser",
        component="BrowserExecutor",
        input_summary={"action": "navigate"},
    )
    recorder.record(
        TraceEventType.VERIFICATION,
        subsystem="verification",
        component="ActionVerifier",
        verification_status="verified",
    )

    # Iteration 2: Stale reference failure and recovery
    recorder.set_iteration(2)
    recorder.record(
        TraceEventType.FAILURE_CLASSIFIED,
        subsystem="recovery",
        component="FailureClassifier",
        input_summary={"failure_type": "STALE_REFERENCE"},
    )
    recorder.record(
        TraceEventType.RECOVERY_ATTEMPTED,
        subsystem="recovery",
        component="RecoveryManager",
        input_summary={"strategy": "RETRY_WITH_FRESH_TARGET"},
        output_summary={"recovered": True},
    )

    # Iteration 3: Safety event (contained redirect)
    recorder.set_iteration(3)
    recorder.record(
        TraceEventType.SECURITY_VIOLATION,
        subsystem="security",
        component="PolicyIntegrityGuard",
        security_violation={"code": SecurityViolationCode.UNAUTHORIZED_REDIRECT.value},
    )

    metrics = MetricsCalculator.calculate(
        recorder.get_events(),
        task_success=True,
        goal_completed=True,
        subgoals_completed=2,
        subgoals_total=2,
        duration_seconds=12.5,
    )

    # Task metrics
    assert metrics.task.task_success is True
    assert metrics.task.goal_completed is True
    assert metrics.task.subgoals_completed_count == 2
    assert metrics.task.verification_successes == 1
    assert metrics.task.verification_success_rate == 1.0

    # Efficiency metrics
    assert metrics.efficiency.iterations_count == 3
    assert metrics.efficiency.total_runtime_seconds == 12.5
    assert metrics.efficiency.model_calls_count == 1
    assert metrics.efficiency.tool_calls_count == 1
    assert metrics.efficiency.browser_actions_count == 1
    assert metrics.efficiency.navigations_count == 1
    assert metrics.efficiency.total_tokens == 1500
    assert metrics.efficiency.estimated_cost_usd == 0.005

    # Recovery metrics
    assert metrics.recovery.failures_encountered_count == 1
    assert metrics.recovery.recovery_attempts_count == 1
    assert metrics.recovery.recoveries_succeeded_count == 1
    assert metrics.recovery.stale_ref_recoveries_count == 1
    assert metrics.recovery.recovery_success_rate == 1.0

    # Safety metrics
    assert metrics.safety.safety_pass is False  # A security violation occurred
    assert metrics.safety.unauthorized_redirects_blocked_count == 1


def test_metrics_do_not_rely_on_model_claims():
    """An LLM claim of completion does not produce task_success without runtime confirmation."""
    recorder = TraceRecorder(run_id="run_claim", scenario_id="golden_claim")
    recorder.record(
        TraceEventType.MODEL_DECISION,
        subsystem="reasoning",
        component="AgentReasoner",
        output_summary={"decision_type": "complete", "reason": "I finished the entire task successfully!"},
    )

    # Explicitly calculate with task_success=False from unfulfilled criteria
    metrics = MetricsCalculator.calculate(recorder.get_events(), task_success=False, goal_completed=False)
    assert metrics.task.task_success is False
    assert metrics.task.goal_completed is False
