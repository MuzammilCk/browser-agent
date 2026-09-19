"""Unit tests for TraceRecorder and causal event logging — Phase 12.

Tests:
1. Trace records scenario identity and schema version.
2. Trace preserves causal parent/child relationships.
3. Trace captures all required lifecycle, decision, tool, policy, and verification events.
4. Schema-valid JSON and JSONL export.
"""

from __future__ import annotations

import json
from app.agent.evaluation.trace import TraceEventType, TraceRecorder


def test_trace_contains_scenario_identity_and_version():
    """Trace events carry schema version, run ID, and scenario ID."""
    recorder = TraceRecorder(run_id="run_001", scenario_id="golden_01", session_id="sess_001")
    evt = recorder.record(
        TraceEventType.RUN_START,
        subsystem="evaluation",
        component="ScenarioRunner",
        input_summary={"goal": "Test goal"},
    )

    assert evt.trace_schema_version == "1.0.0"
    assert evt.run_id == "run_001"
    assert evt.scenario_id == "golden_01"
    assert evt.session_id == "sess_001"
    assert evt.event_id.startswith("evt_")


def test_trace_preserves_causal_parent_child_relationships():
    """Parent event IDs chain causally across iterations and steps."""
    recorder = TraceRecorder(run_id="run_002", scenario_id="golden_02")

    # Step 1: Run Start
    e1 = recorder.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")

    # Step 2: Iteration 1 (child of run start)
    recorder.current_parent_id = e1.event_id
    recorder.set_iteration(1)
    e2 = recorder.record(TraceEventType.ITERATION_START, subsystem="runtime", component="AgentRuntime")
    assert e2.parent_event_id == e1.event_id

    # Step 3: Model Decision (child of iteration 1)
    recorder.current_parent_id = e2.event_id
    e3 = recorder.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner")
    assert e3.parent_event_id == e2.event_id

    # Step 4: Tool Proposal (child of model decision)
    recorder.current_parent_id = e3.event_id
    e4 = recorder.record(TraceEventType.TOOL_PROPOSAL, subsystem="tools", component="ToolRegistry", tool_name="click")
    assert e4.parent_event_id == e3.event_id


def test_trace_captures_full_subsystem_event_types():
    """Recorder faithfully captures all mandated runtime and safety event types."""
    recorder = TraceRecorder(run_id="run_003", scenario_id="golden_03")

    # Policy evaluation
    p_evt = recorder.record(
        TraceEventType.POLICY_EVALUATION,
        subsystem="policy",
        component="PolicyEngine",
        policy_decision="require_confirmation",
    )
    assert p_evt.policy_decision == "require_confirmation"

    # HITL interrupt
    h_evt = recorder.record(
        TraceEventType.HITL_INTERRUPT,
        subsystem="interrupts",
        component="AgentRuntime",
        input_summary={"reason": "OTP_REQUIRED"},
    )
    assert h_evt.input_summary["reason"] == "OTP_REQUIRED"

    # Verification
    v_evt = recorder.record(
        TraceEventType.VERIFICATION,
        subsystem="verification",
        component="ActionVerifier",
        verification_status="verified",
    )
    assert v_evt.verification_status == "verified"

    # World state update
    w_evt = recorder.record(
        TraceEventType.WORLD_STATE_UPDATE,
        subsystem="world",
        component="AgentWorldState",
        world_state_version=5,
    )
    assert w_evt.world_state_version == 5

    # Memory write
    m_evt = recorder.record(
        TraceEventType.MEMORY_WRITE,
        subsystem="memory",
        component="MemoryStore",
        input_summary={"key": "USER.full_name"},
    )
    assert m_evt.input_summary["key"] == "USER.full_name"

    # Specialist invocation
    s_evt = recorder.record(
        TraceEventType.SPECIALIST_INVOCATION,
        subsystem="specialists",
        component="SpecialistRegistry",
        specialist_type="form_semantics",
    )
    assert s_evt.specialist_type == "form_semantics"


def test_trace_json_and_jsonl_export_are_schema_valid():
    """Exported JSON and JSONL strings parse cleanly and validate against TraceEvent schema."""
    recorder = TraceRecorder(run_id="run_004", scenario_id="golden_04")
    recorder.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")
    recorder.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner")
    recorder.record(TraceEventType.RUN_END, subsystem="runtime", component="AgentRuntime")

    # JSON export
    raw_json = recorder.to_json()
    parsed_json = json.loads(raw_json)
    assert isinstance(parsed_json, list)
    assert len(parsed_json) == 3
    assert parsed_json[0]["event_type"] == "run_start"

    # JSONL export
    raw_jsonl = recorder.to_jsonl()
    lines = raw_jsonl.strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert "event_id" in obj
        assert "trace_schema_version" in obj
