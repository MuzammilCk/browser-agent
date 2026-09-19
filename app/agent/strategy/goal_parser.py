"""Deterministic goal parser — Phase 5 (requirement 1).

Turns the user's task text into a structured AgentGoal WITHOUT any LLM
call: this is strategic normalization, not reasoning. The AgentReasoner
(Phase 4) stays the only LLM component; the plan it later receives is
deterministic state.

Approach: conservative keyword/shape classification over the goal text.
Ambiguity beats guessing (AGENTS.md rule 8): anything uncertain becomes
an explicit unresolved question rather than a silently-inferred plan
step. Sensitive reference names are NEVER inferred as available — the
available-references list comes from the ReferenceRegistry, and raw
values must never enter the goal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.registry import ReferenceRegistry, get_registry
from app.agent.strategy.models import AgentGoal, SuccessCriterion

# ── Conservative domain classification ──────────────────────────────

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "identity": ("aadhaar", "uidai", "pan", "identity", "kyc"),
    "welfare": ("subsidy", "welfare", "pmkisan", "pension", "scheme"),
    "transport": ("driving", "licence", "license", "vehicle", "transport", "rto"),
    "education": ("school", "college", "university", "admission", "scholarship"),
    "recruitment": ("recruitment", "vacancy", "application", "exam"),
    "certificate": ("certificate", "birth", "death", "marriage"),
    "grievance": ("complaint", "grievance", "report"),
    "appointment": ("appointment", "slot", "booking"),
    "tax": ("gst", "income tax", "itr", "tax"),
}

# Multi-step shape hints: any of these suggests a form-filling workflow
# with more than one page/step (heuristic, conservative).
_MULTI_STEP_HINTS = (
    "apply", "register", "registration", "renew", "renewal",
    "fill", "submit", "application", "form", "book", "schedule",
)

# Phrases that indicate the user expects the agent to stop before the
# final irreversible action (review/submit) — the DEFAULT stance.
_REVIEW_BOUNDARY_HINTS = (
    "review", "before submit", "stop before", "until review",
    "don't submit", "do not submit", "without submitting",
)

_URL_RE = re.compile(r"https?://[^\s]+")


@dataclass
class ParsedGoal:
    """Result of parsing: the structured goal + explicit ambiguity."""

    goal: AgentGoal
    unresolved_questions: list[str] = field(default_factory=list)
    multi_step_hint: bool = False


def _normalize(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _detect_domain(raw: str) -> tuple[str, list[str]]:
    text = raw.lower()
    hits: list[str] = []
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(k in text for k in keywords):
            hits.append(domain)
    if len(hits) == 1:
        return hits[0], []
    if not hits:
        return "", ["Which government domain/service does this task belong to?"]
    return hits[0], [
        f"Task mentions multiple domains ({', '.join(hits)}); using "
        f"'{hits[0]}' — confirm if wrong."
    ]


def _detect_url(raw: str) -> str:
    match = _URL_RE.search(raw)
    return match.group(0).rstrip(".,;:!?\"')") if match else ""


def _goal_criteria(raw: str, multi_step: bool) -> list[SuccessCriterion]:
    """Goal-level success criteria: explicit and testable only.

    Defaults reflect the project's non-negotiable completion policy:
    required safe fields complete, no unresolved ambiguity, and — for
    multi-step applications — the review/confirmation state reached
    (NOT autonomous submission).
    """
    criteria: list[SuccessCriterion] = [
        SuccessCriterion(
            description="All required fields are filled and verified",
            kind="no_pending_fields",
        ),
        SuccessCriterion(
            description="No ambiguous field mappings remain",
            kind="no_ambiguous_fields",
        ),
    ]
    if multi_step:
        criteria.append(SuccessCriterion(
            description="Review/confirmation state reached (never autonomous submission)",
            kind="page_type_reached",
            params={"page_type": "review"},
        ))
    return criteria


def parse_goal(
    raw: str,
    *,
    available_references: list[str] | None = None,
    registry: ReferenceRegistry | None = None,
) -> ParsedGoal:
    """Parse the user's task text into a structured AgentGoal.

    ``available_references`` (e.g. from ReferenceRegistry.get_all_refs())
    is recorded as INFORMATION ONLY on unresolved questions when missing;
    the parser never invents reference availability, and no values —
    only names — ever enter the goal.
    """
    text = _normalize(raw)
    if not text:
        raise ValueError("goal text is empty")

    domain, questions = _detect_domain(text)
    url = _detect_url(text)
    multi_step = any(h in text.lower() for h in _MULTI_STEP_HINTS)

    description = text
    if not url and not domain:
        questions.insert(0, "No target site/portal identified — where should this run?")

    goal = AgentGoal(
        raw=raw,
        description=description,
        domain=domain,
        success_criteria=_goal_criteria(text, multi_step),
    )

    if multi_step:
        questions.append(
            "Multi-step application detected — confirm the step order on the portal."
        )
    if available_references is None:
        questions.append(
            "Vault reference availability not provided — pass "
            "available_references to constrain which USER./DOCUMENT. refs "
            "the plan may assume."
        )
    elif not available_references:
        questions.append(
            "No vault references available — the plan cannot assume "
            "value_ref-backed fills; user input may be required."
        )
    else:
        known = {r for r in available_references}
        # Record which families exist (names only — never values).
        families = sorted({r.split(".", 1)[0] for r in known if "." in r})
        questions.append(
            f"Available reference families: {', '.join(families) or 'none'} "
            f"({len(known)} refs)."
        )

    return ParsedGoal(
        goal=goal,
        unresolved_questions=questions,
        multi_step_hint=multi_step,
    )
