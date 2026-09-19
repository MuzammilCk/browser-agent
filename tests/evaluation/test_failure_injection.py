"""Unit tests for Failure Injection Framework — Phase 12.

Tests:
1. Failure injection is disabled by default.
2. Fault triggers match on iteration, tool_name, and trigger count deterministically.
3. Fault activations are auditable and visible in injected records.
4. Failure injection cannot leak across independent runs.
"""

from __future__ import annotations

from app.agent.evaluation.injection import (
    FailureInjectionPlan,
    FailureInjector,
    FaultTrigger,
    FaultType,
    InjectedFault,
)


def test_failure_injection_disabled_by_default():
    """Default injector has enabled=False and triggers no faults."""
    injector = FailureInjector()
    assert injector.is_enabled is False

    fault = injector.should_inject(FaultType.STALE_REFERENCE, iteration=1, tool_name="click")
    assert fault is None
    assert len(injector.get_injected_events()) == 0


def test_failure_injection_triggers_deterministically_on_iteration_and_tool():
    """Injector triggers matching fault exactly once at target iteration and tool."""
    plan = FailureInjectionPlan(
        enabled=True,
        faults=[
            InjectedFault(
                fault_id="fault_stale_1",
                fault_type=FaultType.STALE_REFERENCE,
                trigger=FaultTrigger(iteration=2, tool_name="fill_field", trigger_count=1),
                description="Inject stale target ref on iteration 2 fill_field",
            )
        ],
    )

    injector = FailureInjector(plan)

    # Iteration 1: should not trigger
    f1 = injector.should_inject(FaultType.STALE_REFERENCE, iteration=1, tool_name="fill_field")
    assert f1 is None

    # Iteration 2 with different tool: should not trigger
    f2 = injector.should_inject(FaultType.STALE_REFERENCE, iteration=2, tool_name="click")
    assert f2 is None

    # Iteration 2 with matching tool: TRIGGERS
    f3 = injector.should_inject(FaultType.STALE_REFERENCE, iteration=2, tool_name="fill_field")
    assert f3 is not None
    assert f3.fault_id == "fault_stale_1"

    # Iteration 2 second call (count exceeded): should not trigger again
    f4 = injector.should_inject(FaultType.STALE_REFERENCE, iteration=2, tool_name="fill_field")
    assert f4 is None

    # Verify audit record
    events = injector.get_injected_events()
    assert len(events) == 1
    assert events[0]["fault_id"] == "fault_stale_1"
    assert events[0]["iteration"] == 2


def test_failure_injection_state_does_not_leak_across_instances():
    """Each FailureInjector instance maintains isolated state."""
    plan = FailureInjectionPlan(
        enabled=True,
        faults=[
            InjectedFault(
                fault_id="fault_budget_1",
                fault_type=FaultType.BUDGET_EXHAUSTION,
                trigger=FaultTrigger(iteration=1, trigger_count=1),
                description="Inject budget exhaustion",
            )
        ],
    )

    inj1 = FailureInjector(plan)
    assert inj1.should_inject(FaultType.BUDGET_EXHAUSTION, iteration=1) is not None

    # Second fresh injector on same plan starts fresh
    inj2 = FailureInjector(plan)
    assert inj2.should_inject(FaultType.BUDGET_EXHAUSTION, iteration=1) is not None
