"""PostgreSQL MemoryStore implementation — Phase 9.

Uses asyncpg with connection pooling, transactional multi-row consistency,
provenance preservation, and deterministic indexing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import asyncpg

from app.agent.memory.models import (
    AuthorType,
    CompactionRecord,
    EpisodeOutcome,
    EpisodicMemory,
    EpistemicStatus,
    ExperienceMemory,
    MemoryProvenance,
    SemanticMemoryItem,
    utc_now_iso,
)
from app.agent.memory.schema import apply_memory_schema


def _parse_dt(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class PostgresMemoryStore:
    """Production-grade PostgreSQL memory store backed by asyncpg."""

    def __init__(self, dsn: str, min_connections: int = 1, max_connections: int = 10) -> None:
        self._dsn = dsn
        self._min_conn = min_connections
        self._max_conn = max_connections
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Initialize connection pool and apply schema migrations."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_conn,
                max_size=self._max_conn,
            )
            await self.initialize_schema()

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def initialize_schema(self) -> None:
        """Ensure all Phase 9 memory tables and indexes exist."""
        pool = self._ensure_pool()
        await apply_memory_schema(pool)

    def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresMemoryStore is not connected. Call connect() first.")
        return self._pool

    # ── Semantic Memory ────────────────────────────────────────────────────────

    async def create_semantic_memory(self, item: SemanticMemoryItem) -> SemanticMemoryItem:
        pool = self._ensure_pool()
        created_dt = _parse_dt(item.created_at) or datetime.now(timezone.utc)
        updated_dt = _parse_dt(item.updated_at) or datetime.now(timezone.utc)
        valid_from_dt = _parse_dt(item.valid_from) or datetime.now(timezone.utc)
        valid_until_dt = _parse_dt(item.valid_until)

        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Insert into semantic_memories
                await conn.execute(
                    """
                    INSERT INTO semantic_memories (
                        memory_id, subject, predicate, value_json, portal, user_session_id,
                        confidence, epistemic_status, created_at, updated_at, valid_from,
                        valid_until, is_current, superseded_by, provenance_json, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    """,
                    item.memory_id,
                    item.subject,
                    item.predicate,
                    json.dumps(item.value),
                    item.portal,
                    item.user_session_id,
                    float(item.confidence),
                    item.epistemic_status.value,
                    created_dt,
                    updated_dt,
                    valid_from_dt,
                    valid_until_dt,
                    item.is_current,
                    item.superseded_by,
                    json.dumps(item.provenance.model_dump(mode="json")),
                    json.dumps(item.metadata),
                )

                # 2. Insert into memory_provenance
                prov = item.provenance
                prov_dt = _parse_dt(prov.timestamp) or datetime.now(timezone.utc)
                await conn.execute(
                    """
                    INSERT INTO memory_provenance (
                        memory_id, source, author_type, run_id, observation_id,
                        tool_name, state_version, timestamp, details
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    item.memory_id,
                    prov.source,
                    prov.author_type.value,
                    prov.run_id,
                    prov.observation_id,
                    prov.tool_name,
                    prov.state_version,
                    prov_dt,
                    json.dumps(prov.details),
                )

        return item

    async def get_semantic_memory(self, memory_id: str) -> SemanticMemoryItem | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT memory_id, subject, predicate, value_json, portal, user_session_id,
                       confidence, epistemic_status, created_at, updated_at, valid_from,
                       valid_until, is_current, superseded_by, provenance_json, metadata
                FROM semantic_memories
                WHERE memory_id = $1
                """,
                memory_id,
            )
            if not row:
                return None

            prov_data = json.loads(row["provenance_json"])
            provenance = MemoryProvenance(**prov_data)
            return SemanticMemoryItem(
                memory_id=row["memory_id"],
                subject=row["subject"],
                predicate=row["predicate"],
                value=json.loads(row["value_json"]),
                portal=row["portal"] or "",
                user_session_id=row["user_session_id"] or "",
                confidence=row["confidence"],
                epistemic_status=EpistemicStatus(row["epistemic_status"]),
                created_at=_format_dt(row["created_at"]),
                updated_at=_format_dt(row["updated_at"]),
                valid_from=_format_dt(row["valid_from"]),
                valid_until=_format_dt(row["valid_until"]) if row["valid_until"] else None,
                is_current=row["is_current"],
                superseded_by=row["superseded_by"],
                provenance=provenance,
                metadata=json.loads(row["metadata"]),
            )

    async def update_semantic_memory(self, item: SemanticMemoryItem) -> None:
        pool = self._ensure_pool()
        updated_dt = datetime.now(timezone.utc)
        valid_until_dt = _parse_dt(item.valid_until)

        async with pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE semantic_memories
                SET value_json = $1,
                    confidence = $2,
                    epistemic_status = $3,
                    updated_at = $4,
                    valid_until = $5,
                    is_current = $6,
                    superseded_by = $7,
                    metadata = $8
                WHERE memory_id = $9
                """,
                json.dumps(item.value),
                float(item.confidence),
                item.epistemic_status.value,
                updated_dt,
                valid_until_dt,
                item.is_current,
                item.superseded_by,
                json.dumps(item.metadata),
                item.memory_id,
            )
            if res == "UPDATE 0":
                raise KeyError(f"Semantic memory not found: {item.memory_id}")

    async def supersede_semantic_memory(
        self, old_id: str, new_item: SemanticMemoryItem
    ) -> SemanticMemoryItem:
        pool = self._ensure_pool()
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Supersede old record
                res = await conn.execute(
                    """
                    UPDATE semantic_memories
                    SET is_current = FALSE,
                        valid_until = $1,
                        superseded_by = $2,
                        updated_at = $1
                    WHERE memory_id = $3
                    """,
                    now_dt,
                    new_item.memory_id,
                    old_id,
                )
                if res == "UPDATE 0":
                    raise KeyError(f"Cannot supersede missing semantic memory: {old_id}")

                # 2. Insert new record
                created_dt = _parse_dt(new_item.created_at) or now_dt
                await conn.execute(
                    """
                    INSERT INTO semantic_memories (
                        memory_id, subject, predicate, value_json, portal, user_session_id,
                        confidence, epistemic_status, created_at, updated_at, valid_from,
                        valid_until, is_current, superseded_by, provenance_json, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    """,
                    new_item.memory_id,
                    new_item.subject,
                    new_item.predicate,
                    json.dumps(new_item.value),
                    new_item.portal,
                    new_item.user_session_id,
                    float(new_item.confidence),
                    new_item.epistemic_status.value,
                    created_dt,
                    now_dt,
                    now_dt,
                    None,
                    True,
                    None,
                    json.dumps(new_item.provenance.model_dump(mode="json")),
                    json.dumps(new_item.metadata),
                )

                # 3. Insert provenance
                prov = new_item.provenance
                prov_dt = _parse_dt(prov.timestamp) or now_dt
                await conn.execute(
                    """
                    INSERT INTO memory_provenance (
                        memory_id, source, author_type, run_id, observation_id,
                        tool_name, state_version, timestamp, details
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    new_item.memory_id,
                    prov.source,
                    prov.author_type.value,
                    prov.run_id,
                    prov.observation_id,
                    prov.tool_name,
                    prov.state_version,
                    prov_dt,
                    json.dumps(prov.details),
                )

        stored = new_item.model_copy(deep=True)
        stored.is_current = True
        stored.valid_from = now_iso
        stored.updated_at = now_iso
        return stored

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
        pool = self._ensure_pool()
        conditions = []
        params = []
        idx = 1

        if is_current is not None:
            conditions.append(f"is_current = ${idx}")
            params.append(is_current)
            idx += 1

        if subject:
            conditions.append(f"subject = ${idx}")
            params.append(subject)
            idx += 1

        if predicate:
            conditions.append(f"predicate = ${idx}")
            params.append(predicate)
            idx += 1

        if portal:
            conditions.append(f"(portal = '' OR portal = ${idx})")
            params.append(portal)
            idx += 1

        if user_session_id:
            conditions.append(f"(user_session_id = '' OR user_session_id = ${idx})")
            params.append(user_session_id)
            idx += 1

        if epistemic_status:
            conditions.append(f"epistemic_status = ${idx}")
            params.append(epistemic_status.value)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT memory_id, subject, predicate, value_json, portal, user_session_id,
                   confidence, epistemic_status, created_at, updated_at, valid_from,
                   valid_until, is_current, superseded_by, provenance_json, metadata
            FROM semantic_memories
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ${idx}
        """
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            results = []
            for row in rows:
                prov_data = json.loads(row["provenance_json"])
                provenance = MemoryProvenance(**prov_data)
                results.append(
                    SemanticMemoryItem(
                        memory_id=row["memory_id"],
                        subject=row["subject"],
                        predicate=row["predicate"],
                        value=json.loads(row["value_json"]),
                        portal=row["portal"] or "",
                        user_session_id=row["user_session_id"] or "",
                        confidence=row["confidence"],
                        epistemic_status=EpistemicStatus(row["epistemic_status"]),
                        created_at=_format_dt(row["created_at"]),
                        updated_at=_format_dt(row["updated_at"]),
                        valid_from=_format_dt(row["valid_from"]),
                        valid_until=_format_dt(row["valid_until"]) if row["valid_until"] else None,
                        is_current=row["is_current"],
                        superseded_by=row["superseded_by"],
                        provenance=provenance,
                        metadata=json.loads(row["metadata"]),
                    )
                )
            return results

    # ── Episodic Memory ────────────────────────────────────────────────────────

    async def create_episode(self, episode: EpisodicMemory) -> EpisodicMemory:
        pool = self._ensure_pool()
        created_dt = _parse_dt(episode.created_at) or datetime.now(timezone.utc)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, run_id, portal, goal, subgoal, summary,
                    key_events, outcome, confidence, provenance_json, created_at, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                episode.episode_id,
                episode.run_id,
                episode.portal,
                episode.goal,
                episode.subgoal,
                episode.summary,
                json.dumps(episode.key_events),
                episode.outcome.value,
                float(episode.confidence),
                json.dumps(episode.provenance.model_dump(mode="json")),
                created_dt,
                json.dumps(episode.metadata),
            )
        return episode

    async def get_episode(self, episode_id: str) -> EpisodicMemory | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT episode_id, run_id, portal, goal, subgoal, summary,
                       key_events, outcome, confidence, provenance_json, created_at, metadata
                FROM episodes
                WHERE episode_id = $1
                """,
                episode_id,
            )
            if not row:
                return None
            return EpisodicMemory(
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                portal=row["portal"] or "",
                goal=row["goal"],
                subgoal=row["subgoal"] or "",
                summary=row["summary"],
                key_events=json.loads(row["key_events"]),
                outcome=EpisodeOutcome(row["outcome"]),
                confidence=row["confidence"],
                provenance=MemoryProvenance(**json.loads(row["provenance_json"])),
                created_at=_format_dt(row["created_at"]),
                metadata=json.loads(row["metadata"]),
            )

    async def list_episodes(
        self,
        portal: str | None = None,
        run_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        pool = self._ensure_pool()
        conditions = []
        params = []
        idx = 1

        if portal:
            conditions.append(f"(portal = '' OR portal = ${idx})")
            params.append(portal)
            idx += 1

        if run_id:
            conditions.append(f"run_id = ${idx}")
            params.append(run_id)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT episode_id, run_id, portal, goal, subgoal, summary,
                   key_events, outcome, confidence, provenance_json, created_at, metadata
            FROM episodes
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [
                EpisodicMemory(
                    episode_id=row["episode_id"],
                    run_id=row["run_id"],
                    portal=row["portal"] or "",
                    goal=row["goal"],
                    subgoal=row["subgoal"] or "",
                    summary=row["summary"],
                    key_events=json.loads(row["key_events"]),
                    outcome=EpisodeOutcome(row["outcome"]),
                    confidence=row["confidence"],
                    provenance=MemoryProvenance(**json.loads(row["provenance_json"])),
                    created_at=_format_dt(row["created_at"]),
                    metadata=json.loads(row["metadata"]),
                )
                for row in rows
            ]

    # ── Experience Memory ──────────────────────────────────────────────────────

    async def create_experience(self, experience: ExperienceMemory) -> ExperienceMemory:
        pool = self._ensure_pool()
        created_dt = _parse_dt(experience.created_at) or datetime.now(timezone.utc)
        updated_dt = _parse_dt(experience.updated_at) or datetime.now(timezone.utc)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO experiences (
                    experience_id, run_id, portal, task_type, trigger_condition,
                    recovery_strategy, context_features, outcome, success_count,
                    failure_count, confidence, provenance_json, created_at, updated_at, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                experience.experience_id,
                experience.run_id,
                experience.portal,
                experience.task_type,
                experience.trigger_condition,
                experience.recovery_strategy,
                json.dumps(experience.context_features),
                experience.outcome,
                experience.success_count,
                experience.failure_count,
                float(experience.confidence),
                json.dumps(experience.provenance.model_dump(mode="json")),
                created_dt,
                updated_dt,
                json.dumps(experience.metadata),
            )
        return experience

    async def get_experience(self, experience_id: str) -> ExperienceMemory | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT experience_id, run_id, portal, task_type, trigger_condition,
                       recovery_strategy, context_features, outcome, success_count,
                       failure_count, confidence, provenance_json, created_at, updated_at, metadata
                FROM experiences
                WHERE experience_id = $1
                """,
                experience_id,
            )
            if not row:
                return None
            return ExperienceMemory(
                experience_id=row["experience_id"],
                run_id=row["run_id"] or "",
                portal=row["portal"] or "",
                task_type=row["task_type"] or "",
                trigger_condition=row["trigger_condition"],
                recovery_strategy=row["recovery_strategy"],
                context_features=json.loads(row["context_features"]),
                outcome=row["outcome"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                confidence=row["confidence"],
                provenance=MemoryProvenance(**json.loads(row["provenance_json"])),
                created_at=_format_dt(row["created_at"]),
                updated_at=_format_dt(row["updated_at"]),
                metadata=json.loads(row["metadata"]),
            )

    async def search_experiences(
        self,
        portal: str | None = None,
        task_type: str | None = None,
        trigger_condition: str | None = None,
        limit: int = 5,
    ) -> list[ExperienceMemory]:
        pool = self._ensure_pool()
        conditions = []
        params = []
        idx = 1

        if portal:
            conditions.append(f"(portal = '' OR portal = ${idx})")
            params.append(portal)
            idx += 1

        if task_type:
            conditions.append(f"task_type = ${idx}")
            params.append(task_type)
            idx += 1

        if trigger_condition:
            conditions.append(f"trigger_condition = ${idx}")
            params.append(trigger_condition)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT experience_id, run_id, portal, task_type, trigger_condition,
                   recovery_strategy, context_features, outcome, success_count,
                   failure_count, confidence, provenance_json, created_at, updated_at, metadata
            FROM experiences
            {where_clause}
            ORDER BY confidence DESC, success_count DESC
            LIMIT ${idx}
        """
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [
                ExperienceMemory(
                    experience_id=row["experience_id"],
                    run_id=row["run_id"] or "",
                    portal=row["portal"] or "",
                    task_type=row["task_type"] or "",
                    trigger_condition=row["trigger_condition"],
                    recovery_strategy=row["recovery_strategy"],
                    context_features=json.loads(row["context_features"]),
                    outcome=row["outcome"],
                    success_count=row["success_count"],
                    failure_count=row["failure_count"],
                    confidence=row["confidence"],
                    provenance=MemoryProvenance(**json.loads(row["provenance_json"])),
                    created_at=_format_dt(row["created_at"]),
                    updated_at=_format_dt(row["updated_at"]),
                    metadata=json.loads(row["metadata"]),
                )
                for row in rows
            ]

    async def update_experience_success(self, experience_id: str) -> None:
        pool = self._ensure_pool()
        now_dt = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experiences
                SET success_count = success_count + 1,
                    confidence = LEAST(0.95, confidence + 0.1),
                    updated_at = $1
                WHERE experience_id = $2
                """,
                now_dt,
                experience_id,
            )

    # ── Compaction Records ─────────────────────────────────────────────────────

    async def record_compaction(self, record: CompactionRecord) -> None:
        pool = self._ensure_pool()
        created_dt = _parse_dt(record.created_at) or datetime.now(timezone.utc)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO compaction_records (
                    compaction_id, run_id, created_at, pre_items_count,
                    post_items_count, preserved_keys, compacted_summary, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                record.compaction_id,
                record.run_id,
                created_dt,
                record.pre_items_count,
                record.post_items_count,
                json.dumps(record.preserved_keys),
                record.compacted_summary,
                json.dumps(record.metadata),
            )

    async def get_compaction_records(self, run_id: str) -> list[CompactionRecord]:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT compaction_id, run_id, created_at, pre_items_count,
                       post_items_count, preserved_keys, compacted_summary, metadata
                FROM compaction_records
                WHERE run_id = $1
                ORDER BY created_at ASC
                """,
                run_id,
            )
            return [
                CompactionRecord(
                    compaction_id=row["compaction_id"],
                    run_id=row["run_id"],
                    created_at=_format_dt(row["created_at"]),
                    pre_items_count=row["pre_items_count"],
                    post_items_count=row["post_items_count"],
                    preserved_keys=json.loads(row["preserved_keys"]),
                    compacted_summary=row["compacted_summary"],
                    metadata=json.loads(row["metadata"]),
                )
                for row in rows
            ]
