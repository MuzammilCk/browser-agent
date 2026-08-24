"""Action planner — LLM-based and deterministic action selection.

Extracted from runner.py per software-architecture skill:
files < 200 lines, single responsibility.

Two strategies:
1. LLM-based planning via OpenRouter structured output
2. Deterministic fallback (no LLM needed)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.field_mapper_models import MappingResult
from app.browser.observer import PageObservation
from app.llm.base import LLMGateway
from app.llm.sanitizer import PromptSanitizer
from app.models.actions import BrowserAction
from app.models.workflow_state import WorkflowState

logger = logging.getLogger(__name__)

# ─── Action schema for LLM structured output ───────────────────

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "fill", "click", "select", "check", "uncheck",
                "scroll_to", "press", "wait", "stop",
                "request_user_action",
            ],
        },
        "target_ref": {"type": "string"},
        "value_ref": {"type": "string"},
        "literal_value": {"type": "string"},
        "option": {"type": "string"},
        "key": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["action"],
}


_sanitizer = PromptSanitizer()


def _build_elements_info(observation: PageObservation) -> list[dict]:
    """Extract element info for LLM context (sanitized)."""
    raw = []
    for el in observation.page_state.elements:
        if el.role in (
            "textbox", "combobox", "radiogroup",
            "checkbox", "button", "link",
        ):
            raw.append({
                "ref": el.ref,
                "role": el.role,
                "name": el.accessible_name or el.label_text or "",
                "value": el.value or "",
                "required": el.required,
                "disabled": el.disabled,
            })
    return _sanitizer.sanitize_elements(raw)


def _build_bindings_info(mapping_result: MappingResult) -> list[dict]:
    """Extract binding info for LLM context."""
    return [
        {"ref": b.field_ref, "binding": b.binding, "confidence": b.confidence.value}
        for b in mapping_result.bindings
    ]


def _build_pending_fields(
    mapping_result: MappingResult, completed: list[str],
) -> list[str]:
    """Get pending field refs with high/medium confidence."""
    return [
        b.field_ref for b in mapping_result.bindings
        if b.field_ref not in completed
        and b.binding is not None
        and b.confidence.value in ("high", "medium")
    ]


def _parse_llm_action(
    action_data: dict, observation_id: str,
) -> BrowserAction | None:
    """Parse LLM JSON response into a BrowserAction."""
    action_type = action_data.get("action", "stop")

    if action_type == "stop":
        return None

    if action_type == "request_user_action":
        return BrowserAction(
            action="request_user_action",
            reason=action_data.get("reason", "LLM requested user action"),
        )

    kwargs: dict[str, Any] = {"action": action_type}

    for field in ("target_ref", "value_ref", "literal_value", "option", "key"):
        if action_data.get(field):
            kwargs[field] = action_data[field]

    if action_data.get("confidence") is not None:
        kwargs["confidence"] = action_data["confidence"]

    kwargs["observation_id"] = observation_id
    return BrowserAction(**kwargs)


async def plan_with_llm(
    llm: LLMGateway,
    workflow: WorkflowState,
    observation: PageObservation,
    mapping_result: MappingResult,
) -> BrowserAction | None:
    """Use LLM to plan the next action.

    Builds context from observation + mappings, sends to LLM,
    parses structured JSON response into BrowserAction.
    """
    page_state = observation.page_state
    completed = workflow.completed_bindings

    elements_info = _build_elements_info(observation)
    bindings_info = _build_bindings_info(mapping_result)
    pending = _build_pending_fields(mapping_result, completed)

    system_prompt = f"""You are a government form-filling browser agent.

TASK: {workflow.task_description or 'Fill the form on the current page'}

RULES:
1. Take ONE action at a time.
2. Fill fields in order from top to bottom.
3. Use value_ref (e.g., USER.full_name) for sensitive fields.
4. Use literal_value only for non-sensitive PUBLIC fields.
5. After filling all fields, click the submit/next button.
6. If you see CAPTCHA/OTP/password, stop and request user action.
7. Never guess values — use only provided bindings.
8. Output ONLY valid JSON."""

    user_prompt = f"""Current page: {page_state.url}
Page type: {page_state.page_type}
Title: {page_state.title}

Elements:
{json.dumps(elements_info[:20], indent=2)}

Field bindings:
{json.dumps(bindings_info[:20], indent=2)}

Completed fields: {completed}
Pending fields: {pending[:10]}
Unmapped fields: {workflow.unmapped_fields[:10]}

What is the next action?"""

    try:
        response = await llm.complete(
            system=system_prompt,
            user=user_prompt,
            schema=ACTION_SCHEMA,
            temperature=0.0,
        )

        if response.parsed:
            return _parse_llm_action(response.parsed, observation.observation_id)

    except Exception as e:
        logger.warning("LLM planning failed: %s", e)

    return None


def plan_deterministic(
    workflow: WorkflowState,
    observation: PageObservation,
    mapping_result: MappingResult,
) -> BrowserAction | None:
    """Deterministic planning fallback — no LLM needed.

    Strategy: fill HIGH-confidence fields in order, then click submit.
    """
    page_state = observation.page_state
    obs_id = observation.observation_id

    for binding in mapping_result.bindings:
        if binding.field_ref in workflow.completed_bindings:
            continue
        if binding.confidence.value != "high" or not binding.binding:
            continue

        if binding.field_type == "textbox":
            return BrowserAction(
                action="fill",
                target_ref=binding.field_ref,
                value_ref=binding.binding,
                observation_id=obs_id,
            )

        if binding.field_type == "combobox":
            for el in page_state.elements:
                if el.ref == binding.field_ref and el.selected_options:
                    return BrowserAction(
                        action="select",
                        target_ref=binding.field_ref,
                        option=el.selected_options[0],
                        observation_id=obs_id,
                    )

        if binding.field_type == "checkbox":
            return BrowserAction(
                action="check",
                target_ref=binding.field_ref,
                observation_id=obs_id,
            )

    # Look for submit/next button
    for el in page_state.elements:
        if el.role == "button" and el.accessible_name:
            name = el.accessible_name.lower()
            if any(kw in name for kw in ("submit", "next", "apply", "save")):
                return BrowserAction(
                    action="click",
                    target_ref=el.ref,
                    observation_id=obs_id,
                )

    return None
