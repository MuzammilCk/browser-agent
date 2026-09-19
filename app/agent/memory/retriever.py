"""Deterministic memory retriever — Phase 9.

Performs deterministic property-based retrieval across semantic, episodic,
and experience memory layers without vector databases or embeddings.

Enforces:
- Small, bounded result sets so as not to overwhelm LLM reasoner context.
- Read-only retrieval (never mutates WorldState).
- Strict epistemic ranking: VERIFIED facts prioritized over INFERRED facts.
- Contextual filtering by portal, goal, user session, and active subjects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.memory.models import (
    EpisodicMemory,
    EpistemicStatus,
    ExperienceMemory,
    SemanticMemoryItem,
)
from app.agent.memory.store import MemoryStore

# Bounded caps for reasoner injection
MAX_RETRIEVED_SEMANTIC = 5
MAX_RETRIEVED_EPISODES = 3
MAX_RETRIEVED_EXPERIENCES = 3


@dataclass
class RetrievedMemories:
    """Bounded, prompt-safe collections of retrieved memories."""

    semantic_facts: list[SemanticMemoryItem] = field(default_factory=list)
    episodes: list[EpisodicMemory] = field(default_factory=list)
    experiences: list[ExperienceMemory] = field(default_factory=list)

    def to_context_dict(self) -> dict[str, Any]:
        """Convert into prompt-safe dictionary format for ReasoningContext."""
        facts_payload = []
        for f in self.semantic_facts[:MAX_RETRIEVED_SEMANTIC]:
            facts_payload.append({
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "status": f.epistemic_status.value,
                "confidence": round(f.confidence, 2),
            })

        episodes_payload = []
        for ep in self.episodes[:MAX_RETRIEVED_EPISODES]:
            episodes_payload.append({
                "goal": ep.goal,
                "summary": ep.summary,
                "outcome": ep.outcome.value,
            })

        experiences_payload = []
        for exp in self.experiences[:MAX_RETRIEVED_EXPERIENCES]:
            experiences_payload.append({
                "trigger_condition": exp.trigger_condition,
                "recovery_strategy": exp.recovery_strategy,
                "confidence": round(exp.confidence, 2),
            })

        return {
            "semantic_facts": facts_payload,
            "past_episodes": episodes_payload,
            "recovery_experiences": experiences_payload,
        }

    def is_empty(self) -> bool:
        return not (self.semantic_facts or self.episodes or self.experiences)


class MemoryRetriever:
    """Deterministic, query-based retriever for the four memory layers."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def retrieve(
        self,
        *,
        portal: str = "",
        goal: str = "",
        user_session_id: str = "",
        active_subjects: list[str] | None = None,
        task_type: str = "",
        trigger_condition: str | None = None,
    ) -> RetrievedMemories:
        """Retrieve bounded, relevant memories matching current execution context."""
        retrieved = RetrievedMemories()

        # 1. Retrieve current semantic memories
        # Query active subjects or general user/portal preferences
        candidates: list[SemanticMemoryItem] = []
        if active_subjects:
            for subj in active_subjects[:5]:
                items = await self._store.search_semantic_memories(
                    subject=subj,
                    portal=portal or None,
                    user_session_id=user_session_id or None,
                    is_current=True,
                    limit=MAX_RETRIEVED_SEMANTIC,
                )
                candidates.extend(items)

        # Also retrieve general user preferences/profile facts
        user_facts = await self._store.search_semantic_memories(
            portal=portal or None,
            user_session_id=user_session_id or None,
            is_current=True,
            limit=MAX_RETRIEVED_SEMANTIC,
        )
        candidates.extend(user_facts)

        # Deduplicate candidates by memory_id and prioritize VERIFIED > OBSERVED > INFERRED
        seen_ids = set()
        unique_semantic: list[SemanticMemoryItem] = []
        # Sort by epistemic status rank
        status_rank = {
            EpistemicStatus.VERIFIED: 4,
            EpistemicStatus.OBSERVED: 3,
            EpistemicStatus.INFERRED: 2,
            EpistemicStatus.STALE: 1,
        }
        candidates.sort(
            key=lambda x: (status_rank.get(x.epistemic_status, 1), x.confidence),
            reverse=True,
        )
        for item in candidates:
            if item.memory_id not in seen_ids:
                seen_ids.add(item.memory_id)
                unique_semantic.append(item)
                if len(unique_semantic) >= MAX_RETRIEVED_SEMANTIC:
                    break

        retrieved.semantic_facts = unique_semantic

        # 2. Retrieve recent relevant episodes for this portal
        episodes = await self._store.list_episodes(
            portal=portal or None,
            limit=MAX_RETRIEVED_EPISODES,
        )
        retrieved.episodes = episodes[:MAX_RETRIEVED_EPISODES]

        # 3. Retrieve relevant experience lessons
        experiences = await self._store.search_experiences(
            portal=portal or None,
            task_type=task_type or None,
            trigger_condition=trigger_condition or None,
            limit=MAX_RETRIEVED_EXPERIENCES,
        )
        retrieved.experiences = experiences[:MAX_RETRIEVED_EXPERIENCES]

        return retrieved
