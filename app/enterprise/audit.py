"""Append-only enterprise audit trail — Phase 13.

Invariants 12/13: audit is append-only, causally linked, and
secret-redacted. Redaction reuses the Phase 11/12 sensitivity rules
(structural key classification + content scrubbing) so a raw secret can
never enter an audit payload.

Causality: every event may reference parent_event_id; the service
validates that a declared parent already exists in the same tenant
(fail closed on dangling/foreign causality).
"""

from __future__ import annotations

from app.enterprise.models import (
    ActorType,
    AuditEvent,
    Identity,
)
from app.enterprise.store import EnterpriseStore
from app.agent.evaluation.trace import redact_trace_value


class AuditService:
    """Facade over store.append_audit/list_audit with redaction + causality."""

    def __init__(self, store: EnterpriseStore) -> None:
        self._store = store

    async def record(
        self,
        *,
        event_type: str,
        identity: Identity | None = None,
        tenant_id: str = "",
        user_id: str = "",
        workflow_id: str | None = None,
        run_id: str | None = None,
        worker_id: str | None = None,
        parent_event_id: str | None = None,
        action: str | None = None,
        policy_result: str | None = None,
        hitl_result: str | None = None,
        security_event: str | None = None,
        payload: dict | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
    ) -> AuditEvent:
        """Append one redacted, causally-linked audit event.

        Scope rule: the event is attributed to the identity's tenant;
        worker-driven events (workers carry no tenant) MUST pass the
        run's tenant_id explicitly so they land in the run's tenant
        scope — never in an unscoped void."""
        if identity is not None and identity.tenant_id:
            tid = identity.tenant_id
        else:
            tid = tenant_id
        uid = (
            identity.subject_id
            if identity is not None and identity.actor_type is not ActorType.WORKER
            else user_id
        )
        atype = actor_type or (
            identity.actor_type.value if identity is not None
            else ActorType.SYSTEM.value
        )
        aid = actor_id or (
            identity.subject_id if identity is not None else "system"
        )

        event = AuditEvent(
            event_type=event_type,
            parent_event_id=parent_event_id,
            tenant_id=tid,
            user_id=uid,
            workflow_id=workflow_id,
            run_id=run_id,
            worker_id=worker_id,
            actor_type=atype,
            actor_id=aid,
            action=action,
            policy_result=policy_result,
            hitl_result=hitl_result,
            security_event=security_event,
            payload=redact_trace_value(None, dict(payload or {})),
        )

        if parent_event_id:
            parents = await self._store.list_audit(
                tenant_id=tid, run_id=run_id, workflow_id=workflow_id, limit=1000,
            )
            if not any(p.event_id == parent_event_id for p in parents):
                raise ValueError(
                    f"audit parent {parent_event_id} not found in scope "
                    f"(dangling or foreign causality is rejected)"
                )
        return await self._store.append_audit(event)

    async def read(
        self,
        *,
        identity: Identity,
        tenant_id: str | None = None,
        workflow_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Tenant-scoped audit read. Users/admins only (workers have no
        audit-read role), and always scoped to the identity's tenant
        unless the caller is admin explicitly requesting another tenant
        (admin cross-tenant read is the one concrete admin capability)."""
        from app.enterprise.models import Role
        from app.enterprise.security import require_role

        require_role(identity, Role.USER, Role.ADMIN)
        scope_tenant = identity.tenant_id
        if identity.is_admin and tenant_id:
            scope_tenant = tenant_id
        elif tenant_id and tenant_id != identity.tenant_id:
            from app.enterprise.security import require_same_tenant
            require_same_tenant(identity, tenant_id)
        return await self._store.list_audit(
            tenant_id=scope_tenant, workflow_id=workflow_id,
            run_id=run_id, limit=limit,
        )
