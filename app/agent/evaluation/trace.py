"""Causal Tracing and Redaction System — Phase 12.

Key Invariants:
1. Trace is the primary evaluation artifact.
2. Preserves strict causal parent/child relationships (parent_event_id, correlation_id).
3. Secret redaction occurs BEFORE persistence/export using Phase 11 SensitivityLevel rules.
4. Schema validated exports (JSON and JSONL).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field

from app.agent.security.models import SensitivityLevel


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_trace_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class TraceEventType(str, Enum):
    """Types of structured runtime evaluation events."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    ITERATION_START = "iteration_start"
    OBSERVATION = "observation"
    REASONING_PROMPT = "reasoning_prompt"
    MODEL_DECISION = "model_decision"
    TOOL_PROPOSAL = "tool_proposal"
    TOOL_VALIDATION = "tool_validation"
    POLICY_EVALUATION = "policy_evaluation"
    HITL_INTERRUPT = "hitl_interrupt"
    HITL_RESUME = "hitl_resume"
    BROWSER_ACTION = "browser_action"
    BROWSER_RESULT = "browser_result"
    POST_OBSERVATION = "post_observation"
    VERIFICATION = "verification"
    WORLD_STATE_UPDATE = "world_state_update"
    MEMORY_CANDIDATE = "memory_candidate"
    MEMORY_WRITE = "memory_write"
    SPECIALIST_INVOCATION = "specialist_invocation"
    SPECIALIST_RESULT = "specialist_result"
    FAILURE_CLASSIFIED = "failure_classified"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    REPLAN_TRIGGERED = "replan_triggered"
    SECURITY_VIOLATION = "security_violation"
    BUDGET_CONSUMPTION = "budget_consumption"
    BUDGET_EXHAUSTION = "budget_exhaustion"
    FAULT_INJECTED = "fault_injected"


_SENSITIVE_KEY_PATTERNS = [
    re.compile(r"(password|passwd|pwd)", re.IGNORECASE),
    re.compile(r"(otp|one_time_password|totp)", re.IGNORECASE),
    re.compile(r"(pin|pincode_secret|mpin)", re.IGNORECASE),
    re.compile(r"(cvv|cvc|card_security_code)", re.IGNORECASE),
    re.compile(r"(token|auth_token|access_token|refresh_token|bearer)", re.IGNORECASE),
    re.compile(r"(cookie|session_cookie|session_id)", re.IGNORECASE),
    re.compile(r"(private_key|secret_key|api_key)", re.IGNORECASE),
    re.compile(r"(authorization|auth_header)", re.IGNORECASE),
]

_CONTENT_PATTERNS = [
    (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE), "[REDACTED:AUTH_TOKEN]"),
    (re.compile(r"\b\d{6}\b"), "[REDACTED:OTP_OR_PIN]"),  # 6-digit OTP defense-in-depth
]


def redact_trace_value(key: str | None, value: Any) -> Any:
    """Recursively scrub sensitive fields and content before persistence."""
    if value is None:
        return None

    # Check structural key sensitivity
    if key:
        for pat in _SENSITIVE_KEY_PATTERNS:
            if pat.search(key):
                return f"[REDACTED:{SensitivityLevel.RESTRICTED_SECRET.value}]"

    if isinstance(value, dict):
        return {k: redact_trace_value(k, v) for k, v in value.items()}

    if isinstance(value, list):
        return [redact_trace_value(None, item) for item in value]

    if isinstance(value, str):
        # Content pattern scrubbing (defense in depth)
        scrubbed = value
        for pat, repl in _CONTENT_PATTERNS:
            scrubbed = pat.sub(repl, scrubbed)
        return scrubbed

    return value


class TraceEvent(BaseModel):
    """Immutable structured trace event representing a single causal step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_schema_version: str = "1.0.0"
    event_id: str
    parent_event_id: str | None = None
    correlation_id: str | None = None
    run_id: str
    session_id: str = ""
    scenario_id: str
    iteration: int = 0
    timestamp: str
    event_type: TraceEventType
    subsystem: str
    component: str
    tool_name: str | None = None
    specialist_type: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    policy_decision: str | None = None
    verification_status: str | None = None
    world_state_version: int | None = None
    latency_ms: float | None = None
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None
    security_violation: dict[str, Any] | None = None
    failure_info: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceRecorder:
    """Thread-safe append-only trace recorder managing causality and redaction."""

    def __init__(self, run_id: str, scenario_id: str, session_id: str = "") -> None:
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.session_id = session_id
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()
        self._current_parent_id: str | None = None
        self._current_iteration = 0

    @property
    def current_parent_id(self) -> str | None:
        with self._lock:
            return self._current_parent_id

    @current_parent_id.setter
    def current_parent_id(self, parent_id: str | None) -> None:
        with self._lock:
            self._current_parent_id = parent_id

    def set_iteration(self, iteration: int) -> None:
        with self._lock:
            self._current_iteration = iteration

    def record(
        self,
        event_type: TraceEventType,
        *,
        subsystem: str,
        component: str,
        parent_event_id: str | None = None,
        correlation_id: str | None = None,
        tool_name: str | None = None,
        specialist_type: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        policy_decision: str | None = None,
        verification_status: str | None = None,
        world_state_version: int | None = None,
        latency_ms: float | None = None,
        token_usage: dict[str, int] | None = None,
        cost_usd: float | None = None,
        security_violation: dict[str, Any] | None = None,
        failure_info: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record and append an immutable, redacted trace event."""
        with self._lock:
            evt_id = new_trace_event_id()
            p_id = parent_event_id if parent_event_id is not None else self._current_parent_id

            # Apply strict Phase 11 redaction
            clean_input = redact_trace_value(None, input_summary or {})
            clean_output = redact_trace_value(None, output_summary or {})
            clean_meta = redact_trace_value(None, metadata or {})
            clean_sec = redact_trace_value(None, security_violation) if security_violation else None
            clean_fail = redact_trace_value(None, failure_info) if failure_info else None

            event = TraceEvent(
                trace_schema_version="1.0.0",
                event_id=evt_id,
                parent_event_id=p_id,
                correlation_id=correlation_id,
                run_id=self.run_id,
                session_id=self.session_id,
                scenario_id=self.scenario_id,
                iteration=self._current_iteration,
                timestamp=utc_now_iso(),
                event_type=event_type,
                subsystem=subsystem,
                component=component,
                tool_name=tool_name,
                specialist_type=specialist_type,
                input_summary=clean_input,
                output_summary=clean_output,
                policy_decision=policy_decision,
                verification_status=verification_status,
                world_state_version=world_state_version,
                latency_ms=latency_ms,
                token_usage=token_usage,
                cost_usd=cost_usd,
                security_violation=clean_sec,
                failure_info=clean_fail,
                metadata=clean_meta,
            )
            self._events.append(event)
            return event

    def get_events(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._events)

    def to_json(self, indent: int = 2) -> str:
        """Export all recorded trace events as validated JSON string."""
        with self._lock:
            dicts = [e.model_dump() for e in self._events]
            return json.dumps(dicts, indent=indent)

    def to_jsonl(self) -> str:
        """Export trace events in JSON Lines format."""
        with self._lock:
            lines = [json.dumps(e.model_dump()) for e in self._events]
            return "\n".join(lines)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
