"""Government Browser Agent — FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

app_settings = get_settings()
app_settings.setup_logging()

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
app.include_router(api_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health endpoint."""
    return {"status": "ok", "service": "government-browser-agent"}


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
