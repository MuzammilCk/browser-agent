"""API routes for the Government Browser Agent frontend.

Includes:
- Site registry browsing endpoints
- Automation endpoints (start, poll, confirm, abort, screenshot)

Audit fixes applied here:
- C1: confirmation checkpoints wait for an explicit user decision via
  POST /api/automate/{id}/confirm, then resume the same AgentRunner.
- C2: VaultManager is loaded from disk (settings-configured encryption)
  and handed to AgentRunner so value_ref fills actually resolve.
- C5: abort cancels the running task; tasks hold strong references;
  screenshot history and the workflow store are bounded.
- C6: CAPTCHA/OTP steps are stripped from task instructions before they
  reach the LLM planner (policy forbids automating them).
- C12: typed request bodies, optional bearer-token auth on /api/*.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.config.settings import get_settings
from app.models.workflow_state import WorkflowStatus
from app.sites.registry import TrustedDomainRegistry, sanitize_task_instructions

logger = logging.getLogger(__name__)


async def _require_api_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token gate for /api/* (no-op until api_token is configured)."""
    token = get_settings().api_token
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


router = APIRouter(dependencies=[Depends(_require_api_token)])

# Singleton registry
_registry: TrustedDomainRegistry | None = None

# ── In-memory workflow store ────────────────────────────────

_workflows: dict[str, dict[str, Any]] = {}
_automation_tasks: dict[str, asyncio.Task] = {}

_MAX_WORKFLOWS = 100          # bounded workflow store
_MAX_SCREENSHOTS = 6          # per-workflow screenshot history cap
_CONFIRM_TIMEOUT_S = 600      # max wait for a user confirmation decision
_MAX_CONFIRM_ROUNDS = 10      # max sequential confirmation gates per run


def _get_registry() -> TrustedDomainRegistry:
    global _registry
    if _registry is None:
        _registry = TrustedDomainRegistry()
    return _registry


def _add_screenshot(wf: dict[str, Any], step: str, url: str, data_hex: str) -> None:
    """Append a screenshot, keeping only the most recent ones (memory cap)."""
    wf["screenshots"].append({"step": step, "url": url, "data": data_hex})
    if len(wf["screenshots"]) > _MAX_SCREENSHOTS:
        del wf["screenshots"][: len(wf["screenshots"]) - _MAX_SCREENSHOTS]


def _evict_finished_workflows() -> None:
    """Keep the workflow store bounded by dropping oldest finished runs."""
    if len(_workflows) <= _MAX_WORKFLOWS:
        return
    finished = [
        wid for wid, wf in _workflows.items()
        if wf.get("status") in ("completed", "failed", "aborted")
    ]
    for wid in finished:
        if len(_workflows) <= _MAX_WORKFLOWS:
            break
        _workflows.pop(wid, None)
        _automation_tasks.pop(wid, None)


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
    result = []
    for state in reg.list_states():
        sites = reg.list_by_state(state)
        result.append({
            "state": state,
            "sites_count": len(sites),
            "domains": [s.domain for s in sites],
        })
    return {"states": result}


# ── Automation Endpoints ───────────────────────────────────


class AutomateRequest(BaseModel):
    """Body for starting an automation run."""

    domain: str
    task: str = ""


class ConfirmRequest(BaseModel):
    """Body for approving/declining a pending confirmation-gated action."""

    approved: bool


@router.post("/api/automate")
async def start_automation(body: AutomateRequest) -> dict:
    """Start automation for a site."""
    domain = body.domain.strip()
    task = body.task.strip()

    if not domain:
        return {"error": "domain is required"}

    # Look up site URL from registry
    reg = _get_registry()
    entry = reg.get_entry(domain)
    if entry is None:
        return {"error": f"Site '{domain}' not found in registry"}

    url = entry.url
    workflow_id = str(uuid.uuid4())[:8]

    # Look up detailed instructions for this task from the registry,
    # then strip CAPTCHA/OTP steps (audit C6): policy forbids automating
    # them, so coaching the planner toward them is counterproductive.
    task_instructions = sanitize_task_instructions(task) if task else ""
    if task:
        for t in entry.tasks:
            if t.name == task:
                raw = t.instructions or t.description or task
                task_instructions = sanitize_task_instructions(raw)
                break

    effective_task = task_instructions or f"Navigate to {entry.official_name}"

    _evict_finished_workflows()

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
        "pending_action": None,
        "vault_loaded": False,
        "confirm_event": asyncio.Event(),
        "approved": None,
    }

    # Launch background automation (strong reference kept — audit C5)
    t = asyncio.create_task(_run_automation(workflow_id, url, effective_task))
    _automation_tasks[workflow_id] = t

    return {
        "workflow_id": workflow_id,
        "domain": domain,
        "url": url,
        "status": "starting",
    }


async def _run_automation(workflow_id: str, url: str, task: str) -> None:
    """Run the agent automation loop in the background.

    Pauses at confirmation checkpoints and waits for the user's decision
    delivered through /api/automate/{id}/confirm (audit C1).
    """
    from app.agent.runner import AgentRunner
    from app.browser.manager import BrowserManager
    from app.vault.manager import VaultManager

    wf = _workflows[workflow_id]
    settings = get_settings()

    manager = BrowserManager(settings)
    llm = None
    try:
        wf["status"] = "launching_browser"

        await manager.start()

        # Navigate to the target URL
        wf["status"] = "navigating"
        page = await manager.open(url)
        wf["current_url"] = url
        wf["page_title"] = await page.title()

        # Take initial screenshot
        try:
            screenshot = await page.screenshot(full_page=False)
            _add_screenshot(wf, "initial", url, screenshot.hex())
        except Exception:
            pass

        # Try to create LLM gateway for intelligent planning
        if settings.openrouter_api_key:
            try:
                from app.llm.openrouter import OpenRouterGateway
                llm = OpenRouterGateway(settings)
            except Exception as e:
                logger.warning("Could not create LLM gateway: %s", e)

        # Audit C2 fix: load the persisted vault + documents so value_ref
        # actions resolve against real data instead of an empty UserVault.
        vault_manager = VaultManager(
            settings.data_dir / "vault",
            encryption_key=settings.vault_encryption_key,
        )
        vault_data = vault_manager.vault.model_dump()
        wf["vault_loaded"] = any(bool(v) for v in vault_data.values())
        if not wf["vault_loaded"]:
            logger.warning(
                "Automation %s: vault is empty — value_ref fills will fail. "
                "Populate data/vault/user_vault.json first.", workflow_id,
            )

        # Create and run agent
        from app.policy.document_policy import DocumentPolicy
        document_policy = DocumentPolicy(
            allowed_roots=settings.document_allowed_dirs or None,
        )
        runner = AgentRunner(
            llm=llm,
            max_iterations=30,
            vault=vault_manager.vault,
            document_registry=vault_manager.registry,
            document_policy=document_policy,
        )

        wf["status"] = "running"
        workflow_state = await runner.run(page=page, task=task, domain=wf["domain"])

        # Audit C1 fix: confirmation loop. While the workflow sits at a
        # REQUIRE_CONFIRMATION gate, wait for the user's decision and let
        # runner.resume continue the SAME workflow.
        rounds = 0
        while (
            workflow_state.pending_action is not None
            and workflow_state.status == WorkflowStatus.READY_FOR_CONFIRMATION
        ):
            rounds += 1
            if rounds > _MAX_CONFIRM_ROUNDS:
                workflow_state.set_error("fatal", "Too many confirmation rounds")
                workflow_state.status = WorkflowStatus.FAILED
                break

            _sync_workflow_to_wf(wf, workflow_state)
            wf["status"] = "ready_for_confirmation"

            event: asyncio.Event = wf["confirm_event"]
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=_CONFIRM_TIMEOUT_S)
            except asyncio.TimeoutError:
                workflow_state.pending_action = None
                workflow_state.set_error(
                    "fatal",
                    f"Confirmation not given within {_CONFIRM_TIMEOUT_S}s — session closed",
                )
                workflow_state.status = WorkflowStatus.FAILED
                break

            # Abort may have been requested while we were waiting.
            if wf.get("abort_requested"):
                break

            approved = bool(wf.get("approved"))
            wf["approved"] = None

            workflow_state = await runner.resume(
                page=page, workflow=workflow_state, approved=approved,
            )

        # Update workflow with results
        _sync_workflow_to_wf(wf, workflow_state)
        wf["status"] = workflow_state.status.value

        # Take final screenshot
        try:
            screenshot = await page.screenshot(full_page=False)
            _add_screenshot(wf, "final", workflow_state.current_url or url, screenshot.hex())
        except Exception:
            pass

        logger.info(
            "Automation %s finished: %s (%d actions)",
            workflow_id, workflow_state.status.value, workflow_state.total_actions,
        )

    except asyncio.CancelledError:
        wf["status"] = "aborted"
        wf.setdefault("checkpoints", []).append("Cancelled by user (abort)")
        logger.info("Automation %s aborted by user", workflow_id)
        raise
    except Exception as e:
        logger.error("Automation %s failed: %s", workflow_id, e, exc_info=True)
        wf["status"] = "failed"
        wf["error"] = str(e)
    finally:
        if llm:
            try:
                await llm.close()
            except Exception:
                pass
        try:
            await manager.stop()
        except Exception:
            pass
        wf.pop("confirm_event", None)
        wf.pop("approved", None)
        wf.pop("abort_requested", None)
        _automation_tasks.pop(workflow_id, None)


def _sync_workflow_to_wf(wf: dict[str, Any], ws) -> None:
    """Copy public fields from WorkflowState into the API workflow record."""
    wf["actions"] = [
        {
            "type": r.action_type,
            "target": r.target_ref,
            "success": r.success,
            "message": r.message,
            "policy": r.policy_decision,
        }
        for r in ws.actions_taken
    ]
    wf["checkpoints"] = ws.checkpoints
    wf["total_actions"] = ws.total_actions
    wf["successful_actions"] = ws.successful_actions
    wf["failed_actions"] = ws.failed_actions
    if ws.pending_action:
        wf["pending_action"] = {
            "action": ws.pending_action.get("action"),
            "target_ref": ws.pending_action.get("target_ref"),
            "value_ref": ws.pending_action.get("value_ref"),
            "reason": ws.pending_action.get("reason"),
        }
    else:
        wf["pending_action"] = None


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
        # True once the background automation task has exited (browser
        # stopped). Clients must stop polling when this is set — statuses
        # like waiting_for_user / waiting_for_captcha are terminal here,
        # not pauses. Only ready_for_confirmation keeps the task alive.
        "finished": workflow_id not in _automation_tasks,
        "current_url": wf["current_url"],
        "page_title": wf.get("page_title", ""),
        "actions": wf["actions"],
        "checkpoints": wf["checkpoints"],
        "pending_action": wf.get("pending_action"),
        "vault_loaded": wf.get("vault_loaded"),
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


@router.post("/api/automate/{workflow_id}/confirm")
async def confirm_automation(workflow_id: str, body: ConfirmRequest) -> dict:
    """Approve or decline the action waiting at a confirmation checkpoint.

    Audit C1: delivers the user's decision to the paused automation loop.
    """
    if workflow_id not in _workflows:
        return {"error": "Workflow not found"}

    wf = _workflows[workflow_id]
    event = wf.get("confirm_event")
    if event is None:
        return {"error": "Workflow is not waiting for confirmation"}

    wf["approved"] = bool(body.approved)
    event.set()
    return {"workflow_id": workflow_id, "approved": bool(body.approved)}


@router.post("/api/automate/{workflow_id}/abort")
async def abort_automation(workflow_id: str) -> dict:
    """Abort a running automation.

    Audit C5 fix: actually cancels the background task instead of just
    flipping a status flag the running loop later overwrites.
    """
    if workflow_id not in _workflows:
        return {"error": "Workflow not found"}

    wf = _workflows[workflow_id]
    if wf["status"] in ("completed", "failed", "aborted"):
        return {"message": "Workflow already finished", "status": wf["status"]}

    wf["abort_requested"] = True
    task = _automation_tasks.get(workflow_id)
    if task is not None and not task.done():
        task.cancel()
        wf["status"] = "aborted"
        return {"workflow_id": workflow_id, "status": "aborted"}

    wf["status"] = "aborted"
    return {"workflow_id": workflow_id, "status": "aborted"}
