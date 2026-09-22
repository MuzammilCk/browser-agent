"""Government Browser Agent — FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

app_settings = get_settings()
app_settings.setup_logging()


def refresh_app_settings() -> None:
    """Re-read the cached settings singleton (Phase 15 H8).

    Used by tests and by deployments that mutate configuration before
    serving; keeps the /ready endpoint's view of the world current.
    """
    global app_settings
    app_settings = get_settings()

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown."""
    logger.info("Government Browser Agent starting...")
    yield
    logger.info("Government Browser Agent shutting down...")


app = FastAPI(
    title="Government Browser Agent",
    description="Semantic browser agent for government form filling",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Mount API routes ──────────────────────────────────────

from app.api.routes import router as api_router
from app.api.vault_routes import router as vault_router
app.include_router(api_router)
app.include_router(vault_router)

# ── Phase 13: enterprise runtime API (gateway + worker endpoints) ──

from fastapi import FastAPI as _FastAPI


def mount_enterprise_runtime(target: _FastAPI) -> None:
    """Initialize the enterprise runtime (Phase 13) and mount its routers.

    Uses the in-memory store by default so local development works
    without configuration; production deployments swap in
    PostgresEnterpriseStore via set_enterprise_state(store=...).
    """
    from app.enterprise.api.gateway import router as enterprise_router
    from app.enterprise.api.gateway import set_enterprise_state
    from app.enterprise.api.worker_api import worker_router
    from app.enterprise.audit import AuditService
    from app.enterprise.in_memory_store import InMemoryEnterpriseStore
    from app.enterprise.security import IdentityProvider
    from app.enterprise.workflow_service import WorkflowService

    store = InMemoryEnterpriseStore()
    audit = AuditService(store)
    service = WorkflowService(store, audit)
    provider = IdentityProvider()

    settings = get_settings()
    if settings.enterprise_user_token:
        provider.register_principal(
            settings.enterprise_user_token,
            tenant_id="default",
            subject_id="enterprise-user",
        )
    if settings.enterprise_worker_token:
        provider.register_worker(settings.enterprise_worker_token)

    set_enterprise_state(
        store=store, identity_provider=provider,
        service=service, audit=audit,
    )
    target.include_router(enterprise_router)
    target.include_router(worker_router)


mount_enterprise_runtime(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health endpoint."""
    return {"status": "ok", "service": "government-browser-agent"}


@app.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness endpoint — Phase 15 H8.

    Distinguishes "process up" (/health) from "runtime usable for a
    production deployment". Always reports component states; when
    production_mode is set and validation produced blocking conditions,
    responds 503 so orchestrators fail the deployment.
    """
    blockers, warnings = app_settings.validate_production_readiness()
    ready = not blockers
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "checks": {
                "api_auth": bool(app_settings.api_token),
                "vault_encryption": bool(app_settings.vault_encryption_key),
                "enterprise_worker_auth": bool(
                    app_settings.enterprise_worker_token
                ),
                "model": app_settings.openrouter_model,
                "production_mode": app_settings.production_mode,
            },
            "blocking": blockers,
            "warnings": warnings,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the frontend — reads fresh from disk, no caching."""
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/automation/{workflow_id}", response_class=HTMLResponse)
async def automation_view(workflow_id: str) -> HTMLResponse:
    """Full-page automation monitor (opened via the panel's Pop out button)."""
    html = (FRONTEND_DIR / "automation.html").read_text(encoding="utf-8")
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
