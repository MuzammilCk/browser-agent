"""Enterprise runtime domain models — Phase 13.

Additive layer around the Phase 1-12 agent runtime. This module owns the
ENTERPRISE lifecycle state only (Workflow / WorkflowRun / queue / lease /
identity / audit). It deliberately does NOT duplicate AgentRunState: a
WorkflowRun references the existing runtime run (agent_run_id) and the
existing checkpoint store remains authoritative for resume (Phase 8).

Design constraints:
- Transitions are table-validated and fail closed (same pattern as the
  Phase 2 LIFECYCLE_TRANSITIONS and Phase 8 INTERRUPT_TRANSITIONS).
- Tenant/user identity is part of every externally addressable record
  (Phase 13 invariant 14). UUID obscurity is never the authz mechanism.
- Queue payloads carry REFERENCES only - never secrets, never browser
  handles, never checkpoint bytes (invariants 5, 10).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ============================================================
# Run lifecycle (explicit, deterministic, fail closed)
# ============================================================


class RunStatus(str, Enum):
    """Enterprise run lifecycle states (Phase 13 spec)."""

    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    PAUSED_HITL = "paused_hitl"
    PAUSED_RECOVERY = "paused_recovery"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ABANDONED = "abandoned"
    RECOVERY_REQUIRED = "recovery_required"


TERMINAL_RUN_STATUSES = frozenset({
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.EXPIRED,
    RunStatus.ABANDONED,
})

PAUSED_RUN_STATUSES = frozenset({
    RunStatus.PAUSED_HITL,
    RunStatus.PAUSED_RECOVERY,
})


# Deterministic transition table: from -> set of legal targets.
# Anything not listed raises InvalidRunTransition (fail closed).
RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({
        RunStatus.DISPATCHED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
    }),
    RunStatus.DISPATCHED: frozenset({
        RunStatus.RUNNING,
        RunStatus.RECOVERY_REQUIRED,  # worker died between claim and start
        RunStatus.CANCELLATION_REQUESTED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    }),
    RunStatus.RUNNING: frozenset({
        RunStatus.PAUSED_HITL,
        RunStatus.PAUSED_RECOVERY,
        RunStatus.CANCELLATION_REQUESTED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.RECOVERY_REQUIRED,  # lease lost / worker crash
    }),
    RunStatus.PAUSED_HITL: frozenset({
        RunStatus.RUNNING,           # resumed
        RunStatus.CANCELLATION_REQUESTED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
        RunStatus.RECOVERY_REQUIRED,
    }),
    RunStatus.PAUSED_RECOVERY: frozenset({
        RunStatus.RUNNING,
        RunStatus.RECOVERY_REQUIRED,
        RunStatus.CANCELLATION_REQUESTED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
    }),
    RunStatus.CANCELLATION_REQUESTED: frozenset({
        RunStatus.CANCELLED,         # worker confirms at safe boundary
        RunStatus.RECOVERY_REQUIRED,  # worker died before confirming
    }),
    RunStatus.RECOVERY_REQUIRED: frozenset({
        RunStatus.QUEUED,            # re-dispatch for a new worker
        RunStatus.CANCELLED,
        RunStatus.ABANDONED,
        RunStatus.FAILED,
    }),
    # Terminal: a NEW run, not a transition, restarts work.
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.EXPIRED: frozenset(),
    RunStatus.ABANDONED: frozenset(),
}


class InvalidRunTransition(Exception):
    """Raised when an enterprise run transition is not in the table."""


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in RUN_TRANSITIONS[current]


def validate_transition(current: RunStatus, target: RunStatus) -> None:
    if not can_transition(current, target):
        raise InvalidRunTransition(
            f"illegal run transition {current.value} -> {target.value}"
        )


# ============================================================
# Identity / authorization (server-side only)
# ============================================================


class ActorType(str, Enum):
    USER = "user"
    WORKER = "worker"
    SERVICE = "service"
    ADMIN = "admin"
    SYSTEM = "system"


class Role(str, Enum):
    """Only roles with concrete runtime meaning (Phase 13: no fake RBAC)."""

    USER = "user"
    WORKER = "worker"
    ADMIN = "admin"


class Identity(BaseModel):
    """Authenticated server-side identity. NEVER built from client input."""

    actor_type: ActorType
    tenant_id: str
    subject_id: str          # user_id, worker_id, or service id
    role: Role

    @property
    def is_worker(self) -> bool:
        return self.role is Role.WORKER

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


class AuthorizationError(Exception):
    """Server-side authorization failure (fail closed)."""


class NotFoundError(Exception):
    """Resource missing OR not visible to this identity (no distinction)."""


# ============================================================
# Workflow / WorkflowRun
# ============================================================


class Workflow(BaseModel):
    workflow_id: str = Field(default_factory=lambda: new_id("wf"))
    tenant_id: str
    user_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    status: str = "active"
    current_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = 1


class WorkflowRun(BaseModel):
    """Enterprise lifecycle record AROUND one runtime run.

    References (never duplicates) the Phase 2 AgentRunState via
    agent_run_id and the Phase 8 checkpoint store via checkpoint_id.
    """

    run_id: str = Field(default_factory=lambda: new_id("run"))
    workflow_id: str
    tenant_id: str
    user_id: str
    status: RunStatus = RunStatus.QUEUED

    # Worker ownership (lease/fencing details live in WorkerLease;
    # the run carries the current assignment mirror).
    worker_id: str | None = None
    lease_id: str | None = None
    fencing_token: int = 0

    # Runtime linkage (existing Phase 2/8 subsystems stay authoritative)
    checkpoint_id: str | None = None
    agent_run_id: str | None = None

    created_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)
    completed_at: str | None = None

    cancellation_requested: bool = False
    failure_code: str | None = None

    # Bounded service-level retry budget (distinct from agent recovery
    # budgets and from worker retries - invariant: layers don't multiply).
    dispatch_attempts: int = 0
    max_dispatch_attempts: int = 3

    version: int = 1

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def is_paused(self) -> bool:
        return self.status in PAUSED_RUN_STATUSES


# ============================================================
# Lease / fencing
# ============================================================


class LeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class WorkerLease(BaseModel):
    """Durable execution lease for exactly one run (invariant 1, 6).

    Fencing token is monotonic per run: every worker-side durable write
    must carry the token it was issued; the store rejects stale tokens.
    """

    run_id: str
    worker_id: str
    lease_id: str = Field(default_factory=lambda: new_id("lease"))
    fencing_token: int = Field(default=1, ge=1)
    acquired_at: str = Field(default_factory=utc_now_iso)
    expires_at: str = ""
    renewed_at: str = Field(default_factory=utc_now_iso)
    state: LeaseState = LeaseState.ACTIVE

    def is_expired(self, now: datetime | None = None) -> bool:
        check = now or datetime.now(timezone.utc)
        if not self.expires_at:
            return True
        exp = datetime.fromisoformat(self.expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return check > exp


# ============================================================
# Queue / dispatch
# ============================================================


class QueueItemState(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DEAD = "dead"          # dead-letter after bounded attempts
    DONE = "done"


class ExecutionQueueItem(BaseModel):
    """Durable dispatch record. Payload carries REFERENCES ONLY
    (invariant 5: no secrets, no browser handles, no checkpoint bytes).
    """

    queue_id: str = Field(default_factory=lambda: new_id("q"))
    run_id: str
    workflow_id: str
    tenant_id: str
    user_id: str
    state: QueueItemState = QueueItemState.QUEUED
    payload: dict[str, Any] = Field(default_factory=dict)
    available_at: str = Field(default_factory=utc_now_iso)
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = Field(default_factory=utc_now_iso)


# ============================================================
# Idempotency (durable, invariant 16)
# ============================================================


class IdempotencyRecord(BaseModel):
    key: str
    tenant_id: str
    operation: str
    request_hash: str
    status_code: int = 200
    response: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


# ============================================================
# Audit (append-only, causally linked, secret-redacted)
# ============================================================


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    parent_event_id: str | None = None

    # Scope (tenant/user are set by the server, not the caller)
    tenant_id: str = ""
    user_id: str = ""
    workflow_id: str | None = None
    run_id: str | None = None
    worker_id: str | None = None

    event_type: str
    actor_type: str = ActorType.SYSTEM.value
    actor_id: str = ""

    action: str | None = None          # tool/action name
    policy_result: str | None = None
    hitl_result: str | None = None
    security_event: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
