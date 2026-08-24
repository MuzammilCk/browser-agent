"""Agent runner — the core workflow orchestrator.

Per audit issues #25, #26, #28, #43:
- Implements the full loop: observe → map → plan → policy → execute → verify → repeat
- Owns WorkflowState across page transitions
- Integrates FieldMapper, PolicyEngine, BrowserExecutor, LLM
- Recovery logic with bounded retries
- User checkpoints for CAPTCHA/OTP/payment

Architecture:
    User Task
        ↓
    AgentRunner
        ├── BrowserManager (Playwright)
        ├── PageObserver (perception)
        ├── FieldMapper (field mapping)
        ├── LLMGateway (reasoning)
        ├── PolicyEngine (safety)
        ├── BrowserExecutor (execution)
        └── ActionVerifier (verification)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.field_mapper import FieldMapper
from app.agent.field_mapper_models import MappingResult
from app.agent.registry import ReferenceRegistry, get_registry
from app.browser.executor import ActionResult, BrowserExecutor
from app.browser.observer import PageObservation, PageObserver
from app.llm.base import LLMGateway
from app.models.actions import BrowserAction
from app.models.page_state import PageState
from app.models.workflow_state import (
    ActionRecord,
    WorkflowState,
    WorkflowStatus,
)
from app.policy.engine import PolicyDecision, PolicyEngine

logger = logging.getLogger(__name__)


class AgentRunner:
    """The core workflow orchestrator.

    Implements the full observe → map → plan → policy → execute → verify loop.

    Usage:
        runner = AgentRunner(llm=llm_gateway)
        result = await runner.run(
            page=page,
            task="Fill the scholarship application form",
        )
    """

    def __init__(
        self,
        llm: LLMGateway | None = None,
        policy_engine: PolicyEngine | None = None,
        registry: ReferenceRegistry | None = None,
        max_iterations: int = 50,
    ) -> None:
        self._llm = llm
        self._policy = policy_engine or PolicyEngine()
        self._registry = registry or get_registry()
        self._observer = PageObserver()
        self._mapper = FieldMapper(llm_gateway=llm, registry=self._registry)
        self._executor = BrowserExecutor(policy_engine=self._policy)
        self._max_iterations = max_iterations

    async def run(
        self,
        page: Any,
        task: str = "",
        domain: str = "",
    ) -> WorkflowState:
        """Run the full agent loop.

        Args:
            page: Playwright Page object
            task: User's task description
            domain: Target domain

        Returns:
            Final WorkflowState with all results
        """
        # Initialize workflow
        workflow = WorkflowState(
            workflow_id=str(uuid.uuid4())[:8],
            domain=domain,
            task_description=task,
            status=WorkflowStatus.RUNNING,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info("Starting workflow %s: %s", workflow.workflow_id, task)

        try:
            iteration = 0
            while iteration < self._max_iterations:
                iteration += 1
                logger.info("=== Iteration %d ===", iteration)

                # ─── 1. OBSERVE ──────────────────────────────────
                observation = await self._observer.observe(page)
                workflow.current_observation_id = observation.observation_id
                workflow.current_url = observation.page_state.url
                workflow.current_page_type = observation.page_state.page_type

                logger.info(
                    "Observed: %d elements, page_type=%s, url=%s",
                    len(observation.page_state.elements),
                    observation.page_state.page_type,
                    observation.page_state.url[:80],
                )

                # ─── 2. CHECK AUTHENTICATION ─────────────────────
                auth = observation.page_state.authentication
                if auth.detected:
                    auth_type = auth.challenge_type or "unknown"
                    workflow.authentication_state = "detected"
                    workflow.add_checkpoint(auth_type)
                    workflow.status = WorkflowStatus.WAITING_FOR_AUTH

                    logger.warning(
                        "Authentication detected: %s (confidence: %d%%)",
                        auth_type, int(auth.confidence * 100),
                    )

                    # Request user action
                    return workflow

                # ─── 3. MAP FIELDS ──────────────────────────────
                mapping_result = await self._mapper.map_fields(observation)
                workflow.unmapped_fields = mapping_result.unmapped_fields
                workflow.ambiguous_fields = mapping_result.ambiguous_fields

                logger.info(
                    "Mapped: %d bindings, %d unmapped, %d ambiguous",
                    mapping_result.mapped_count,
                    len(mapping_result.unmapped_fields),
                    len(mapping_result.ambiguous_fields),
                )

                # ─── 4. PLAN NEXT ACTION ────────────────────────
                action = await self._plan_action(
                    workflow, observation, mapping_result
                )

                if action is None:
                    # No action needed — workflow complete or stuck
                    if not mapping_result.unmapped_fields:
                        workflow.status = WorkflowStatus.READY_FOR_SUBMISSION
                        logger.info("All fields mapped, ready for submission")
                    else:
                        workflow.status = WorkflowStatus.WAITING_FOR_USER
                        workflow.set_error(
                            "user_required",
                            f"Cannot map {len(mapping_result.unmapped_fields)} fields",
                        )
                    break

                # ─── 5. POLICY CHECK ────────────────────────────
                policy_result = self._policy.evaluate(
                    action, observation.page_state
                )

                if policy_result.blocked:
                    logger.warning("Policy DENIED: %s", policy_result.reason)
                    workflow.set_error("user_required", policy_result.reason)
                    workflow.status = WorkflowStatus.WAITING_FOR_USER
                    break

                if policy_result.needs_user:
                    logger.warning("Policy PAUSE: %s", policy_result.reason)
                    workflow.add_checkpoint(policy_result.reason)
                    workflow.status = WorkflowStatus.WAITING_FOR_USER
                    break

                if policy_result.needs_confirmation:
                    workflow.status = WorkflowStatus.READY_FOR_CONFIRMATION
                    logger.warning("Policy CONFIRM: %s", policy_result.reason)
                    # For now, proceed — Phase C confirmation UI comes later

                # ─── 6. EXECUTE ─────────────────────────────────
                result = await self._executor.execute(page, action, observation)

                # ─── 7. RECORD ──────────────────────────────────
                record = ActionRecord(
                    action_type=action.action,
                    target_ref=action.target_ref,
                    binding=action.value_ref or action.document_ref or "",
                    success=result.success,
                    verification_status=(
                        result.verification.status.value
                        if result.verification else ""
                    ),
                    policy_decision=policy_result.decision.value,
                    message=result.message,
                    observation_id=observation.observation_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                workflow.record_action(record)

                logger.info(
                    "Action %s: success=%s, verification=%s, message=%s",
                    action.action,
                    result.success,
                    record.verification_status,
                    result.message[:100],
                )

                # ─── 8. HANDLE RESULT ───────────────────────────
                if result.user_action_required:
                    workflow.status = WorkflowStatus.WAITING_FOR_USER
                    workflow.add_checkpoint(result.message)
                    break

                if not result.success:
                    workflow.failed_actions += 1

                    if result.recovery_required:
                        if workflow.can_retry():
                            workflow.increment_recovery()
                            logger.info(
                                "Recovery attempt %d/%d",
                                workflow.recovery_attempts,
                                workflow.max_recovery_attempts,
                            )
                            continue  # Re-observe and try again
                        else:
                            workflow.status = WorkflowStatus.FAILED
                            workflow.set_error("fatal", result.message)
                            break

                # Success — reset recovery counter
                workflow.reset_recovery()

                # Use post_observation for next iteration
                if result.post_observation:
                    observation = result.post_observation

            else:
                # Max iterations reached
                workflow.status = WorkflowStatus.FAILED
                workflow.set_error("fatal", f"Max iterations ({self._max_iterations}) reached")

        except Exception as e:
            logger.error("Workflow failed: %s", e, exc_info=True)
            workflow.status = WorkflowStatus.FAILED
            workflow.set_error("fatal", str(e))

        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("Workflow %s finished: %s", workflow.workflow_id, workflow.status.value)
        return workflow

    async def _plan_action(
        self,
        workflow: WorkflowState,
        observation: PageObservation,
        mapping_result: MappingResult,
    ) -> BrowserAction | None:
        """Plan the next action based on current state.

        This is the "reasoning" step — either uses LLM or deterministic rules.
        """
        # If we have an LLM, use it for planning
        if self._llm:
            return await self._plan_with_llm(workflow, observation, mapping_result)

        # Deterministic planning fallback
        return self._plan_deterministic(workflow, observation, mapping_result)

    async def _plan_with_llm(
        self,
        workflow: WorkflowState,
        observation: PageObservation,
        mapping_result: MappingResult,
    ) -> BrowserAction | None:
        """Use LLM to plan the next action."""
        import json

        # Build context for LLM
        page_state = observation.page_state
        elements_info = []
        for el in page_state.elements:
            if el.role in ("textbox", "combobox", "radiogroup", "checkbox", "button", "link"):
                elements_info.append({
                    "ref": el.ref,
                    "role": el.role,
                    "name": el.accessible_name or el.label_text or "",
                    "value": el.value or "",
                    "required": el.required,
                    "disabled": el.disabled,
                })

        bindings_info = [
            {"ref": b.field_ref, "binding": b.binding, "confidence": b.confidence.value}
            for b in mapping_result.bindings
        ]

        completed = workflow.completed_bindings
        pending = [
            b.field_ref for b in mapping_result.bindings
            if b.field_ref not in completed
            and b.binding is not None
            and b.confidence.value in ("high", "medium")
        ]

        schema = {
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
            response = await self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                schema=schema,
                temperature=0.0,
            )

            if response.parsed:
                action_data = response.parsed
                action_type = action_data.get("action", "stop")

                if action_type == "stop":
                    return None

                if action_type == "request_user_action":
                    return BrowserAction(
                        action="request_user_action",
                        reason=action_data.get("reason", "LLM requested user action"),
                    )

                kwargs: dict[str, Any] = {"action": action_type}

                if action_data.get("target_ref"):
                    kwargs["target_ref"] = action_data["target_ref"]
                if action_data.get("value_ref"):
                    kwargs["value_ref"] = action_data["value_ref"]
                if action_data.get("literal_value"):
                    kwargs["literal_value"] = action_data["literal_value"]
                if action_data.get("option"):
                    kwargs["option"] = action_data["option"]
                if action_data.get("key"):
                    kwargs["key"] = action_data["key"]
                if action_data.get("confidence") is not None:
                    kwargs["confidence"] = action_data["confidence"]

                # Set observation_id for stale ref prevention
                kwargs["observation_id"] = observation.observation_id

                return BrowserAction(**kwargs)

        except Exception as e:
            logger.warning("LLM planning failed: %s", e)

        return None

    def _plan_deterministic(
        self,
        workflow: WorkflowState,
        observation: PageObservation,
        mapping_result: MappingResult,
    ) -> BrowserAction | None:
        """Deterministic planning fallback — no LLM needed.

        Simple strategy: fill fields in order, then click submit.
        """
        page_state = observation.page_state

        # Find unfilled fields with HIGH confidence bindings
        for binding in mapping_result.bindings:
            if binding.field_ref in workflow.completed_bindings:
                continue
            if binding.confidence.value not in ("high",):
                continue
            if binding.binding is None:
                continue

            # Determine action based on field type
            if binding.field_type == "textbox":
                return BrowserAction(
                    action="fill",
                    target_ref=binding.field_ref,
                    value_ref=binding.binding,
                    observation_id=observation.observation_id,
                )
            elif binding.field_type == "combobox":
                # For dropdowns, we need to know the option
                # Find the element to get its options
                for el in page_state.elements:
                    if el.ref == binding.field_ref:
                        if el.selected_options:
                            return BrowserAction(
                                action="select",
                                target_ref=binding.field_ref,
                                option=el.selected_options[0] if el.selected_options else "",
                                observation_id=observation.observation_id,
                            )
            elif binding.field_type == "checkbox":
                return BrowserAction(
                    action="check",
                    target_ref=binding.field_ref,
                    observation_id=observation.observation_id,
                )

        # If all fields filled, look for a submit/next button
        for el in page_state.elements:
            if el.role == "button" and el.accessible_name:
                name = el.accessible_name.lower()
                if any(kw in name for kw in ("submit", "next", "apply", "save")):
                    return BrowserAction(
                        action="click",
                        target_ref=el.ref,
                        observation_id=observation.observation_id,
                    )

        return None
