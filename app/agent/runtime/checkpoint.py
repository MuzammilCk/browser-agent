"""Checkpoints — Phase 2 serialization/restoration boundary.

An AgentCheckpoint is the complete, self-contained serialization of one
agent run: state + full event log. Restoring a checkpoint yields a run
indistinguishable — logically — from the one that was paused (Phase 2
exit criterion: "A paused run can be serialized and restored without
losing logical task state").

The store is a protocol with an in-memory implementation. SQLite
persistence and process-restart durability arrive in Phase 8
(implementation_plan.md); building them now would front-run the durable
interrupt work they exist to support.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.agent.runtime.events import AgentEvent, AgentEventLog
from app.agent.runtime.state import AgentRunState

CHECKPOINT_FORMAT_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentCheckpoint(BaseModel):
    """Complete serialization of one agent run.

    ``format_version`` lets Phase 8 migrate stored checkpoints forward.
    """

    format_version: int = CHECKPOINT_FORMAT_VERSION
    checkpoint_id: str = Field(default="", description="Unique checkpoint id")
    run_id: str = Field(description="Run this checkpoint captures")
    created_at: str = Field(default="", description="ISO-8601 UTC")
    reason: str = Field(
        default="",
        description="Why the checkpoint was taken (interrupt, manual, shutdown)",
    )
    state: AgentRunState = Field(description="Full run state")
    events: list[AgentEvent] = Field(
        default_factory=list, description="Full append-only event log"
    )

    # ------------------------------------------------------------------
    # Serialization / restoration
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Lossless JSON serialization (Phase 2 exit criterion)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> AgentCheckpoint:
        """Restore from JSON. Raises pydantic ValidationError on
        corrupt/incompatible input — fail closed, never partially load."""
        return cls.model_validate_json(raw)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCheckpoint:
        return cls.model_validate(data)


@runtime_checkable
class CheckpointStore(Protocol):
    """Storage boundary for checkpoints."""

    def save(self, checkpoint: AgentCheckpoint) -> None: ...

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None: ...

    def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None: ...

    def list_for_run(self, run_id: str) -> list[str]: ...


class InMemoryCheckpointStore:
    """In-memory CheckpointStore. Durability decisions (SQLite,
    process-restart resume) are Phase 8 scope; this store is the seam
    they will implement against."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, AgentCheckpoint] = {}

    def save(self, checkpoint: AgentCheckpoint) -> None:
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None:
        return self._checkpoints.get(checkpoint_id)

    def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None:
        latest: AgentCheckpoint | None = None
        for cp in self._checkpoints.values():
            if cp.run_id == run_id and (
                latest is None or cp.created_at > latest.created_at
            ):
                latest = cp
        return latest

    def list_for_run(self, run_id: str) -> list[str]:
        return sorted(
            cp.checkpoint_id
            for cp in self._checkpoints.values()
            if cp.run_id == run_id
        )
