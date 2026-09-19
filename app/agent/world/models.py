"""Durable semantic WorldState models — Phase 6.

Core invariant (AGENTS.md rules 4, 5, 12):
    Plan = intended strategy.
    WorldState = observed / verified reality.
    DOM refs = ephemeral execution handles only.

Design principles:
1. EPHEMERAL vs DURABLE: DOM references (e.g. 'e12') are ephemeral handles that
   belong to exactly one PageObservation. Semantic fields, verified values,
   workflow bindings, and document states are durable across re-observations.
2. EPISTEMIC HIERARCHY: VERIFIED > OBSERVED > INFERRED > STALE. An unverified or
   inferred observation cannot silently overwrite or erase a verified fact.
3. SECRET-FREE: Sensitive data crosses as semantic references (USER.full_name,
   DOCUMENT.aadhaar). No raw secrets, passwords, OTPs, or document byte contents
   are stored in WorldState.
4. PROVENANCE: Every state mutation has an immutable Provenance record with source,
   observation_id, timestamp, and monotonically increasing state_version.
5. NO RAW DOM SNAPSHOTS: Does not store Playwright Page objects or duplicate the
   raw PageState tree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


class EpistemicStatus(str, Enum):
    """Trust level of a field or fact.

    VERIFIED: Confirmed by deterministic runtime execution/verification.
    OBSERVED: Directly extracted from current live page observation.
    INFERRED: Derived by mapper, heuristic, or model proposal (unconfirmed).
    STALE: Previously observed/inferred, but no longer present on active page.
    """

    OBSERVED = "observed"
    INFERRED = "inferred"
    VERIFIED = "verified"
    STALE = "stale"


class Provenance(BaseModel):
    """Immutable audit trail for every meaningful WorldState mutation."""

    source: Literal["observation", "tool_result", "verification", "user", "inferred"]
    observation_id: str = Field(default="", description="Observation that triggered update")
    tool_name: str = Field(default="", description="Tool name if from tool_result")
    target_ref: str | None = Field(default=None, description="Ephemeral target ref if any")
    semantic_id: str | None = Field(default=None, description="Semantic field identifier if any")
    state_version: int = Field(default=0, description="WorldState version at time of change")
    timestamp: str = Field(default_factory=utc_now_iso, description="ISO-8601 UTC timestamp")
    details: dict[str, Any] = Field(default_factory=dict, description="Safe metadata")


class SemanticField(BaseModel):
    """A durable semantic form field or interactive control.

    Identified by a stable semantic_id that survives DOM re-renders and
    re-indexing. Ephemeral DOM ref is tracked via current_ref and invalidated
    when observations change.
    """

    semantic_id: str = Field(description="Stable semantic identifier (e.g. 'field:state')")
    binding: str | None = Field(
        default=None,
        description="User-data reference if mapped (e.g. 'USER.state')",
    )
    label: str | None = Field(default=None, description="Human-readable label / accessible name")
    role: str | None = Field(default=None, description="ARIA or implicit role (textbox, combobox, etc.)")
    field_type: str | None = Field(default=None, description="HTML input type or role classification")

    # Ephemeral handle — valid ONLY for current_observation_id
    current_ref: str | None = Field(
        default=None,
        description="Ephemeral DOM ref from current observation; None when stale/absent",
    )
    current_observation_id: str | None = Field(
        default=None,
        description="Observation ID that granted current_ref",
    )

    # Values
    value: str | None = Field(
        default=None,
        description="Last observed value on page (raw string)",
    )
    verified_value: Any | None = Field(
        default=None,
        description="Value confirmed by deterministic execution verification",
    )

    # Trust & Status
    status: EpistemicStatus = Field(
        default=EpistemicStatus.OBSERVED,
        description="Epistemic status of this field",
    )
    required: bool = Field(default=False, description="Whether field is marked required")
    disabled: bool = Field(default=False, description="Whether field is currently disabled")
    options: list[str] = Field(default_factory=list, description="Dropdown options if select/combobox")

    # Provenance
    provenance: Provenance | None = Field(default=None, description="Last provenance record")

    def is_actionable(self, expected_obs_id: str | None = None) -> bool:
        """True if the field has a valid ephemeral ref for the given observation."""
        if not self.current_ref or self.status == EpistemicStatus.STALE:
            return False
        if expected_obs_id is not None and self.current_observation_id != expected_obs_id:
            return False
        return True


class TabWorldState(BaseModel):
    """Semantic workflow state for one browser tab."""

    tab_index: int = Field(description="Tab position in browser context")
    url: str = Field(default="", description="Current URL of this tab")
    title: str = Field(default="", description="Title of this tab")
    active: bool = Field(default=False, description="True if this is the active tab")
    observation_id: str = Field(default="", description="Observation ID for this tab")
    page_type: str = Field(default="unknown", description="Page type classification")
    semantic_fields: dict[str, SemanticField] = Field(
        default_factory=dict,
        description="Semantic fields observed on this tab",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Visible validation errors on this tab",
    )
    last_observed_at: str = Field(default="", description="ISO-8601 UTC timestamp")


class DocumentWorldState(BaseModel):
    """Workflow state of an uploaded or requested document."""

    document_ref: str = Field(description="Semantic reference (e.g. 'DOCUMENT.aadhaar')")
    status: Literal["pending", "resolved", "uploaded"] = Field(
        default="pending",
        description="Document lifecycle status",
    )
    target_field_semantic_id: str | None = Field(
        default=None,
        description="Semantic ID of file input field",
    )
    target_field_ref: str | None = Field(
        default=None,
        description="Ephemeral DOM ref used during upload",
    )
    file_name: str | None = Field(default=None, description="Uploaded file name (non-sensitive)")
    mime_type: str | None = Field(default=None, description="MIME type")
    verified: bool = Field(default=False, description="True if upload was verified")
    provenance: Provenance | None = Field(default=None, description="Provenance record")


class AuthenticationWorldState(BaseModel):
    """Authentication challenge status."""

    status: Literal["none", "detected", "in_progress", "verified", "blocked"] = Field(
        default="none",
        description="Authentication lifecycle state",
    )
    challenge_type: str | None = Field(
        default=None,
        description="login | password | otp | captcha | identity_verification | unknown",
    )
    reason: str | None = Field(default=None, description="Detection reason")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Detection confidence 0-1")
    last_detected_at: str | None = Field(default=None, description="Timestamp of challenge detection")
    provenance: Provenance | None = Field(default=None, description="Provenance record")


class AgentWorldState(BaseModel):
    """Durable semantic WorldState.

    Represents workflow reality independently from ephemeral DOM references.
    Persists across page transitions, DOM re-renders, and tab switches.
    """

    # Versioning & Identity
    version: int = Field(default=0, description="Monotonically increasing state version")
    portal: str = Field(default="", description="Target portal / domain identifier")
    created_at: str = Field(default_factory=utc_now_iso, description="Creation timestamp")
    updated_at: str = Field(default_factory=utc_now_iso, description="Last update timestamp")

    # Current Page & Tab
    current_tab_index: int = Field(default=0, description="Index of currently active tab")
    current_page_url: str = Field(default="", description="URL of currently active page")
    current_page_title: str = Field(default="", description="Title of currently active page")
    current_page_type: str = Field(default="unknown", description="Page type of currently active page")
    current_observation_id: str = Field(default="", description="ID of current active observation")

    # Multi-tab Tracking
    tabs: dict[int, TabWorldState] = Field(
        default_factory=dict,
        description="All open tabs indexed by tab_index",
    )

    # Semantic Fields & Mappings
    semantic_fields: dict[str, SemanticField] = Field(
        default_factory=dict,
        description="Semantic fields on the active page, keyed by semantic_id",
    )
    field_mappings: dict[str, str] = Field(
        default_factory=dict,
        description="Map from semantic_id to user reference (e.g. 'field:name' -> 'USER.full_name')",
    )
    verified_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Authoritative verified values keyed by semantic_id and binding",
    )

    # Validation & Diagnostics
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Visible validation errors on the current page",
    )

    # Authentication & Documents
    authentication: AuthenticationWorldState = Field(
        default_factory=AuthenticationWorldState,
        description="Authentication challenge state",
    )
    documents: dict[str, DocumentWorldState] = Field(
        default_factory=dict,
        description="Documents tracked in workflow",
    )

    # Workflow Milestones
    completed_subgoals: list[str] = Field(
        default_factory=list,
        description="IDs of completed subgoals",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="Ambiguities or user questions requiring resolution",
    )

    # Provenance Log
    evidence: list[Provenance] = Field(
        default_factory=list,
        description="Immutable audit trail of state changes",
    )

    def is_field_verified(self, semantic_id_or_binding: str) -> bool:
        """True if the field or binding has a verified value."""
        if semantic_id_or_binding in self.verified_values:
            return True
        field = self.semantic_fields.get(semantic_id_or_binding)
        return bool(field and field.status == EpistemicStatus.VERIFIED and field.verified_value is not None)

    def get_verified_value(self, semantic_id_or_binding: str) -> Any | None:
        """Get the verified value for a semantic ID or user binding."""
        if semantic_id_or_binding in self.verified_values:
            return self.verified_values[semantic_id_or_binding]
        field = self.semantic_fields.get(semantic_id_or_binding)
        if field and field.status == EpistemicStatus.VERIFIED:
            return field.verified_value
        return None

    def active_fields_count(self) -> int:
        """Count of actionable fields with valid current DOM refs."""
        return sum(
            1 for f in self.semantic_fields.values()
            if f.is_actionable(self.current_observation_id)
        )
