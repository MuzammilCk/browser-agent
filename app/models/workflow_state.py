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

    # Observation tracking
    current_observation_id: str = Field(
        default="",
        description="ID of the current observation (for stale ref prevention)",
    )
    current_page_type: str = Field(
        default="unknown",
        description="Current page type classification",
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
