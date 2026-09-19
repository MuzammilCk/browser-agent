"""Memory persistence protocol — Phase 9.

The AgentRuntime, AgentReasoner, and memory services interact strictly
via this protocol, never directly with SQL or database connections.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agent.memory.models import (
    CompactionRecord,
    EpisodicMemory,
    EpistemicStatus,
    ExperienceMemory,
    SemanticMemoryItem,
)


@runtime_checkable
class MemoryStore(Protocol):
    """Abstract storage boundary for semantic, episodic, experience memories and compaction records."""

    # ── Semantic Memory ────────────────────────────────────────────────────────
    async def create_semantic_memory(self, item: SemanticMemoryItem) -> SemanticMemoryItem:
        """Persist a new semantic memory item."""
        ...

    async def get_semantic_memory(self, memory_id: str) -> SemanticMemoryItem | None:
        """Fetch a semantic memory item by ID."""
        ...

    async def update_semantic_memory(self, item: SemanticMemoryItem) -> None:
        """Update an existing semantic memory item."""
        ...

    async def supersede_semantic_memory(
        self, old_id: str, new_item: SemanticMemoryItem
    ) -> SemanticMemoryItem:
        """Supersede an older semantic memory item with a new one.

        Marks old_id as is_current=False, valid_until=now, superseded_by=new_item.memory_id.
        Persists new_item with is_current=True.
        Preserves historical lineage and provenance.
        """
        ...

    async def search_semantic_memories(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        portal: str | None = None,
        user_session_id: str | None = None,
        is_current: bool | None = True,
        epistemic_status: EpistemicStatus | None = None,
        limit: int = 10,
    ) -> list[SemanticMemoryItem]:
        """Query semantic memories using deterministic filtering."""
        ...

    # ── Episodic Memory ────────────────────────────────────────────────────────
    async def create_episode(self, episode: EpisodicMemory) -> EpisodicMemory:
        """Persist a workflow episode milestone."""
        ...

    async def get_episode(self, episode_id: str) -> EpisodicMemory | None:
        """Fetch an episode by ID."""
        ...

    async def list_episodes(
        self,
        portal: str | None = None,
        run_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """List recent episodes ordered by creation timestamp descending."""
        ...

    # ── Experience Memory ──────────────────────────────────────────────────────
    async def create_experience(self, experience: ExperienceMemory) -> ExperienceMemory:
        """Persist a contextual execution lesson."""
        ...

    async def get_experience(self, experience_id: str) -> ExperienceMemory | None:
        """Fetch an experience memory item by ID."""
        ...

    async def search_experiences(
        self,
        portal: str | None = None,
        task_type: str | None = None,
        trigger_condition: str | None = None,
        limit: int = 5,
    ) -> list[ExperienceMemory]:
        """Query experience memories ordered by confidence descending."""
        ...

    async def update_experience_success(self, experience_id: str) -> None:
        """Increment success count and adjust confidence for a verified strategy."""
        ...

    # ── Compaction Records ─────────────────────────────────────────────────────
    async def record_compaction(self, record: CompactionRecord) -> None:
        """Persist an audit record of working memory compaction."""
        ...

    async def get_compaction_records(self, run_id: str) -> list[CompactionRecord]:
        """List compaction records for a run ordered chronologically."""
        ...
