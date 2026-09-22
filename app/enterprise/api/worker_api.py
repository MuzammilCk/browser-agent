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


def _parse_fencing_token(body: dict | None) -> int:
    """Phase 15 H5: parse a client-supplied fencing token deterministically.

    Missing → 0 (the fenced store write rejects it with the standard
    lease-lost semantics). Non-integer → explicit 400, never a 500.
    """
    raw = (body or {}).get("fencing_token", 0)
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise HTTPException(status_code=400, detail="fencing_token must be an integer")
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="fencing_token must be an integer")


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
    # Phase 15 H5: cache the token for this (run, worker) so the claiming
    # worker's heartbeats resolve server-side even without a body token.
    cache_worker_token(run.run_id, identity.subject_id, lease.fencing_token)
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
    body: dict | None = None,
    identity: Identity = Depends(get_identity),
) -> dict:
    """Renew the caller's lease on a run.

    Phase 15 H5: the fencing token may be supplied in the request body
    (the token was returned by /claim, so an out-of-process worker can
    always present it). The process-local cache is a fallback. A missing
    token is a 400 — never a 500 — and a token that does not match the
    active lease is the standard fail-closed 409.
    """
    from app.enterprise.security import require_role

    try:
        require_role(identity, Role.WORKER)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    store = _state()["store"]

    body_token = (body or {}).get("fencing_token")
    if body_token is not None:
        fencing_token = _parse_fencing_token({"fencing_token": body_token})
    else:
        try:
            fencing_token = int(_worker_token_cache.get(run_id, identity.subject_id))
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "fencing_token required: supply the token returned by "
                    "/claim in the request body"
                ),
            )
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid cached fencing token")

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
    fencing_token = _parse_fencing_token(body)
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
    fencing_token = _parse_fencing_token(body)
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
    service = _state()["service"]
    try:
        run = await service.report_pause(
            identity, run_id,
            fencing_token=_parse_fencing_token(body),
            paused_hitl=bool((body or {}).get("paused_hitl", True)),
            checkpoint_id=(body or {}).get("checkpoint_id"),
        )
    except (NotFoundError, AuthorizationError, RunTransitionError) as exc:
        status = 404 if isinstance(exc, NotFoundError) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return {"run_id": run.run_id, "status": run.status.value}
