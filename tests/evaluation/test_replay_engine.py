"""Unit tests for Replay Engine and Divergence Detector — Phase 12.

Tests:
1. Replay matches identical traces perfectly.
2. Replay detects divergence in event type, tool selection, policy verdict, arguments.
3. Structured ReplayDiff identifies the exact step and causal reason.
4. Incomplete or mismatched trace fails replay explicitly.
"""

from __future__ import annotations

from app.agent.evaluation.replay import ReplayDiffSeverity, ReplayEngine, ReplayMode
from app.agent.evaluation.trace import TraceEventType, TraceRecorder


def test_replay_matches_identical_traces():
    """Identical recorded and replayed traces yield perfect reproducibility."""
    rec1 = TraceRecorder(run_id="run_orig", scenario_id="golden_rep")
    rec1.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")
    rec1.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner", tool_name="click")
    rec1.record(TraceEventType.RUN_END, subsystem="runtime", component="AgentRuntime")

    rec2 = TraceRecorder(run_id="run_replay", scenario_id="golden_rep")
    rec2.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")
    rec2.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner", tool_name="click")
    rec2.record(TraceEventType.RUN_END, subsystem="runtime", component="AgentRuntime")

    result = ReplayEngine.compare_traces(rec1.get_events(), rec2.get_events(), replay_mode=ReplayMode.MODEL_REPLAY)
    assert result.is_reproducible is True
    assert len(result.diffs) == 0
    assert result.replay_mode == ReplayMode.MODEL_REPLAY
    assert result.divergence_event_id is None


def test_replay_detects_tool_selection_divergence():
    """Tool choice divergence generates a structured HIGH severity ReplayDiff."""
    rec_expected = TraceRecorder(run_id="exp", scenario_id="golden_rep")
    rec_expected.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner", tool_name="click")

    rec_actual = TraceRecorder(run_id="act", scenario_id="golden_rep")
    rec_actual.record(TraceEventType.MODEL_DECISION, subsystem="reasoning", component="AgentReasoner", tool_name="fill_field")

    result = ReplayEngine.compare_traces(rec_expected.get_events(), rec_actual.get_events(), replay_mode=ReplayMode.MODEL_REPLAY)
    assert result.is_reproducible is False
    assert len(result.diffs) == 1

    diff = result.diffs[0]
    assert diff.category == "tool_name"
    assert diff.expected == "click"
    assert diff.actual == "fill_field"
    assert diff.severity == ReplayDiffSeverity.HIGH
    assert diff.is_deterministic is True
    assert "Tool selection diverged" in diff.explanation


def test_replay_detects_policy_decision_divergence():
    """Policy decision divergence generates a CRITICAL ReplayDiff."""
    rec_expected = TraceRecorder(run_id="exp", scenario_id="golden_rep")
    rec_expected.record(TraceEventType.POLICY_EVALUATION, subsystem="policy", component="PolicyEngine", policy_decision="allow")

    rec_actual = TraceRecorder(run_id="act", scenario_id="golden_rep")
    rec_actual.record(TraceEventType.POLICY_EVALUATION, subsystem="policy", component="PolicyEngine", policy_decision="require_confirmation")

    result = ReplayEngine.compare_traces(rec_expected.get_events(), rec_actual.get_events())
    assert result.is_reproducible is False
    assert len(result.diffs) == 1
    assert result.diffs[0].category == "policy_decision"
    assert result.diffs[0].severity == ReplayDiffSeverity.CRITICAL


def test_replay_detects_length_truncation_or_drift():
    """Incomplete trace with missing terminal events is flagged explicitly."""
    rec_expected = TraceRecorder(run_id="exp", scenario_id="golden_rep")
    rec_expected.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")
    rec_expected.record(TraceEventType.RUN_END, subsystem="runtime", component="AgentRuntime")

    rec_actual = TraceRecorder(run_id="act", scenario_id="golden_rep")
    rec_actual.record(TraceEventType.RUN_START, subsystem="runtime", component="AgentRuntime")
    # Truncated: RUN_END missing

    result = ReplayEngine.compare_traces(rec_expected.get_events(), rec_actual.get_events())
    assert result.is_reproducible is False
    assert any(d.category == "event_count" for d in result.diffs)
