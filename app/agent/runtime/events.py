"""Append-only event log — Phase 2 event model.

AgentEvent is immutable (frozen pydantic) and the AgentEventLog is
append-only with ordered replay (implementation_plan.md Phase 2:
"event append/replay"). Events carry safe metadata only — never raw
secrets, OTPs, or document contents (docs/SECURITY_MODEL.md).

Episodic memory will be event-backed from this log (Phase 9), which is
why events must be a durable, replayable record — not log lines.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class AgentEventType(str, Enum):
    """Event types for the runtime lifecycle.

    Phase 2 covers lifecycle/state/event/checkpoint/decision events.
    Phase 3-4 will add TOOL_* events; the enum is open for extension.
    """

    RUN_STARTED = "run_started"
    STATE_CHANGED = "state_changed"
    INTERRUPT_RAISED = "interrupt_raised"
    INTERRUPT_RESOLVED = "interrupt_resolved"
    CHECKPOINT_CREATED = "checkpoint_created"
    RUN_RESTORED = "run_restored"
    DECISION_RECORDED = "decision_recorded"
    PLAN_UPDATED = "plan_updated"
    SUBGOAL_UPDATED = "subgoal_updated"
    USAGE_UPDATED = "usage_updated"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_ABORTED = "run_aborted"
    NOTE = "note"


class AgentEvent(BaseModel):
    """One immutable runtime event.

    Frozen and extra-fields-forbidden so a recorded event cannot be
    mutated after the fact. ``sequence`` is assigned by the log at append
    time and defines the replay order.
    """

    model_config = ConfigDict(frozen=True)

    sequence: int = Field(description="Monotonic, assigned by AgentEventLog")
    event_type: AgentEventType
    run_id: str
    timestamp: str = Field(description="ISO-8601 UTC")
    iteration: int = Field(default=0)
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe structured payload (no secrets, no DOM refs as state)",
    )
    message: str = Field(default="", description="Human-readable summary")


class AgentEventLog(BaseModel):
    """Append-only, in-memory event log with ordered replay.

    Thread-safe via a lock; append is the only mutation. The log belongs
    to the run state's durability envelope: it is included in checkpoints
    so a restored run replays its full history (Phase 2 exit criterion).
    """

    run_id: str = Field(default="")
    events: list[AgentEvent] = Field(default_factory=list)
    # Private, never serialized: concurrency guard for append.
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def append(
        self,
        event_type: AgentEventType,
        *,
        run_id: str | None = None,
        iteration: int = 0,
        data: dict[str, Any] | None = None,
        message: str = "",
        timestamp: str = "",
    ) -> AgentEvent:
        """Append an event; sequence is assigned here, never by callers."""
        with self._lock:
            seq = len(self.events) + 1
            event = AgentEvent(
                sequence=seq,
                event_type=event_type,
                run_id=run_id or self.run_id,
                timestamp=timestamp,
                iteration=iteration,
                data=dict(data or {}),
                message=message,
            )
            self.events.append(event)
            return event

    def replay(self) -> Iterator[AgentEvent]:
        """Yield events in deterministic sequence order."""
        return iter(self.events)

    def events_of_type(self, event_type: AgentEventType) -> list[AgentEvent]:
        return [e for e in self.events if e.event_type == event_type]

    def last(self) -> AgentEvent | None:
        return self.events[-1] if self.events else None

    def __len__(self) -> int:
        return len(self.events)
