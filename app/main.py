"""Government Browser Agent — FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

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
    """Health check endpoint."""
    return {"status": "ok", "service": "government-browser-agent"}


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    """Serve the frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")
