"""Evaluation Platform Core Models — Phase 12.

Key Architectural Invariants:
1. Real runtime is the subject under test.
2. Evaluator has NO execution authority.
3. Outcome dimensions are separated: task_success and safety_pass are NOT collapsed.
4. Model claims are never treated as ground truth.
5. Strict schema validation (extra="forbid").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.security.budget import RuntimeBudget


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_eval_id(prefix: str = "eval") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ScenarioCategory(str, Enum):
    """Canonical categories of evaluation scenarios."""

    BASIC_FORM = "basic_form"
    DYNAMIC_DOM = "dynamic_dom"
    MULTI_STEP = "multi_step"
    MULTI_TAB = "multi_tab"
    VALIDATION_FAILURE = "validation_failure"
    STALE_REFERENCE = "stale_reference"
    BROWSER_FAILURE = "browser_failure"
    AUTHENTICATION_HITL = "authentication_hitl"
    DOCUMENT_SELECTION = "document_selection"
    SPECIALIST_ASSISTED = "specialist_assisted"
    PROMPT_INJECTION = "prompt_injection"
    MALICIOUS_DOCUMENT = "malicious_document"
    UNAUTHORIZED_REDIRECT = "unauthorized_redirect"
    APPROVAL_TAMPERING = "approval_tampering"
    AMBIGUOUS_FIELD = "ambiguous_field"
    BUDGET_EXHAUSTION = "budget_exhaustion"
    MALFORMED_MODEL = "malformed_model"
    UNSATISFIABLE_TASK = "unsatisfiable_task"


class SuccessCriterionKind(str, Enum):
    """Typed deterministic success predicates evaluated against DOM and state."""

    DOM_FIELD_VALUE = "dom_field_value"
    DOM_ELEMENT_VISIBLE = "dom_element_visible"
    DOM_ELEMENT_TEXT_CONTAINS = "dom_element_text_contains"
    WORLD_STATE_FACT = "world_state_fact"
    WORLD_STATE_VERIFIED = "world_state_verified"
    SUBGOAL_COMPLETED = "subgoal_completed"
    URL_MATCH = "url_match"
    NO_VALIDATION_ERRORS = "no_validation_errors"


class SuccessCriterionSpec(BaseModel):
    """Specification of an objective success condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SuccessCriterionKind
    description: str
    selector: str | None = None
    field_name: str | None = None
    expected_value: Any | None = None
    required: bool = True
    negate: bool = False


class SafetyConstraintKind(str, Enum):
    """Safety invariants enforced independently of task success."""

    ZERO_UNAUTHORIZED_MUTATIONS = "zero_unauthorized_mutations"
    REQUIRED_CONFIRMATION_GATING = "required_confirmation_gating"
    PROHIBIT_EXTERNAL_REDIRECTS = "prohibit_external_redirects"
    PROHIBIT_SECRET_LEAKAGE = "prohibit_secret_leakage"
    PREVENT_APPROVAL_BYPASS = "prevent_approval_bypass"
    CONTAIN_PROMPT_INJECTION = "contain_prompt_injection"
    ENFORCE_BUDGET_HALT = "enforce_budget_halt"


class SafetyConstraintSpec(BaseModel):
    """Specification of a safety requirement for an evaluation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SafetyConstraintKind
    description: str
    enforce_zero_violations: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class BaselineIdentity(BaseModel):
    """Immutable identity identifying code, model, and scenario baseline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit_sha: str = "HEAD"
    scenario_version: str = "1.0.0"
    eval_schema_version: str = "1.0.0"
    trace_schema_version: str = "1.0.0"
    model_identity: str = "mock-model"
    config_fingerprint: str = ""
    environment_version: str = "local-synthetic"


class EvaluationStatus(str, Enum):
    """Overall outcome status of an evaluation run."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    SAFETY_VIOLATION = "safety_violation"
    INCONCLUSIVE = "inconclusive"


class EvaluationScenario(BaseModel):
    """Structured evaluation scenario specification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    version: str = "1.0.0"
    name: str
    description: str
    category: ScenarioCategory
    tags: list[str] = Field(default_factory=list)
    page_url: str
    task_goal: str
    initial_user_vault: dict[str, Any] = Field(default_factory=dict)
    allowed_origins: list[str] = Field(default_factory=list)
    runtime_budget: RuntimeBudget | None = None
    success_criteria: list[SuccessCriterionSpec] = Field(default_factory=list)
    safety_constraints: list[SafetyConstraintSpec] = Field(default_factory=list)
    failure_injection: dict[str, Any] | None = None
    expected_hitl_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CriterionEvaluationResult(BaseModel):
    """Evaluation of an individual success criterion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    kind: SuccessCriterionKind
    satisfied: bool
    required: bool
    observed_value: Any = None
    expected_value: Any = None
    details: str = ""


class SafetyEvaluationResult(BaseModel):
    """Evaluation of an individual safety constraint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    kind: SafetyConstraintKind
    passed: bool
    violations_detected: int = 0
    details: str = ""


class EvaluationResult(BaseModel):
    """Final multi-dimensional outcome of a scenario execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    run_id: str
    status: EvaluationStatus
    task_success: bool
    safety_pass: bool
    duration_seconds: float
    baseline_identity: BaselineIdentity
    criteria_results: list[CriterionEvaluationResult] = Field(default_factory=list)
    safety_results: list[SafetyEvaluationResult] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    trace_summary: dict[str, Any] = Field(default_factory=dict)
    failure_diagnosis: dict[str, Any] | None = None
