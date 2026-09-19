"""AgentSession — Phase 2 persistent session envelope.

An AgentSession is the durable container that outlives individual runs
and process restarts (context.md: "Persistent AgentSession"). It owns
runs by reference (run_id), tracks which run is active, and — as a
top-level pydantic model — it serializes and restores as a whole.

Run state itself lives in AgentRunState/AgentCheckpoint; the session
references runs so that sessions stay small while run state stays
self-contained.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.runtime.checkpoint import utc_now_iso


class AgentSession(BaseModel):
    """Durable session container.

    Invariants:
    - ``active_run_id`` is None iff no run is active.
    - ``run_ids`` preserves creation order.
    - Restoring a session restores its identity, history and active
      pointer; run payloads are restored via checkpoints.
    """

    session_id: str = Field(default="", description="Unique session id")
    created_at: str = Field(default="", description="ISO-8601 UTC")
    updated_at: str = Field(default="", description="ISO-8601 UTC")

    # Owned runs, in creation order
    run_ids: list[str] = Field(
        default_factory=list, description="All runs created in this session"
    )
    active_run_id: str | None = Field(
        default=None, description="Currently active run, if any"
    )

    # Session-level metadata
    label: str = Field(
        default="", description="Human-readable label (e.g. portal name)"
    )
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Safe metadata"
    )

    def start_run(self, run_id: str) -> None:
        """Register a run and make it active."""
        if run_id not in self.run_ids:
            self.run_ids.append(run_id)
        self.active_run_id = run_id
        self.updated_at = utc_now_iso()

    def end_run(self, run_id: str) -> None:
        """Clear the active pointer when the run reaches a terminal state."""
        if self.active_run_id == run_id:
            self.active_run_id = None
            self.updated_at = utc_now_iso()

    def is_active(self, run_id: str) -> bool:
        return self.active_run_id == run_id
