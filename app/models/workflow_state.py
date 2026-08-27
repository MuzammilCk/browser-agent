"""Workflow state model — first-class contract for multi-page workflows.

Per audit issues #28, #49, #50:
- WorkflowState describes the APPLICATION ACROSS PAGES
- PageState describes ONE page
- Explicit user checkpoint states
- Recovery logic states
- Completed bindings and pending fields tracking

Architecture:
    PageState = one page snapshot
    WorkflowState = entire application lifecycle
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    """Workflow lifecycle states.

    Per audit #49: explicit user checkpoint states.
    """

    INITIALIZED = "initialized"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_AUTH = "waiting_for_auth"
    WAITING_FOR_CAPTCHA = "waiting_for_captcha"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    READY_FOR_SUBMISSION = "ready_for_submission"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class ActionRecord(BaseModel):
    """Record of a single executed action."""

    action_type: str
    target_ref: str | None = None
    binding: str | None = None
    success: bool = False
    verification_status: str = ""
    policy_decision: str = ""
    message: str = ""
    observation_id: str = ""
    timestamp: str = ""


class WorkflowState(BaseModel):
    """Complete workflow state — persists across page transitions.

    Per audit #28: first-class contract for multi-step forms.
    """

    # Identity
    workflow_id: str = Field(default="", description="Unique workflow ID")
    domain: str = Field(default="", description="Target domain")
    current_url: str = Field(default="", description="Current page URL")
    task_description: str = Field(default="", description="User's task description")

    # Status
    status: WorkflowStatus = Field(
        default=WorkflowStatus.INITIALIZED,
        description="Current workflow status",
    )

    # Planning-mode visibility (P0-37 / audit Z8): answerable at a glance
    # whether the LLM is actually in the loop for this workflow.
    planning_mode: str = Field(
        default="deterministic_fallback",
        description="'llm' | 'deterministic_fallback'",
    )
    llm_model: str | None = Field(
        default=None,
        description="Resolved model string when planning_mode == 'llm', else null",
    )
    llm_disabled_reason: str | None = Field(
        default=None,
        description="Why the LLM is not in use: 'no_api_key' or "
        "'gateway_init_failed: <msg>'; null when the LLM is active",
    )

    # Vault visibility (audit Z3): an empty vault is visible from workflow
    # state, not only from server console logs.
    vault_loaded: bool = Field(
        default=False,
        description="True when at least one vault field has a value",
    )
    vault_warning: str | None = Field(
        default=None,
        description="Human-readable warning when the vault is empty",
    )

    # Vision fallback (audit Z7 / P0-16): budget is one attempt per
    # workflow, taken only at a confirmed planning stall.
    vision_fallback_attempts: int = Field(
        default=0,
        description="Number of vision-fallback passes attempted (max 1)",
    )

    # Observation tracking
    current_observation_id: str = Field(
        default="",
        description="ID of the current observation (for stale ref prevention)",
    )
    current_page_type: str = Field(
        default="unknown",
        description="Current page type classification",
    )

    # Multi-tab awareness (audit Phase 8): which tab the agent is on is
    # explicit state, and every switch is part of the workflow trace
    # instead of being handled silently inside the browser layer.
    open_tab_count: int = Field(
        default=1,
        description="Number of browser tabs open at the last observation",
    )
    tab_switches: list[str] = Field(
        default_factory=list,
        description="Human-readable trace of active-tab switches, in order",
    )

    # Stall detection (audit Phase 9): a loop repeating one identical
    # action against an unchanged page gets its own labeled stop instead
    # of a generic max-iteration failure.
    last_action_signature: str = Field(
        default="",
        description="Signature key of the most recently planned action",
    )
    repeated_action_count: int = Field(
        default=0,
        description="Consecutive times the current signature has been planned",
    )
    stall_reason: str | None = Field(
        default=None,
        description="Labeled stall cause, e.g. 'repeated_action_no_progress'",
    )

    # Confirmation gate (audit B2)
    pending_action: dict | None = Field(
        default=None,
        description="Action awaiting user confirmation (serialized BrowserAction)",
    )
    pending_observation_id: str = Field(
        default="",
        description="Observation ID for the pending action (stale-ref prevention)",
    )
    pending_target_signature: dict | None = Field(
        default=None,
        description="Role + accessible name of the pending target, used to "
        "verify after resume that the ref still points at the same element",
    )

    # Field mapping state
    completed_bindings: list[str] = Field(
        default_factory=list,
        description="Field refs that have been successfully filled",
    )
    pending_fields: list[str] = Field(
        default_factory=list,
        description="Field refs that need to be filled",
    )
    unmapped_fields: list[str] = Field(
        default_factory=list,
        description="Field refs that could not be mapped",
    )
    ambiguous_fields: list[str] = Field(
        default_factory=list,
        description="Field refs with uncertain mappings",
    )

    # Action tracking
    actions_taken: list[ActionRecord] = Field(
        default_factory=list,
        description="History of all executed actions",
    )
    total_actions: int = Field(default=0, description="Total actions executed")
    successful_actions: int = Field(default=0, description="Successful actions")
    failed_actions: int = Field(default=0, description="Failed actions")

    # Checkpoints
    checkpoints: list[str] = Field(
        default_factory=list,
        description="User checkpoints encountered (CAPTCHA, OTP, etc.)",
    )

    # Authentication state
    authentication_state: str = Field(
        default="none",
        description="none | detected | handled | blocked",
    )

    # Submission state
    submission_state: str = Field(
        default="not_ready",
        description="not_ready | ready | submitted | confirmed",
    )

    # Error state
    error_state: str = Field(
        default="none",
        description="none | recoverable | fatal | user_required",
    )
    error_message: str = Field(default="", description="Last error message")

    # Recovery
    recovery_attempts: int = Field(
        default=0,
        description="Number of recovery attempts for current issue",
    )
    max_recovery_attempts: int = Field(
        default=3,
        description="Maximum recovery attempts before stopping",
    )

    # Metadata
    created_at: str = Field(default="", description="Workflow creation timestamp")
    updated_at: str = Field(default="", description="Last update timestamp")

    def record_action(self, record: ActionRecord) -> None:
        """Record an executed action."""
        self.actions_taken.append(record)
        self.total_actions += 1
        if record.success:
            self.successful_actions += 1
            if record.target_ref and record.target_ref not in self.completed_bindings:
                self.completed_bindings.append(record.target_ref)
                if record.target_ref in self.pending_fields:
                    self.pending_fields.remove(record.target_ref)
        else:
            self.failed_actions += 1

    def mark_field_completed(self, ref: str) -> None:
        """Mark a field as successfully filled."""
        if ref not in self.completed_bindings:
            self.completed_bindings.append(ref)
        if ref in self.pending_fields:
            self.pending_fields.remove(ref)

    def mark_field_pending(self, ref: str) -> None:
        """Mark a field as needing to be filled."""
        if ref not in self.pending_fields and ref not in self.completed_bindings:
            self.pending_fields.append(ref)

    def add_checkpoint(self, checkpoint: str) -> None:
        """Add a user checkpoint."""
        if checkpoint not in self.checkpoints:
            self.checkpoints.append(checkpoint)

    def record_tab_switch(self, description: str) -> None:
        """Record an active-tab switch in the workflow trace (Phase 8)."""
        self.tab_switches.append(description)
        self.add_checkpoint(description)

    def set_error(self, error_type: str, message: str = "") -> None:
        """Set error state."""
        self.error_state = error_type
        self.error_message = message

    def can_retry(self) -> bool:
        """Check if recovery can be attempted."""
        return self.recovery_attempts < self.max_recovery_attempts

    def increment_recovery(self) -> None:
        """Increment recovery attempt counter."""
        self.recovery_attempts += 1

    def reset_recovery(self) -> None:
        """Reset recovery counter (after successful action)."""
        self.recovery_attempts = 0

    def summary(self) -> str:
        """Human-readable workflow summary."""
        return (
            f"Workflow {self.workflow_id}: {self.status.value}\n"
            f"  Domain: {self.domain}\n"
            f"  URL: {self.current_url}\n"
            f"  Actions: {self.total_actions} total, "
            f"{self.successful_actions} success, {self.failed_actions} failed\n"
            f"  Completed: {len(self.completed_bindings)} fields\n"
            f"  Pending: {len(self.pending_fields)} fields\n"
            f"  Unmapped: {len(self.unmapped_fields)} fields\n"
            f"  Checkpoints: {len(self.checkpoints)}\n"
            f"  Error: {self.error_state}"
        )
