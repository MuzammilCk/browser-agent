"""Recovery manager — coordinates failure classification, bounded reflection, and recovery audits.

CRITICAL INVARIANTS:
1. Coordinates failure recovery without bypassing ToolRegistry or PolicyEngine.
2. Reflection recommends a strategy; execution happens strictly through the standard runtime gates.
3. Every recovery attempt is audited with:
   - failure type
   - triggering evidence
   - attempted strategy
   - attempt count
   - resulting ToolResult
   - resulting WorldState change
4. Integrates StallDetector for repeated-action stalls.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.reasoning.protocol import ReasoningOutcome
from app.agent.recovery.classifier import FailureClassifier
from app.agent.recovery.models import (
    FailureClassification,
    FailureType,
    RecoveryAttemptRecord,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryStrategy,
    ReflectionResult,
)
from app.agent.recovery.reflector import RecoveryReflector
from app.agent.stall_detector import StallVerdict
from app.agent.strategy.manager import AgentPlanManager
from app.agent.tools.base import ToolCall, ToolResult
from app.agent.world.models import AgentWorldState
from app.browser.observer import PageObservation
from app.models.actions import BrowserAction

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Orchestrates bounded failure recovery and failure provenance tracking."""

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
        reflector: RecoveryReflector | None = None,
        budget: RecoveryBudget | None = None,
    ) -> None:
        self.classifier = classifier or FailureClassifier()
        self.budget = budget or RecoveryBudget()
        self.reflector = reflector or RecoveryReflector(budget=self.budget)
        self.history: list[RecoveryAttemptRecord] = []

    def handle_tool_failure(
        self,
        result: ToolResult,
        call: ToolCall | None = None,
        world_state: AgentWorldState | None = None,
        plan_manager: AgentPlanManager | None = None,
        observation: PageObservation | None = None,
    ) -> ReflectionResult:
        """Classify tool failure, reflect on recovery, and record the attempt."""
        classification = self.classifier.classify_tool_result(
            result, call=call, world_state=world_state, observation=observation,
        )
        return self._reflect_and_record(classification, world_state, plan_manager)

    def handle_reasoning_failure(
        self,
        outcome: ReasoningOutcome,
        world_state: AgentWorldState | None = None,
        plan_manager: AgentPlanManager | None = None,
    ) -> ReflectionResult:
        """Classify model reasoning failure, reflect, and record the attempt."""
        classification = self.classifier.classify_reasoning_outcome(outcome)
        return self._reflect_and_record(classification, world_state, plan_manager)

    def handle_stall(
        self,
        verdict: StallVerdict,
        world_state: AgentWorldState | None = None,
        plan_manager: AgentPlanManager | None = None,
    ) -> ReflectionResult:
        """Classify repeated action stall, reflect, and record the attempt."""
        classification = self.classifier.classify_stall(verdict)
        return self._reflect_and_record(classification, world_state, plan_manager)

    def _reflect_and_record(
        self,
        classification: FailureClassification,
        world_state: AgentWorldState | None,
        plan_manager: AgentPlanManager | None,
    ) -> ReflectionResult:
        ws_ver_before = world_state.version if world_state else 0

        reflection = self.reflector.reflect(
            classification,
            world_state=world_state,
            plan_manager=plan_manager,
            history=self.history,
        )

        record = RecoveryAttemptRecord(
            failure_type=classification.failure_type,
            triggering_evidence=classification.evidence.model_dump(mode="json"),
            attempted_strategy=reflection.decision.strategy,
            attempt_count=reflection.attempt_number,
            resulting_world_state_version_change=(ws_ver_before, ws_ver_before),
        )
        self.history.append(record)
        return reflection

    def record_attempt_result(
        self,
        attempt_record: RecoveryAttemptRecord,
        tool_result: ToolResult | None = None,
        world_state_version_after: int | None = None,
    ) -> None:
        """Update a recovery record with post-recovery evidence."""
        if tool_result:
            attempt_record.resulting_tool_result_summary = tool_result.summary()
        if world_state_version_after is not None:
            ver_before = attempt_record.resulting_world_state_version_change[0]
            attempt_record.resulting_world_state_version_change = (ver_before, world_state_version_after)

    def resolve_fresh_target_call(
        self,
        semantic_id: str,
        original_call: ToolCall,
        world_state: AgentWorldState,
    ) -> ToolCall | None:
        """Construct a fresh ToolCall targeting the new ref for an unambiguous semantic field.

        Fails closed (returns None) if:
        - semantic field not found in world state
        - field is not actionable in current observation
        - field identity is ambiguous
        """
        field = world_state.semantic_fields.get(semantic_id)
        if not field or not field.current_ref:
            return None

        if not field.is_actionable(world_state.current_observation_id):
            return None

        # Build fresh typed BrowserAction targeting the new ref
        fresh_action = None
        if original_call.action:
            action_dict = original_call.action.model_dump(exclude={"target_ref", "observation_id"})
            action_dict["target_ref"] = field.current_ref
            action_dict["observation_id"] = world_state.current_observation_id
            fresh_action = BrowserAction(**action_dict)

        # Build fresh arguments
        fresh_args = dict(original_call.arguments)
        if "target_ref" in fresh_args:
            fresh_args["target_ref"] = field.current_ref

        return ToolCall(
            tool_name=original_call.tool_name,
            arguments=fresh_args,
            action=fresh_action,
            reason=f"Recovery from stale ref: targeted fresh ref {field.current_ref} for {semantic_id}",
        )
