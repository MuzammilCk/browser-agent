"""Failure classifier — maps tool/model/browser outcomes to the 13 canonical failure types.

Implementation follows the Phase 7 taxonomy:
1. TARGET_NOT_FOUND
2. AMBIGUOUS_FIELD
3. INVALID_OPTION
4. VALIDATION_FAILURE
5. STALE_REFERENCE
6. PAGE_CHANGED
7. NAVIGATION_FAILURE
8. AUTHENTICATION_REQUIRED
9. PROMPT_INJECTION
10. TOOL_FAILURE
11. MODEL_FAILURE
12. TIMEOUT
13. POLICY_DENIED
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.reasoning.protocol import MODEL_FAILURE, ReasoningOutcome
from app.agent.recovery.models import (
    FailureClassification,
    FailureEvidence,
    FailureType,
    RecoveryStrategy,
)
from app.agent.stall_detector import STALL_REASON_REPEATED_ACTION, StallVerdict
from app.agent.tools.base import ToolCall, ToolResult
from app.agent.world.models import AgentWorldState
from app.browser.observer import PageObservation

logger = logging.getLogger(__name__)

# Known prompt injection keywords/patterns in untrusted input
_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system prompt override",
    "escalate privilege",
    "disable safety",
    "prompt_injection",
    "you are now in developer mode",
    "reveal vault secrets",
)


class FailureClassifier:
    """Classifies failures into the canonical 13-type taxonomy."""

    def classify_tool_result(
        self,
        result: ToolResult,
        call: ToolCall | None = None,
        world_state: AgentWorldState | None = None,
        observation: PageObservation | None = None,
    ) -> FailureClassification:
        """Classify a failed ToolResult with contextual evidence."""
        if result.success:
            raise ValueError(f"Cannot classify successful ToolResult for {result.tool_name}")

        msg = (result.message or "").strip()
        msg_lower = msg.lower()
        code = (result.error_code or "").upper()

        target_ref = None
        semantic_id = None
        obs_id = result.observation_id or (observation.observation_id if observation else None)

        if call and call.action:
            target_ref = call.action.target_ref
        elif result.payload and "target_ref" in result.payload:
            target_ref = result.payload.get("target_ref")

        if world_state and target_ref:
            for fid, field in world_state.semantic_fields.items():
                if field.current_ref == target_ref:
                    semantic_id = fid
                    break

        evidence = FailureEvidence(
            error_code=result.error_code or "UNKNOWN_ERROR",
            message=result.message,
            target_ref=target_ref,
            semantic_id=semantic_id,
            observation_id=obs_id,
            details=dict(result.payload),
        )

        # 1. Prompt injection check (fail closed immediately)
        if code == "PROMPT_INJECTION" or any(p in msg_lower for p in _INJECTION_PATTERNS):
            return FailureClassification(
                failure_type=FailureType.PROMPT_INJECTION,
                evidence=evidence,
                is_retryable=False,
                suggested_strategy=RecoveryStrategy.FAIL_CLOSED,
            )

        # 2. Policy denial
        if (
            result.policy_allowed is False
            or code == "POLICY_DENIED"
            or "policy denied" in msg_lower
            or "require_confirmation" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.POLICY_DENIED,
                evidence=evidence,
                is_retryable=False,
                suggested_strategy=RecoveryStrategy.SURFACE_DENIAL,
            )

        # 3. Authentication / Human interaction required
        if (
            code in ("USER_ACTION_REQUIRED", "AUTHENTICATION_REQUIRED", "CONFIRMATION_REQUIRED")
            or "pause_for_user" in msg_lower
            or "captcha" in msg_lower
            or (observation and getattr(observation.page_state, "authentication", None) and observation.page_state.authentication.detected)
        ):
            return FailureClassification(
                failure_type=FailureType.AUTHENTICATION_REQUIRED,
                evidence=evidence,
                is_retryable=False,
                suggested_strategy=RecoveryStrategy.REQUEST_USER_INPUT,
            )

        # 4. Stale Reference
        if (
            code in ("STALE_REFERENCE", "STALE_OR_INVALID_TARGET")
            or "stale reference" in msg_lower
            or "stale observation" in msg_lower
            or "targets observation" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.STALE_REFERENCE,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.ACQUIRE_FRESH_REF,
            )

        # 5. Invalid Option in select dropdown
        if (
            code == "INVALID_OPTION"
            or ("option '" in msg_lower and "not found" in msg_lower)
            or "no option provided" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.INVALID_OPTION,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.REVISE_INPUT,
            )

        # 6. Target not found
        if (
            code in ("ELEMENT_NOT_FOUND", "TARGET_NOT_FOUND")
            or "could not locate element" in msg_lower
            or "no target ref" in msg_lower
            or "target not found" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.TARGET_NOT_FOUND,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
            )

        # 7. Ambiguous Field
        if (
            code == "AMBIGUOUS_FIELD"
            or "ambiguous" in msg_lower
            or evidence.details.get("ambiguous", False)
        ):
            return FailureClassification(
                failure_type=FailureType.AMBIGUOUS_FIELD,
                evidence=evidence,
                is_retryable=False,
                suggested_strategy=RecoveryStrategy.REQUEST_USER_INPUT,
            )

        # 8. Validation Failure
        has_validation_errs = False
        if observation and observation.page_state.validation_errors:
            has_validation_errs = True
        elif world_state and world_state.validation_errors:
            has_validation_errs = True

        if (
            code == "VALIDATION_FAILURE"
            or has_validation_errs
            or "validation" in msg_lower
            or (result.verification_status and result.verification_status.lower() in ("failure", "uncertain"))
        ):
            return FailureClassification(
                failure_type=FailureType.VALIDATION_FAILURE,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.REVISE_INPUT,
            )

        # 9. Navigation Failure
        if (
            result.tool_name == "navigate"
            or code == "NAVIGATION_FAILURE"
            or "navigation" in msg_lower
            or "net::" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.NAVIGATION_FAILURE,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
            )

        # 10. Timeout
        if (
            code == "TIMEOUT"
            or "timeout" in msg_lower
            or "timed out" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.TIMEOUT,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
            )

        # 11. Page Changed
        if (
            code == "PAGE_CHANGED"
            or "page changed" in msg_lower
            or "url changed" in msg_lower
        ):
            return FailureClassification(
                failure_type=FailureType.PAGE_CHANGED,
                evidence=evidence,
                is_retryable=True,
                suggested_strategy=RecoveryStrategy.REPLAN_SUBGOAL,
            )

        # 12. Default: Tool Failure
        return FailureClassification(
            failure_type=FailureType.TOOL_FAILURE,
            evidence=evidence,
            is_retryable=True,
            suggested_strategy=RecoveryStrategy.RE_OBSERVE_AND_RETRY,
        )

    def classify_reasoning_outcome(self, outcome: ReasoningOutcome) -> FailureClassification:
        """Classify a non-decided or failed ReasoningOutcome."""
        if outcome.decided:
            raise ValueError("Cannot classify successful ReasoningOutcome as failure")

        code = outcome.model_failure_code or MODEL_FAILURE
        reason = outcome.reason or "Model produced no usable decision"

        evidence = FailureEvidence(
            error_code=code,
            message=reason,
            details={"attempts": outcome.attempts, "phase": outcome.phase},
        )
        return FailureClassification(
            failure_type=FailureType.MODEL_FAILURE,
            evidence=evidence,
            is_retryable=False,  # AgentReasoner already exhausted internal retries
            suggested_strategy=RecoveryStrategy.TERMINAL_FAILURE,
        )

    def classify_stall(self, verdict: StallVerdict) -> FailureClassification:
        """Classify a repeated-action stall verdict from StallDetector."""
        if not verdict.halt:
            raise ValueError("Cannot classify non-halting stall verdict as failure")

        evidence = FailureEvidence(
            error_code=STALL_REASON_REPEATED_ACTION,
            message=verdict.reason,
            details={"repeat_count": verdict.repeat_count, "stall_key": verdict.key},
        )
        return FailureClassification(
            failure_type=FailureType.TOOL_FAILURE,
            evidence=evidence,
            is_retryable=False,
            suggested_strategy=RecoveryStrategy.TERMINAL_FAILURE,
        )
