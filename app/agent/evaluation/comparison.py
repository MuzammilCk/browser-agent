"""Baseline vs Candidate Comparison Engine — Phase 12.

Key Architectural Invariants:
1. Objective comparison across runs, commits, models, and configurations.
2. Identifies specific metric deltas, regressions, and improvements.
3. Does NOT declare an arbitrary universal "winner".
4. Strict schema validation (extra="forbid").
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.agent.evaluation.models import BaselineIdentity, EvaluationResult
from app.agent.evaluation.metrics import EvaluationMetrics


class MetricDelta(BaseModel):
    """Calculated difference between candidate and baseline for one metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_name: str
    baseline_value: Any
    candidate_value: Any
    delta: float | None = None
    is_regression: bool = False
    is_improvement: bool = False
    details: str = ""


class EvaluationComparison(BaseModel):
    """Structured comparison between two evaluation results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    baseline_identity: BaselineIdentity
    candidate_identity: BaselineIdentity
    metric_deltas: list[MetricDelta] = Field(default_factory=list)
    regressions_count: int = 0
    improvements_count: int = 0
    unchanged_count: int = 0
    has_safety_regression: bool = False
    summary: str = ""


class ComparisonEngine:
    """Computes multidimensional differences between baseline and candidate evaluation runs."""

    # Metrics where a higher value is better
    HIGHER_IS_BETTER = {
        "task.task_success",
        "task.goal_completed",
        "task.subgoals_completed_count",
        "task.verification_success_rate",
        "recovery.recovery_success_rate",
        "recovery.recoveries_succeeded_count",
        "safety.safety_pass",
    }

    # Metrics where a lower value is better
    LOWER_IS_BETTER = {
        "efficiency.total_runtime_seconds",
        "efficiency.iterations_count",
        "efficiency.tool_calls_count",
        "efficiency.total_tokens",
        "efficiency.estimated_cost_usd",
        "recovery.unrecovered_failures_count",
        "safety.policy_denials_count",
        "safety.security_violations_count",
        "reliability.exceptions_count",
        "reliability.timeouts_count",
        "reliability.model_failures_count",
    }

    @classmethod
    def compare(
        cls,
        baseline: EvaluationResult,
        candidate: EvaluationResult,
    ) -> EvaluationComparison:
        """Compare candidate result against baseline."""
        deltas: list[MetricDelta] = []
        regressions = 0
        improvements = 0
        unchanged = 0
        has_safety_regression = False

        # Flatten metrics
        base_flat = cls._flatten_dict(baseline.metrics)
        cand_flat = cls._flatten_dict(candidate.metrics)

        all_keys = sorted(set(base_flat.keys()) | set(cand_flat.keys()))

        for key in all_keys:
            bv = base_flat.get(key)
            cv = cand_flat.get(key)

            if bv is None or cv is None:
                continue

            delta_val: float | None = None
            is_reg = False
            is_imp = False

            if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
                delta_val = round(float(cv) - float(bv), 4)
                if delta_val != 0:
                    if key in cls.HIGHER_IS_BETTER:
                        is_imp = delta_val > 0
                        is_reg = delta_val < 0
                    elif key in cls.LOWER_IS_BETTER:
                        is_imp = delta_val < 0
                        is_reg = delta_val > 0
            elif isinstance(bv, bool) and isinstance(cv, bool):
                if bv != cv:
                    if key in cls.HIGHER_IS_BETTER:
                        is_imp = cv is True
                        is_reg = cv is False
                    elif key in cls.LOWER_IS_BETTER:
                        is_imp = cv is False
                        is_reg = cv is True

            if is_reg:
                regressions += 1
                if key.startswith("safety."):
                    has_safety_regression = True
            elif is_imp:
                improvements += 1
            else:
                unchanged += 1

            deltas.append(
                MetricDelta(
                    metric_name=key,
                    baseline_value=bv,
                    candidate_value=cv,
                    delta=delta_val,
                    is_regression=is_reg,
                    is_improvement=is_imp,
                    details=f"{key}: {bv} -> {cv} (delta={delta_val})",
                )
            )

        summary = (
            f"Comparison for {baseline.scenario_id}: {improvements} improvements, "
            f"{regressions} regressions, {unchanged} unchanged. "
            f"{'CRITICAL: Safety regression detected!' if has_safety_regression else 'No safety regressions.'}"
        )

        return EvaluationComparison(
            scenario_id=baseline.scenario_id,
            baseline_identity=baseline.baseline_identity,
            candidate_identity=candidate.baseline_identity,
            metric_deltas=deltas,
            regressions_count=regressions,
            improvements_count=improvements,
            unchanged_count=unchanged,
            has_safety_regression=has_safety_regression,
            summary=summary,
        )

    @classmethod
    def _flatten_dict(cls, d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        result = {}
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(cls._flatten_dict(v, full_key))
            else:
                result[full_key] = v
        return result
