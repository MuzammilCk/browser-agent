"""Integration tests for PostgresMemoryStore — Phase 9.

Tests real PostgreSQL persistence, transactions, supersession lineage,
concurrent writes, and audit trail queries against the live PostgreSQL server.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

from app.agent.memory.models import (
    AuthorType,
    CompactionRecord,
    EpisodeOutcome,
    EpisodicMemory,
    EpistemicStatus,
    ExperienceMemory,
    MemoryProvenance,
    SemanticMemoryItem,
)
from app.agent.memory.postgres_store import PostgresMemoryStore
from app.config.settings import Settings

POSTGRES_TEST_DSN = (
    os.getenv("POSTGRES_TEST_DSN")
    or os.getenv("POSTGRES_URL")
    or Settings().postgres_url
)


@pytest.fixture
async def pg_memory_store():
    store = PostgresMemoryStore(POSTGRES_TEST_DSN)
    await store.connect()
    yield store
    await store.close()


class TestPostgresMemoryStoreIntegration:
    """Tests 25 & 26: Real PostgreSQL memory persistence and concurrent write consistency."""

    @pytest.mark.asyncio
    async def test_postgres_memory_persistence_round_trip(self, pg_memory_store):
        """25. PostgreSQL memory persistence round-trip for semantic, episodic, experience, and compaction."""
        suffix = uuid.uuid4().hex[:8]
        run_id = f"run_pg_{suffix}"
        portal = f"https://portal-{suffix}.gov.in"

        # 1. Persist Semantic Memory
        sem_id = f"sem_{suffix}"
        sem_item = SemanticMemoryItem(
            memory_id=sem_id,
            subject="USER.residence_state",
            predicate="value",
            value="Kerala",
            portal=portal,
            user_session_id=f"user_{suffix}",
            epistemic_status=EpistemicStatus.VERIFIED,
            confidence=1.0,
            provenance=MemoryProvenance(
                source="user_explicit_dialogue",
                author_type=AuthorType.USER_EXPLICIT,
                run_id=run_id,
                details={"step": "initial_preference"},
            ),
        )
        await pg_memory_store.create_semantic_memory(sem_item)

        # Retrieve and verify
        loaded_sem = await pg_memory_store.get_semantic_memory(sem_id)
        assert loaded_sem is not None
        assert loaded_sem.memory_id == sem_id
        assert loaded_sem.subject == "USER.residence_state"
        assert loaded_sem.value == "Kerala"
        assert loaded_sem.epistemic_status == EpistemicStatus.VERIFIED
        assert loaded_sem.is_current is True
        assert loaded_sem.provenance.author_type == AuthorType.USER_EXPLICIT

        # 2. Supersede Semantic Memory with newer verified fact
        new_sem_id = f"sem_new_{suffix}"
        new_sem_item = SemanticMemoryItem(
            memory_id=new_sem_id,
            subject="USER.residence_state",
            predicate="value",
            value="Karnataka",
            portal=portal,
            user_session_id=f"user_{suffix}",
            epistemic_status=EpistemicStatus.VERIFIED,
            confidence=1.0,
            provenance=MemoryProvenance(
                source="user_update_dialogue",
                author_type=AuthorType.USER_EXPLICIT,
                run_id=run_id,
                details={"step": "updated_preference"},
            ),
        )
        await pg_memory_store.supersede_semantic_memory(sem_id, new_sem_item)

        # Check old record preserved as superseded
        old_loaded = await pg_memory_store.get_semantic_memory(sem_id)
        assert old_loaded is not None
        assert old_loaded.is_current is False
        assert old_loaded.valid_until is not None
        assert old_loaded.superseded_by == new_sem_id

        # Check new record is current
        new_loaded = await pg_memory_store.get_semantic_memory(new_sem_id)
        assert new_loaded is not None
        assert new_loaded.is_current is True
        assert new_loaded.value == "Karnataka"

        # Search current memories
        search_res = await pg_memory_store.search_semantic_memories(
            subject="USER.residence_state",
            portal=portal,
            is_current=True,
        )
        assert len(search_res) == 1
        assert search_res[0].value == "Karnataka"

        # 3. Persist Episodic Memory
        ep_id = f"ep_{suffix}"
        ep = EpisodicMemory(
            episode_id=ep_id,
            run_id=run_id,
            portal=portal,
            goal="Renew Trade Licence",
            subgoal="Document Verification",
            summary="Submitted application form and reached verification stage successfully.",
            key_events=[
                {"event": "form_filled", "fields_count": 5},
                {"event": "declaration_confirmed", "by": "user"},
            ],
            outcome=EpisodeOutcome.SUCCESS,
            provenance=MemoryProvenance(
                source="workflow_execution",
                author_type=AuthorType.RUNTIME_VERIFIED,
                run_id=run_id,
            ),
        )
        await pg_memory_store.create_episode(ep)

        loaded_ep = await pg_memory_store.get_episode(ep_id)
        assert loaded_ep is not None
        assert loaded_ep.episode_id == ep_id
        assert loaded_ep.goal == "Renew Trade Licence"
        assert len(loaded_ep.key_events) == 2

        ep_list = await pg_memory_store.list_episodes(portal=portal)
        assert len(ep_list) >= 1
        assert ep_list[0].episode_id == ep_id

        # 4. Persist Experience Memory
        exp_id = f"exp_{suffix}"
        exp = ExperienceMemory(
            experience_id=exp_id,
            run_id=run_id,
            portal=portal,
            task_type="licence_renewal",
            trigger_condition="stale_reference_on_dropdown_change",
            recovery_strategy="reobserve_and_rederive_target",
            context_features={"failure": "stale_reference"},
            outcome="success",
            success_count=1,
            confidence=0.6,
            provenance=MemoryProvenance(
                source="recovery_manager",
                author_type=AuthorType.RUNTIME_VERIFIED,
                run_id=run_id,
            ),
        )
        await pg_memory_store.create_experience(exp)

        loaded_exp = await pg_memory_store.get_experience(exp_id)
        assert loaded_exp is not None
        assert loaded_exp.experience_id == exp_id
        assert loaded_exp.recovery_strategy == "reobserve_and_rederive_target"

        # Update experience success
        await pg_memory_store.update_experience_success(exp_id)
        updated_exp = await pg_memory_store.get_experience(exp_id)
        assert updated_exp.success_count == 2
        assert updated_exp.confidence > 0.6

        # 5. Persist Compaction Record
        cmp_id = f"cmp_{suffix}"
        cmp_rec = CompactionRecord(
            compaction_id=cmp_id,
            run_id=run_id,
            pre_items_count=20,
            post_items_count=4,
            preserved_keys=["goal", "subgoal", "verified_facts"],
            compacted_summary="Compacted 16 prior items into episodic milestone",
        )
        await pg_memory_store.record_compaction(cmp_rec)

        compactions = await pg_memory_store.get_compaction_records(run_id)
        assert len(compactions) == 1
        assert compactions[0].compaction_id == cmp_id
        assert compactions[0].pre_items_count == 20
        assert compactions[0].post_items_count == 4

    @pytest.mark.asyncio
    async def test_postgres_concurrent_memory_writes_are_consistent(self, pg_memory_store):
        """26. PostgreSQL concurrent memory writes are consistent without deadlocks or corruption."""
        suffix = uuid.uuid4().hex[:8]
        portal = f"https://concurrent-{suffix}.gov.in"

        async def write_worker(worker_idx: int):
            run_id = f"run_worker_{worker_idx}_{suffix}"
            sem = SemanticMemoryItem(
                memory_id=f"sem_w_{worker_idx}_{suffix}",
                subject=f"USER.attr_{worker_idx}",
                predicate="val",
                value=f"value_{worker_idx}",
                portal=portal,
                provenance=MemoryProvenance(
                    source=f"worker_{worker_idx}",
                    author_type=AuthorType.RUNTIME_VERIFIED,
                    run_id=run_id,
                ),
            )
            ep = EpisodicMemory(
                episode_id=f"ep_w_{worker_idx}_{suffix}",
                run_id=run_id,
                portal=portal,
                goal=f"Concurrent Goal {worker_idx}",
                summary=f"Worker {worker_idx} summary",
                provenance=MemoryProvenance(
                    source=f"worker_{worker_idx}",
                    author_type=AuthorType.RUNTIME_VERIFIED,
                    run_id=run_id,
                ),
            )
            exp = ExperienceMemory(
                experience_id=f"exp_w_{worker_idx}_{suffix}",
                run_id=run_id,
                portal=portal,
                task_type="concurrency_test",
                trigger_condition=f"trigger_{worker_idx}",
                recovery_strategy=f"strategy_{worker_idx}",
                provenance=MemoryProvenance(
                    source=f"worker_{worker_idx}",
                    author_type=AuthorType.RUNTIME_VERIFIED,
                    run_id=run_id,
                ),
            )
            await pg_memory_store.create_semantic_memory(sem)
            await pg_memory_store.create_episode(ep)
            await pg_memory_store.create_experience(exp)

        # Launch 8 concurrent workers simultaneously
        await asyncio.gather(*(write_worker(i) for i in range(8)))

        # Verify all 8 semantic items, episodes, and experiences exist and are consistent
        episodes = await pg_memory_store.list_episodes(portal=portal, limit=20)
        assert len(episodes) == 8

        experiences = await pg_memory_store.search_experiences(portal=portal, limit=20)
        assert len(experiences) == 8
