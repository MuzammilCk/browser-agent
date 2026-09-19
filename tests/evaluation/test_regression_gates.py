"""Unit tests for Regression Gates — Phase 12.

Tests:
1. Regression thresholds PASS on clean evaluation metrics.
2. Regression thresholds FAIL and pinpoint degraded metrics with explanation.
3. INCONCLUSIVE verdict when metric is missing.
4. Support for custom scenario thresholds.
"""

from __future__ import annotations

from app.agent.evaluation.gates import (
    GateReport,
    GateThreshold,
    GateVerdict,
    MetricComparisonOp,
    RegressionGate,
)
from app.agent.evaluation.metrics import (
    EfficiencyMetrics,
    EvaluationMetrics,
    RecoveryMetrics,
    ReliabilityMetrics,
    SafetyMetrics,
    TaskMetrics,
)


def _sample_metrics(*, task_success: bool = True, safety_pass: bool = True, runtime: float = 10.0) -> EvaluationMetrics:
    return EvaluationMetrics(
        task=TaskMetrics(task_success=task_success, goal_completed=task_success),
        efficiency=EfficiencyMetrics(total_runtime_seconds=runtime, iterations_count=3),
        recovery=RecoveryMetrics(recovery_success_rate=1.0),
        safety=SafetyMetrics(safety_pass=safety_pass),
        reliability=ReliabilityMetrics(),
    )


def test_regression_gate_passes_on_compliant_metrics():
    """Default regression gate reports PASS when all safety conditions hold."""
    gate = RegressionGate()
    metrics = _sample_metrics(task_success=True, safety_pass=True)

    report = gate.evaluate(metrics, target_identifier="golden_test")
    assert report.overall_verdict == GateVerdict.PASS
    assert report.failed_checks_count == 0
    assert all(c.passed for c in report.checks)


def test_regression_gate_fails_on_degraded_metric_with_explanation():
    """Gate catches failed threshold, marking overall FAIL and detailing root cause."""
    gate = RegressionGate(
        thresholds=[
            GateThreshold(
                metric_name="task.task_success",
                operator=MetricComparisonOp.EQUAL,
                target_value=True,
                description="Task must succeed",
            ),
            GateThreshold(
                metric_name="efficiency.total_runtime_seconds",
                operator=MetricComparisonOp.LESS_THAN_OR_EQUAL,
                target_value=15.0,
                description="Max 15 seconds runtime",
            ),
        ]
    )

    # Degraded metrics: runtime is 25.0s
    degraded = _sample_metrics(task_success=True, runtime=25.0)
    report = gate.evaluate(degraded, target_identifier="scenario_slow")

    assert report.overall_verdict == GateVerdict.FAIL
    assert report.failed_checks_count == 1

    failed_check = next(c for c in report.checks if not c.passed)
    assert failed_check.metric_name == "efficiency.total_runtime_seconds"
    assert failed_check.verdict == GateVerdict.FAIL
    assert failed_check.observed == 25.0
    assert failed_check.threshold == 15.0
    assert "FAILED requirement" in failed_check.explanation


def test_regression_gate_inconclusive_on_missing_metric():
    """Gate reports INCONCLUSIVE when referenced metric path does not exist."""
    gate = RegressionGate(
        thresholds=[
            GateThreshold(
                metric_name="nonexistent.metric_field",
                operator=MetricComparisonOp.EQUAL,
                target_value=10,
                description="Checking unknown metric",
            )
        ]
    )

    metrics = _sample_metrics()
    report = gate.evaluate(metrics, target_identifier="scenario_unknown")
    assert report.overall_verdict == GateVerdict.FAIL  # Inconclusive fails closed
    assert report.checks[0].verdict == GateVerdict.INCONCLUSIVE
    assert "not found" in report.checks[0].explanation
