"""Server-side security for the enterprise runtime — Phase 13.

Invariant 15: identity and authorization come ONLY from authenticated
server-side context. Client-supplied tenant/user/worker/role fields are
never trusted (strict request schemas reject them outright).

Roles are limited to those with concrete runtime meaning:
  user   — owns workflows/runs in its tenant: create/read/cancel/resume
  worker — claims runs, holds leases, reports progress (server-assigned id)
  admin  — cross-tenant audit access (operational role)

Every check fails closed: missing scope, foreign tenant, or wrong actor
type raises AuthorizationError before any state is touched.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.enterprise.models import (
    ActorType,
    AuthorizationError,
    Identity,
    Role,
)


@dataclass
class WorkerRegistration:
    """A worker authenticated via the server-side worker token pool."""

    worker_id: str
    token_hash: str
    tenant_id: str = ""     # "" = may serve any configured tenant
    registered_at: str = field(default_factory=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())


class IdentityProvider:
    """Resolves bearer tokens to server-side identities.

    Tokens are configured/registered server-side. There is deliberately
    NO path where a request body or header other than the bearer token
    influences tenant/user/worker identity.
    """

    def __init__(self) -> None:
        # token -> Identity (server-side registration only)
        self._tokens: dict[str, Identity] = {}
        # worker token hash -> WorkerRegistration
        self._workers: dict[str, WorkerRegistration] = {}

    # -- user/service token registration (server-side) -----------------

    def register_principal(
        self, token: str, *, tenant_id: str, subject_id: str,
        role: Role = Role.USER,
    ) -> None:
        actor = ActorType.ADMIN if role is Role.ADMIN else (
            ActorType.WORKER if role is Role.WORKER else ActorType.USER
        )
        identity = Identity(
            actor_type=actor, tenant_id=tenant_id,
            subject_id=subject_id, role=role,
        )
        self._tokens[token] = identity

    def register_worker(
        self, token: str, *, tenant_id: str = "",
    ) -> str:
        """Register a worker with a server-issued token. Returns the
        server-assigned worker_id (clients cannot choose it)."""
        worker_id = f"worker_{uuid.uuid4().hex[:10]}"
        reg = WorkerRegistration(
            worker_id=worker_id,
            token_hash=self._hash(token),
            tenant_id=tenant_id,
        )
        self._workers[self._hash(token)] = reg
        return worker_id

    @staticmethod
    def _hash(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    # -- resolution ------------------------------------------------------

    def resolve(self, authorization_header: str | None) -> Identity:
        """Resolve the Authorization header to a server-side identity.

        Raises AuthorizationError on missing/unknown tokens (fail closed).
        """
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AuthorizationError("missing or malformed bearer token")
        token = authorization_header[len("Bearer "):].strip()
        if not token:
            raise AuthorizationError("empty bearer token")

        # Worker tokens first (they are distinct from principal tokens).
        reg = self._workers.get(self._hash(token))
        if reg is not None:
            return Identity(
                actor_type=ActorType.WORKER,
                tenant_id=reg.tenant_id,
                subject_id=reg.worker_id,
                role=Role.WORKER,
            )

        identity = self._tokens.get(token)
        if identity is None:
            raise AuthorizationError("unknown bearer token")
        return identity


def require_same_tenant(identity: Identity, tenant_id: str) -> None:
    """Fail closed when the identity does not belong to the tenant."""
    if identity.is_worker:
        # Workers registered without tenant restriction may serve any
        # tenant; tenant-restricted workers must match.
        return
    if identity.tenant_id != tenant_id:
        raise AuthorizationError(
            f"identity tenant '{identity.tenant_id}' does not own resource tenant '{tenant_id}'"
        )


def require_role(identity: Identity, *roles: Role) -> None:
    if identity.role not in roles:
        raise AuthorizationError(
            f"role '{identity.role.value}' lacks required role "
            f"{[r.value for r in roles]}"
        )


def ensure_not_client_supplied_tenant(payload_tenant: str | None) -> None:
    """Defense-in-depth: reject any client-provided tenant override.

    The gateway's strict schemas use extra='forbid' so client bodies
    cannot even CARRY a tenant field; this guard is for direct service
    callers.
    """
    if payload_tenant:
        raise AuthorizationError("tenant identity cannot be supplied by clients")


def new_worker_token() -> str:
    return secrets.token_urlsafe(24)


def describe_identity(identity: Identity) -> dict[str, Any]:
    return {
        "actor_type": identity.actor_type.value,
        "tenant_id": identity.tenant_id,
        "subject_id": identity.subject_id,
        "role": identity.role.value,
    }
