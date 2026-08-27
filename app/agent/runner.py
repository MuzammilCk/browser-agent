"""Agent runner — the core workflow orchestrator.

Per audit issues #25, #26, #28, #43:
- Full loop: observe → map → plan → policy → execute → verify → repeat
- Owns WorkflowState across page transitions
- Integrates FieldMapper, PolicyEngine, BrowserExecutor, LLM
- Recovery logic with bounded retries
- User checkpoints for CAPTCHA/OTP/payment
- Confirmation pause/resume with real resumption (audit C1)

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
from app.agent.planning_result import (
    ActionPlanned, NoValidAction, PlanLLMError, PlanOutcome, TaskComplete,
)
from app.agent.registry import ReferenceRegistry, get_registry
from app.agent.vision_fallback import (
    request_vision_action, should_attempt_vision,
)
from app.browser.executor import ActionResult, BrowserExecutor
from app.browser.observer import PageObservation, PageObserver
from app.browser.vision import assess_completeness
from app.llm.base import LLMGateway
from app.models.actions import BrowserAction
from app.models.workflow_state import (
    ActionRecord, WorkflowState, WorkflowStatus,
)
from app.policy.engine import PolicyEngine
from app.vault.resolver import DocumentRegistry, UserVault

logger = logging.getLogger(__name__)

# Terminal statuses after which the loop must not continue.
_TERMINAL_STATUSES = {
    WorkflowStatus.FAILED,
    WorkflowStatus.ABORTED,
    WorkflowStatus.COMPLETED,
}


class AgentRunner:
    """Core workflow orchestrator.

    Usage:
        runner = AgentRunner(llm=llm_gateway)
        result = await runner.run(page=page, task="Fill the form")

        # Later, after a confirmation pause:
        result = await runner.resume(page=page, workflow=result, approved=True)
    """

    def __init__(
        self,
        llm: LLMGateway | None = None,
        policy_engine: PolicyEngine | None = None,
        registry: ReferenceRegistry | None = None,
        max_iterations: int = 50,
        vault: UserVault | None = None,
        document_registry: DocumentRegistry | None = None,
        document_policy: Any | None = None,
        llm_disabled_reason: str | None = None,
        vault_loaded: bool = False,
        vault_warning: str | None = None,
        vision_fallback_enabled: bool = False,
    ) -> None:
        self._llm = llm
        # Why the LLM is absent (P0-37): callers who know better than the
        # default pass an explicit reason, e.g. "gateway_init_failed: ...".
        self._llm_disabled_reason = (
            llm_disabled_reason if llm is None else None
        )
        # Vault visibility (Z3): declared on workflow state from the start.
        self._vault_loaded = vault_loaded
        self._vault_warning = vault_warning
        # Vision fallback (Z7 / P0-16): one-shot rescue at planning stalls.
        self._vision_fallback_enabled = vision_fallback_enabled
        self._policy = policy_engine or PolicyEngine()
        self._registry = registry or get_registry()
        self._observer = PageObserver()
        self._mapper = FieldMapper(llm_gateway=llm, registry=self._registry)
        self._executor = BrowserExecutor(
            policy_engine=self._policy,
            vault=vault,
            document_registry=document_registry,
            document_policy=document_policy,
        )
        self._max_iterations = max_iterations

    @property
    def executor(self) -> BrowserExecutor:
        """Expose the executor (for vault/document wiring by callers)."""
        return self._executor

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
        self._apply_planning_metadata(workflow)
        workflow.vault_loaded = self._vault_loaded
        workflow.vault_warning = self._vault_warning
        logger.info("Starting workflow %s: %s", workflow.workflow_id, task)
        return await self._loop(workflow, page)

    def _apply_planning_metadata(self, workflow: WorkflowState) -> None:
        """Declare whether the LLM is actually in the loop (P0-37 / Z8).

        Set from the very first moment of the workflow so "is the LLM even
        running" is answerable from workflow state alone.
        """
        if self._llm is not None:
            workflow.planning_mode = "llm"
            workflow.llm_model = getattr(self._llm, "model_name", None)
            workflow.llm_disabled_reason = None
        else:
            workflow.planning_mode = "deterministic_fallback"
            workflow.llm_model = None
            workflow.llm_disabled_reason = (
                self._llm_disabled_reason or "no_api_key"
            )

    async def _loop(self, workflow: WorkflowState, page: Any) -> WorkflowState:
        """Run observe→map→plan→policy→execute iterations until a halt.

        Shared by run() and resume() so a resumed workflow continues
        in the same WorkflowState instead of starting over.
        """
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

        # 4. PLAN — typed outcome; None no longer overloaded (P0-13)
        outcome = await self._plan(workflow, observation, mapping)
        if isinstance(outcome, ActionPlanned):
            action = outcome.action
        elif isinstance(outcome, NoValidAction) and self._vision_gate_open(workflow):
            # Z7 / P0-16: one vision pass before surfacing the stall.
            vision_outcome = await self._attempt_vision_fallback(
                workflow, observation, page,
            )
            if isinstance(vision_outcome, ActionPlanned):
                action = vision_outcome.action
            else:
                self._handle_plan_outcome(workflow, vision_outcome, mapping)
                return "break"
        else:
            self._handle_plan_outcome(workflow, outcome, mapping)
            return "break"

        # 5. POLICY CHECK — audit B2 fix: REQUIRE_CONFIRMATION now halts
        policy_result = self._policy.evaluate(action, observation.page_state)
        if self._check_policy(workflow, policy_result, action, observation):
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

        # A success/acknowledgement page means the application flow completed.
        if obs.page_state.page_type == "success" and workflow.actions_taken:
            if workflow.status not in _TERMINAL_STATUSES | {WorkflowStatus.WAITING_FOR_USER}:
                workflow.status = WorkflowStatus.COMPLETED
            if workflow.submission_state in ("ready", "not_ready"):
                workflow.submission_state = "submitted"

    def _check_auth(
        self, workflow: WorkflowState, obs: PageObservation,
    ) -> bool:
        auth = obs.page_state.authentication
        if not auth.detected:
            return False
        auth_type = auth.challenge_type or "unknown"
        workflow.authentication_state = "detected"
        workflow.add_checkpoint(auth_type)
        # Distinct status for CAPTCHA vs other auth challenges (#49)
        if auth_type == "captcha":
            workflow.status = WorkflowStatus.WAITING_FOR_CAPTCHA
        else:
            workflow.status = WorkflowStatus.WAITING_FOR_AUTH
        logger.warning("Auth detected: %s (%d%%)", auth_type, int(auth.confidence * 100))
        return True

    async def _plan(
        self, workflow: WorkflowState, obs: PageObservation, mapping,
    ) -> PlanOutcome:
        if self._llm:
            return await plan_with_llm(self._llm, workflow, obs, mapping)
        # Deterministic planning resolves bindings through the vault so
        # select/fill actions carry real values (audit C4).
        return plan_deterministic(
            workflow, obs, mapping,
            value_resolver=self._executor.value_resolver,
        )

    def _vision_gate_open(self, workflow: WorkflowState) -> bool:
        """Vision fallback runs at most once per workflow (Z7 / P0-16)."""
        return should_attempt_vision(
            enabled=self._vision_fallback_enabled,
            has_llm=self._llm is not None,
            attempts_used=workflow.vision_fallback_attempts,
        )

    async def _attempt_vision_fallback(
        self, workflow: WorkflowState, observation: PageObservation, page: Any,
    ) -> PlanOutcome:
        """Take the single vision-fallback attempt; trace it in checkpoints."""
        workflow.vision_fallback_attempts += 1
        assessment = assess_completeness(observation)
        workflow.add_checkpoint(
            f"Vision fallback attempted ({assessment.reason})"
        )
        logger.info(
            "Workflow %s: vision fallback attempt %d (%s)",
            workflow.workflow_id, workflow.vision_fallback_attempts,
            assessment.reason,
        )
        return await request_vision_action(
            self._llm, page, observation, workflow.task_description,
        )

    def _handle_plan_outcome(
        self, workflow: WorkflowState, outcome: PlanOutcome, mapping,
    ) -> None:
        """Translate a non-action plan outcome into honest workflow status.

        Dispatch rules (Phase 1 / Z2):
        - PlanLLMError → WAITING_FOR_USER with the error surfaced verbatim.
        - NoValidAction on navigation/unknown pages → WAITING_FOR_USER
          ("stalled"), never READY_FOR_SUBMISSION — a page without fields
          trivially has zero unmapped fields, which said nothing about
          completion.
        - NoValidAction on form/review with nothing unmapped/ambiguous →
          the one legitimate path to READY_FOR_SUBMISSION.
        - TaskComplete → COMPLETED only via the existing success-page guard.
        """
        if isinstance(outcome, PlanLLMError):
            logger.warning("Planning failed: %s", outcome.message)
            workflow.set_error("user_required", f"LLM planning failed: {outcome.message}")
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return

        reason = (
            outcome.reason if isinstance(outcome, (NoValidAction, TaskComplete))
            else "planner produced no action"
        )
        workflow.add_checkpoint(f"Planner stopped: {reason}")
        logger.info("Planner stopped: %s", reason)

        page_type = workflow.current_page_type

        if isinstance(outcome, TaskComplete) and page_type == "success":
            workflow.status = WorkflowStatus.COMPLETED
            if workflow.submission_state in ("ready", "not_ready"):
                workflow.submission_state = "submitted"
            return

        stalled_page_types = {"navigation", "unknown", "otp", "captcha"}
        if page_type in stalled_page_types:
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            workflow.set_error(
                "user_required",
                f"Stalled on '{page_type}' page — planner found no next "
                f"step ({reason}). Manual attention needed.",
            )
            return

        if (
            page_type in ("form", "review")
            and not mapping.unmapped_fields
            and not mapping.ambiguous_fields
        ):
            workflow.status = WorkflowStatus.READY_FOR_SUBMISSION
            if workflow.submission_state == "not_ready":
                workflow.submission_state = "ready"
            return

        # Anything else (unmapped fields, odd page types) → loud halt.
        workflow.status = WorkflowStatus.WAITING_FOR_USER
        workflow.set_error(
            "user_required",
            f"Cannot map {len(mapping.unmapped_fields)} fields",
        )

    def _check_policy(
        self,
        workflow: WorkflowState,
        policy_result,
        action: BrowserAction | None = None,
        observation: PageObservation | None = None,
    ) -> bool:
        """Check policy result. Returns True to halt the iteration.

        Audit B2 fix: REQUIRE_CONFIRMATION stores the pending action
        and halts execution instead of falling through.
        """
        if policy_result.blocked:
            workflow.set_error("user_required", policy_result.reason)
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return True
        if policy_result.needs_user:
            workflow.add_checkpoint(policy_result.reason)
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return True
        if policy_result.needs_confirmation:
            # Store the pending action so caller can present it and resume
            if action is not None:
                workflow.pending_action = action.model_dump()
                workflow.pending_target_signature = self._target_signature(
                    action, observation,
                )
            if observation is not None:
                workflow.pending_observation_id = observation.observation_id
            workflow.status = WorkflowStatus.READY_FOR_CONFIRMATION
            workflow.add_checkpoint(
                f"Confirmation required: {policy_result.reason}"
            )
            logger.warning(
                "REQUIRE_CONFIRMATION: %s — halting for user approval",
                policy_result.reason,
            )
            return True
        return False

    @staticmethod
    def _target_signature(
        action: BrowserAction, observation: PageObservation,
    ) -> dict | None:
        """Capture role + accessible name of the action's target element."""
        if not action.target_ref:
            return None
        for el in observation.page_state.elements:
            if el.ref == action.target_ref:
                return {
                    "role": el.role,
                    "accessible_name": el.accessible_name,
                }
        return None

    async def resume(
        self,
        page: Any,
        workflow: WorkflowState,
        approved: bool,
    ) -> WorkflowState:
        """Resume after a confirmation pause.

        If approved, re-observes the page, verifies the pending target is
        still the same element, re-targets the action at the FRESH
        observation (clearing staleness), and executes it with explicit
        user confirmation — then continues the normal loop in the same
        WorkflowState. If declined, stops the workflow cleanly.

        Audit C1 fix: the confirmed action is executed with user_confirmed=True
        so the executor's own gate does not refuse it again.
        """
        if workflow.pending_action is None:
            workflow.status = WorkflowStatus.FAILED
            workflow.set_error("no_pending_action", "No pending action to resume")
            return workflow

        if not approved:
            workflow.pending_action = None
            workflow.pending_observation_id = ""
            workflow.pending_target_signature = None
            workflow.status = WorkflowStatus.ABORTED
            workflow.add_checkpoint("User declined confirmation")
            return workflow

        # Re-observe before replaying (never trust a paused snapshot)
        observation = await self._observer.observe(page)
        self._update_workflow_observation(workflow, observation)

        # Reconstruct the action from stored state
        try:
            action = BrowserAction(**workflow.pending_action)
        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            workflow.set_error("invalid_pending_action", str(e))
            return workflow

        # Verify the target still exists and still looks like the element
        # the user approved (refs are ephemeral; pages can shift).
        signature = workflow.pending_target_signature
        fresh_target = None
        if action.target_ref:
            fresh_target = next(
                (el for el in observation.page_state.elements
                 if el.ref == action.target_ref),
                None,
            )
        if action.target_ref and fresh_target is None:
            workflow.pending_action = None
            workflow.pending_observation_id = ""
            workflow.pending_target_signature = None
            workflow.set_error(
                "user_required",
                f"Pending action target {action.target_ref} no longer on page "
                "after confirmation pause — manual review required",
            )
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return workflow
        if signature and fresh_target is not None:
            fresh_sig = {"role": fresh_target.role, "accessible_name": fresh_target.accessible_name}
            if fresh_sig != signature:
                workflow.pending_action = None
                workflow.pending_observation_id = ""
                workflow.pending_target_signature = None
                workflow.set_error(
                    "user_required",
                    "Pending action target changed identity after pause "
                    f"({signature} -> {fresh_sig}) — manual review required",
                )
                workflow.status = WorkflowStatus.WAITING_FOR_USER
                return workflow

        # Clear pending state
        workflow.pending_action = None
        workflow.pending_observation_id = ""
        workflow.pending_target_signature = None

        # Re-evaluate policy against the fresh state: DENY / PAUSE still win.
        policy_result = self._policy.evaluate(action, observation.page_state)
        if policy_result.blocked or policy_result.needs_user:
            workflow.set_error(
                "user_required",
                f"Pending action no longer permitted after resume: {policy_result.reason}",
            )
            workflow.status = WorkflowStatus.WAITING_FOR_USER
            return workflow

        # Re-target the action at the fresh observation so the executor's
        # stale-reference guard accepts it (the user just approved THIS
        # action; re-observation replaced the paused snapshot).
        action = action.model_copy(update={"observation_id": observation.observation_id})

        # Execute with explicit user confirmation (audit C1 fix)
        result = await self._executor.execute(
            page, action, observation, user_confirmed=True,
        )
        self._record_action(workflow, action, result, policy_result, observation)
        workflow.status = WorkflowStatus.RUNNING
        workflow.submission_state = "confirmed"

        next_step = self._handle_result(workflow, result, observation)
        if next_step == "break":
            return workflow

        # Continue the normal loop from here in the same WorkflowState
        return await self._loop(workflow, page)

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
