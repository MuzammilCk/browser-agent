"""Vault Integration Service — Phase 13.

Invariants 10/11: raw secrets NEVER enter model context, queue payloads,
API responses, audit payloads, or logs — and possessing a secret grants
NO authority (approval/HITL/policy remain separate concepts).

Design: the service validates the reference (reusing the existing
ReferenceRegistry), checks tenant/user scoping, and requires proof of
execution authority (an ACTIVE lease fencing token for the run). Only
then does it resolve the value locally, in-process, at the execution
boundary. The value is returned to the immediate caller (the worker's
executor path) and is never serialized anywhere.

Tenant scoping uses per-tenant VaultManager directories:
    data/vault/<tenant_id>/<user_id>/user_vault.json
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.enterprise.models import (
    Identity,
    RunStatus,
    WorkerLease,
    WorkflowRun,
)


class VaultReferenceError(Exception):
    """Invalid, unknown, or unauthorized vault reference (fail closed)."""


class VaultNotAuthorizedError(VaultReferenceError):
    """Caller lacks execution authority for this resolution."""


@dataclass(frozen=True)
class ResolvedSecret:
    """Raw secret handed ONLY to the in-process execution boundary.

    Never persist, log, serialize, or display this object.
    """

    reference: str
    value: str
    tenant_id: str
    user_id: str


class VaultIntegrationService:
    """Local vault resolution boundary for enterprise workers."""

    def __init__(
        self,
        *,
        vault_root: str | Path = "data/vault",
        vault_encryption_key: str | None = None,
    ) -> None:
        self._vault_root = Path(vault_root)
        self._encryption_key = vault_encryption_key
        self._managers: dict[tuple[str, str], Any] = {}

    def _manager_for(self, tenant_id: str, user_id: str) -> Any:
        """Per-tenant/user VaultManager (Phase 1 vault stack reused)."""
        from app.vault.manager import VaultManager

        key = (tenant_id, user_id)
        if key not in self._managers:
            self._managers[key] = VaultManager(
                self._vault_root / tenant_id / user_id,
                encryption_key=self._encryption_key or None,
            )
        return self._managers[key]

    # ------------------------------------------------------------------
    # Reference validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_reference_shape(reference: str) -> tuple[str, str]:
        if not reference or "." not in reference:
            raise VaultReferenceError(
                f"invalid vault reference shape: {reference!r}"
            )
        prefix, name = reference.split(".", 1)
        prefix = prefix.strip().upper()
        if prefix not in ("USER", "DOCUMENT"):
            raise VaultReferenceError(
                f"unsupported vault reference prefix: {prefix}"
            )
        if not name or not name.replace("_", "").isalnum():
            raise VaultReferenceError(
                f"invalid vault reference name: {name!r}"
            )
        return prefix, name

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    @staticmethod
    def _require_execution_authority(
        run: WorkflowRun,
        lease: WorkerLease | None,
        fencing_token: int,
    ) -> None:
        """Secret possession never implies authority — the caller must
        hold the ACTIVE lease for THIS run with the CURRENT token."""
        if lease is None or lease.worker_id != run.worker_id:
            raise VaultNotAuthorizedError(
                "vault resolution requires the run's active lease"
            )
        if lease.fencing_token != fencing_token:
            raise VaultNotAuthorizedError("stale fencing token")
        if lease.is_expired():
            raise VaultNotAuthorizedError("lease expired")
        if run.status not in (
            RunStatus.RUNNING,
            RunStatus.DISPATCHED,
            RunStatus.PAUSED_HITL,
            RunStatus.PAUSED_RECOVERY,
        ):
            raise VaultNotAuthorizedError(
                f"run not in an executable state: {run.status.value}"
            )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve(
        self,
        reference: str,
        *,
        run: WorkflowRun,
        lease: WorkerLease | None,
        fencing_token: int,
        identity: Identity,
    ) -> ResolvedSecret:
        """Resolve a vault reference to a raw value at the execution
        boundary. Raises VaultReferenceError on any validation,
        scoping, or authorization failure (fail closed)."""
        prefix, name = self._validate_reference_shape(reference)

        # Tenant/user scoping: the run's own tenant/user, never the
        # caller's claim (the caller IS the run's worker here).
        if identity.subject_id != run.worker_id:
            raise VaultNotAuthorizedError(
                "resolving identity is not the run's owning worker"
            )
        tenant_id = run.tenant_id
        user_id = run.user_id

        self._require_execution_authority(run, lease, fencing_token)

        manager = self._manager_for(tenant_id, user_id)
        try:
            if prefix == "USER":
                from app.vault.resolver import ValueResolver
                resolver = ValueResolver(manager.vault)
                if not resolver.is_valid_ref(reference):
                    raise VaultReferenceError(
                        f"unknown vault reference: {reference!r}"
                    )
                value = resolver.resolve(reference)
            else:
                from app.vault.resolver import DocumentResolver
                resolver = DocumentResolver(manager.registry)
                doc = resolver.resolve(reference)
                value = doc.path if doc is not None else None
        except VaultReferenceError:
            raise
        except Exception as exc:  # resolution infra failure — no value
            raise VaultReferenceError(
                f"vault resolution failed for {reference!r}: {type(exc).__name__}"
            ) from exc

        if value is None or value == "":
            raise VaultReferenceError(
                f"reference {reference!r} has no resolvable value"
            )
        return ResolvedSecret(
            reference=reference, value=str(value),
            tenant_id=tenant_id, user_id=user_id,
        )

    def audit_metadata(self, resolved: ResolvedSecret) -> dict[str, Any]:
        """Safe audit metadata — the VALUE is never included."""
        return {
            "reference": resolved.reference,
            "tenant_id": resolved.tenant_id,
            "user_id": resolved.user_id,
            "resolved": True,
        }
