"""Minimal context assembler — Phase 4 (implementation_plan.md).

Assembles the structured reasoning context the model receives each
iteration. Minimality and safety rules (user instruction, Phase 4):

- BOUNDED: element cap, visible-text cap, recent-results cap. The full
  DOM, conversation transcript, or repository is never dumped.
- SECRET-FREE: sensitive data crosses as semantic references
  (USER.full_name, DOCUMENT.aadhaar). This module never opens the vault
  and never formats raw values into the prompt.
- OBSERVATION IS AUTHORITATIVE: the page section is serialized from the
  fresh PageObservation (AGENTS.md rule 4) — the model never invents or
  carries over browser state between iterations.
- POLICY INTERNALS STAY OUT: tool schemas describe what a tool does and
  its descriptive policy_class; the authoritative PolicyEngine rules,
  decision thresholds and internals are never exposed.

Sections per user instruction (exactly these, nothing more):
goal, current subgoal, plan state, latest verified WorldState, current
page observation, tool schemas, unresolved questions, recent ToolResults,
safety/runtime constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.agent.registry import ReferenceRegistry, get_registry
from app.agent.tools.base import ToolMetadata, ToolResult
from app.browser.observer import PageObservation
from app.models.workflow_state import WorkflowState

# ── Bounds (kept deliberately small: minimal context, minimal cost) ──
MAX_ELEMENTS = 60
MAX_RECENT_RESULTS = 5
MAX_PLAN_STEPS = 15
MAX_VISIBLE_TEXT_CHARS = 1500
MAX_VALUE_SNIPPET = 40

# Runtime constraints injected verbatim into every prompt. These restate
# non-negotiable AGENTS.md rules so the model cannot claim ignorance —
# but the runtime enforces them regardless of what the model says
# (policy is deterministic, not prompt-enforced).
RUNTIME_CONSTRAINTS: tuple[str, ...] = (
    "You PROPOSE actions only; the deterministic runtime authorizes and executes them.",
    "Emit exactly one decision per iteration as the specified JSON.",
    "Target refs are ephemeral: use refs from the CURRENT observation only.",
    "Sensitive values must use semantic references (e.g. USER.aadhaar_number, "
    "DOCUMENT.aadhaar) — never literal values.",
    "CAPTCHA, OTP, login, password/PIN, payment and final submission are human "
    "checkpoints: choose ask_user instead of attempting them.",
    "Do not invent browser state; if unsure, choose observe_page first.",
)

# Tool payload keys that are safe to show the model on success. A
# key-based whitelist (NOT a type-based filter) is deliberate: value-
# bearing keys like `resolved_value` must never reach the prompt no
# matter what type they carry (docs/SECURITY_MODEL.md).
_TOOL_PAYLOAD_SAFE_KEYS = frozenset({
    "executor_message", "refreshed_observation", "tab_switched",
    "url", "page_type", "found", "options", "selected",
    "resolvable", "sensitivity", "display_name", "resolution_hint",
})


@dataclass
class ReasoningContext:
    """One assembled, bounded, prompt-safe reasoning context."""

    system_prompt: str
    context_payload: dict
    element_count: int = 0
    truncated: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Deterministic JSON serialization for the model-facing message."""
        return json.dumps(self.context_payload, indent=2, sort_keys=True)


def _ref_registry() -> ReferenceRegistry:
    return get_registry()


def _describe_ref(ref: str) -> str:
    """Human-readable, safe description of a semantic reference."""
    registry = _ref_registry()
    definition = registry.get(ref)
    if definition is None:
        return ref
    sensitivity = registry.get_sensitivity(ref)
    return f"{ref} ({definition.description}; sensitivity: {sensitivity.value})"


def _available_references() -> list[str]:
    """The semantic references the model may use — names only, no values."""
    registry = _ref_registry()
    return sorted(registry.get_all_refs(visible_only=True).keys())


def _element_lines(observation: PageObservation) -> list[dict]:
    """Compact model-facing element list from the AUTHORITATIVE observation."""
    elements = [
        el for el in observation.page_state.elements
        if el.visible
    ][:MAX_ELEMENTS]
    lines: list[dict] = []
    for el in elements:
        value = el.value
        if value:
            # Values on the page are shown only as short previews; vault
            # values never reach the observation in raw form anyway, but
            # keep the cap as defense in depth.
            value = value[:MAX_VALUE_SNIPPET]
        lines.append({
            "ref": el.ref,
            "role": el.role,
            "name": el.name,
            "html_name": el.html_name,
            "value": value,
            "required": el.required,
            "disabled": el.disabled,
            "checked": el.checked,
            "selected": el.selected_options or None,
            "input_type": el.input_type,
            "frame": el.frame_id,
        })
    return lines


def _page_section(observation: PageObservation) -> dict:
    ps = observation.page_state
    auth = ps.authentication
    visible_text = (observation.visible_text or "")[:MAX_VISIBLE_TEXT_CHARS]
    return {
        "url": ps.url,
        "title": ps.title,
        "page_type": ps.page_type,
        "observation_id": observation.observation_id,
        "open_tabs": ps.tabs.total,
        "auth_challenge": (
            auth.challenge_type if auth.detected else None
        ),
        "elements": _element_lines(observation),
        "validation_errors": [
            f"{v.target_ref}: {v.message}"
            for v in ps.validation_errors if v.visible
        ],
        "alerts": [a.text or a.name or a.ref for a in ps.alerts if a.visible],
        "visible_text": visible_text or None,
    }


def _plan_section(state: WorkflowState, plan: list[dict], subgoal: str) -> dict:
    return {
        "current_subgoal": subgoal,
        "plan": [
            {k: step.get(k) for k in ("id", "title", "status") if k in step}
            for step in plan[:MAX_PLAN_STEPS]
        ],
        "completed_bindings": len(state.completed_bindings),
        "pending_fields": len(state.pending_fields),
        "unmapped_fields": len(state.unmapped_fields),
        "ambiguous_fields": len(state.ambiguous_fields),
    }


def _result_section(results: list[ToolResult]) -> list[dict]:
    """Recent ToolResults — safe metadata only, capped."""
    section: list[dict] = []
    for result in results[-MAX_RECENT_RESULTS:]:
        payload = {
            "tool": result.tool_name,
            "success": result.success,
            "error_code": result.error_code,
            "message": result.message[:300],
            "verification": result.verification_status,
        }
        if result.success:
            # Only explicitly whitelisted keys cross over, and only when
            # scalar — defense in depth against value-bearing keys.
            safe_payload = {
                k: v for k, v in result.payload.items()
                if k in _TOOL_PAYLOAD_SAFE_KEYS
                and isinstance(v, (str, int, float, bool))
            }
            payload["result"] = safe_payload
        section.append(payload)
    return section


def _tool_catalog(tools: list[ToolMetadata]) -> list[dict]:
    return [tool.model_catalog_entry() for tool in tools]


def _system_prompt(constraints: tuple[str, ...]) -> str:
    constraint_lines = "\n".join(f"- {c}" for c in constraints)
    return f"""You are the decision-making controller of a browser agent that helps \
citizens complete Indian government-service forms.

Each iteration you receive a JSON context describing the current goal, \
verified workflow state, the authoritative browser observation, and the \
available typed tools. You respond with EXACTLY ONE JSON object choosing \
the next decision:

- tool_call: choose ONE registered tool by name. Browser mutation tools \
(click, fill_field, select_option, check_control, uncheck_control, \
upload_document, scroll, press_key, go_back) additionally require an \
"action" object with a target_ref taken from the CURRENT observation, and \
observation_id copied from the observation. fill_field takes either \
literal_value (non-sensitive only) or value_ref (semantic reference). \
upload_document takes document_ref in the action.
- replan: propose a new plan (plan: [{{id, title, status}}]) with a reason.
- reflect: record what you learned (reason required).
- ask_user: ask the human to handle something (question required). This is \
the ONLY way past CAPTCHA/OTP/login/payment/final submission.
- complete: declare the goal met (reason required). Never declare complete \
while required fields are pending or validation errors are visible.

Hard rules:
{constraint_lines}

Your output is validated against a strict schema; unknown fields, unknown \
tools, or malformed actions are rejected and reported back to you as \
failures. You never see or provide raw secrets — only semantic references."""


def build_reasoning_context(
    *,
    goal: str,
    subgoal: str = "",
    plan: list[dict] | None = None,
    workflow: WorkflowState | None = None,
    observation: PageObservation | None = None,
    tool_metadata: list[ToolMetadata],
    recent_results: list[ToolResult] | None = None,
    unresolved_questions: list[str] | None = None,
    retrieved_memories: dict | None = None,
    working_memory_summary: str | None = None,
) -> ReasoningContext:
    """Assemble the bounded reasoning context for one model call.

    Every section is derived from deterministic state the runtime owns;
    nothing is accepted from the model, and no secret-bearing source is
    read.
    """
    workflow = workflow or WorkflowState()
    plan = plan or []
    recent_results = recent_results or []
    unresolved_questions = unresolved_questions or []

    context_payload: dict = {
        "goal": goal,
        "plan_state": _plan_section(workflow, plan, subgoal),
        "world_state": {
            "status": workflow.status.value,
            "workflow_id": workflow.workflow_id,
            "authentication_state": workflow.authentication_state,
            "submission_state": workflow.submission_state,
            "error_state": workflow.error_state,
            "total_actions": workflow.total_actions,
            "successful_actions": workflow.successful_actions,
            "failed_actions": workflow.failed_actions,
        },
        "page_observation": (
            _page_section(observation) if observation is not None
            else None
        ),
        "available_references": _available_references(),
        "available_references_note": (
            "Values are resolved locally at execution time. Use these refs "
            "as value_ref / document_ref. Descriptions only — never values."
        ),
        "tools": _tool_catalog(tool_metadata),
        "recent_tool_results": _result_section(recent_results),
        "unresolved_questions": unresolved_questions,
        "runtime_constraints": list(RUNTIME_CONSTRAINTS),
    }

    if retrieved_memories:
        context_payload["retrieved_memories"] = retrieved_memories
    if working_memory_summary:
        context_payload["compacted_history"] = working_memory_summary

    truncated: list[str] = []
    if observation is not None:
        visible_elements = [
            el for el in observation.page_state.elements if el.visible
        ]
        if len(visible_elements) > MAX_ELEMENTS:
            truncated.append(
                f"elements capped at {MAX_ELEMENTS}/{len(visible_elements)}"
            )
    if len(recent_results) > MAX_RECENT_RESULTS:
        truncated.append(
            f"recent results capped at {MAX_RECENT_RESULTS}/{len(recent_results)}"
        )

    return ReasoningContext(
        system_prompt=_system_prompt(RUNTIME_CONSTRAINTS),
        context_payload=context_payload,
        element_count=len(context_payload["page_observation"]["elements"])
        if context_payload["page_observation"] else 0,
        truncated=truncated,
    )
