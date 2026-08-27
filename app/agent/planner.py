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
import re
from typing import Any

from app.agent.field_mapper_models import MappingResult
from app.agent.planning_result import (
    ActionPlanned, NoValidAction, PlanLLMError, PlanOutcome, TaskComplete,
)
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

# Upper bound on elements sent to the LLM. Portals commonly expose 100+
# interactive elements on their landing pages; truncating to the first few
# hides the link/button the task targets and makes the planner stop with
# "no action" despite the element being present on the page.
_MAX_ELEMENTS_FOR_LLM = 120

# Words too generic to score element relevance by (audit Z4).
_TASK_STOPWORDS = frozenset(
    """a an and are as at be been being by for from had has have how i in
    into is it its me my not of on onto or our so than that the their them
    then there these this those to was we were what when where which who
    will with without you your do does did done can could should would""".split(),
)


def _task_keywords(task: str) -> set[str]:
    """Extract meaningful lowercase tokens from the task description."""
    return {
        w for w in re.findall(r"[a-z0-9]+", (task or "").lower())
        if len(w) > 1 and w not in _TASK_STOPWORDS
    }


def _element_relevance(el: dict, keywords: set[str]) -> int:
    """Token overlap between an element's name and the task keywords."""
    if not keywords:
        return 0
    tokens = set(re.findall(r"[a-z0-9]+", (el.get("name") or "").lower()))
    return len(tokens & keywords)


def _select_elements_for_llm(
    elements_info: list[dict],
    keywords: set[str],
    *,
    protected_refs: set[str] | None = None,
) -> tuple[list[dict], bool]:
    """Relevance-ranked selection of the LLM element context (audit Z4).

    Replaces flat DOM-order truncation: elements overlapping the task
    keywords rank first, in-progress binding targets are always retained
    regardless of rank, remaining slots are filled in DOM order, and the
    memory/token cap is preserved. Returned list keeps DOM order for a
    stable, readable prompt.
    """
    protected = protected_refs or set()
    if len(elements_info) <= _MAX_ELEMENTS_FOR_LLM:
        return elements_info, False

    scored = [
        (
            -_element_relevance(el, keywords),   # higher overlap first
            0 if el.get("ref") in protected else 1,  # bound fields survive ties
            idx,
            el,
        )
        for idx, el in enumerate(elements_info)
    ]
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    chosen = sorted(scored[:_MAX_ELEMENTS_FOR_LLM], key=lambda t: t[2])
    return [el for _, _, _, el in chosen], True


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
    action_data: dict, observation_id: str, page_type: str,
) -> PlanOutcome:
    """Parse LLM JSON response into a typed PlanOutcome."""
    action_type = action_data.get("action", "stop")

    if action_type == "stop":
        reason = action_data.get("reason") or "planner decided no further action"
        # Deliberate stop on a success page is a completion claim; anywhere
        # else it is "nothing more to do from here" (runner dispatches both).
        if page_type == "success":
            return TaskComplete(reason=reason)
        return NoValidAction(reason=reason)

    if action_type == "request_user_action":
        return ActionPlanned(BrowserAction(
            action="request_user_action",
            reason=action_data.get("reason", "LLM requested user action"),
        ))

    kwargs: dict[str, Any] = {"action": action_type}

    for field in ("target_ref", "value_ref", "literal_value", "option", "key"):
        if action_data.get(field):
            kwargs[field] = action_data[field]

    if action_data.get("confidence") is not None:
        kwargs["confidence"] = action_data["confidence"]

    kwargs["observation_id"] = observation_id
    return ActionPlanned(BrowserAction(**kwargs))


async def plan_with_llm(
    llm: LLMGateway,
    workflow: WorkflowState,
    observation: PageObservation,
    mapping_result: MappingResult,
) -> PlanOutcome:
    """Use LLM to plan the next action.

    Builds context from observation + mappings, sends to LLM,
    parses structured JSON response into a typed PlanOutcome.
    A transport failure or an unparseable structured response is
    surfaced as PlanLLMError — never silently treated as "no action".
    """
    page_state = observation.page_state
    completed = workflow.completed_bindings

    elements_info = _build_elements_info(observation)
    bindings_info = _build_bindings_info(mapping_result)
    pending = _build_pending_fields(mapping_result, completed)

    # Ranked selection (audit Z4): keep task-relevant elements and bound
    # fields instead of truncating by raw DOM position.
    visible_elements, truncated = _select_elements_for_llm(
        elements_info,
        _task_keywords(workflow.task_description),
        protected_refs={b["ref"] for b in bindings_info},
    )

    system_prompt = f"""You are a government portal browser agent.

TASK: {workflow.task_description or 'Fill the form on the current page'}

RULES:
1. Take ONE action at a time.
2. If the task requires reaching another page (e.g. "Click 'Download Aadhaar'"),
   click the link or button whose name matches the task. Use the exact ref.
3. Fill fields in order from top to bottom.
4. Use value_ref (e.g., USER.full_name) for sensitive fields.
5. Use literal_value only for non-sensitive PUBLIC fields.
6. After filling all fields, click the submit/next button.
7. If you see CAPTCHA/OTP/password, stop and request user action.
8. Never guess values — use only provided bindings.
9. Only choose "stop" when the task is complete or genuinely impossible
   from this page. Do NOT stop merely because the target is not in the
   visible list — prefer scroll_to or the closest matching element.
10. Output ONLY valid JSON."""

    user_prompt = f"""Current page: {page_state.url}
Page type: {page_state.page_type}
Title: {page_state.title}
Interactive elements on page: {len(elements_info)}{'; list truncated to top ' + str(_MAX_ELEMENTS_FOR_LLM) + ' by task relevance' if truncated else ''}

Elements (ref, role, name — match task keywords against "name"):
{json.dumps(visible_elements, indent=2)}

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

        if response.parsed is not None:
            return _parse_llm_action(
                response.parsed, observation.observation_id,
                page_state.page_type,
            )

        # Schema was requested but the content is missing or non-JSON
        # (fenced markdown, trailing prose, truncation). This is a real
        # failure — surface it instead of degrading to "no action" (Z5).
        content = (response.content or "").strip()
        return PlanLLMError(
            message=(
                "unparseable structured LLM response "
                f"(finish_reason={response.finish_reason!r}, "
                f"{len(content)} chars of non-JSON content)"
            ),
        )

    except Exception as e:
        logger.warning("LLM planning failed: %s", e)
        return PlanLLMError(message=str(e))


def plan_deterministic(
    workflow: WorkflowState,
    observation: PageObservation,
    mapping_result: MappingResult,
    value_resolver=None,
) -> PlanOutcome:
    """Deterministic planning fallback — no LLM needed.

    Strategy: fill HIGH-confidence fields in order, then click submit.

    Audit C4 fix: combobox selections resolve the bound reference through
    the ValueResolver (vault) instead of re-selecting whatever is already
    selected; checkboxes only act when their current state differs;
    fields already holding the correct value are skipped rather than
    replayed into UNCERTAIN verification loops.
    """
    page_state = observation.page_state
    obs_id = observation.observation_id

    def _resolve(ref: str) -> str | None:
        if value_resolver is None:
            return None
        return value_resolver.resolve(ref)

    for binding in mapping_result.bindings:
        if binding.field_ref in workflow.completed_bindings:
            continue
        if binding.confidence.value != "high" or not binding.binding:
            continue

        element = next(
            (el for el in page_state.elements if el.ref == binding.field_ref),
            None,
        )

        if binding.field_type == "textbox":
            desired = _resolve(binding.binding)
            if not desired:
                continue
            # Already holds the right value → nothing to do
            if element is not None and (element.value or "").strip() == desired.strip():
                continue
            return ActionPlanned(BrowserAction(
                action="fill",
                target_ref=binding.field_ref,
                value_ref=binding.binding,
                observation_id=obs_id,
            ))

        if binding.field_type == "combobox":
            desired = _resolve(binding.binding)
            if not desired:
                continue
            # Already showing the desired option → nothing to do
            if element is not None and element.selected_options:
                current = element.selected_options[0].strip()
                if current == desired.strip():
                    continue
            return ActionPlanned(BrowserAction(
                action="select",
                target_ref=binding.field_ref,
                option=desired,
                observation_id=obs_id,
            ))

        if binding.field_type == "checkbox":
            # Only check when currently unchecked; a checked box is done
            if element is not None and element.checked:
                continue
            return ActionPlanned(BrowserAction(
                action="check",
                target_ref=binding.field_ref,
                observation_id=obs_id,
            ))

    # Look for submit/next button
    for el in page_state.elements:
        if el.role == "button" and el.accessible_name:
            name = el.accessible_name.lower()
            if any(kw in name for kw in ("submit", "next", "apply", "save")):
                return ActionPlanned(BrowserAction(
                    action="click",
                    target_ref=el.ref,
                    observation_id=obs_id,
                ))

    return NoValidAction(
        reason=(
            "deterministic planner exhausted: no uncompleted high-confidence "
            "binding resolved to a value and no submit/next button found"
        ),
    )
