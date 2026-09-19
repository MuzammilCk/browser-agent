"""Worker-facing operational API — Phase 13.

Endpoints used by an out-of-process worker (or the in-process worker
runtime) against the WorkflowService. Authentication is via the WORKER
role bearer token; worker_id is server-assigned from the token, never
from the request. Mutating reports are fencing-validated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.enterprise.api.gateway import _state, get_identity
from app.enterprise.models import (
    AuthorizationError,
    Identity,
    NotFoundError,
    Role,
    RunStatus,
)
from app.enterprise.workflow_service import RunTransitionError

worker_router = APIRouter(prefix="/enterprise/worker", tags=["enterprise-worker"])


class ClaimResponse:
    pass


@worker_router.post("/claim")
async def claim_next_run(
    identity: Identity = Depends(get_identity),
) -> dict:
    from app.enterprise.security import require_role

    try:
        require_role(identity, Role.WORKER)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    store = _state()["store"]
    result = await store.claim_next_run(
        identity.subject_id, lease_seconds=30.0,
    )
    if result is None:
        return {"claimed": False}
    run, lease, item = result
    return {
        "claimed": True,
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "lease_id": lease.lease_id,
        "fencing_token": lease.fencing_token,
        "agent_run_id": run.agent_run_id,
        "checkpoint_id": run.checkpoint_id,
        "status": run.status.value,
    }


@worker_router.post("/runs/{run_id}/heartbeat")
async def heartbeat(
    run_id: str,
    identity: Identity = Depends(get_identity),
) -> dict:
    from app.enterprise.security import require_role

    try:
        require_role(identity, Role.WORKER)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    store = _state()["store"]
    try:
        fencing_token = int(_worker_token_cache.get(run_id, identity.subject_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid fencing token")
    lease = await store.renew_lease(
        run_id, identity.subject_id, fencing_token, 30.0,
    )
    if lease is None:
        raise HTTPException(status_code=409, detail="lease lost — fail closed")
    return {
        "run_id": run_id,
        "fencing_token": lease.fencing_token,
        "expires_at": lease.expires_at,
    }


class _WorkerTokenCache:
    """Process-local map of (run_id -> last known fencing token) per worker."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], int] = {}

    def put(self, run_id: str, worker_id: str, token: int) -> None:
        self._tokens[(run_id, worker_id)] = token

    def get(self, run_id: str, worker_id: str) -> int:
        return self._tokens[(run_id, worker_id)]


_worker_token_cache = _WorkerTokenCache()


def cache_worker_token(run_id: str, worker_id: str, token: int) -> None:
    _worker_token_cache.put(run_id, worker_id, token)


@worker_router.post("/runs/{run_id}/complete")
async def report_complete(
    run_id: str,
    body: dict | None = None,
    identity: Identity = Depends(get_identity),
) -> dict:
    body = body or {}
    fencing_token = int(body.get("fencing_token", 0))
    service = _state()["service"]
    try:
        run = await service.complete_run(
            identity, run_id,
            fencing_token=fencing_token,
            checkpoint_id=body.get("checkpoint_id"),
        )
    except (NotFoundError, AuthorizationError, RunTransitionError) as exc:
        status = 404 if isinstance(exc, NotFoundError) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return {"run_id": run.run_id, "status": run.status.value}


@worker_router.post("/runs/{run_id}/fail")
async def report_failed(
    run_id: str,
    body: dict | None = None,
    identity: Identity = Depends(get_identity),
) -> dict:
    body = body or {}
    fencing_token = int(body.get("fencing_token", 0))
    service = _state()["service"]
    try:
        run = await service.fail_run(
            identity, run_id,
            fencing_token=fencing_token,
            failure_code=str(body.get("failure_code", "engine_failed")),
            checkpoint_id=body.get("checkpoint_id"),
        )
    except (NotFoundError, AuthorizationError, RunTransitionError) as exc:
        status = 404 if isinstance(exc, NotFoundError) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return {"run_id": run.run_id, "status": run.status.value}


@worker_router.post("/runs/{run_id}/pause")
async def report_paused(
    run_id: str,
    body: dict | None = None,
    identity: Identity = Depends(get_identity),
) -> dict:
    body = body or {}
    service = _state()["service"]
    try:
        run = await service.report_pause(
            identity, run_id,
            fencing_token=int(body.get("fencing_token", 0)),
            paused_hitl=bool(body.get("paused_hitl", True)),
            checkpoint_id=body.get("checkpoint_id"),
        )
    except (NotFoundError, AuthorizationError, RunTransitionError) as exc:
        status = 404 if isinstance(exc, NotFoundError) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return {"run_id": run.run_id, "status": run.status.value}
