"""Controlled Failure Injection Framework — Phase 12.

Key Architectural Invariants:
1. Scenario-configured and explicit (disabled by default).
2. Uses dependency-injection test seams rather than fragile global monkeypatching.
3. Cannot be triggered or controlled by LLM output.
4. Emits FAULT_INJECTED trace events so faults are fully auditable.
5. Strict schema validation (extra="forbid").
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class FaultType(str, Enum):
    """Supported fault injection types."""

    STALE_REFERENCE = "stale_reference"
    TARGET_DISAPPEARANCE = "target_disappearance"
    VALIDATION_FAILURE = "validation_failure"
    NAVIGATION_FAILURE = "navigation_failure"
    BROWSER_FAILURE = "browser_failure"
    MODEL_FAILURE = "model_failure"
    MALFORMED_MODEL_OUTPUT = "malformed_model_output"
    TOOL_FAILURE = "tool_failure"
    POLICY_DENIAL = "policy_denial"
    HITL_TIMEOUT = "hitl_timeout"
    SPECIALIST_TIMEOUT = "specialist_timeout"
    SPECIALIST_FAILURE = "specialist_failure"
    STATE_VERSION_DRIFT = "state_version_drift"
    APPROVAL_MISMATCH = "approval_mismatch"
    UNAUTHORIZED_REDIRECT = "unauthorized_redirect"
    BUDGET_EXHAUSTION = "budget_exhaustion"


class FaultTrigger(BaseModel):
    """Condition specifying when a fault should trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    iteration: int | None = None
    tool_name: str | None = None
    target_ref: str | None = None
    trigger_count: int = 1  # how many times this fault should trigger


class InjectedFault(BaseModel):
    """Specification of an individual injected fault."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fault_id: str
    fault_type: FaultType
    trigger: FaultTrigger
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class FailureInjectionPlan(BaseModel):
    """Scenario-scoped collection of injected faults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    faults: list[InjectedFault] = Field(default_factory=list)


class FailureInjector:
    """Stateful runtime failure injector evaluating fault triggers."""

    def __init__(self, plan: FailureInjectionPlan | dict[str, Any] | None = None) -> None:
        if isinstance(plan, dict):
            self.plan = FailureInjectionPlan.model_validate(plan)
        else:
            self.plan = plan or FailureInjectionPlan(enabled=False)
        self._trigger_counts: dict[str, int] = {}
        self._injected_events: list[dict[str, Any]] = []

    @property
    def is_enabled(self) -> bool:
        return self.plan.enabled

    def should_inject(
        self,
        fault_type: FaultType,
        *,
        iteration: int | None = None,
        tool_name: str | None = None,
        target_ref: str | None = None,
    ) -> InjectedFault | None:
        """Check whether any active fault matches the current execution context."""
        if not self.is_enabled:
            return None

        for fault in self.plan.faults:
            if fault.fault_type != fault_type:
                continue

            current_count = self._trigger_counts.get(fault.fault_id, 0)
            if current_count >= fault.trigger.trigger_count:
                continue

            # Check trigger constraints
            if fault.trigger.iteration is not None and fault.trigger.iteration != iteration:
                continue
            if fault.trigger.tool_name is not None and fault.trigger.tool_name != tool_name:
                continue
            if fault.trigger.target_ref is not None and fault.trigger.target_ref != target_ref:
                continue

            # Matched trigger condition
            self._trigger_counts[fault.fault_id] = current_count + 1
            record = {
                "fault_id": fault.fault_id,
                "fault_type": fault.fault_type.value,
                "iteration": iteration,
                "tool_name": tool_name,
                "target_ref": target_ref,
                "count": current_count + 1,
            }
            self._injected_events.append(record)
            return fault

        return None

    def get_injected_events(self) -> list[dict[str, Any]]:
        return list(self._injected_events)
