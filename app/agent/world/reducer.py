"""Semantic observation and action reducer — Phase 6.

Reduces raw PageObservation and ToolResults into durable AgentWorldState.

Key invariants (AGENTS.md rules 4, 10, 12, 13):
1. Epistemic hierarchy: VERIFIED > OBSERVED > INFERRED > STALE.
   An unverified observation (or partial DOM blanking during re-render) NEVER
   destroys or downgrades an already verified fact.
2. Ephemeral DOM ref invalidation:
   When observation_id changes, old DOM refs become invalid/stale. Semantic
   fields are matched across observations by stable semantic_id, updating
   current_ref to the new observation's ref while preserving verified status.
3. Multi-tab continuity:
   Tab state is preserved across active tab changes. Actions against inactive
   tabs or stale tab observations fail closed.
4. Deterministic provenance:
   Every state update increments version by 1 and appends a Provenance record.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.tools.base import ToolCall, ToolResult
from app.agent.world.models import (
    AgentWorldState,
    DocumentWorldState,
    EpistemicStatus,
    Provenance,
    SemanticField,
    TabWorldState,
    utc_now_iso,
)
from app.agent.world.semantic_id import compute_semantic_id
from app.browser.observer import PageObservation

logger = logging.getLogger(__name__)


def reduce_observation(
    world_state: AgentWorldState,
    observation: PageObservation,
    timestamp: str | None = None,
) -> AgentWorldState:
    """Reduce a PageObservation into AgentWorldState.

    Updates semantic fields, tab state, validation errors, and authentication.
    Invalidates stale DOM refs while preserving durable verified facts.
    """
    ts = timestamp or utc_now_iso()
    new_obs_id = observation.observation_id
    ps = observation.page_state

    # 1. Monotonically increment version
    world_state.version += 1
    world_state.updated_at = ts

    # 2. Determine active tab index
    active_tab_index = ps.tabs.active_index if ps.tabs and ps.tabs.tabs else 0
    previous_tab_index = world_state.current_tab_index

    # If tab switched, save previous tab's fields into its TabWorldState
    if previous_tab_index in world_state.tabs:
        world_state.tabs[previous_tab_index].semantic_fields = dict(world_state.semantic_fields)
        world_state.tabs[previous_tab_index].active = False

    world_state.current_tab_index = active_tab_index
    world_state.current_page_url = ps.url
    world_state.current_page_title = ps.title
    world_state.current_page_type = ps.page_type
    world_state.current_observation_id = new_obs_id

    # 3. Synchronize TabWorldState
    if ps.tabs and ps.tabs.tabs:
        for tab in ps.tabs.tabs:
            if tab.index not in world_state.tabs:
                world_state.tabs[tab.index] = TabWorldState(
                    tab_index=tab.index,
                    url=tab.url,
                    active=tab.active,
                    last_observed_at=ts,
                )
            else:
                world_state.tabs[tab.index].url = tab.url
                world_state.tabs[tab.index].active = tab.active
    else:
        if active_tab_index not in world_state.tabs:
            world_state.tabs[active_tab_index] = TabWorldState(
                tab_index=active_tab_index,
                url=ps.url,
                title=ps.title,
                active=True,
                observation_id=new_obs_id,
                page_type=ps.page_type,
                last_observed_at=ts,
            )

    active_tab_state = world_state.tabs.get(active_tab_index)
    if active_tab_state:
        active_tab_state.url = ps.url
        active_tab_state.title = ps.title
        active_tab_state.active = True
        active_tab_state.observation_id = new_obs_id
        active_tab_state.page_type = ps.page_type
        active_tab_state.last_observed_at = ts

    # 4. Invalidate old ephemeral DOM refs and match elements to semantic fields
    # First, collect interactive/actionable elements from the observation
    observed_semantic_ids: set[str] = set()
    collision_counts: dict[str, int] = {}

    for el in ps.elements:
        if not el.visible:
            continue

        raw_id = compute_semantic_id(el)
        count = collision_counts.get(raw_id, 0)
        collision_counts[raw_id] = count + 1
        semantic_id = compute_semantic_id(el, disambiguation_index=count)
        observed_semantic_ids.add(semantic_id)

        existing_field = world_state.semantic_fields.get(semantic_id)
        if existing_field is not None:
            # Field already tracked in WorldState: update ephemeral handle to new ref
            existing_field.current_ref = el.ref
            existing_field.current_observation_id = new_obs_id
            existing_field.role = el.role
            existing_field.field_type = el.input_type or el.role
            existing_field.label = el.name or existing_field.label
            existing_field.required = el.required
            existing_field.disabled = el.disabled
            existing_field.options = el.selected_options or existing_field.options
            existing_field.value = el.value

            # EPISTEMIC INVARIANT: Do NOT overwrite a VERIFIED status or verified_value!
            if existing_field.status != EpistemicStatus.VERIFIED:
                existing_field.status = EpistemicStatus.OBSERVED

            # If this field has a verified value in verified_values, keep it verified
            if semantic_id in world_state.verified_values:
                existing_field.status = EpistemicStatus.VERIFIED
                existing_field.verified_value = world_state.verified_values[semantic_id]
        else:
            # New semantic field (e.g. dynamic field introduced after interaction)
            is_verified = semantic_id in world_state.verified_values
            verified_val = world_state.verified_values.get(semantic_id)

            new_field = SemanticField(
                semantic_id=semantic_id,
                current_ref=el.ref,
                current_observation_id=new_obs_id,
                label=el.name,
                role=el.role,
                field_type=el.input_type or el.role,
                value=el.value,
                verified_value=verified_val,
                status=EpistemicStatus.VERIFIED if is_verified else EpistemicStatus.OBSERVED,
                required=el.required,
                disabled=el.disabled,
                options=el.selected_options,
            )
            world_state.semantic_fields[semantic_id] = new_field

    # 5. Handle fields missing from this observation
    for sem_id, field in list(world_state.semantic_fields.items()):
        if sem_id not in observed_semantic_ids:
            # Field disappeared from current DOM: invalidate its ephemeral ref
            field.current_ref = None
            field.current_observation_id = None
            if field.status != EpistemicStatus.VERIFIED:
                field.status = EpistemicStatus.STALE
            # If VERIFIED, status remains VERIFIED (the fact is verified, but current_ref is None)

    # Sync back to active tab's semantic_fields
    if active_tab_state:
        active_tab_state.semantic_fields = dict(world_state.semantic_fields)

    # 6. Validation errors
    errors: list[str] = []
    for ve in ps.validation_errors:
        if ve.visible and ve.message:
            msg = f"{ve.target_ref}: {ve.message}" if ve.target_ref else str(ve.message)
            errors.append(msg)
    world_state.validation_errors = errors
    if active_tab_state:
        active_tab_state.validation_errors = errors

    # 7. Authentication detection
    if ps.authentication and ps.authentication.detected:
        world_state.authentication.status = "detected"
        world_state.authentication.challenge_type = ps.authentication.challenge_type
        world_state.authentication.reason = ps.authentication.reason
        world_state.authentication.confidence = ps.authentication.confidence
        world_state.authentication.last_detected_at = ts
        world_state.authentication.provenance = Provenance(
            source="observation",
            observation_id=new_obs_id,
            state_version=world_state.version,
            timestamp=ts,
            details={"challenge_type": ps.authentication.challenge_type},
        )
    elif world_state.authentication.status == "detected":
        # Challenge cleared
        world_state.authentication.status = "none"

    # 8. Provenance record
    world_state.evidence.append(
        Provenance(
            source="observation",
            observation_id=new_obs_id,
            state_version=world_state.version,
            timestamp=ts,
            details={
                "url": ps.url,
                "tab_index": active_tab_index,
                "elements_observed": len(observed_semantic_ids),
                "validation_errors": len(errors),
            },
        )
    )

    return world_state


def record_verified_action(
    world_state: AgentWorldState,
    target_ref_or_semantic_id: str,
    verified_value: Any,
    *,
    binding: str | None = None,
    tool_name: str = "",
    observation_id: str = "",
    timestamp: str | None = None,
) -> AgentWorldState:
    """Record a verified action result into AgentWorldState.

    Promotes field to VERIFIED status, stores verified_value, and updates
    field_mappings and verified_values dictionaries.
    """
    ts = timestamp or utc_now_iso()
    world_state.version += 1
    world_state.updated_at = ts

    # Find the target field by semantic_id or current_ref
    target_field: SemanticField | None = None
    if target_ref_or_semantic_id in world_state.semantic_fields:
        target_field = world_state.semantic_fields[target_ref_or_semantic_id]
    else:
        for f in world_state.semantic_fields.values():
            if f.current_ref == target_ref_or_semantic_id:
                target_field = f
                break

    semantic_id = target_field.semantic_id if target_field else target_ref_or_semantic_id

    prov = Provenance(
        source="verification",
        observation_id=observation_id or world_state.current_observation_id,
        tool_name=tool_name,
        target_ref=target_field.current_ref if target_field else target_ref_or_semantic_id,
        semantic_id=semantic_id,
        state_version=world_state.version,
        timestamp=ts,
        details={"verified_value": str(verified_value)},
    )

    if target_field is not None:
        target_field.status = EpistemicStatus.VERIFIED
        target_field.verified_value = verified_value
        if binding:
            target_field.binding = binding
        target_field.provenance = prov

    # Record into verified_values
    world_state.verified_values[semantic_id] = verified_value
    if binding:
        world_state.verified_values[binding] = verified_value
        world_state.field_mappings[semantic_id] = binding

    # If this is a document upload
    if binding and binding.startswith("DOCUMENT."):
        world_state.documents[binding] = DocumentWorldState(
            document_ref=binding,
            status="uploaded",
            target_field_semantic_id=semantic_id,
            target_field_ref=target_field.current_ref if target_field else None,
            verified=True,
            provenance=prov,
        )

    world_state.evidence.append(prov)
    return world_state


def record_tool_result(
    world_state: AgentWorldState,
    tool_result: ToolResult,
    *,
    tool_call: ToolCall | None = None,
    timestamp: str | None = None,
) -> AgentWorldState:
    """Process a ToolResult and update WorldState accordingly.

    If verification succeeded on a mutating action, updates verified_values.
    If post_observation is present, immediately reduces it into WorldState.
    """
    ts = timestamp or utc_now_iso()

    if tool_result.success and tool_result.verification_status in ("verified", "success", "confirmed"):
        target_ref = None
        verified_val = None
        binding = None

        action = (getattr(tool_call, "action", None) or getattr(tool_call, "browser_action", None)) if tool_call else None
        if action:
            target_ref = action.target_ref
            verified_val = action.literal_value or action.value_ref
            binding = action.value_ref or action.document_ref
        elif tool_result.payload:
            target_ref = tool_result.payload.get("target_ref")
            verified_val = tool_result.payload.get("selected") or tool_result.payload.get("value")

        if target_ref:
            record_verified_action(
                world_state,
                target_ref,
                verified_val,
                binding=binding,
                tool_name=tool_result.tool_name,
                observation_id=tool_result.observation_id or world_state.current_observation_id,
                timestamp=ts,
            )

    # Immediately reduce post_observation if returned by executor
    if tool_result.post_observation:
        reduce_observation(world_state, tool_result.post_observation, timestamp=ts)

    return world_state


def is_target_ref_valid(
    world_state: AgentWorldState,
    target_ref: str,
    observation_id: str,
    tab_index: int | None = None,
    expected_semantic_id: str | None = None,
) -> bool:
    """Validate whether an ephemeral target ref is currently valid for execution.

    Fails closed if:
    1. observation_id does not match world_state.current_observation_id
    2. tab_index does not match world_state.current_tab_index
    3. expected_semantic_id (if specified) does not match target_ref
    4. target_ref is not the current_ref of any active semantic field on the page
    """
    if not target_ref or not observation_id:
        return False

    if observation_id != world_state.current_observation_id:
        return False

    if tab_index is not None and tab_index != world_state.current_tab_index:
        return False

    if expected_semantic_id is not None:
        field = world_state.semantic_fields.get(expected_semantic_id)
        if not field:
            return False
        return field.current_ref == target_ref and field.is_actionable(observation_id)

    return any(
        f.current_ref == target_ref and f.is_actionable(observation_id)
        for f in world_state.semantic_fields.values()
    )
