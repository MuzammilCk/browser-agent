"""Government Browser Agent — FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

app_settings = get_settings()
app_settings.setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown."""
    logger.info("Government Browser Agent starting...")
    yield
    logger.info("Government Browser Agent shutting down...")


app = FastAPI(
    title="Government Browser Agent",
    description="Semantic browser agent for government form filling",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "government-browser-agent"}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Minimal local UI."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Government Browser Agent</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .container { max-width: 640px; width: 100%; padding: 2rem; }
        h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #f1f5f9; }
        label { display: block; font-size: 0.875rem; color: #94a3b8; margin-bottom: 0.5rem; }
        input, textarea { width: 100%; padding: 0.75rem; border: 1px solid #334155; border-radius: 0.5rem; background: #1e293b; color: #e2e8f0; font-size: 0.875rem; margin-bottom: 1rem; }
        input:focus, textarea:focus { outline: none; border-color: #3b82f6; }
        textarea { height: 80px; resize: vertical; }
        button { width: 100%; padding: 0.75rem; border: none; border-radius: 0.5rem; background: #2563eb; color: white; font-size: 0.875rem; font-weight: 500; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        .status { margin-top: 1.5rem; padding: 1rem; border-radius: 0.5rem; background: #1e293b; border: 1px solid #334155; font-size: 0.8rem; color: #94a3b8; min-height: 60px; }
        .status .entry { padding: 0.25rem 0; }
        .status .ok { color: #4ade80; }
        .status .warn { color: #facc15; }
        .status .err { color: #f87171; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏛️ Government Browser Agent</h1>
        <label for="url">Official Website URL</label>
        <input type="url" id="url" placeholder="https://example.gov.in">
        <label for="task">Task</label>
        <textarea id="task" placeholder="Fill this application using my saved information"></textarea>
        <button onclick="startAgent()">Start Browser</button>
        <div class="status" id="status">
            <div class="entry">Waiting to start...</div>
        </div>
    </div>
    <script>
        function startAgent() {
            const status = document.getElementById('status');
            const url = document.getElementById('url').value;
            if (!url) { status.innerHTML = '<div class="entry err">Please enter a URL</div>'; return; }
            status.innerHTML = '<div class="entry warn">⚠️ Not yet connected — implementation pending</div>';
        }
    </script>
</body>
</html>"""
