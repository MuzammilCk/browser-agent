"""Strict decision parsing — Phase 4 (user instruction: schema validation).

The model's JSON output is untrusted data (docs/SECURITY_MODEL.md). This
module converts it into an AgentDecision through fixed, deterministic
steps — never guessing:

    raw dict
      → ReasonerDecisionSchema (strict pydantic, extra=forbid)
      → decision_type allow-list
      → tool_name known? (fail closed on unknown tools HERE, before the
        registry — the registry re-checks anyway: defense in depth)
      → browser action dict → typed BrowserAction (pydantic validators:
        sensitive-literal policy, required-field combinations)
      → AgentDecision (its own model validators run again)

Any failure returns a machine-readable (code, detail) pair that the
reasoner feeds back to the model on repair attempts and, once retries
are exhausted, turns into an explicit MODEL_FAILURE.

Note on observation_id: for browser mutation actions the parser stamps
the CURRENT authoritative observation id onto the action. This does not
weaken any gate — it is exactly what the executor's stale-ref guard
checks (targets must bind to the fresh observation), applied
deterministically by the runtime instead of trusting the model to copy
it. Refs themselves still must exist in that observation (registry +
executor verify).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.agent.reasoning.protocol import (
    ALLOWED_DECISION_TYPES,
    DECISION_SCHEMA_INVALID,
    DECISION_VALIDATION_FAILED,
    ReasonerDecisionSchema,
)
from app.agent.runtime.decision import AgentDecision, AgentDecisionType
from app.models.actions import BrowserAction

# Deterministic aliases: some models echo the TOOL name in the action
# literal. Mapping tool name → primitive action is a fixed table, not a
# guess; anything else is rejected.
_ACTION_ALIASES: dict[str, str] = {
    "fill_field": "fill",
    "select_option": "select",
    "check_control": "check",
    "uncheck_control": "uncheck",
    "upload_document": "upload",
    "press_key": "press",
}


def parse_model_decision(
    raw: Any,
    *,
    known_tools: frozenset[str] | set[str],
    action_tools: frozenset[str] | set[str],
    observation_id: str = "",
) -> tuple[AgentDecision | None, tuple[str, str] | None]:
    """Parse and validate one model decision.

    Returns (decision, None) on success, or (None, (code, detail)) on
    any rejection. Never raises, never guesses.
    """
    if not isinstance(raw, dict):
        return None, (
            DECISION_SCHEMA_INVALID,
            f"model output must be a JSON object, got {type(raw).__name__}",
        )

    # 1. Strict schema (forbids unknown/prompt-injected fields).
    try:
        candidate = ReasonerDecisionSchema.model_validate(raw)
    except ValidationError as e:
        return None, (DECISION_SCHEMA_INVALID, _format_validation_error(e))

    # 2. Decision-type allow-list (HANDOFF reserved for Phase 10).
    if candidate.decision_type not in ALLOWED_DECISION_TYPES:
        return None, (
            DECISION_SCHEMA_INVALID,
            f"unknown decision_type '{candidate.decision_type}' "
            f"(allowed: {sorted(ALLOWED_DECISION_TYPES)})",
        )

    decision_type = AgentDecisionType(candidate.decision_type)

    # 3. TOOL_CALL: tool must exist and carry a well-formed action.
    action: BrowserAction | None = None
    if decision_type is AgentDecisionType.TOOL_CALL:
        if not candidate.tool_name:
            return None, (
                DECISION_VALIDATION_FAILED,
                "tool_call requires a tool_name",
            )
        if candidate.tool_name not in known_tools:
            return None, (
                DECISION_VALIDATION_FAILED,
                f"unknown tool '{candidate.tool_name}'",
            )
        if candidate.tool_name in action_tools:
            action, failure = _parse_browser_action(candidate, observation_id)
            if failure is not None:
                return None, failure
        elif candidate.action is not None:
            return None, (
                DECISION_VALIDATION_FAILED,
                f"tool '{candidate.tool_name}' does not accept an action object",
            )

    # 4. AgentDecision boundary (its validators re-check per-type fields).
    try:
        decision = AgentDecision(
            decision_type=decision_type,
            tool_name=candidate.tool_name,
            arguments=dict(candidate.arguments),
            action=action,
            reason=candidate.reason,
            question=candidate.question,
            plan=list(candidate.plan),
            confidence=candidate.confidence,
        )
    except ValidationError as e:
        return None, (DECISION_VALIDATION_FAILED, _format_validation_error(e))

    return decision, None


def _parse_browser_action(
    candidate: ReasonerDecisionSchema,
    observation_id: str,
) -> tuple[BrowserAction | None, tuple[str, str] | None]:
    """Convert the model's action dict into a typed BrowserAction."""
    if not isinstance(candidate.action, dict) or not candidate.action:
        return None, (
            DECISION_VALIDATION_FAILED,
            f"tool '{candidate.tool_name}' requires an action object "
            "(action, target_ref, ...)",
        )
    action_data = dict(candidate.action)

    # Normalize the action literal (fixed alias table; else reject).
    raw_action = action_data.get("action")
    if isinstance(raw_action, str):
        action_data["action"] = _ACTION_ALIASES.get(raw_action, raw_action)

    # Stamp the CURRENT authoritative observation id (stale-ref binding).
    if observation_id:
        action_data["observation_id"] = observation_id

    try:
        return BrowserAction(**action_data), None
    except ValidationError as e:
        return None, (DECISION_VALIDATION_FAILED, _format_validation_error(e))


def _format_validation_error(error: ValidationError) -> str:
    """Compact, model-readable validation error summary."""
    parts: list[str] = []
    for item in error.errors()[:5]:
        loc = ".".join(str(part) for part in item.get("loc", ())) or "<root>"
        parts.append(f"{loc}: {item.get('msg', 'invalid')}")
    return "; ".join(parts)
