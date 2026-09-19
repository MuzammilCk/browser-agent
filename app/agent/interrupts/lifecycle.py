"""Interrupt lifecycle and approval invalidation engine — Phase 8 Part A.

Enforces deterministic transitions for human interrupts.
Illegal transitions fail closed and raise InvalidInterruptTransition.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptStatus,
    parse_iso,
)


class InvalidInterruptTransition(Exception):
    """Raised when an illegal transition is attempted on a HumanInterrupt."""

    def __init__(self, current: InterruptStatus, target: InterruptStatus) -> None:
        super().__init__(
            f"Illegal interrupt transition from {current.value} to {target.value}"
        )
        self.current = current
        self.target = target


# Explicit deterministic transition table
INTERRUPT_TRANSITIONS: dict[InterruptStatus, frozenset[InterruptStatus]] = {
    InterruptStatus.PENDING: frozenset({
        InterruptStatus.WAITING_FOR_USER,
        InterruptStatus.CANCELLED,
        InterruptStatus.EXPIRED,
    }),
    InterruptStatus.WAITING_FOR_USER: frozenset({
        InterruptStatus.APPROVED,
        InterruptStatus.REJECTED,
        InterruptStatus.EXPIRED,
        InterruptStatus.INVALIDATED,
        InterruptStatus.CANCELLED,
    }),
    InterruptStatus.APPROVED: frozenset({
        InterruptStatus.RESUMING,
        InterruptStatus.EXPIRED,
        InterruptStatus.INVALIDATED,
        InterruptStatus.CANCELLED,
    }),
    InterruptStatus.RESUMING: frozenset({
        InterruptStatus.RESUMED,
        InterruptStatus.INVALIDATED,
        InterruptStatus.WAITING_FOR_USER,  # Re-prompt when validation forces re-confirmation
        InterruptStatus.REJECTED,
    }),
    InterruptStatus.INVALIDATED: frozenset({
        InterruptStatus.WAITING_FOR_USER,  # Re-prompt user with fresh context
        InterruptStatus.APPROVED,          # Re-approved with valid binding
        InterruptStatus.CANCELLED,
    }),
    # Terminal states
    InterruptStatus.RESUMED: frozenset(),
    InterruptStatus.REJECTED: frozenset(),
    InterruptStatus.EXPIRED: frozenset(),
    InterruptStatus.CANCELLED: frozenset(),
}


def can_transition(current: InterruptStatus, target: InterruptStatus) -> bool:
    """Return True if transition from current to target is permitted."""
    return target in INTERRUPT_TRANSITIONS.get(current, frozenset())


def validate_transition(current: InterruptStatus, target: InterruptStatus) -> None:
    """Validate transition; raise InvalidInterruptTransition if illegal."""
    if not can_transition(current, target):
        raise InvalidInterruptTransition(current, target)


def is_expired(item: HumanInterrupt | ApprovalBinding, now: datetime | None = None) -> bool:
    """Check whether an interrupt or approval binding has expired."""
    check_time = now or datetime.now(timezone.utc)
    exp = parse_iso(item.expires_at)
    return check_time > exp


def validate_approval(
    approval: ApprovalBinding,
    current_world_state_version: int,
    current_action: str,
    current_target_identity: str,
    current_semantic_id: str | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Deterministically validate approval against live logical state.

    Enforces all invalidation criteria:
    - Expiration check
    - WorldState version monotonicity and match
    - Target identity and semantic ID match
    - Action match
    """
    return approval.is_valid_for(
        current_world_state_version=current_world_state_version,
        current_action=current_action,
        current_target_identity=current_target_identity,
        current_semantic_id=current_semantic_id,
        now=now,
    )
