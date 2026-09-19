"""Durable Human-in-the-loop (HITL) Interrupts — Phase 8.

Turns human-required pauses (OTP, CAPTCHA, authentication, clarification,
confirmation, final review) into durable, resumable run states that survive
process termination without trusting stale browser state or stale approvals.
"""

from app.agent.interrupts.lifecycle import (
    INTERRUPT_TRANSITIONS,
    InvalidInterruptTransition,
    can_transition,
    validate_transition,
    validate_approval,
)
from app.agent.interrupts.models import (
    ApprovalBinding,
    CheckpointReference,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
    ResumeRequest,
    ResumeResult,
)

__all__ = [
    "ApprovalBinding",
    "CheckpointReference",
    "HumanInterrupt",
    "InterruptReason",
    "InterruptStatus",
    "InvalidInterruptTransition",
    "ResumeRequest",
    "ResumeResult",
    "INTERRUPT_TRANSITIONS",
    "can_transition",
    "validate_transition",
    "validate_approval",
]
