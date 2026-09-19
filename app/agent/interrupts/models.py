"""Durable Human Interrupt data models — Phase 8 Part A.

Non-negotiable principles (AGENTS.md rule 14, Phase 8 specification):
1. Pauses for human interaction (OTP, CAPTCHA, Auth, Confirmation, Review)
   must be durable, resumable run states that survive process crashes.
2. Approvals are NEVER equivalent to a permanent boolean: every approval
   is strictly bound to run_id, interrupt_id, requested action, target identity,
   semantic_id, WorldState version, observation_id, and explicit expiration.
3. If page state or WorldState version changes before execution, the approval
   invalidates immediately (fail closed).
4. No secrets, credentials, or raw OTP values are stored in interrupt models.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class InterruptReason(str, Enum):
    """Canonical reasons requiring human-in-the-loop intervention."""

    OTP_REQUIRED = "otp_required"
    CAPTCHA_REQUIRED = "captcha_required"
    AUTHENTICATION_REQUIRED = "authentication_required"
    USER_CLARIFICATION_REQUIRED = "user_clarification_required"
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"
    FINAL_REVIEW_REQUIRED = "final_review_required"


class InterruptStatus(str, Enum):
    """Deterministic interrupt lifecycle states."""

    PENDING = "pending"
    WAITING_FOR_USER = "waiting_for_user"
    APPROVED = "approved"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    RESUMING = "resuming"
    RESUMED = "resumed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ApprovalBinding(BaseModel):
    """Durable cryptographic/state binding for a granted human approval.

    Approval is NEVER a permanent boolean: it binds tightly to the exact
    WorldState version, observation ID, target semantic identity, and
    requested action against which it was granted.
    """

    approval_id: str = Field(default_factory=lambda: _new_id("appr"))
    run_id: str = Field(description="Run this approval authorizes")
    interrupt_id: str = Field(description="Interrupt this approval resolves")
    requested_action: str = Field(
        description="Exact tool/action name (e.g. 'fill', 'click', 'confirm_final_review')"
    )
    target_identity: str = Field(
        description="Target semantic identity or accessible name"
    )
    semantic_id: str | None = Field(
        default=None,
        description="Durable semantic field identifier (e.g. 'field:otp')",
    )
    world_state_version: int = Field(
        description="WorldState version at the moment of approval"
    )
    observation_id: str = Field(
        description="Observation ID under which the action was approved"
    )
    created_at: str = Field(default_factory=utc_now_iso)
    expires_at: str = Field(
        description="ISO-8601 UTC timestamp after which approval is invalid"
    )
    approved_by: str = Field(
        default="user",
        description="Origin of approval ('user', 'citizen_portal', etc.)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe non-sensitive metadata (no secrets/passwords/OTPs)",
    )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Check if approval has passed its expiration timestamp."""
        check_time = now or datetime.now(timezone.utc)
        exp = parse_iso(self.expires_at)
        return check_time > exp

    def is_valid_for(
        self,
        current_world_state_version: int,
        current_action: str,
        current_target_identity: str,
        current_semantic_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """Validate if approval remains valid against current state.

        Returns (is_valid, invalidation_reason).
        """
        if self.is_expired(now):
            return False, f"approval expired at {self.expires_at}"

        if self.world_state_version != current_world_state_version:
            return (
                False,
                f"world_state_version mismatch: approved for v{self.world_state_version}, current is v{current_world_state_version}",
            )

        if self.requested_action != current_action:
            return (
                False,
                f"action mismatch: approved for '{self.requested_action}', requested '{current_action}'",
            )

        if self.target_identity != current_target_identity:
            return (
                False,
                f"target mismatch: approved for '{self.target_identity}', current is '{current_target_identity}'",
            )

        if self.semantic_id and current_semantic_id and self.semantic_id != current_semantic_id:
            return (
                False,
                f"semantic_id mismatch: approved for '{self.semantic_id}', current is '{current_semantic_id}'",
            )

        return True, "valid"


class HumanInterrupt(BaseModel):
    """Durable human-in-the-loop pause representation."""

    interrupt_id: str = Field(default_factory=lambda: _new_id("int"))
    run_id: str = Field(description="Run paused by this interrupt")
    checkpoint_id: str | None = Field(
        default=None, description="Checkpoint capturing state at interrupt"
    )
    reason: InterruptReason = Field(description="Canonical interrupt cause")
    status: InterruptStatus = Field(default=InterruptStatus.PENDING)
    description: str = Field(description="Human-readable explanation of why run paused")
    observation_id: str = Field(
        description="Observation ID during which interrupt occurred"
    )
    world_state_version: int = Field(
        description="WorldState version at the time interrupt was raised"
    )
    subgoal_id: str | None = Field(
        default=None, description="Active subgoal id at interrupt"
    )
    required_action: str | None = Field(
        default=None,
        description="Action required from human or agent upon resumption",
    )
    target_identity: str | None = Field(
        default=None,
        description="Target field / button identity associated with pause",
    )
    semantic_id: str | None = Field(
        default=None,
        description="Stable semantic field identifier (e.g. 'field:captcha')",
    )
    created_at: str = Field(default_factory=utc_now_iso)
    expires_at: str = Field(
        description="ISO-8601 UTC timestamp after which interrupt expires"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe non-sensitive details (field label, hint, prompt)",
    )
    approval_binding: ApprovalBinding | None = Field(
        default=None, description="Approval binding once approved by human"
    )

    def is_expired(self, now: datetime | None = None) -> bool:
        check_time = now or datetime.now(timezone.utc)
        exp = parse_iso(self.expires_at)
        return check_time > exp


class ResumeRequest(BaseModel):
    """Payload submitted to request resuming an interrupted run."""

    run_id: str
    interrupt_id: str
    worker_id: str = Field(
        default_factory=lambda: f"worker_{uuid.uuid4().hex[:8]}",
        description="ID of worker process executing the resume",
    )
    approval: ApprovalBinding | None = None
    human_inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe user inputs (clarification answer, ack confirmation; NEVER secrets)",
    )
    requested_at: str = Field(default_factory=utc_now_iso)


class ResumeResult(BaseModel):
    """Result of attempting to resume an interrupted run."""

    success: bool
    run_id: str
    interrupt_id: str
    status: str = Field(
        description="'resumed', 'rejected', 'reconfirmation_required', 'expired', 'invalid_target'"
    )
    reason: str
    checkpoint_id: str | None = None
    resumed_subgoal_id: str | None = None
    resumed_at: str = Field(default_factory=utc_now_iso)


class CheckpointReference(BaseModel):
    """Lightweight reference metadata for stored checkpoints."""

    checkpoint_id: str
    run_id: str
    schema_version: int
    created_at: str
    state_version: int
    lifecycle: str
    has_pending_interrupt: bool
    expires_at: str | None = None
