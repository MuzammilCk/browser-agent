"""API routes for the Government Browser Agent frontend.

Includes:
- Site registry browsing endpoints
- Automation endpoints (start, poll, abort, screenshot)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response

from app.sites.registry import TrustedDomainRegistry

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton registry
_registry: TrustedDomainRegistry | None = None


def _get_registry() -> TrustedDomainRegistry:
    global _registry
    if _registry is None:
        _registry = TrustedDomainRegistry()
    return _registry


# ── In-memory workflow store ────────────────────────────────

_workflows: dict[str, dict[str, Any]] = {}


# ── Site Registry Endpoints ────────────────────────────────


@router.get("/api/sites")
async def list_sites() -> dict:
    """List all sites grouped by category."""
    reg = _get_registry()
    view = reg.get_categorized_view()
    result = {}
    for cat, subcats in view.items():
        result[cat] = {}
        for subcat, entries in subcats.items():
            result[cat][subcat] = [
                {
                    "domain": e.domain,
                    "official_name": e.official_name,
                    "url": e.url,
                    "description": e.description,
                    "government_level": e.government_level,
                    "state": e.state,
                    "tasks_count": len(e.tasks),
                    "interaction_classes": e.interaction_classes,
                }
                for e in entries
            ]
    return {"categories": result, "stats": reg.get_stats()}


@router.get("/api/categories")
async def list_categories() -> dict:
    """List all categories with counts."""
    reg = _get_registry()
    cats = reg.list_categories()
    return {
        "categories": [
            {
                "name": cat,
                "count": len(reg.list_by_category(cat)),
            }
            for cat in cats
        ]
    }


@router.get("/api/site/{domain}")
async def get_site_detail(domain: str) -> dict:
    """Get full details for a specific site including all tasks."""
    reg = _get_registry()
    entry = reg.get_entry(domain)
    if entry is None:
        return {"error": f"Site '{domain}' not found"}
    return {
        "domain": entry.domain,
        "official_name": entry.official_name,
        "url": entry.url,
        "description": entry.description,
        "category": entry.category,
        "subcategory": entry.subcategory,
        "government_level": entry.government_level,
        "state": entry.state,
        "tasks": [
            {
                "name": t.name,
                "description": t.description,
                "requires_auth": t.requires_auth,
                "requires_payment": t.requires_payment,
                "difficulty": t.difficulty,
            }
            for t in entry.tasks
        ],
        "interaction_classes": entry.interaction_classes,
    }


@router.get("/api/search")
async def search_sites(q: str = Query(..., min_length=1)) -> dict:
    """Search sites by name, description, or task."""
    reg = _get_registry()
    results = reg.search(q)
    return {
        "query": q,
        "results": [
            {
                "domain": e.domain,
                "official_name": e.official_name,
                "url": e.url,
                "description": e.description,
                "category": e.category,
                "tasks_count": len(e.tasks),
            }
            for e in results
        ],
    }


@router.get("/api/stats")
async def get_stats() -> dict:
    """Get registry statistics."""
    reg = _get_registry()
    return reg.get_stats()


@router.get("/api/states")
async def list_states() -> dict:
    """List all states with available portals."""
    reg = _get_registry()
    states = set()
    for entry in reg._domains.values():
        if entry.state:
            states.add(entry.state)
    result = []
    for state in sorted(states):
        sites = reg.list_by_state(state)
        result.append({
            "state": state,
            "sites_count": len(sites),
            "domains": [s.domain for s in sites],
        })
    return {"states": result}


# ── Automation Endpoints ───────────────────────────────────


@router.post("/api/automate")
async def start_automation(body: dict) -> dict:
    """Start automation for a site.

    Body:
        domain: str - the site domain
        task: str - what to automate (e.g. "View Digital Aadhaar")
    """
    domain = body.get("domain", "")
    task = body.get("task", "")

    if not domain:
        return {"error": "domain is required"}

    # Look up site URL from registry
    reg = _get_registry()
    entry = reg.get_entry(domain)
    if entry is None:
        return {"error": f"Site '{domain}' not found in registry"}

    url = entry.url
    workflow_id = str(uuid.uuid4())[:8]

    # Look up detailed instructions for this task from the registry
    task_instructions = task  # default: use the raw task name
    if task:
        for t in entry.tasks:
            if t.name == task:
                task_instructions = t.instructions or t.description or task
                break

    effective_task = task_instructions or f"Navigate to {entry.official_name}"

    # Store initial state
    _workflows[workflow_id] = {
        "workflow_id": workflow_id,
        "domain": domain,
        "task": effective_task,
        "url": url,
        "status": "starting",
        "current_url": url,
        "actions": [],
        "error": None,
        "screenshots": [],
        "page_title": "",
        "checkpoints": [],
    }

    # Launch background automation
    asyncio.create_task(_run_automation(workflow_id, url, effective_task))

    return {
        "workflow_id": workflow_id,
        "domain": domain,
        "url": url,
        "status": "starting",
    }


async def _run_automation(workflow_id: str, url: str, task: str) -> None:
    """Run the full agent automation loop in the background."""
    from app.browser.manager import BrowserManager
    from app.config.settings import get_settings

    wf = _workflows[workflow_id]
    settings = get_settings()

    try:
        wf["status"] = "launching_browser"

        async with BrowserManager(settings) as manager:
            # Navigate to the target URL
            wf["status"] = "navigating"
            page = await manager.open(url)
            wf["current_url"] = url
            wf["page_title"] = await page.title()

            # Take initial screenshot
            try:
                screenshot = await page.screenshot(full_page=False)
                wf["screenshots"].append({
                    "step": "initial",
                    "url": url,
                    "data": screenshot.hex(),
                })
            except Exception:
                pass

            # Try to create LLM gateway for intelligent planning
            llm = None
            if settings.openrouter_api_key:
                try:
                    from app.llm.openrouter import OpenRouterGateway
                    llm = OpenRouterGateway(settings)
                except Exception as e:
                    logger.warning("Could not create LLM gateway: %s", e)

            # Create and run agent
            from app.agent.runner import AgentRunner
            runner = AgentRunner(llm=llm, max_iterations=30)

            wf["status"] = "running"

            # Run the agent loop
            workflow_state = await runner.run(page=page, task=task, domain=wf["domain"])

            # Update workflow with results
            wf["status"] = workflow_state.status.value
            wf["actions"] = [
                {
                    "type": r.action_type,
                    "target": r.target_ref,
                    "success": r.success,
                    "message": r.message,
                    "policy": r.policy_decision,
                }
                for r in workflow_state.actions_taken
            ]
            wf["checkpoints"] = workflow_state.checkpoints
            wf["total_actions"] = workflow_state.total_actions
            wf["successful_actions"] = workflow_state.successful_actions
            wf["failed_actions"] = workflow_state.failed_actions

            # Take final screenshot
            try:
                screenshot = await page.screenshot(full_page=False)
                wf["screenshots"].append({
                    "step": "final",
                    "url": workflow_state.current_url or url,
                    "data": screenshot.hex(),
                })
            except Exception:
                pass

            # Close LLM gateway
            if llm:
                try:
                    await llm.close()
                except Exception:
                    pass

            logger.info(
                "Automation %s finished: %s (%d actions)",
                workflow_id, workflow_state.status.value, workflow_state.total_actions,
            )

    except Exception as e:
        logger.error("Automation %s failed: %s", workflow_id, e, exc_info=True)
        wf["status"] = "failed"
        wf["error"] = str(e)


@router.get("/api/automate/{workflow_id}")
async def get_automation_status(workflow_id: str) -> dict:
    """Poll automation status."""
    if workflow_id not in _workflows:
        return {"error": "Workflow not found"}

    wf = _workflows[workflow_id]
    # Return status without screenshot data (too large for polling)
    return {
        "workflow_id": wf["workflow_id"],
        "domain": wf["domain"],
        "task": wf["task"],
        "url": wf["url"],
        "status": wf["status"],
        "current_url": wf["current_url"],
        "page_title": wf.get("page_title", ""),
        "actions": wf["actions"],
        "checkpoints": wf["checkpoints"],
        "error": wf["error"],
        "total_actions": wf.get("total_actions", 0),
        "successful_actions": wf.get("successful_actions", 0),
        "failed_actions": wf.get("failed_actions", 0),
        "screenshot_count": len(wf["screenshots"]),
    }


@router.get("/api/automate/{workflow_id}/screenshot")
async def get_automation_screenshot(workflow_id: str, step: str = "latest") -> Response:
    """Get a screenshot from the automation."""
    if workflow_id not in _workflows:
        return Response(content="Workflow not found", status_code=404)

    wf = _workflows[workflow_id]
    if not wf["screenshots"]:
        return Response(content="No screenshots available", status_code=404)

    if step == "latest":
        screenshot_data = wf["screenshots"][-1]["data"]
    else:
        for s in wf["screenshots"]:
            if s["step"] == step:
                screenshot_data = s["data"]
                break
        else:
            return Response(content=f"Screenshot '{step}' not found", status_code=404)

    return Response(
        content=bytes.fromhex(screenshot_data),
        media_type="image/png",
    )


@router.post("/api/automate/{workflow_id}/abort")
async def abort_automation(workflow_id: str) -> dict:
    """Abort a running automation."""
    if workflow_id not in _workflows:
        return {"error": "Workflow not found"}

    wf = _workflows[workflow_id]
    if wf["status"] in ("completed", "failed", "aborted"):
        return {"message": "Workflow already finished", "status": wf["status"]}

    wf["status"] = "aborted"
    return {"workflow_id": workflow_id, "status": "aborted"}
