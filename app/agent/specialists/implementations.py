"""Initial 5 specialist agent implementations — Phase 10.

CRITICAL INVARIANTS:
1. All specialists are ADVISORS, never authorities (Rule 1).
2. All specialists are non-mutating (no browser mutation, no direct WorldState mutation).
3. No specialist can access BrowserExecutor, Playwright Page, or call other specialists.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent.specialists.base import SpecialistAgent
from app.agent.specialists.models import (
    CriterionEvaluation,
    DocumentMetadataProjection,
    DocumentSpecialistOutput,
    ElementSummaryProjection,
    FieldSemanticInfo,
    FormSemanticsOutput,
    MatchedDocumentInfo,
    PortalResearchOutput,
    RecoverySpecialistOutput,
    ResultKind,
    SpecialistContext,
    SpecialistOutcome,
    SpecialistPermission,
    SpecialistResult,
    SpecialistType,
    VerificationSpecialistOutput,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. PortalResearchAgent (READ_ONLY)
# ==============================================================================


class PortalResearchInput(BaseModel):
    """Input parameters for PortalResearchAgent."""

    focus: str = Field(default="structure", description="Analysis focus (e.g. 'structure', 'navigation')")
    max_landmarks: int = Field(default=10, ge=1, le=50)


class PortalResearchAgent(SpecialistAgent):
    """Read-only specialist that researches portal structure and navigation."""

    specialist_type = SpecialistType.PORTAL_RESEARCH
    permission = SpecialistPermission.READ_ONLY
    default_timeout = 8.0
    input_schema = PortalResearchInput
    output_schema = PortalResearchOutput

    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        obs = context.observation_projection
        if obs is None:
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.FAILURE,
                error_code="MISSING_OBSERVATION",
                error_message="PortalResearchAgent requires an observation projection",
            )

        evidence: list[str] = [
            f"Observed URL: {obs.url}",
            f"Observed title: {obs.title}",
            f"Interactive elements count: {len(obs.elements)}",
        ]

        # Extract landmarks and workflow entrypoints
        landmarks: list[str] = []
        entrypoints: list[str] = []
        workflows: list[str] = []

        for el in obs.elements:
            name = el.name or el.ref
            if el.role in ("button", "link") and el.name:
                entrypoints.append(f"{el.role}: {el.name} [{el.ref}]")
            elif el.role in ("heading", "region", "banner", "navigation"):
                landmarks.append(f"{el.role}: {name}")

        if "login" in obs.url.lower() or "auth" in obs.url.lower():
            workflows.append("authentication_flow")
        if any("apply" in ep.lower() or "register" in ep.lower() for ep in entrypoints):
            workflows.append("application_registration_flow")
        if not workflows:
            workflows.append("general_navigation_flow")

        portal_name = obs.title.split("-")[0].strip() if obs.title else "Government Portal"

        output = PortalResearchOutput(
            portal_name=portal_name,
            identified_workflows=workflows,
            entrypoints=entrypoints[:10],
            form_landmarks=landmarks[:10],
            navigation_hints=[
                "Standard official workflow structure detected",
                f"Page type identified as {obs.page_type}",
            ],
            confidence=0.9,
            evidence=evidence,
        )

        return SpecialistResult(
            result_kind=ResultKind.SPECIALIST_ANALYSIS,
            invocation_id=context.invocation_id,
            parent_run_id=context.parent_run_id,
            specialist_type=self.specialist_type,
            permission=self.permission,
            outcome=SpecialistOutcome.SUCCESS,
            confidence=0.9,
            data=output.model_dump(),
            evidence=evidence,
        )


# ==============================================================================
# 2. FormSemanticsAgent (READ_ONLY)
# ==============================================================================


class FormSemanticsInput(BaseModel):
    """Input parameters for FormSemanticsAgent."""

    target_subgoal: str | None = Field(default=None, description="Current subgoal if available")
    identify_ambiguity: bool = Field(default=True)


class FormSemanticsAgent(SpecialistAgent):
    """Read-only specialist that analyzes form structure and field semantics."""

    specialist_type = SpecialistType.FORM_SEMANTICS
    permission = SpecialistPermission.READ_ONLY
    default_timeout = 10.0
    input_schema = FormSemanticsInput
    output_schema = FormSemanticsOutput

    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        obs = context.observation_projection
        if obs is None:
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.FAILURE,
                error_code="MISSING_OBSERVATION",
                error_message="FormSemanticsAgent requires an observation projection",
            )

        fields: list[FieldSemanticInfo] = []
        ambiguities: list[str] = []
        evidence: list[str] = []
        suggested_mappings: dict[str, str] = {}

        # Track labels to detect duplicate / ambiguous fields
        seen_labels: dict[str, list[str]] = {}

        for el in obs.elements:
            if el.role in ("textbox", "combobox", "checkbox", "radio", "searchbox", "spinbutton") or el.input_type in ("text", "email", "tel", "number", "select"):
                label = (el.name or el.placeholder or el.ref).strip()
                label_norm = label.lower()
                slug = _derive_semantic_slug(label, el.input_type or el.role or "text")

                seen_labels.setdefault(label_norm, []).append(el.ref)

                field_info = FieldSemanticInfo(
                    element_ref=el.ref,
                    semantic_slug=slug,
                    field_label=label,
                    input_type=el.input_type or "text",
                    is_required=el.required,
                    confidence=0.92,
                )
                fields.append(field_info)
                evidence.append(f"Mapped {el.ref} ('{label}') -> {slug}")

                # Suggest mapping to standard user references
                user_ref = _suggest_user_ref(slug)
                if user_ref:
                    suggested_mappings[slug] = user_ref

        # Check for ambiguity (Rule: ambiguity beats guessing)
        for label, refs in seen_labels.items():
            if len(refs) > 1:
                amb_msg = f"Ambiguous field label '{label}' matches multiple elements: {refs}"
                ambiguities.append(amb_msg)
                for f in fields:
                    if f.element_ref in refs:
                        f.ambiguity_reason = amb_msg
                        f.confidence = 0.5

        output = FormSemanticsOutput(
            field_semantics=fields,
            ambiguities=ambiguities,
            confidence=0.7 if ambiguities else 0.95,
            evidence=evidence,
            suggested_field_mappings=suggested_mappings,
        )

        return SpecialistResult(
            result_kind=ResultKind.SPECIALIST_ANALYSIS,
            invocation_id=context.invocation_id,
            parent_run_id=context.parent_run_id,
            specialist_type=self.specialist_type,
            permission=self.permission,
            outcome=SpecialistOutcome.SUCCESS,
            confidence=output.confidence,
            data=output.model_dump(),
            evidence=evidence,
            ambiguities=ambiguities,
        )


def _derive_semantic_slug(label: str, role: str) -> str:
    """Generate normalized semantic slug."""
    clean = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")
    clean = "_".join(part for part in clean.split("_") if part)
    return f"field:{clean}" if clean else f"field:{role}"


def _suggest_user_ref(slug: str) -> str | None:
    """Suggest semantic user profile reference for common slugs."""
    s = slug.lower()
    if "name" in s or "fullname" in s:
        return "USER.full_name"
    if "dob" in s or "birth" in s:
        return "USER.date_of_birth"
    if "gender" in s:
        return "USER.gender"
    if "phone" in s or "mobile" in s:
        return "USER.phone_number"
    if "email" in s:
        return "USER.email"
    if "pin" in s or "postal" in s:
        return "USER.pincode"
    if "aadhaar" in s:
        return "DOCUMENT.aadhaar"
    if "pan" in s:
        return "DOCUMENT.pan"
    return None


# ==============================================================================
# 3. DocumentAgent (VAULT_SCOPED)
# ==============================================================================


class DocumentSpecialistInput(BaseModel):
    """Input parameters for DocumentAgent."""

    required_types: list[str] = Field(default_factory=list)
    form_requirements: list[str] = Field(default_factory=list)


class DocumentAgent(SpecialistAgent):
    """Vault-scoped specialist that inspects document metadata references."""

    specialist_type = SpecialistType.DOCUMENT
    permission = SpecialistPermission.VAULT_SCOPED
    default_timeout = 8.0
    input_schema = DocumentSpecialistInput
    output_schema = DocumentSpecialistOutput

    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        available_docs = context.document_metadata
        args = DocumentSpecialistInput.model_validate(context.parameters)

        matched: list[MatchedDocumentInfo] = []
        missing: list[str] = []
        evidence: list[str] = []

        # Available references lookup
        avail_map = {d.reference.lower(): d for d in available_docs}
        avail_types = {d.document_type.lower(): d for d in available_docs}

        # Check required document types
        for req in args.required_types:
            req_clean = req.lower().replace("document.", "").replace(" ", "_")
            doc = avail_types.get(req_clean) or avail_map.get(f"document.{req_clean}")
            if doc and doc.is_available:
                matched.append(
                    MatchedDocumentInfo(
                        reference=doc.reference,
                        document_type=doc.document_type,
                        match_reason=f"Matches required type '{req}'",
                        is_present=True,
                    )
                )
                evidence.append(f"Found available document reference '{doc.reference}' for '{req}'")
            else:
                missing.append(req)
                evidence.append(f"Required document '{req}' not available in local metadata")

        # If no specific required types were requested, summarize all available metadata
        if not args.required_types:
            for d in available_docs:
                if d.is_available:
                    matched.append(
                        MatchedDocumentInfo(
                            reference=d.reference,
                            document_type=d.document_type,
                            match_reason="Available in local metadata",
                            is_present=True,
                        )
                    )
                    evidence.append(f"Available document reference '{d.reference}'")

        output = DocumentSpecialistOutput(
            matched_documents=matched,
            missing_documents=missing,
            confidence=0.9 if not missing else 0.6,
            evidence=evidence,
        )

        return SpecialistResult(
            result_kind=ResultKind.SPECIALIST_ANALYSIS,
            invocation_id=context.invocation_id,
            parent_run_id=context.parent_run_id,
            specialist_type=self.specialist_type,
            permission=self.permission,
            outcome=SpecialistOutcome.SUCCESS,
            confidence=output.confidence,
            data=output.model_dump(),
            evidence=evidence,
        )


# ==============================================================================
# 4. RecoveryAgent (ANALYSIS_ONLY)
# ==============================================================================


class RecoverySpecialistInput(BaseModel):
    """Input parameters for RecoveryAgent."""

    consider_recent_failures: bool = Field(default=True)


class RecoveryAgent(SpecialistAgent):
    """Analysis-only specialist that investigates failure evidence and suggests recovery."""

    specialist_type = SpecialistType.RECOVERY
    permission = SpecialistPermission.ANALYSIS_ONLY
    default_timeout = 8.0
    input_schema = RecoverySpecialistInput
    output_schema = RecoverySpecialistOutput

    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        ev = context.failure_evidence
        ws = context.world_state_projection

        if ev is None:
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.FAILURE,
                error_code="MISSING_FAILURE_EVIDENCE",
                error_message="RecoveryAgent requires failure evidence projection",
            )

        evidence: list[str] = [
            f"Failure type: {ev.failure_type}",
            f"Error code: {ev.error_code}",
            f"Message: {ev.message}",
            f"Attempt number: {ev.attempt_number}",
        ]

        ft = ev.failure_type.upper()
        recommended_strategy = "RETRY_WITH_FRESH_TARGET"
        target_semantic_id = ev.target_semantic_id
        root_cause = "Unknown failure"
        budget = "within_budget" if ev.attempt_number <= 3 else "budget_exhausted"

        if "STALE" in ft or "STALE" in ev.error_code:
            root_cause = "Stale reference: page DOM updated or dynamic re-render invalidated target reference"
            recommended_strategy = "RETRY_WITH_FRESH_TARGET"
            evidence.append("Stale reference detected — recommend re-observation and fresh target resolution")
        elif "VALIDATION" in ft:
            root_cause = "Form input rejected by client-side or server-side validation rule"
            recommended_strategy = "REVISE_INPUT_AND_RETRY"
            evidence.append("Validation failure detected — recommend revising input format")
        elif "NAVIGATION" in ft:
            root_cause = "Page navigation timed out or encountered HTTP error"
            recommended_strategy = "REOBSERVE_AND_RETRY"
            evidence.append("Navigation issue detected — recommend page re-observation")
        elif "AMBIGUOUS" in ft:
            root_cause = "Multiple interactive targets match ambiguous label"
            recommended_strategy = "REQUEST_CLARIFICATION"
            evidence.append("Ambiguity detected — ambiguity beats guessing, recommend user clarification")
        elif "POLICY" in ft:
            root_cause = "PolicyEngine denied proposed action"
            recommended_strategy = "FAIL_CLOSED"
            evidence.append("Policy denial cannot be automatically retried")
        elif "PROMPT_INJECTION" in ft:
            root_cause = "Security violation: prompt injection detected"
            recommended_strategy = "FAIL_CLOSED"
            evidence.append("Prompt injection cannot be retried")

        if ev.attempt_number > 3:
            recommended_strategy = "TERMINAL_FAILURE"
            evidence.append("Exceeded attempt budget — recommend halting workflow safely")

        output = RecoverySpecialistOutput(
            recommended_strategy=recommended_strategy,
            suggested_target_semantic_id=target_semantic_id,
            root_cause_analysis=root_cause,
            budget_assessment=budget,
            confidence=0.9,
            evidence=evidence,
        )

        return SpecialistResult(
            result_kind=ResultKind.SPECIALIST_ANALYSIS,
            invocation_id=context.invocation_id,
            parent_run_id=context.parent_run_id,
            specialist_type=self.specialist_type,
            permission=self.permission,
            outcome=SpecialistOutcome.SUCCESS,
            confidence=0.9,
            data=output.model_dump(),
            evidence=evidence,
        )


# ==============================================================================
# 5. VerificationAgent (VERIFICATION_ONLY)
# ==============================================================================


class VerificationSpecialistInput(BaseModel):
    """Input parameters for VerificationAgent."""

    criteria: list[str] = Field(default_factory=list, description="Target criteria to evaluate")


class VerificationAgent(SpecialistAgent):
    """Verification-only specialist that assesses evidence against criteria (advisory only)."""

    specialist_type = SpecialistType.VERIFICATION
    permission = SpecialistPermission.VERIFICATION_ONLY
    default_timeout = 8.0
    input_schema = VerificationSpecialistInput
    output_schema = VerificationSpecialistOutput

    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        obs = context.observation_projection
        ws = context.world_state_projection
        args = VerificationSpecialistInput.model_validate(context.parameters)

        evaluations: list[CriterionEvaluation] = []
        missing: list[str] = []
        evidence: list[str] = []

        all_satisfied = True

        for crit in args.criteria:
            crit_lower = crit.lower()
            # Check verified facts in world state
            if ws and any(k.lower() in crit_lower for k in ws.verified_facts.keys()):
                evaluations.append(
                    CriterionEvaluation(
                        criterion_kind="verified_field",
                        description=crit,
                        recommended_verdict="satisfied",
                        evidence="Found matching verified fact in WorldState projection",
                    )
                )
                evidence.append(f"Criterion '{crit}' satisfied by verified WorldState facts")
            # Check page elements
            elif obs and any(
                el.name and (el.name.lower() in crit_lower or crit_lower in el.name.lower())
                for el in obs.elements
            ):
                evaluations.append(
                    CriterionEvaluation(
                        criterion_kind="observed_element",
                        description=crit,
                        recommended_verdict="satisfied",
                        evidence="Found matching element in observation projection",
                    )
                )
                evidence.append(f"Criterion '{crit}' satisfied by observation projection")
            else:
                evaluations.append(
                    CriterionEvaluation(
                        criterion_kind="unobserved",
                        description=crit,
                        recommended_verdict="unsatisfied",
                        evidence="No matching evidence found in current projections",
                    )
                )
                missing.append(crit)
                all_satisfied = False
                evidence.append(f"Criterion '{crit}' not satisfied by current projections")

        output = VerificationSpecialistOutput(
            recommended_verified=all_satisfied and bool(args.criteria),
            criteria_evaluations=evaluations,
            missing_evidence=missing,
            confidence=0.88,
            evidence=evidence,
        )

        return SpecialistResult(
            result_kind=ResultKind.SPECIALIST_ANALYSIS,
            invocation_id=context.invocation_id,
            parent_run_id=context.parent_run_id,
            specialist_type=self.specialist_type,
            permission=self.permission,
            outcome=SpecialistOutcome.SUCCESS,
            confidence=0.88,
            data=output.model_dump(),
            evidence=evidence,
        )
