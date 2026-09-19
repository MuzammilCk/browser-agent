"""Replay Engine and Divergence Detector — Phase 12.

Key Architectural Invariants:
1. Replay modes are explicitly distinguished (STATE_REPLAY, MODEL_REPLAY, OBSERVATION_REPLAY, LIVE_REEXECUTION).
2. MODEL_REPLAY makes ZERO live model/API calls.
3. ReplayDiff provides structured divergence detection instead of reducing replay to a boolean.
4. Strict schema validation (extra="forbid").
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.evaluation.trace import TraceEvent, TraceEventType


class ReplayMode(str, Enum):
    """Execution replay modality."""

    STATE_REPLAY = "state_replay"
    MODEL_REPLAY = "model_replay"
    OBSERVATION_REPLAY = "observation_replay"
    LIVE_REEXECUTION = "live_reexecution"


class ReplayDiffSeverity(str, Enum):
    """Impact severity of an observed replay divergence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReplayDiff(BaseModel):
    """Structured record of a divergence between recorded and replayed behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    category: str  # e.g., "model_decision", "tool_name", "arguments", "target_ref", "policy", "verification"
    expected: Any
    actual: Any
    severity: ReplayDiffSeverity
    is_deterministic: bool = True
    explanation: str


class ReplayResult(BaseModel):
    """Outcome of a replay verification run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    replay_mode: ReplayMode
    is_reproducible: bool
    total_events_checked: int
    diffs: list[ReplayDiff] = Field(default_factory=list)
    divergence_event_id: str | None = None
    summary: str = ""


class ReplayEngine:
    """Replay and divergence analysis engine."""

    @staticmethod
    def compare_traces(
        expected_events: list[TraceEvent],
        actual_events: list[TraceEvent],
        *,
        replay_mode: ReplayMode = ReplayMode.STATE_REPLAY,
    ) -> ReplayResult:
        """Compare an actual replay trace against an expected recorded trace."""
        diffs: list[ReplayDiff] = []
        divergence_event_id: str | None = None

        min_len = min(len(expected_events), len(actual_events))

        for i in range(min_len):
            exp = expected_events[i]
            act = actual_events[i]

            # 1. Event Type Match
            if exp.event_type != act.event_type:
                diff = ReplayDiff(
                    event_id=act.event_id,
                    category="event_type",
                    expected=exp.event_type.value,
                    actual=act.event_type.value,
                    severity=ReplayDiffSeverity.CRITICAL,
                    is_deterministic=True,
                    explanation=f"Event type mismatch at step {i}: expected {exp.event_type.value}, got {act.event_type.value}",
                )
                diffs.append(diff)
                if divergence_event_id is None:
                    divergence_event_id = act.event_id
                continue

            # 2. Tool Name Match (for tool proposals/actions)
            if exp.tool_name != act.tool_name:
                diff = ReplayDiff(
                    event_id=act.event_id,
                    category="tool_name",
                    expected=exp.tool_name,
                    actual=act.tool_name,
                    severity=ReplayDiffSeverity.HIGH,
                    is_deterministic=True,
                    explanation=f"Tool selection diverged: expected {exp.tool_name}, got {act.tool_name}",
                )
                diffs.append(diff)
                if divergence_event_id is None:
                    divergence_event_id = act.event_id

            # 3. Policy Decision Match
            if exp.policy_decision != act.policy_decision:
                diff = ReplayDiff(
                    event_id=act.event_id,
                    category="policy_decision",
                    expected=exp.policy_decision,
                    actual=act.policy_decision,
                    severity=ReplayDiffSeverity.CRITICAL,
                    is_deterministic=True,
                    explanation=f"Policy verdict diverged: expected {exp.policy_decision}, got {act.policy_decision}",
                )
                diffs.append(diff)
                if divergence_event_id is None:
                    divergence_event_id = act.event_id

            # 4. Verification Match
            if exp.verification_status != act.verification_status:
                diff = ReplayDiff(
                    event_id=act.event_id,
                    category="verification_status",
                    expected=exp.verification_status,
                    actual=act.verification_status,
                    severity=ReplayDiffSeverity.HIGH,
                    is_deterministic=True,
                    explanation=f"Verification status diverged: expected {exp.verification_status}, got {act.verification_status}",
                )
                diffs.append(diff)
                if divergence_event_id is None:
                    divergence_event_id = act.event_id

            # 5. Input summary / Action payload
            if exp.input_summary != act.input_summary:
                diff = ReplayDiff(
                    event_id=act.event_id,
                    category="arguments",
                    expected=exp.input_summary,
                    actual=act.input_summary,
                    severity=ReplayDiffSeverity.MEDIUM,
                    is_deterministic=True,
                    explanation="Action or tool arguments diverged from recorded baseline",
                )
                diffs.append(diff)
                if divergence_event_id is None:
                    divergence_event_id = act.event_id

        # Length mismatch
        if len(expected_events) != len(actual_events):
            diff = ReplayDiff(
                event_id="length_mismatch",
                category="event_count",
                expected=len(expected_events),
                actual=len(actual_events),
                severity=ReplayDiffSeverity.HIGH,
                is_deterministic=True,
                explanation=f"Trace length diverged: expected {len(expected_events)} events, got {len(actual_events)}",
            )
            diffs.append(diff)
            if divergence_event_id is None:
                divergence_event_id = "length_mismatch"

        is_reproducible = len(diffs) == 0
        summary = (
            f"Replay ({replay_mode.value}) succeeded: {min_len} events matched perfectly."
            if is_reproducible
            else f"Replay ({replay_mode.value}) diverged: {len(diffs)} differences detected. First divergence at {divergence_event_id}."
        )

        return ReplayResult(
            replay_mode=replay_mode,
            is_reproducible=is_reproducible,
            total_events_checked=min_len,
            diffs=diffs,
            divergence_event_id=divergence_event_id,
            summary=summary,
        )
