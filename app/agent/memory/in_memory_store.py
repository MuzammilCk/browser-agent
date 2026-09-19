"""In-memory implementation of MemoryStore for unit testing — Phase 9."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.agent.memory.models import (
    CompactionRecord,
    EpisodicMemory,
    EpistemicStatus,
    ExperienceMemory,
    SemanticMemoryItem,
    utc_now_iso,
)


class InMemoryMemoryStore:
    """Thread-safe, in-memory implementation of MemoryStore for fast unit testing."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._semantic: dict[str, SemanticMemoryItem] = {}
        self._episodes: dict[str, EpisodicMemory] = {}
        self._experiences: dict[str, ExperienceMemory] = {}
        self._compactions: list[CompactionRecord] = []

    # ── Semantic Memory ────────────────────────────────────────────────────────
    async def create_semantic_memory(self, item: SemanticMemoryItem) -> SemanticMemoryItem:
        async with self._lock:
            stored = item.model_copy(deep=True)
            self._semantic[stored.memory_id] = stored
            return stored

    async def get_semantic_memory(self, memory_id: str) -> SemanticMemoryItem | None:
        async with self._lock:
            item = self._semantic.get(memory_id)
            return item.model_copy(deep=True) if item else None

    async def update_semantic_memory(self, item: SemanticMemoryItem) -> None:
        async with self._lock:
            if item.memory_id not in self._semantic:
                raise KeyError(f"Semantic memory not found: {item.memory_id}")
            updated = item.model_copy(deep=True)
            updated.updated_at = utc_now_iso()
            self._semantic[updated.memory_id] = updated

    async def supersede_semantic_memory(
        self, old_id: str, new_item: SemanticMemoryItem
    ) -> SemanticMemoryItem:
        async with self._lock:
            old = self._semantic.get(old_id)
            if old is None:
                raise KeyError(f"Cannot supersede missing semantic memory: {old_id}")
            now = utc_now_iso()
            old.is_current = False
            old.valid_until = now
            old.superseded_by = new_item.memory_id
            old.updated_at = now

            stored_new = new_item.model_copy(deep=True)
            stored_new.is_current = True
            stored_new.valid_from = now
            stored_new.updated_at = now
            self._semantic[stored_new.memory_id] = stored_new
            return stored_new

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
        async with self._lock:
            results: list[SemanticMemoryItem] = []
            for item in self._semantic.values():
                if is_current is not None and item.is_current != is_current:
                    continue
                if subject and item.subject != subject:
                    continue
                if predicate and item.predicate != predicate:
                    continue
                if portal and item.portal and item.portal != portal:
                    continue
                if user_session_id and item.user_session_id and item.user_session_id != user_session_id:
                    continue
                if epistemic_status and item.epistemic_status != epistemic_status:
                    continue
                results.append(item.model_copy(deep=True))

            # Order by updated_at descending
            results.sort(key=lambda x: x.updated_at, reverse=True)
            return results[:limit]

    # ── Episodic Memory ────────────────────────────────────────────────────────
    async def create_episode(self, episode: EpisodicMemory) -> EpisodicMemory:
        async with self._lock:
            stored = episode.model_copy(deep=True)
            self._episodes[stored.episode_id] = stored
            return stored

    async def get_episode(self, episode_id: str) -> EpisodicMemory | None:
        async with self._lock:
            ep = self._episodes.get(episode_id)
            return ep.model_copy(deep=True) if ep else None

    async def list_episodes(
        self,
        portal: str | None = None,
        run_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        async with self._lock:
            results: list[EpisodicMemory] = []
            for ep in self._episodes.values():
                if portal and ep.portal and ep.portal != portal:
                    continue
                if run_id and ep.run_id != run_id:
                    continue
                results.append(ep.model_copy(deep=True))
            results.sort(key=lambda x: x.created_at, reverse=True)
            return results[:limit]

    # ── Experience Memory ──────────────────────────────────────────────────────
    async def create_experience(self, experience: ExperienceMemory) -> ExperienceMemory:
        async with self._lock:
            stored = experience.model_copy(deep=True)
            self._experiences[stored.experience_id] = stored
            return stored

    async def get_experience(self, experience_id: str) -> ExperienceMemory | None:
        async with self._lock:
            exp = self._experiences.get(experience_id)
            return exp.model_copy(deep=True) if exp else None

    async def search_experiences(
        self,
        portal: str | None = None,
        task_type: str | None = None,
        trigger_condition: str | None = None,
        limit: int = 5,
    ) -> list[ExperienceMemory]:
        async with self._lock:
            results: list[ExperienceMemory] = []
            for exp in self._experiences.values():
                if portal and exp.portal and exp.portal != portal:
                    continue
                if task_type and exp.task_type and exp.task_type != task_type:
                    continue
                if trigger_condition and exp.trigger_condition != trigger_condition:
                    continue
                results.append(exp.model_copy(deep=True))
            # Sort by confidence descending, then success_count descending
            results.sort(key=lambda x: (x.confidence, x.success_count), reverse=True)
            return results[:limit]

    async def update_experience_success(self, experience_id: str) -> None:
        async with self._lock:
            exp = self._experiences.get(experience_id)
            if exp is not None:
                exp.success_count += 1
                # Increment confidence toward 1.0 asymptotically
                exp.confidence = min(0.95, exp.confidence + 0.1)
                exp.updated_at = utc_now_iso()

    # ── Compaction Records ─────────────────────────────────────────────────────
    async def record_compaction(self, record: CompactionRecord) -> None:
        async with self._lock:
            self._compactions.append(record.model_copy(deep=True))

    async def get_compaction_records(self, run_id: str) -> list[CompactionRecord]:
        async with self._lock:
            return [
                c.model_copy(deep=True)
                for c in self._compactions
                if c.run_id == run_id
            ]
