"""Bounded recovery reflection — Phase 7.

Analyzes failure classifications and world state to recommend a RecoveryDecision.
CRITICAL INVARIANTS:
1. Reflection recommends a strategy; it NEVER executes browser actions directly.
2. Recovery is strictly bounded by RecoveryBudget.
3. Policy denials and prompt injections are never silently retried.
4. Ambiguity is never resolved by guessing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.recovery.models import (
    FailureClassification,
    FailureType,
    RecoveryAttemptRecord,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryStrategy,
    ReflectionResult,
)
from app.agent.strategy.manager import AgentPlanManager
from app.agent.world.models import AgentWorldState

logger = logging.getLogger(__name__)


class RecoveryReflector:
    """Bounded, non-mutating reflection on failures."""

    def __init__(self, budget: RecoveryBudget | None = None) -> None:
        self.budget = budget or RecoveryBudget()

    def reflect(
        self,
        classification: FailureClassification,
        world_state: AgentWorldState | None = None,
        plan_manager: AgentPlanManager | None = None,
        history: list[RecoveryAttemptRecord] | None = None,
    ) -> ReflectionResult:
        """Analyze failure and recommend the next recovery decision within budget limits."""
        history = history or []
        ft = classification.failure_type
        limit = self.budget.limit_for(ft)

        # Count prior attempts for this failure type in the current run
        prior_attempts = sum(1 for r in history if r.failure_type == ft)
        attempt_number = prior_attempts + 1
        budget_remaining = max(0, limit - prior_attempts)

        # 0. Stall detection check (repeated action producing no progress)
        from app.agent.stall_detector import STALL_REASON_REPEATED_ACTION
        if classification.evidence.error_code == STALL_REASON_REPEATED_ACTION:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.TERMINAL_FAILURE,
                action_required="stop",
                reason=f"Stall detected: {classification.evidence.message}",
                is_terminal=True,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Repeated identical action produced no observable progress",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        # 1. Immediate Non-Retryable Failures
        if ft == FailureType.POLICY_DENIED:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.SURFACE_DENIAL,
                action_required="stop",
                reason=f"Policy denied proposed action: {classification.evidence.message}",
                is_terminal=True,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="PolicyEngine blocked action (high-risk or unconfirmed)",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        if ft == FailureType.PROMPT_INJECTION:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.FAIL_CLOSED,
                action_required="stop",
                reason=f"Prompt injection pattern detected: {classification.evidence.message}",
                is_terminal=True,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Untrusted page content attempted instruction injection",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        if ft == FailureType.AUTHENTICATION_REQUIRED:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.REQUEST_USER_INPUT,
                action_required="user_interrupt",
                pause_for_user=True,
                user_interrupt_kind="authentication",
                user_question="Authentication or human checkpoint required. Please complete it to continue.",
                reason="Authentication / CAPTCHA challenge requires human action",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Portal presented an authentication or verification checkpoint",
                can_recover=False,  # Automated agent cannot self-authenticate
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        if ft == FailureType.AMBIGUOUS_FIELD:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.REQUEST_USER_INPUT,
                action_required="user_interrupt",
                pause_for_user=True,
                user_interrupt_kind="clarification",
                user_question=f"Ambiguous target field ({classification.evidence.target_ref or 'unknown'}). Please clarify which field to target.",
                reason="Ambiguous field identity beats guessing (AGENTS.md rule 8)",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Multiple candidate elements matched target description without disambiguation",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        if ft == FailureType.MODEL_FAILURE:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.TERMINAL_FAILURE,
                action_required="stop",
                reason=f"Model failure cannot be resolved: {classification.evidence.message}",
                is_terminal=True,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Model produced persistent parse/schema failure; no fallback decision fabricated",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        # 2. Check Budget Boundaries
        if prior_attempts >= limit or len(history) >= self.budget.max_total_attempts:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.TERMINAL_FAILURE,
                action_required="stop",
                reason=f"Recovery budget exhausted for {ft.value} ({prior_attempts}/{limit} attempts used)",
                is_terminal=True,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause=f"Repeated failures exceeded maximum recovery budget of {limit}",
                can_recover=False,
                attempt_number=attempt_number,
                budget_remaining=0,
                decision=decision,
            )

        # 3. Handle Retryable Strategies

        # STALE_REFERENCE
        if ft == FailureType.STALE_REFERENCE:
            # Re-observe current page, validate semantic target, obtain fresh ref
            semantic_id = classification.evidence.semantic_id
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.ACQUIRE_FRESH_REF,
                action_required="re_observe",
                reason=(
                    f"DOM ref {classification.evidence.target_ref} became stale. "
                    f"Re-observe page to obtain fresh ref for semantic target {semantic_id or 'unknown'}."
                ),
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Observation ID changed or target DOM node was re-rendered",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # TARGET_NOT_FOUND
        if ft == FailureType.TARGET_NOT_FOUND:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
                action_required="re_observe",
                reason=(
                    f"Element {classification.evidence.target_ref} not found. "
                    "Re-observe page to check if it appeared dynamically."
                ),
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Element locator failed on current observation",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # INVALID_OPTION
        if ft == FailureType.INVALID_OPTION:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.REVISE_INPUT,
                action_required="re_observe",
                reason="Select option not found in dropdown. Re-observe and inspect available options.",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Option literal did not match select element options",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # VALIDATION_FAILURE
        if ft == FailureType.VALIDATION_FAILURE:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.REVISE_INPUT,
                action_required="re_observe",
                reason=f"Form validation failed: {classification.evidence.message}. Re-observe to inspect error messages and revise input.",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Input violated portal validation constraints",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # PAGE_CHANGED
        if ft == FailureType.PAGE_CHANGED:
            # If plan manager is available, invalidate the affected active subgoal
            subgoal_id = None
            if plan_manager and plan_manager.plan:
                from app.agent.strategy.models import SubgoalStatus
                active_subgoals = plan_manager.plan.by_status(SubgoalStatus.ACTIVE)
                if active_subgoals:
                    active_sg = active_subgoals[0]
                    subgoal_id = active_sg.id
                    try:
                        plan_manager.invalidate(
                            subgoal_id,
                            evidence=f"Page changed unexpectedly: {classification.evidence.message}",
                        )
                    except Exception as e:
                        logger.warning("Could not invalidate active subgoal: %s", e)

            decision = RecoveryDecision(
                strategy=RecoveryStrategy.REPLAN_SUBGOAL,
                action_required="replan",
                recommended_subgoal_id=subgoal_id,
                reason="Unexpected page change detected. Subgoal invalidated; strategic replan required.",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Page navigated or dynamic layout changed unexpectedly",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # NAVIGATION_FAILURE
        if ft == FailureType.NAVIGATION_FAILURE:
            decision = RecoveryDecision(
                strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
                action_required="re_observe",
                reason=f"Navigation encountered error: {classification.evidence.message}. Performing bounded retry.",
                is_terminal=False,
            )
            return ReflectionResult(
                failure_type=ft,
                root_cause="Navigation timed out or encountered network error",
                can_recover=True,
                attempt_number=attempt_number,
                budget_remaining=budget_remaining - 1,
                decision=decision,
            )

        # TIMEOUT / TOOL_FAILURE
        decision = RecoveryDecision(
            strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
            action_required="re_observe",
            reason=f"Tool execution failed: {classification.evidence.message}. Re-observe page before retry.",
            is_terminal=False,
        )
        return ReflectionResult(
            failure_type=ft,
            root_cause="Tool execution or timeout error during browser interaction",
            can_recover=True,
            attempt_number=attempt_number,
            budget_remaining=budget_remaining - 1,
            decision=decision,
        )
