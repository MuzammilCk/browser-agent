"""Phase 14 live-portal validation models.

Every live run produces structured evidence separating:
- observed behavior (deterministic, from the browser)
- agent inference (model/mapper output, advisory)
- deterministic verification (executor verifiers)
- human-confirmed result (explicit review records)
- environment failure (external conditions, never counted as agent failure)

Portal content remains UNTRUSTED_WEB: nothing extracted from a live page can
flip run mode, alter policy, mint approvals, or write trusted memory.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# Live run modes
# ============================================================


class LiveRunMode(str, Enum):
    """Live validation modes. Shadow is the default and first required mode."""

    LIVE_SHADOW = "LIVE_SHADOW"
    LIVE_CONTROLLED_EXECUTION = "LIVE_CONTROLLED_EXECUTION"


class EnvironmentCondition(str, Enum):
    """External conditions that are NOT agent failures (invariant 10)."""

    PORTAL_UNAVAILABLE = "PORTAL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    ANTI_BOT_BLOCK = "ANTI_BOT_BLOCK"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LiveOutcomeStatus(str, Enum):
    """Explicit, non-collapsing outcome statuses (Phase 14 evidence model)."""

    PORTAL_OBSERVATION_SUCCESS = "PORTAL_OBSERVATION_SUCCESS"
    SEMANTICS_SUCCESS = "SEMANTICS_SUCCESS"
    MAPPING_SUCCESS = "MAPPING_SUCCESS"
    SHADOW_VALIDATION_SUCCESS = "SHADOW_VALIDATION_SUCCESS"
    CONTROLLED_EXECUTION_SUCCESS = "CONTROLLED_EXECUTION_SUCCESS"
    HITL_REQUIRED = "HITL_REQUIRED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    PORTAL_UNAVAILABLE = "PORTAL_UNAVAILABLE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    AGENT_FAILURE = "AGENT_FAILURE"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


# Statuses that constitute a *successful* shadow validation.
_SHADOW_SUCCESS_STATUSES = frozenset(
    {
        LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS,
        LiveOutcomeStatus.HITL_REQUIRED,
        LiveOutcomeStatus.POLICY_BLOCKED,
        LiveOutcomeStatus.AMBIGUOUS,
        LiveOutcomeStatus.UNSUPPORTED,
    }
)


def shadow_run_is_success(report: "LivePortalRunReport") -> bool:
    """A shadow run 'succeeds' when the pipeline completed safely — even if the
    portal turned out to be AMBIGUOUS/UNSUPPORTED/blocked. What must NOT be
    counted as success: AGENT_FAILURE, or environment conditions silently
    swallowed."""
    if report.final_status == LiveOutcomeStatus.AGENT_FAILURE:
        return False
    if report.final_status in _SHADOW_SUCCESS_STATUSES:
        return True
    if report.final_status in (
        LiveOutcomeStatus.PORTAL_UNAVAILABLE,
        LiveOutcomeStatus.ENVIRONMENT_FAILURE,
    ):
        return True
    return False


# ============================================================
# Portal profiles
# ============================================================


class PortalClass(str, Enum):
    """Portal classes from the Phase 14 plan."""

    TRAINING = "training"
    WELFARE = "welfare"
    IDENTITY_DOCUMENT = "identity_document"
    TRANSPORT = "transport"
    EDUCATION = "education"
    RECRUITMENT = "recruitment"
    GRIEVANCE = "grievance"
    CERTIFICATE = "certificate"
    APPOINTMENTS = "appointments"


class PortalProfile(BaseModel):
    """Trusted metadata for one live portal. NEVER executable scripts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    portal_id: str
    name: str
    official_origin: str = Field(description="Exact origin, e.g. https://pmkisan.gov.in")
    portal_class: PortalClass
    entrypoint: str = Field(description="Safe observation entrypoint URL")
    trusted_domains: list[str] = Field(default_factory=list)
    observed_workflow: str = ""
    authentication_requirements: str = ""
    document_requirements: str = ""
    known_constraints: list[str] = Field(default_factory=list)
    safe_test_path: str = Field(
        description=(
            "Exact validated safe-test path. Never invented: only set after "
            "the path has been exercised on the live portal by this phase."
        )
    )
    last_verified_at: str = ""

    @field_validator("official_origin")
    @classmethod
    def _origin_must_be_https_gov(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("official_origin must be https")
        host = v.split("://", 1)[1].rstrip("/")
        if not (host.endswith(".gov.in") or host.endswith(".nic.in")):
            raise ValueError(f"official_origin must be a gov.in/nic.in host: {host}")
        return v

    def origin_host(self) -> str:
        return self.official_origin.split("://", 1)[1].rstrip("/")

    def origin_matches(self, url: str) -> bool:
        """True when the URL's host is the official origin or a registered
        trusted subdomain of it.

        file:// URLs match only file:// official origins — used exclusively by
        offline test profiles so shadow/controlled pipelines can be exercised
        on local fixtures without weakening any live-origin check.
        """
        from urllib.parse import urlparse

        if url.startswith("file://"):
            return self.official_origin.startswith("file://")
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        if host == self.origin_host().lower():
            return True
        return any(
            host == d.lower() or host.endswith(f".{d.lower()}")
            for d in self.trusted_domains
        )

    @classmethod
    def offline_test_profile(
        cls,
        *,
        portal_id: str,
        name: str,
        entrypoint_uri: str,
    ) -> "PortalProfile":
        """Build a profile for OFFLINE pipeline tests over local file:// pages.

        Deliberately validator-bypassing and clearly marked test-only: live
        profiles must always use the normal constructor (https gov.in origin).
        """
        return cls.model_construct(
            portal_id=portal_id,
            name=name,
            official_origin=entrypoint_uri,
            portal_class=PortalClass.TRAINING,
            entrypoint=entrypoint_uri,
            trusted_domains=[],
            observed_workflow="offline test fixture",
            authentication_requirements="",
            document_requirements="",
            known_constraints=["TEST-ONLY profile — never use for live portals"],
            safe_test_path="offline fixture observation",
            last_verified_at=utc_now_iso(),
        )


# ============================================================
# Evidence records
# ============================================================


class SemanticExtractionEvidence(BaseModel):
    """Deterministic observation facts from one live observation."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    url: str
    title: str
    page_type: str
    element_count: int
    interactive_count: int
    textboxes: int
    comboboxes: int
    buttons: int
    links: int
    checkboxes: int
    radios: int
    alerts: int
    validation_errors: int
    frames: int
    auth_detected: bool
    auth_challenge_type: str = ""
    aria_snapshot_chars: int
    selected_options_seen: int = 0
    required_fields_seen: int = 0


class FieldMappingEvidence(BaseModel):
    """Field mapping evidence. Advisory (mapper) — never verification."""

    model_config = ConfigDict(extra="forbid")

    total_interactive: int
    mapped: int
    unmapped: list[str]
    ambiguous: list[str]
    ambiguous_examples: list[dict] = Field(default_factory=list)
    strategy_counts: dict[str, int] = Field(default_factory=dict)
    bindings: list[dict] = Field(default_factory=list)


class PlannedAction(BaseModel):
    """One proposed (not executed) action in a planned action trace."""

    model_config = ConfigDict(extra="forbid")

    order: int
    tool: str
    target_semantic_id: str
    target_ref: str
    observation_id: str
    risk: str
    policy_decision: str
    arguments_summary: str
    expected_state_transition: str
    verification_criterion: str
    hitl_required: bool


class FinalBoundaryEvidence(BaseModel):
    """Evidence that the final-submission boundary was enforced on a live run."""

    model_config = ConfigDict(extra="forbid")

    submit_controls_detected: list[str] = Field(default_factory=list)
    submit_controls_classified_high_risk: bool = False
    controlled_run_blocked_at_boundary: bool = False
    no_final_submission_executed: bool = True


class LivePortalRunReport(BaseModel):
    """Structured evidence for one live run.

    Separates observed behavior, agent inference, deterministic verification,
    human-confirmed result, and environment failure.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: LiveRunMode
    portal_id: str
    portal_class: PortalClass
    official_origin: str
    agent_commit: str
    model_identity: str = "no-llm-shadow (deterministic mapper + policy)"
    configuration: str = ""

    # Stage statuses (None = stage not reached)
    observation_status: LiveOutcomeStatus | None = None
    semantics_status: LiveOutcomeStatus | None = None
    mapping_status: LiveOutcomeStatus | None = None
    planning_status: LiveOutcomeStatus | None = None
    review_status: LiveOutcomeStatus | None = None
    execution_status: LiveOutcomeStatus | None = None
    final_status: LiveOutcomeStatus

    observation: SemanticExtractionEvidence | None = None
    final_observation: SemanticExtractionEvidence | None = None
    mapping: FieldMappingEvidence | None = None
    planned_actions: list[PlannedAction] = Field(default_factory=list)
    final_boundary: FinalBoundaryEvidence | None = None
    executed_actions: list[dict] = Field(default_factory=list)
    review_request: dict | None = None
    review_decision: dict | None = None

    environment_condition: EnvironmentCondition = EnvironmentCondition.NOT_APPLICABLE
    security_events: list[str] = Field(default_factory=list)
    injection_exposure: str = "none"
    duration_seconds: float = 0.0
    live_metadata: dict = Field(
        default_factory=dict,
        description="Non-deterministic live metadata (timestamps, URLs). Never replayed as a fixture.",
    )
    frozen_observation_path: str = ""

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)


# ============================================================
# Errors
# ============================================================


class UnsafeLiveRunError(RuntimeError):
    """Raised when a live run would violate a safety invariant."""


class OriginMismatchError(UnsafeLiveRunError):
    """Raised when the live page is not on the portal's official origin."""


class ReviewSignatureError(UnsafeLiveRunError):
    """Raised when a human review decision fails signature verification."""


# ============================================================
# Human review boundary
# ============================================================


class HumanReviewRequest(BaseModel):
    """What a human must inspect before any live mutation."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    run_id: str
    portal_id: str
    portal_origin: str
    intended_actions: list[PlannedAction]
    mapped_references: list[str]
    risk_summary: str
    expected_effect: str
    verification_criteria: list[str]


class HumanReviewDecision(BaseModel):
    """Explicit human review outcome. Human review is NOT PolicyEngine —
    policy authorization, target validation, and verification still apply."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    decision: str  # "approved" | "rejected"
    reviewer: str
    reason: str = ""
    # Deterministic binding — the request digest is recomputed and compared
    # so a decision cannot be transplanted onto a different action set.
    request_digest: str
    signature: str
    # Bounded authorization: approvals expire (ISO-8601 UTC). An empty value
    # means no expiry was recorded by the issuing HITL system; the Phase 14
    # live-validation tests always set an explicit expiry.
    expires_at: str = ""

    def digest_matches(self, request: HumanReviewRequest) -> bool:
        return hmac.compare_digest(self.request_digest, request_digest(request))


def request_digest(request: HumanReviewRequest) -> str:
    """Stable SHA-256 digest binding a review decision to its exact request."""
    payload = request.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sign_review(decision: HumanReviewDecision, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), decision.request_digest.encode("utf-8"), hashlib.sha256).hexdigest()


# ============================================================
# Controlled-execution policy (deterministic, non-LLM)
# ============================================================

# The ONLY tool names a controlled live run may execute, and only for the
# actions below. Everything else is blocked by construction.
CONTROLLED_EXECUTION_ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    "fill_field": frozenset({"fill"}),
    "select_option": frozenset({"select"}),
    "check_control": frozenset({"check"}),
    "uncheck_control": frozenset({"uncheck"}),
}

# Semantic-ID prefixes never allowed in controlled live execution.
FORBIDDEN_CONTROLLED_SEMANTIC_PREFIXES = (
    "field:password",
    "field:otp",
    "field:captcha",
    "field:pin",
    "field:mfa",
    "field:passwd",
)

# SUBMISSION keywords that mark a control as the final-legal boundary.
FINAL_BOUNDARY_KEYWORDS = (
    "submit",
    "finalize",
    "final submit",
    "i declare",
    "declaration",
    "i hereby",
    "confirm submission",
    "apply now",
    "complete application",
    "pay now",
    "pay fee",
    "payment",
    "proceed to pay",
)


class ControlledActionDeniedError(UnsafeLiveRunError):
    """Raised when a proposed action is outside the controlled-execution
    allowlist (deterministic check, not model judgment)."""


def validate_controlled_action(
    tool_name: str,
    action_type: str,
    semantic_id: str | None,
    accessible_text: str = "",
) -> None:
    """Deterministically authorize one controlled action. Raises otherwise."""
    allowed_actions = CONTROLLED_EXECUTION_ALLOWED_ACTIONS.get(tool_name)
    if allowed_actions is None or action_type not in allowed_actions:
        raise ControlledActionDeniedError(
            f"Controlled live execution: tool/action not allowed: "
            f"{tool_name}/{action_type}. Allowed: "
            f"{sorted(CONTROLLED_EXECUTION_ALLOWED_ACTIONS)}"
        )
    sid = (semantic_id or "").lower()
    for prefix in FORBIDDEN_CONTROLLED_SEMANTIC_PREFIXES:
        if sid.startswith(prefix):
            raise ControlledActionDeniedError(
                f"Controlled live execution: sensitive target forbidden: {semantic_id}"
            )
    text = (accessible_text or "").lower()
    for kw in FINAL_BOUNDARY_KEYWORDS:
        if kw in text or kw in sid:
            raise ControlledActionDeniedError(
                f"Controlled live execution: final-boundary control "
                f"('{kw}') is human-gated and never executed autonomously"
            )


# ============================================================
# Ambiguity & injection helpers
# ============================================================

# When both fields map from a single reference, all but the first are ambiguity
# UNLESS the labels are structurally distinct roles (e.g. permanent_address vs
# address carry distinct canonical references).
AMBIGUITY_CASCADE_EXCLUSIONS = frozenset({"address", "permanent_address"})


def classify_injection_exposure(
    visible_text: str,
    alerts_text: str = "",
    placeholder_text: str = "",
) -> str:
    """Detect adversarial instruction patterns in live page content.

    Live pages are untrusted; detected patterns are recorded as exposure
    evidence. They never change policy — PolicyEngine remains authoritative.
    """
    corpus = f"{visible_text}\n{alerts_text}\n{placeholder_text}".lower()
    patterns = (
        "ignore previous instructions",
        "ignore all previous",
        "system prompt",
        "you are now",
        "disregard your",
        "override policy",
        "bypass policy",
        "pre-approved",
        "execute payment",
        "agent mode enabled",
        "developer mode",
        "reset your instructions",
        "new instructions:",
    )
    for pat in patterns:
        if pat in corpus:
            return pat
    return "none"


def classify_environment_error(exc: BaseException) -> EnvironmentCondition:
    """Classify external failures as environment conditions, never agent failure."""
    from playwright.async_api import Error as PlaywrightError

    if isinstance(exc, PlaywrightError):
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            return EnvironmentCondition.TIMEOUT
        if "net::err" in msg or "err_name_not_resolved" in msg or "err_connection" in msg:
            return EnvironmentCondition.NETWORK_FAILURE
        if "target closed" in msg or "browser has been closed" in msg:
            return EnvironmentCondition.ENVIRONMENT_FAILURE
        return EnvironmentCondition.ENVIRONMENT_FAILURE
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return EnvironmentCondition.TIMEOUT
    if "ssl" in name or "connection" in name or "network" in name or "socket" in name:
        return EnvironmentCondition.NETWORK_FAILURE
    return EnvironmentCondition.ENVIRONMENT_FAILURE


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
