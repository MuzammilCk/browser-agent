"""Domain models for Phase 10: Restricted Specialist Agents / Subagents.

CRITICAL INVARIANTS:
1. Specialists are ADVISORS, never authorities. They analyze, recommend, classify,
   and provide evidence. They NEVER mutate state or authorize actions directly.
2. Specialist results are SEMANTICALLY DISTINCT (ResultKind.SPECIALIST_ANALYSIS)
   and can NEVER enter mutation or authoritative verification pipelines.
3. Projections are strictly ALLOWLISTED: no Playwright handles, no BrowserExecutor,
   no AgentRuntime, no ToolRegistry, no passwords/OTPs/secrets, no full state.
4. Specialists have fixed, immutable permissions:
   READ_ONLY, VAULT_SCOPED, ANALYSIS_ONLY, VERIFICATION_ONLY.
5. Specialists cannot invoke other specialists (no recursion, no multi-agent swarms).
6. Epistemic status of specialist output is INFERRED by default; never VERIFIED.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def new_specialist_id(prefix: str = "spec") -> str:
    """Generate a unique identifier for specialist invocations."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ==============================================================================
# 1. Permission and Specialist Enums
# ==============================================================================


class SpecialistPermission(str, Enum):
    """Explicit permission classes for specialist agents.

    No specialist gets unrestricted browser mutation.
    Permissions are fixed by the registered implementation (Rule 5).
    """

    READ_ONLY = "read_only"
    VAULT_SCOPED = "vault_scoped"
    ANALYSIS_ONLY = "analysis_only"
    VERIFICATION_ONLY = "verification_only"


class SpecialistType(str, Enum):
    """Canonical registry of supported specialist agents."""

    PORTAL_RESEARCH = "portal_research"
    FORM_SEMANTICS = "form_semantics"
    DOCUMENT = "document"
    RECOVERY = "recovery"
    VERIFICATION = "verification"


class ResultKind(str, Enum):
    """Semantic distinction for tool results (Rule 2).

    SPECIALIST_ANALYSIS must never enter mutation/verification paths
    as if it were a browser ToolResult.
    """

    SPECIALIST_ANALYSIS = "specialist_analysis"
    BROWSER_MUTATION = "browser_mutation"
    READ_OBSERVATION = "read_observation"


class SpecialistOutcome(str, Enum):
    """Outcome status of a specialist execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    VALIDATION_FAILED = "validation_failed"
    ESCALATION_BLOCKED = "escalation_blocked"


# ==============================================================================
# 2. Allowlisted Projection Models (Rule 3)
# ==============================================================================


class ElementSummaryProjection(BaseModel):
    """Safe, projection-only element summary without live DOM/Playwright nodes."""

    ref: str
    role: str | None = None
    name: str | None = None
    value: str | None = None
    input_type: str | None = None
    required: bool = False
    disabled: bool = False
    checked: bool | None = None
    selected_options: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    placeholder: str | None = None


class PageObservationProjection(BaseModel):
    """Safe, read-only projection of a page observation.

    Strictly contains serialized data. NEVER holds Playwright Page or BrowserContext.
    """

    url: str = ""
    title: str = ""
    page_type: str = "unknown"
    observation_id: str = ""
    elements: list[ElementSummaryProjection] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    open_tabs: int = 1


class WorldStateProjection(BaseModel):
    """Safe, read-only projection of AgentWorldState.

    Specialists may inspect this projection, but can NEVER mutate AgentWorldState.
    """

    portal: str = ""
    state_version: int = 0
    verified_facts: dict[str, Any] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    completed_subgoals: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)


class FailureEvidenceProjection(BaseModel):
    """Safe projection of failure evidence for recovery specialists."""

    failure_type: str
    error_code: str = ""
    message: str = ""
    target_selector: str | None = None
    target_semantic_id: str | None = None
    attempt_number: int = 1


class DocumentMetadataProjection(BaseModel):
    """Safe document metadata projection.

    NEVER contains raw document bytes or unredacted file paths.
    """

    reference: str = Field(description="e.g. 'DOCUMENT.aadhaar'")
    display_name: str = ""
    document_type: str = ""
    sensitivity: str = "masked"
    is_available: bool = False


class MemorySummaryProjection(BaseModel):
    """Safe summary of past memory items for specialist context."""

    memory_type: str = "semantic"
    subject: str = ""
    summary: str = ""
    confidence: float = 1.0


# ==============================================================================
# 3. Specialist Context (Rule 3 & 4)
# ==============================================================================

# Dangerous property substrings that must NEVER be passed into SpecialistContext
_FORBIDDEN_CONTEXT_KEYWORDS = (
    "page",
    "browser",
    "executor",
    "runtime",
    "registry",
    "session",
    "password",
    "otp",
    "secret",
    "credential",
    "private_key",
)


class SpecialistContext(BaseModel):
    """Explicit, isolated context passed to a specialist agent.

    Must contain ONLY scoped projection data.
    Does NOT contain:
    - Live Playwright Page/BrowserContext
    - BrowserExecutor
    - AgentRuntime or ToolRegistry
    - Raw credentials, passwords, OTPs, CAPTCHA answers
    - Raw document file contents
    - Policy internals
    - Full conversation history
    """

    invocation_id: str = Field(default_factory=lambda: new_specialist_id("spec_inv"))
    parent_run_id: str = Field(default="", description="Parent AgentRunState run ID")
    specialist_type: SpecialistType
    permission: SpecialistPermission
    timeout_seconds: float = Field(default=10.0, ge=0.01, le=60.0)

    # Scoped projections (only populated if authorized by permission)
    goal_projection: str | None = None
    subgoal_projection: str | None = None
    observation_projection: PageObservationProjection | None = None
    world_state_projection: WorldStateProjection | None = None
    memory_projections: list[MemorySummaryProjection] = Field(default_factory=list)
    failure_evidence: FailureEvidenceProjection | None = None
    document_metadata: list[DocumentMetadataProjection] = Field(default_factory=list)

    # Safe, isolated task parameters
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_no_dangerous_structures(self) -> SpecialistContext:
        """Enforce strict structural isolation: no dangerous handles or secrets."""
        # Validate parameters dictionary
        for k, v in self.parameters.items():
            key_lower = k.lower()
            for kw in _FORBIDDEN_CONTEXT_KEYWORDS:
                if kw in key_lower:
                    raise ValueError(f"SpecialistContext cannot carry forbidden parameter '{k}'")
            # Check object types
            type_name = type(v).__name__.lower()
            for kw in ("page", "browser", "executor", "runtime", "registry", "playwright"):
                if kw in type_name:
                    raise ValueError(f"SpecialistContext cannot carry runtime object '{type_name}'")

        # Permission scope checks
        if self.permission == SpecialistPermission.READ_ONLY:
            if self.document_metadata:
                raise ValueError("READ_ONLY specialists cannot receive document metadata")
        elif self.permission == SpecialistPermission.VAULT_SCOPED:
            if self.failure_evidence is not None:
                raise ValueError("VAULT_SCOPED specialists cannot receive failure evidence")

        return self


# ==============================================================================
# 4. Specialist Output Models (Rule 1 & 2)
# ==============================================================================


class PortalResearchOutput(BaseModel):
    """Structured result of PortalResearchAgent."""

    portal_name: str = ""
    identified_workflows: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    form_landmarks: list[str] = Field(default_factory=list)
    navigation_hints: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class FieldSemanticInfo(BaseModel):
    """Semantic analysis of a single form field."""

    element_ref: str
    semantic_slug: str
    field_label: str
    input_type: str = "text"
    is_required: bool = False
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    ambiguity_reason: str | None = None


class FormSemanticsOutput(BaseModel):
    """Structured result of FormSemanticsAgent."""

    field_semantics: list[FieldSemanticInfo] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    suggested_field_mappings: dict[str, str] = Field(default_factory=dict)


class MatchedDocumentInfo(BaseModel):
    """Document reference match for form requirement."""

    reference: str
    document_type: str
    match_reason: str
    is_present: bool = True


class DocumentSpecialistOutput(BaseModel):
    """Structured result of DocumentAgent (metadata references only)."""

    matched_documents: list[MatchedDocumentInfo] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class RecoverySpecialistOutput(BaseModel):
    """Structured recommendation of RecoveryAgent (recommendation only)."""

    recommended_strategy: str
    suggested_target_semantic_id: str | None = None
    root_cause_analysis: str = ""
    budget_assessment: str = "within_budget"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class CriterionEvaluation(BaseModel):
    """Verification assessment of a single criterion."""

    criterion_kind: str
    description: str
    recommended_verdict: str = "uncertain"  # "satisfied", "unsatisfied", "uncertain"
    evidence: str = ""


class VerificationSpecialistOutput(BaseModel):
    """Structured analysis of VerificationAgent (advisory only)."""

    recommended_verified: bool = False
    criteria_evaluations: list[CriterionEvaluation] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


# ==============================================================================
# 5. SpecialistResult Container (Rule 2, 6, 10)
# ==============================================================================

# Keywords indicating malicious prompt injection or permission escalation
_ESCALATION_KEYWORDS = (
    "ignore policy",
    "bypass policy",
    "execute payment",
    "skip verification",
    "skip captcha",
    "override permissions",
    "elevate privileges",
    "mark verified",
    "auto submit",
    "unlock submission",
)


class SpecialistResult(BaseModel):
    """Normalized, schema-validated result container returned by a specialist agent.

    CRITICAL INVARIANTS:
    - result_kind is always ResultKind.SPECIALIST_ANALYSIS (never BROWSER_MUTATION).
    - epistemic_status is INFERRED by default (never VERIFIED).
    - Checks for permission escalation attempts (fail closed).
    """

    result_kind: ResultKind = Field(default=ResultKind.SPECIALIST_ANALYSIS)
    invocation_id: str
    parent_run_id: str = ""
    specialist_type: SpecialistType
    permission: SpecialistPermission
    outcome: SpecialistOutcome = Field(default=SpecialistOutcome.SUCCESS)

    # Epistemic trust status (Rule 6: Specialists cannot mark anything VERIFIED)
    epistemic_status: Literal["inferred", "observed"] = Field(
        default="inferred",
        description="Specialist findings are INFERRED or OBSERVED, never VERIFIED",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    # Schema-validated payload matching specialist output schema
    data: dict[str, Any] = Field(default_factory=dict)

    evidence: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)

    # Failure tracking
    error_code: str | None = None
    error_message: str | None = None

    # Safe audit metadata
    audit_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_security_and_epistemic_invariants(self) -> SpecialistResult:
        """Enforce strict security: no escalation, no VERIFIED claims."""
        # 1. Never allow result_kind to masquerade as browser mutation
        if self.result_kind != ResultKind.SPECIALIST_ANALYSIS:
            raise ValueError("SpecialistResult must have result_kind=SPECIALIST_ANALYSIS")

        def check_text(text: str) -> None:
            text_norm = text.lower().replace("_", " ")
            for kw in _ESCALATION_KEYWORDS:
                if kw.replace("_", " ") in text_norm:
                    raise ValueError(f"Malicious escalation attempt detected: '{kw}'")

        # Check evidence, ambiguities, error_message
        for ev in self.evidence:
            check_text(ev)
        for amb in self.ambiguities:
            check_text(amb)
        if self.error_message:
            check_text(self.error_message)

        # Check data fields recursively
        def scan_data(obj: Any) -> None:
            if isinstance(obj, str):
                check_text(obj)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(k, str):
                        check_text(k)
                    scan_data(v)
            elif isinstance(obj, (list, tuple, set)):
                for item in obj:
                    scan_data(item)

        scan_data(self.data)
        return self


# ==============================================================================
# 6. Specialist Audit Record (Rule 11, 12)
# ==============================================================================


class SpecialistAuditRecord(BaseModel):
    """Immutable audit trail of a specialist invocation."""

    parent_run_id: str
    invocation_id: str
    specialist_type: str
    permission: str
    outcome: str
    started_at: str
    ended_at: str
    duration_ms: float
    timeout_or_cancelled: bool
    result_summary: str
    error_message: str | None = None
    input_scope_summary: dict[str, Any] = Field(default_factory=dict)
