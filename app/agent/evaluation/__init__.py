"""Public API for the Evaluation Platform — Phase 12."""

from app.agent.evaluation.comparison import ComparisonEngine, EvaluationComparison, MetricDelta
from app.agent.evaluation.gates import GateReport, GateThreshold, GateVerdict, MetricComparisonOp, RegressionGate
from app.agent.evaluation.injection import FailureInjectionPlan, FailureInjector, FaultTrigger, FaultType, InjectedFault
from app.agent.evaluation.metrics import (
    EfficiencyMetrics,
    EvaluationMetrics,
    MetricsCalculator,
    RecoveryMetrics,
    ReliabilityMetrics,
    SafetyMetrics,
    TaskMetrics,
)
from app.agent.evaluation.models import (
    BaselineIdentity,
    CriterionEvaluationResult,
    EvaluationResult,
    EvaluationScenario,
    EvaluationStatus,
    SafetyConstraintKind,
    SafetyConstraintSpec,
    SafetyEvaluationResult,
    ScenarioCategory,
    SuccessCriterionKind,
    SuccessCriterionSpec,
)
from app.agent.evaluation.replay import ReplayDiff, ReplayDiffSeverity, ReplayEngine, ReplayMode, ReplayResult
from app.agent.evaluation.runner import ScenarioRunner
from app.agent.evaluation.scenarios import get_golden_scenarios
from app.agent.evaluation.trace import TraceEvent, TraceEventType, TraceRecorder, redact_trace_value

__all__ = [
    "BaselineIdentity",
    "ComparisonEngine",
    "CriterionEvaluationResult",
    "EfficiencyMetrics",
    "EvaluationComparison",
    "EvaluationMetrics",
    "EvaluationResult",
    "EvaluationScenario",
    "EvaluationStatus",
    "FailureInjectionPlan",
    "FailureInjector",
    "FaultTrigger",
    "FaultType",
    "GateReport",
    "GateThreshold",
    "GateVerdict",
    "InjectedFault",
    "MetricComparisonOp",
    "MetricDelta",
    "MetricsCalculator",
    "RecoveryMetrics",
    "RegressionGate",
    "ReliabilityMetrics",
    "ReplayDiff",
    "ReplayDiffSeverity",
    "ReplayEngine",
    "ReplayMode",
    "ReplayResult",
    "SafetyConstraintKind",
    "SafetyConstraintSpec",
    "SafetyEvaluationResult",
    "SafetyMetrics",
    "ScenarioCategory",
    "ScenarioRunner",
    "SuccessCriterionKind",
    "SuccessCriterionSpec",
    "TaskMetrics",
    "TraceEvent",
    "TraceEventType",
    "TraceRecorder",
    "get_golden_scenarios",
    "redact_trace_value",
]
