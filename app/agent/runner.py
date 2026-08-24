"""Agent runner — the core workflow orchestrator.

Per audit issues #25, #26, #28, #43:
- Full loop: observe → map → plan → policy → execute → verify → repeat
- Owns WorkflowState across page transitions
- Integrates FieldMapper, PolicyEngine, BrowserExecutor, LLM
- Recovery logic with bounded retries
- User checkpoints for CAPTCHA/OTP/payment

Architecture:
    User Task → AgentRunner → PageObserver, FieldMapper,
    LLMGateway, PolicyEngine, BrowserExecutor, ActionVerifier
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.field_mapper import FieldMapper
from app.agent.planner import plan_deterministic, plan_with_llm
from app.agent.registry import ReferenceRegistry, get_registry
from app.browser.executor import ActionResult, BrowserExecutor
from app.browser.observer import PageObservation, PageObserver
from app.llm.base import LLMGateway
from app.models.actions import BrowserAction
from app.models.workflow_state import (
    ActionRecord, WorkflowState, WorkflowStatus,
)
from app.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


class AgentRunner:
    """Core workflow orchestrator.

    Usage:
        runner = AgentRunner(llm=llm_gateway)
        result = await runner.run(page=page, task="Fill the form")
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
        self, page: Any, task: str = "", domain: str = "",
    ) -> WorkflowState:
        """Run the full agent loop."""
        workflow = WorkflowState(
            workflow_id=str(uuid.uuid4())[:8],
            domain=domain, task_description=task,
            status=WorkflowStatus.RUNNING,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("Starting workflow %s: %s", workflow.workflow_id, task)

        try:
            observation = None
            for iteration in range(1, self._max_iterations + 1):
                logger.info("=== Iteration %d ===", iteration)
                result = await self._run_iteration(workflow, observation, page)
                if result == "break":
                    break
                if result == "continue":
                    observation = None
                    continue
                observation = result
            else:
                workflow.status = WorkflowStatus.FAILED
                workflow.set_error("fatal", f"Max iterations ({self._max_iterations}) reached")
        except Exception as e:
            logger.error("Workflow failed: %s", e, exc_info=True)
            workflow.status = WorkflowStatus.FAILED
            workflow.set_error("fatal", str(e))

        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("Workflow %s finished: %s", workflow.workflow_id, workflow.status.value)
        return workflow

    async def _run_iteration(
        self,
        workflow: WorkflowState,
        prev_observation: PageObservation | None,
        page: Any,
    ) -> PageObservation | str:
        """Run one iteration. Returns next observation, 'break', or 'continue'."""
        # 1. OBSERVE
        observation = await self._observer.observe(page)
        self._update_workflow_observation(workflow, observation)

        # 2. CHECK AUTH
        if self._check_auth(workflow, observation):
            return "break"

        # 3. MAP FIELDS
        mapping = await self._mapper.map_fields(observation)
        workflow.unmapped_fields = mapping.unmapped_fields
        workflow.ambiguous_fields = mapping.ambiguous_fields

        # 4. PLAN
        action = await self._plan(workflow, observation, mapping)
        if action is None:
            self._handle_no_action(workflow, mapping)
            return "break"

        # 5. POLICY CHECK
        policy_result = self._policy.evaluate(action, observation.page_state)
        if self._check_policy(workflow, policy_result):
            return "break"

        # 6. EXECUTE
        result = await self._executor.execute(page, action, observation)

        # 7. RECORD
        self._record_action(workflow, action, result, policy_result, observation)

        # 8. HANDLE RESULT
        return self._handle_result(workflow, result, observation)

    def _update_workflow_observation(
        self, workflow: WorkflowState, obs: PageObservation,
    ) -> None:
        workflow.current_observation_id = obs.observation_id
        workflow.current_url = obs.page_state.url
        workflow.current_page_type = obs.page_state.page_type

    def _check_auth(
        self, workflow: WorkflowState, obs: PageObservation,
    ) -> bool:
        auth = obs.page_state.authentication
        if not auth.detected:
            return False
        auth_type = auth.challenge_type or "unknown"
        workflow.authentication_state = "detected"
        workflow.add_checkpoint(auth_type)
        workflow.status = WorkflowStatus.WAITING_FOR_AUTH
        logger.warning("Auth detected: %s (%d%%)", auth_type, int(auth.confidence * 100))
        return True

    async def _plan(
        self, workflow: WorkflowState, obs: PageObservation, mapping,
    ) -> BrowserAction | None:
        if self._llm:
            return await plan_with_llm(self._llm, workflow, obs, mapping)
        return plan_deterministic(workflow, obs, mapping)

    def _handle_no_action(self, workflow: WorkflowState, mapping) -> None:
        if not mapping.unmapped_fields:
            workflow.status = WorkflowStatus.READY_FOR_SUBMISSION
        else:
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            workflow.set_error("user_required", f"Cannot map {len(mapping.unmapped_fields)} fields")

    def _check_policy(self, workflow: WorkflowState, policy_result) -> bool:
        if policy_result.blocked:
            workflow.set_error("user_required", policy_result.reason)
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return True
        if policy_result.needs_user:
            workflow.add_checkpoint(policy_result.reason)
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return True
        if policy_result.needs_confirmation:
            workflow.status = WorkflowStatus.READY_FOR_CONFIRMATION
        return False

    def _record_action(
        self, workflow: WorkflowState, action: BrowserAction,
        result: ActionResult, policy_result, obs: PageObservation,
    ) -> None:
        record = ActionRecord(
            action_type=action.action,
            target_ref=action.target_ref,
            binding=action.value_ref or action.document_ref or "",
            success=result.success,
            verification_status=(
                result.verification.status.value if result.verification else ""
            ),
            policy_decision=policy_result.decision.value,
            message=result.message,
            observation_id=obs.observation_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        workflow.record_action(record)

    def _handle_result(
        self, workflow: WorkflowState, result: ActionResult,
        observation: PageObservation,
    ) -> PageObservation | str:
        if result.user_action_required:
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            workflow.add_checkpoint(result.message)
            return "break"

        if not result.success:
            workflow.failed_actions += 1
            if result.recovery_required:
                if workflow.can_retry():
                    workflow.increment_recovery()
                    return "continue"
                workflow.status = WorkflowStatus.FAILED
                workflow.set_error("fatal", result.message)
                return "break"

        workflow.reset_recovery()
        if result.post_observation:
            return result.post_observation
        return observation
