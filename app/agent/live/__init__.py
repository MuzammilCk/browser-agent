"""Phase 14 — Live portal validation.

This package validates the existing runtime against REAL government portals
without weakening any Phase 1-13 invariant:

- Shadow mode (LIVE_SHADOW) is observation-only: observe → semantic extraction
  → field mapping → planned action trace → human review record. It NEVER
  executes a mutation against a live portal.
- Controlled execution (LIVE_CONTROLLED_EXECUTION) is a separately-constructed,
  explicitly-authorized mode that still routes every mutation through
  ToolRegistry → PolicyEngine → BrowserExecutor → verification → WorldState.
- Mode can never be flipped by model output: the reasoner is not invoked in
  shadow mode, and escalation to controlled execution requires a signed human
  review decision (deterministic check).

Public API:
    PortalProfile          — trusted portal metadata (origin, safe paths, class)
    LiveRunMode            — LIVE_SHADOW | LIVE_CONTROLLED_EXECUTION
    run_live_shadow        — observation-only live validation
    run_controlled_execution — gated, review-bound bounded execution
    HumanReviewRequest/Decision — explicit human review boundary records
    LivePortalRunReport    — structured evidence report (per stage)
    classify_environment_error — environment vs agent failure separation
"""

from __future__ import annotations

from app.agent.live.models import (
    AMBIGUITY_CASCADE_EXCLUSIONS,
    CONTROLLED_EXECUTION_ALLOWED_ACTIONS,
    EnvironmentCondition,
    FieldMappingEvidence,
    FinalBoundaryEvidence,
    HumanReviewDecision,
    HumanReviewRequest,
    LiveOutcomeStatus,
    LivePortalRunReport,
    LiveRunMode,
    OriginMismatchError,
    PlannedAction,
    PortalClass,
    PortalProfile,
    ReviewSignatureError,
    SemanticExtractionEvidence,
    UnsafeLiveRunError,
    classify_environment_error,
    classify_injection_exposure,
)
from app.agent.live.profiles import (
    INDIA_PORTAL,
    MYScheme_PORTAL,
    PMKISAN_PORTAL,
    get_live_portal_profile,
)

__all__ = [
    "AMBIGUITY_CASCADE_EXCLUSIONS",
    "CONTROLLED_EXECUTION_ALLOWED_ACTIONS",
    "EnvironmentCondition",
    "FieldMappingEvidence",
    "FinalBoundaryEvidence",
    "HumanReviewDecision",
    "HumanReviewRequest",
    "INDIA_PORTAL",
    "LiveOutcomeStatus",
    "LivePortalRunReport",
    "LiveRunMode",
    "MYScheme_PORTAL",
    "OriginMismatchError",
    "PMKISAN_PORTAL",
    "PlannedAction",
    "PortalClass",
    "PortalProfile",
    "ReviewSignatureError",
    "SemanticExtractionEvidence",
    "UnsafeLiveRunError",
    "classify_environment_error",
    "classify_injection_exposure",
    "get_live_portal_profile",
    "run_controlled_execution",
    "run_live_shadow",
]


def __getattr__(name: str):  # lazy imports keep browser deps out of unit tests
    if name == "run_live_shadow":
        from app.agent.live.shadow import run_live_shadow

        return run_live_shadow
    if name == "run_controlled_execution":
        from app.agent.live.execution import run_controlled_execution

        return run_controlled_execution
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
