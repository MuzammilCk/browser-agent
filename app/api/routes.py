"""API routes for the Government Browser Agent frontend."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

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


# ── API Endpoints ──────────────────────────────────────────


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
