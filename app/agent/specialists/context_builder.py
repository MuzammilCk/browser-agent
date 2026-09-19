"""Context builder for Phase 10 specialist agents.

Rule 3: USE ALLOWLISTED PROJECTIONS
- Specialists receive serialized projection objects only.
- Never pass ToolContext, AgentRuntime, AgentWorldState, BrowserExecutor,
  ToolRegistry, Playwright Page/BrowserContext, secrets, credentials,
  raw document bytes, or full conversation history.
- Do not rely only on validators to strip dangerous objects.
- Dangerous runtime objects should never cross the specialist boundary.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.specialists.models import (
    DocumentMetadataProjection,
    ElementSummaryProjection,
    FailureEvidenceProjection,
    MemorySummaryProjection,
    PageObservationProjection,
    SpecialistContext,
    SpecialistPermission,
    SpecialistType,
    WorldStateProjection,
    new_specialist_id,
)
from app.agent.specialists.registry import get_specialist_registry
from app.browser.observer import PageObservation

logger = logging.getLogger(__name__)


def build_specialist_context(
    *,
    parent_run_id: str,
    specialist_type: SpecialistType | str,
    parameters: dict[str, Any] | None = None,
    goal: str | None = None,
    subgoal: str | None = None,
    observation: PageObservation | None = None,
    world_state: Any | None = None,  # AgentWorldState
    failure_evidence: Any | None = None,  # FailureEvidence or FailureClassification
    memory_items: list[Any] | None = None,
    document_references: list[dict[str, str]] | None = None,
    timeout_seconds: float = 10.0,
    invocation_id: str | None = None,
) -> SpecialistContext:
    """Build an isolated, allowlisted SpecialistContext for a specialist invocation.

    Strict projection building based on the specialist's authoritative permission class:
    - READ_ONLY (PortalResearch, FormSemantics): observation projection, goal/subgoal, no vault/failure.
    - VAULT_SCOPED (DocumentAgent): document metadata projection, goal, no failure/full elements.
    - ANALYSIS_ONLY (RecoveryAgent): failure evidence, world state projection, goal/subgoal, no vault.
    - VERIFICATION_ONLY (VerificationAgent): observation projection, world state projection, goal/subgoal.

    Completely strips any live browser objects, Playwright handles, or secrets.
    """
    if isinstance(specialist_type, str):
        specialist_type = SpecialistType(specialist_type)

    # 1. Authoritative permission lookup (Rule 5)
    registry = get_specialist_registry()
    permission = registry.get_permission(specialist_type)
    if permission is None:
        # Default permissions for canonical specialists if registry uninitialized
        _DEFAULT_PERMS = {
            SpecialistType.PORTAL_RESEARCH: SpecialistPermission.READ_ONLY,
            SpecialistType.FORM_SEMANTICS: SpecialistPermission.READ_ONLY,
            SpecialistType.DOCUMENT: SpecialistPermission.VAULT_SCOPED,
            SpecialistType.RECOVERY: SpecialistPermission.ANALYSIS_ONLY,
            SpecialistType.VERIFICATION: SpecialistPermission.VERIFICATION_ONLY,
        }
        permission = _DEFAULT_PERMS.get(specialist_type, SpecialistPermission.READ_ONLY)

    # 2. Build allowlisted PageObservation projection if permitted
    obs_projection: PageObservationProjection | None = None
    if permission in (
        SpecialistPermission.READ_ONLY,
        SpecialistPermission.VERIFICATION_ONLY,
    ) and observation is not None:
        ps = getattr(observation, "page_state", observation)
        raw_elements = getattr(ps, "elements", getattr(observation, "interactive_elements", []))

        elements_proj: list[ElementSummaryProjection] = []
        for el in raw_elements:
            name_val = getattr(el, "accessible_name", None) or getattr(el, "label_text", None) or getattr(el, "name", None) or getattr(el, "html_name", None)
            val = getattr(el, "value", None)
            req = getattr(el, "required", getattr(el, "is_required", False))
            dis = getattr(el, "disabled", getattr(el, "is_disabled", False))
            chk = getattr(el, "checked", getattr(el, "is_checked", None))
            sel = getattr(el, "selected_options", []) or []
            opts = getattr(el, "options", []) or []

            elements_proj.append(
                ElementSummaryProjection(
                    ref=getattr(el, "ref", ""),
                    role=getattr(el, "role", None),
                    name=name_val,
                    value=val if not _is_sensitive_role_or_type(el) else "[MASKED]",
                    input_type=getattr(el, "input_type", None),
                    required=bool(req),
                    disabled=bool(dis),
                    checked=chk,
                    selected_options=list(sel) if sel else [],
                    options=list(opts) if opts else [],
                    placeholder=getattr(el, "placeholder", None),
                )
            )

        url_val = getattr(ps, "url", getattr(observation, "url", ""))
        title_val = getattr(ps, "title", getattr(observation, "title", ""))
        page_type_val = getattr(ps, "page_type", getattr(observation, "page_type", "unknown"))
        if hasattr(page_type_val, "value"):
            page_type_val = page_type_val.value
        else:
            page_type_val = str(page_type_val)

        val_errs: list[str] = []
        raw_errs = getattr(ps, "validation_errors", getattr(observation, "validation_errors", []))
        for ve in raw_errs:
            if hasattr(ve, "message") and ve.message:
                val_errs.append(str(ve.message))
            else:
                val_errs.append(str(ve))

        alert_list: list[str] = []
        raw_alerts = getattr(ps, "alerts", getattr(observation, "alerts", []))
        for al in raw_alerts:
            if hasattr(al, "text") and al.text:
                alert_list.append(str(al.text))
            elif hasattr(al, "name") and al.name:
                alert_list.append(str(al.name))
            else:
                alert_list.append(str(al))

        tabs_obj = getattr(ps, "tabs", getattr(observation, "open_tabs", None))
        total_tabs = getattr(tabs_obj, "total", len(tabs_obj) if isinstance(tabs_obj, (list, tuple)) else 1)

        obs_projection = PageObservationProjection(
            url=url_val,
            title=title_val,
            page_type=page_type_val,
            observation_id=getattr(observation, "observation_id", ""),
            elements=elements_proj,
            validation_errors=val_errs,
            alerts=alert_list,
            open_tabs=total_tabs,
        )

    # 3. Build allowlisted WorldState projection if permitted
    ws_projection: WorldStateProjection | None = None
    if permission in (
        SpecialistPermission.ANALYSIS_ONLY,
        SpecialistPermission.VERIFICATION_ONLY,
    ) and world_state is not None:
        # Extract safe verified facts dictionary (names and strings only, no secrets)
        verified_facts: dict[str, Any] = {}
        if hasattr(world_state, "verified_values"):
            for k, v in world_state.verified_values.items():
                verified_facts[k] = str(v)
        elif isinstance(world_state, dict):
            verified_facts = {
                k: str(v)
                for k, v in world_state.get("verified_facts", {}).items()
            }

        unresolved: list[str] = []
        if hasattr(world_state, "unresolved_questions"):
            unresolved = list(world_state.unresolved_questions)

        completed: list[str] = []
        if hasattr(world_state, "completed_subgoals"):
            completed = list(world_state.completed_subgoals)

        val_errors: list[str] = []
        if hasattr(world_state, "validation_errors"):
            val_errors = list(world_state.validation_errors)

        ws_projection = WorldStateProjection(
            portal=getattr(world_state, "portal", ""),
            state_version=getattr(world_state, "version", 0),
            verified_facts=verified_facts,
            unresolved_questions=unresolved,
            completed_subgoals=completed,
            validation_errors=val_errors,
        )

    # 4. Build allowlisted FailureEvidence projection if permitted
    fail_projection: FailureEvidenceProjection | None = None
    if permission == SpecialistPermission.ANALYSIS_ONLY and failure_evidence is not None:
        if isinstance(failure_evidence, dict):
            ft = failure_evidence.get("failure_type", "UNKNOWN")
            ft_str = ft.value if hasattr(ft, "value") else str(ft)
            ev_obj = failure_evidence.get("evidence", failure_evidence)
            is_ev_dict = isinstance(ev_obj, dict)
            fail_projection = FailureEvidenceProjection(
                failure_type=ft_str,
                error_code=str(ev_obj.get("error_code", "") if is_ev_dict else getattr(ev_obj, "error_code", "")),
                message=str(ev_obj.get("message", "") if is_ev_dict else getattr(ev_obj, "message", "")),
                target_selector=ev_obj.get("selector") if is_ev_dict else getattr(ev_obj, "selector", None),
                target_semantic_id=ev_obj.get("semantic_id") if is_ev_dict else getattr(ev_obj, "semantic_id", None),
                attempt_number=failure_evidence.get("attempt_number", 1),
            )
        else:
            ft = getattr(failure_evidence, "failure_type", "UNKNOWN")
            ft_str = ft.value if hasattr(ft, "value") else str(ft)
            ev_obj = getattr(failure_evidence, "evidence", failure_evidence)
            fail_projection = FailureEvidenceProjection(
                failure_type=ft_str,
                error_code=str(getattr(ev_obj, "error_code", "")),
                message=str(getattr(ev_obj, "message", "")),
                target_selector=getattr(ev_obj, "selector", None),
                target_semantic_id=getattr(ev_obj, "semantic_id", None),
                attempt_number=getattr(failure_evidence, "attempt_number", 1),
            )

    # 5. Build allowlisted DocumentMetadata projection if permitted
    doc_projections: list[DocumentMetadataProjection] = []
    if permission == SpecialistPermission.VAULT_SCOPED and document_references:
        for d in document_references:
            doc_projections.append(
                DocumentMetadataProjection(
                    reference=d.get("ref", ""),
                    display_name=d.get("display_name", ""),
                    document_type=d.get("document_type", ""),
                    sensitivity=d.get("sensitivity", "masked"),
                    is_available=bool(d.get("is_available", True)),
                )
            )

    # 6. Build allowlisted Memory summaries if provided
    mem_projections: list[MemorySummaryProjection] = []
    if memory_items:
        for m in memory_items:
            if isinstance(m, dict):
                mem_projections.append(
                    MemorySummaryProjection(
                        memory_type=m.get("memory_type", "semantic"),
                        subject=m.get("subject", ""),
                        summary=m.get("summary", ""),
                        confidence=float(m.get("confidence", 1.0)),
                    )
                )

    # 7. Safe filtered parameters (no secrets or handles)
    clean_params: dict[str, Any] = {}
    for k, v in (parameters or {}).items():
        if isinstance(v, (str, int, float, bool, list, dict)) and not _is_sensitive_key(k):
            clean_params[k] = v

    return SpecialistContext(
        invocation_id=invocation_id or new_specialist_id("spec_inv"),
        parent_run_id=parent_run_id,
        specialist_type=specialist_type,
        permission=permission,
        timeout_seconds=timeout_seconds,
        goal_projection=goal,
        subgoal_projection=subgoal,
        observation_projection=obs_projection,
        world_state_projection=ws_projection,
        memory_projections=mem_projections,
        failure_evidence=fail_projection,
        document_metadata=doc_projections,
        parameters=clean_params,
    )


def _is_sensitive_key(key: str) -> bool:
    """Check if key suggests sensitive content."""
    key_lower = key.lower()
    return any(
        s in key_lower
        for s in ("password", "otp", "secret", "token", "auth", "credential", "pin", "cvv")
    )


def _is_sensitive_role_or_type(el: Any) -> bool:
    """Check if element input type is a password or masked field."""
    inp_type = str(getattr(el, "input_type", "")).lower()
    return inp_type in ("password", "hidden")
