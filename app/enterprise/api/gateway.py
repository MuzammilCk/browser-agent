"""Enterprise API Gateway — Phase 13 (invariant 2).

The gateway authenticates, authorizes, validates envelopes, enforces
idempotency, and delegates to the WorkflowService. It NEVER executes
Playwright, mutates browser state, bypasses PolicyEngine/HITL, resolves
raw vault secrets, or mutates AgentWorldState.

Responses are strict pydantic schemas. They never contain browser
handles, secrets, raw checkpoints, or internal policy details.

Also mounts the worker-facing operational endpoints (claim/heartbeat/
report) which are authenticated with the WORKER role and fenced by
fencing token at the store layer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.enterprise.audit import AuditService
from app.enterprise.models import (
    AuthorizationError,
    Identity,
    NotFoundError,
)
from app.enterprise.security import IdentityProvider
from app.enterprise.store import EnterpriseStore
from app.enterprise.workflow_service import (
    RunTransitionError,
    WorkflowService,
)

router = APIRouter(prefix="/enterprise", tags=["enterprise"])


# ----------------------------------------------------------------------
# App state wiring (set once at startup by create_enterprise_app_state)
# ----------------------------------------------------------------------

_STATE: dict[str, Any] = {}


def set_enterprise_state(
    *,
    store: EnterpriseStore,
    identity_provider: IdentityProvider,
    service: WorkflowService,
    audit: AuditService,
) -> None:
    _STATE.clear()
    _STATE["store"] = store
    _STATE["identity_provider"] = identity_provider
    _STATE["service"] = service
    _STATE["audit"] = audit


def _state() -> dict[str, Any]:
    if not _STATE:
        raise HTTPException(status_code=503, detail="enterprise runtime not initialized")
    return _STATE


# ----------------------------------------------------------------------
# Authentication dependency (server-side identity ONLY)
# ----------------------------------------------------------------------

async def get_identity(
    authorization: str | None = Header(default=None),
) -> Identity:
    provider: IdentityProvider = _state()["identity_provider"]
    try:
        return provider.resolve(authorization)
    except AuthorizationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ----------------------------------------------------------------------
# Strict request schemas (extra=forbid: client cannot smuggle tenant/
# user/role/worker/policy fields — invariant: untrusted fields never
# control authority)
# ----------------------------------------------------------------------

class CreateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2000)
    start_url: str = Field(min_length=1, max_length=2048)
    metadata: dict[str, str] = Field(default_factory=dict)


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str | None = Field(default=None, max_length=2000)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupt_id: str | None = Field(default=None, max_length=128)


# ----------------------------------------------------------------------
# Strict response schemas (no handles/secrets/checkpoints)
# ----------------------------------------------------------------------

class WorkflowResponse(BaseModel):
    workflow_id: str
    tenant_id: str
    user_id: str
    status: str
    current_run_id: str | None
    created_at: str
    updated_at: str


class RunResponse(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    worker_id: str | None
    checkpoint_id: str | None
    failure_code: str | None
    cancellation_requested: bool
    created_at: str
    updated_at: str


class AuditEventResponse(BaseModel):
    event_id: str
    parent_event_id: str | None
    event_type: str
    actor_type: str
    action: str | None
    policy_result: str | None
    hitl_result: str | None
    created_at: str
    payload: dict[str, Any]


def _workflow_response(wf) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=wf.workflow_id,
        tenant_id=wf.tenant_id,
        user_id=wf.user_id,
        status=wf.status,
        current_run_id=wf.current_run_id,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def _run_response(run) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        workflow_id=run.workflow_id,
        status=run.status.value,
        worker_id=run.worker_id,
        checkpoint_id=run.checkpoint_id,
        failure_code=run.failure_code,
        cancellation_requested=run.cancellation_requested,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


# ----------------------------------------------------------------------
# Idempotency (durable; invariant 16)
# ----------------------------------------------------------------------

def _request_hash(body: BaseModel) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _with_idempotency(
    identity: Identity,
    key: str | None,
    operation: str,
    body: BaseModel,
    execute,
    success_status: int = 200,
):
    store: EnterpriseStore = _state()["store"]
    if not key:
        return await execute()

    from app.enterprise.models import IdempotencyRecord

    rh = _request_hash(body)
    existing = await store.get_idempotency(key, identity.tenant_id)
    if existing is not None:
        if existing.request_hash != rh:
            raise HTTPException(
                status_code=422,
                detail="idempotency key reused with a different request body",
            )
        return JSONResponse(existing.status_code, existing.response)

    # Reserve the key first (atomic INSERT-if-absent), then execute.
    reserved = await store.put_idempotency_if_absent(
        IdempotencyRecord(
            key=key,
            tenant_id=identity.tenant_id,
            operation=operation,
            request_hash=rh,
        ),
    )
    if reserved is None:
        # Concurrent duplicate: replay once the winner persists its
        # response; if not yet persisted, return 409 retry-later.
        existing = await store.get_idempotency(key, identity.tenant_id)
        if existing is not None and existing.response:
            return JSONResponse(existing.status_code, existing.response)
        raise HTTPException(
            status_code=409,
            detail="duplicate in-flight request; retry",
        )

    try:
        result = await execute()
        # Persist the replayable response + real status code.
        if isinstance(result, BaseModel):
            payload = result.model_dump(mode="json")
        elif isinstance(result, dict):
            payload = result
        else:
            payload = {"result": str(result)}
        await store.update_idempotency_response(
            key, identity.tenant_id, success_status, payload,
        )
        return result
    except Exception:
        # Release the reservation so a corrected retry can proceed.
        await store.update_idempotency_response(
            key, identity.tenant_id, 500, {"error": "internal_error"},
        )
        raise


def JSONResponse(status_code: int, content: dict) -> Any:
    from fastapi.responses import JSONResponse as _J
    return _J(status_code=status_code, content=content)


# ----------------------------------------------------------------------
# Client endpoints (USER role)
# ----------------------------------------------------------------------

@router.post("/workflows", status_code=201)
async def create_workflow(
    body: CreateWorkflowRequest,
    identity: Identity = Depends(get_identity),
    idempotency_key: str | None = Header(default=None),
) -> Any:
    service: WorkflowService = _state()["service"]

    async def _execute() -> Any:
        wf = await service.create_workflow(
            identity, goal=body.goal, metadata=dict(body.metadata),
        )
        # Persist start_url inside workflow metadata (server-owned store;
        # the client cannot otherwise influence worker navigation).
        wf.metadata["start_url"] = body.start_url
        await _state()["store"].save_workflow(wf)
        await _state()["audit"].record(
            event_type="WORKFLOW_START_URL_REGISTERED",
            identity=identity,
            workflow_id=wf.workflow_id,
            payload={"start_url": body.start_url},
        )
        return _workflow_response(wf)

    return await _with_idempotency(
        identity, idempotency_key, "create_workflow", body, _execute,
        success_status=201,
    )


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    identity: Identity = Depends(get_identity),
) -> WorkflowResponse:
    service: WorkflowService = _state()["service"]
    try:
        wf = await service.get_workflow(identity, workflow_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="workflow not found")
    return _workflow_response(wf)


@router.post("/workflows/{workflow_id}/runs", status_code=201)
async def create_run(
    workflow_id: str,
    body: CreateRunRequest,
    identity: Identity = Depends(get_identity),
    idempotency_key: str | None = Header(default=None),
) -> Any:
    service: WorkflowService = _state()["service"]

    async def _execute() -> Any:
        try:
            run = await service.create_run(identity, workflow_id, goal=body.goal)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="workflow not found")
        return _run_response(run)

    return await _with_idempotency(
        identity, idempotency_key, "create_run", body, _execute,
        success_status=201,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    identity: Identity = Depends(get_identity),
) -> RunResponse:
    service: WorkflowService = _state()["service"]
    try:
        run = await service.get_run(identity, run_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_response(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    body: CancelRequest,
    identity: Identity = Depends(get_identity),
    idempotency_key: str | None = Header(default=None),
) -> Any:
    service: WorkflowService = _state()["service"]

    async def _execute() -> Any:
        try:
            run = await service.cancel_run(identity, run_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        except RunTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return _run_response(run)

    return await _with_idempotency(
        identity, idempotency_key, "cancel_run", body, _execute,
    )


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    body: ResumeRequest,
    identity: Identity = Depends(get_identity),
    idempotency_key: str | None = Header(default=None),
) -> Any:
    service: WorkflowService = _state()["service"]

    async def _execute() -> Any:
        try:
            run = await service.request_resume(identity, run_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="run not found")
        except RunTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return _run_response(run)

    return await _with_idempotency(
        identity, idempotency_key, "resume_run", body, _execute,
    )


@router.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    identity: Identity = Depends(get_identity),
    limit: int = 100,
) -> list[AuditEventResponse]:
    audit: AuditService = _state()["audit"]
    # Tenant-scoped read (cross-tenant → 404 without distinction).
    events = await audit.read(identity=identity, run_id=run_id, limit=min(limit, 500))
    return [
        AuditEventResponse(
            event_id=e.event_id,
            parent_event_id=e.parent_event_id,
            event_type=e.event_type,
            actor_type=e.actor_type,
            action=e.action,
            policy_result=e.policy_result,
            hitl_result=e.hitl_result,
            created_at=e.created_at,
            payload=e.payload,
        )
        for e in events
    ]
