"""Checkpoints — Phase 2 & Phase 8 serialization/restoration boundary.

An AgentCheckpoint is the complete, self-contained serialization of one
agent run: state + full event log + durable interrupts + approval bindings.
Restoring a checkpoint yields a run indistinguishable logically from the one
that was paused, while never trusting stale browser handles or stale DOM refs.

Phase 8 introduces PostgreSQL-backed persistence via PostgresCheckpointStore
and explicit HumanInterrupt and ApprovalBinding models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.agent.interrupts.models import ApprovalBinding, HumanInterrupt
from app.agent.runtime.events import AgentEvent
from app.agent.runtime.state import AgentRunState

if TYPE_CHECKING:
    from app.agent.world.models import AgentWorldState

CHECKPOINT_FORMAT_VERSION = 2
MIN_SUPPORTED_FORMAT_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncompatibleCheckpointSchema(ValueError):
    """Raised when checkpoint format_version is incompatible."""


class AgentCheckpoint(BaseModel):
    """Complete serialization of one agent run.

    ``format_version`` lets migrations upgrade stored checkpoints forward.
    Checkpoints store logical state only: never live Playwright objects,
    browser handles, raw passwords, OTPs, or document contents.
    """

    format_version: int = CHECKPOINT_FORMAT_VERSION
    checkpoint_id: str = Field(default="", description="Unique checkpoint id")
    run_id: str = Field(description="Run this checkpoint captures")
    created_at: str = Field(default="", description="ISO-8601 UTC")
    expires_at: str | None = Field(default=None, description="ISO-8601 UTC expiration")
    reason: str = Field(
        default="",
        description="Why the checkpoint was taken (interrupt, manual, shutdown)",
    )
    state_version: int = Field(default=0, description="WorldState version captured")
    recovery_cursor: int = Field(default=0, description="Recovery cursor sequence")
    state: AgentRunState = Field(description="Full run state")
    events: list[AgentEvent] = Field(
        default_factory=list, description="Full append-only event log"
    )
    human_interrupt: HumanInterrupt | None = Field(
        default=None, description="Pending human interrupt if paused"
    )
    approval_binding: ApprovalBinding | None = Field(
        default=None, description="Approval binding if approved by human"
    )

    def validate_schema(self) -> None:
        """Validate schema version. Fail closed if incompatible."""
        if (
            self.format_version < MIN_SUPPORTED_FORMAT_VERSION
            or self.format_version > CHECKPOINT_FORMAT_VERSION
        ):
            raise IncompatibleCheckpointSchema(
                f"Unsupported checkpoint schema version {self.format_version}. "
                f"Supported versions: [{MIN_SUPPORTED_FORMAT_VERSION}..{CHECKPOINT_FORMAT_VERSION}]"
            )

    # ------------------------------------------------------------------
    # Serialization / restoration
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Lossless JSON serialization."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> AgentCheckpoint:
        """Restore from JSON. Raises pydantic ValidationError on
        corrupt/incompatible input — fail closed, never partially load."""
        cp = cls.model_validate_json(raw)
        cp.validate_schema()
        return cp

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCheckpoint:
        cp = cls.model_validate(data)
        cp.validate_schema()
        return cp


@runtime_checkable
class CheckpointStore(Protocol):
    """Storage boundary for checkpoints."""

    def save(self, checkpoint: AgentCheckpoint) -> None: ...

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None: ...

    def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None: ...

    def list_for_run(self, run_id: str) -> list[str]: ...


class InMemoryCheckpointStore:
    """In-memory CheckpointStore supporting both sync Phase 2 and async Phase 8 calls."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, AgentCheckpoint] = {}

    def save(self, checkpoint: AgentCheckpoint) -> None:
        cloned = AgentCheckpoint.from_json(checkpoint.to_json())
        self._checkpoints[checkpoint.checkpoint_id] = cloned

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None:
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            return None
        return AgentCheckpoint.from_json(cp.to_json())

    def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None:
        latest: AgentCheckpoint | None = None
        for cp in self._checkpoints.values():
            if cp.run_id == run_id and (
                latest is None or cp.created_at > latest.created_at
            ):
                latest = cp
        if latest is None:
            return None
        return AgentCheckpoint.from_json(latest.to_json())

    def list_for_run(self, run_id: str) -> list[str]:
        return sorted(
            cp.checkpoint_id
            for cp in self._checkpoints.values()
            if cp.run_id == run_id
        )

    # Async aliases for CheckpointStore protocol
    async def save_checkpoint(self, checkpoint: AgentCheckpoint) -> None:
        self.save(checkpoint)

    async def load_checkpoint(self, checkpoint_id: str) -> AgentCheckpoint | None:
        return self.load(checkpoint_id)
