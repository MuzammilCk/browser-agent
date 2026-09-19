"""Unit tests for Evaluation Scenarios — Phase 12.

Tests:
1. Scenario validation rejects malformed scenarios (extra="forbid", missing fields).
2. All 14 golden scenarios are valid and complete.
3. Lossless serialization and deserialization.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.evaluation.models import (
    EvaluationScenario,
    SafetyConstraintKind,
    SafetyConstraintSpec,
    ScenarioCategory,
    SuccessCriterionKind,
    SuccessCriterionSpec,
)
from app.agent.evaluation.scenarios import get_golden_scenarios


def test_scenario_validation_rejects_malformed_scenarios():
    """Scenario validation fails closed on invalid schemas or extra fields."""
    # Extra field rejected
    with pytest.raises(ValidationError):
        EvaluationScenario(
            scenario_id="sc_01",
            name="Test",
            description="Test scenario",
            category=ScenarioCategory.BASIC_FORM,
            page_url="file:///test.html",
            task_goal="Goal",
            unauthorized_extra_field="malicious",  # type: ignore[call-arg]
        )

    # Missing required field rejected
    with pytest.raises(ValidationError):
        EvaluationScenario(
            scenario_id="sc_01",
            # name missing
            description="Test scenario",
            category=ScenarioCategory.BASIC_FORM,
            page_url="file:///test.html",
            task_goal="Goal",
        )  # type: ignore[call-arg]


def test_all_14_golden_scenarios_exist_and_validate():
    """All 14 mandatory golden scenarios exist, have unique IDs, and are valid."""
    scenarios = get_golden_scenarios()
    assert len(scenarios) == 14

    seen_ids = set()
    for sc in scenarios:
        assert sc.scenario_id not in seen_ids
        seen_ids.add(sc.scenario_id)
        assert sc.name
        assert sc.description
        assert sc.task_goal
        assert sc.category in ScenarioCategory
        assert len(sc.success_criteria) > 0
        assert len(sc.safety_constraints) > 0


def test_scenario_json_roundtrip():
    """Evaluation scenarios serialize and deserialize losslessly."""
    sc = EvaluationScenario(
        scenario_id="sc_roundtrip",
        name="Roundtrip Test",
        description="Verify roundtrip serialization",
        category=ScenarioCategory.DYNAMIC_DOM,
        page_url="file:///test.html",
        task_goal="Verify serialization",
        tags=["unit_test", "serialization"],
        success_criteria=[
            SuccessCriterionSpec(
                kind=SuccessCriterionKind.DOM_FIELD_VALUE,
                description="Test field check",
                selector="#test",
                expected_value="pass",
            )
        ],
        safety_constraints=[
            SafetyConstraintSpec(
                kind=SafetyConstraintKind.ZERO_UNAUTHORIZED_MUTATIONS,
                description="No bad actions",
            )
        ],
    )

    data = sc.model_dump()
    restored = EvaluationScenario.model_validate(data)
    assert restored == sc
