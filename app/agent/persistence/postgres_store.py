"""PostgreSQL CheckpointStore implementation — Phase 8 Part B.

Uses asyncpg with connection pooling, transactional state persistence,
atomic lease-based concurrency locking with fencing tokens, and schema migrations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import asyncpg

from app.agent.interrupts.lifecycle import validate_transition
from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
    parse_iso,
    utc_now_iso,
)
from app.agent.persistence.schema import apply_schema
from app.agent.runtime.checkpoint import AgentCheckpoint


class PostgresCheckpointStore:
    """Production-grade PostgreSQL checkpoint and interrupt persistence store."""

    def __init__(self, dsn: str, min_connections: int = 1, max_connections: int = 10) -> None:
        self._dsn = dsn
        self._min_conn = min_connections
        self._max_conn = max_connections
        self._pool: asyncpg.Pool | None = None
        self._cache: dict[str, AgentCheckpoint] = {}

    def save(self, checkpoint: AgentCheckpoint) -> None:
        """Synchronous cache for AgentRuntime checkpointing."""
        self._cache[checkpoint.checkpoint_id] = checkpoint

    def load(self, checkpoint_id: str) -> AgentCheckpoint | None:
        """Synchronous load from memory cache."""
        return self._cache.get(checkpoint_id)

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
        """Ensure all tables and indexes exist."""
        pool = self._ensure_pool()
        await apply_schema(pool)

    def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresCheckpointStore is not connected. Call connect() first.")
        return self._pool

    # ---------------------------------------------------------------------------
    # Checkpoints
    # ---------------------------------------------------------------------------

    async def save_checkpoint(self, checkpoint: AgentCheckpoint) -> None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Upsert agent_run
                run_state = checkpoint.state
                created_dt = parse_iso(checkpoint.created_at) if checkpoint.created_at else datetime.now(timezone.utc)
                now_dt = datetime.now(timezone.utc)
                expires_dt = parse_iso(checkpoint.expires_at) if getattr(checkpoint, "expires_at", None) else None

                portal_val = getattr(run_state.world_state, "portal", "") if hasattr(run_state, "world_state") else ""
                state_ver = getattr(checkpoint, "state_version", 0)

                await conn.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, created_at, updated_at, lifecycle, goal, portal, current_subgoal_id, state_version, total_iterations
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (run_id) DO UPDATE SET
                        updated_at = EXCLUDED.updated_at,
                        lifecycle = EXCLUDED.lifecycle,
                        current_subgoal_id = EXCLUDED.current_subgoal_id,
                        state_version = EXCLUDED.state_version,
                        total_iterations = EXCLUDED.total_iterations
                    """,
                    checkpoint.run_id,
                    created_dt,
                    now_dt,
                    run_state.lifecycle.value if hasattr(run_state.lifecycle, "value") else str(run_state.lifecycle),
                    run_state.goal,
                    portal_val,
                    run_state.current_subgoal or "",
                    state_ver,
                    run_state.iteration,
                )

                # 2. Mark previous checkpoints as not latest
                await conn.execute(
                    "UPDATE agent_checkpoints SET is_latest = FALSE WHERE run_id = $1",
                    checkpoint.run_id,
                )

                # 3. Insert new checkpoint
                state_json = json.dumps(run_state.model_dump(mode="json"))
                events_json = json.dumps([e.model_dump(mode="json") for e in checkpoint.events])
                lifecycle_str = run_state.lifecycle.value if hasattr(run_state.lifecycle, "value") else str(run_state.lifecycle)

                await conn.execute(
                    """
                    INSERT INTO agent_checkpoints (
                        checkpoint_id, run_id, format_version, created_at, expires_at,
                        reason, lifecycle, state_version, state_payload, events_payload,
                        recovery_cursor, is_latest
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, TRUE)
                    ON CONFLICT (checkpoint_id) DO UPDATE SET
                        state_payload = EXCLUDED.state_payload,
                        events_payload = EXCLUDED.events_payload,
                        lifecycle = EXCLUDED.lifecycle,
                        state_version = EXCLUDED.state_version,
                        is_latest = TRUE
                    """,
                    checkpoint.checkpoint_id,
                    checkpoint.run_id,
                    checkpoint.format_version,
                    created_dt,
                    expires_dt,
                    checkpoint.reason,
                    lifecycle_str,
                    state_ver,
                    state_json,
                    events_json,
                    getattr(checkpoint, "recovery_cursor", 0),
                )

                # 4. If checkpoint contains pending interrupt, upsert it
                if getattr(checkpoint, "human_interrupt", None):
                    intr = checkpoint.human_interrupt
                    intr_created = parse_iso(intr.created_at) if intr.created_at else now_dt
                    intr_expires = parse_iso(intr.expires_at) if intr.expires_at else now_dt
                    await conn.execute(
                        """
                        INSERT INTO human_interrupts (
                            interrupt_id, run_id, checkpoint_id, reason, status, description,
                            observation_id, world_state_version, subgoal_id, required_action,
                            target_identity, semantic_id, created_at, expires_at, metadata
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb)
                        ON CONFLICT (interrupt_id) DO UPDATE SET
                            checkpoint_id = EXCLUDED.checkpoint_id,
                            status = EXCLUDED.status,
                            description = EXCLUDED.description,
                            metadata = EXCLUDED.metadata
                        """,
                        intr.interrupt_id,
                        intr.run_id,
                        checkpoint.checkpoint_id,
                        intr.reason.value,
                        intr.status.value,
                        intr.description,
                        intr.observation_id,
                        intr.world_state_version,
                        intr.subgoal_id,
                        intr.required_action,
                        intr.target_identity,
                        intr.semantic_id,
                        intr_created,
                        intr_expires,
                        json.dumps(intr.metadata),
                    )

                # 5. Record audit event
                await conn.execute(
                    """
                    INSERT INTO hitl_audit_events (run_id, event_type, payload, timestamp)
                    VALUES ($1, $2, $3::jsonb, $4)
                    """,
                    checkpoint.run_id,
                    "CHECKPOINT_SAVED",
                    json.dumps({
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "reason": checkpoint.reason,
                        "format_version": checkpoint.format_version,
                        "state_version": state_ver,
                    }),
                    now_dt,
                )

    async def load_checkpoint(self, checkpoint_id: str) -> AgentCheckpoint | None:
        pool = self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT checkpoint_id, run_id, format_version, created_at, expires_at,
                   reason, lifecycle, state_version, state_payload, events_payload, recovery_cursor
            FROM agent_checkpoints
            WHERE checkpoint_id = $1
            """,
            checkpoint_id,
        )
        if not row:
            return None
        return self._row_to_checkpoint(row)

    async def load_latest_for_run(self, run_id: str) -> AgentCheckpoint | None:
        pool = self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT checkpoint_id, run_id, format_version, created_at, expires_at,
                   reason, lifecycle, state_version, state_payload, events_payload, recovery_cursor
            FROM agent_checkpoints
            WHERE run_id = $1 AND is_latest = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        if not row:
            return None
        return self._row_to_checkpoint(row)

    async def list_checkpoints_for_run(self, run_id: str) -> list[str]:
        pool = self._ensure_pool()
        rows = await pool.fetch(
            """
            SELECT checkpoint_id FROM agent_checkpoints
            WHERE run_id = $1
            ORDER BY created_at ASC
            """,
            run_id,
        )
        return [r["checkpoint_id"] for r in rows]

    def _row_to_checkpoint(self, row: asyncpg.Record) -> AgentCheckpoint:
        state_data = json.loads(row["state_payload"]) if isinstance(row["state_payload"], str) else row["state_payload"]
        events_data = json.loads(row["events_payload"]) if isinstance(row["events_payload"], str) else row["events_payload"]

        created_str = row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"])
        expires_str = row["expires_at"].isoformat() if row["expires_at"] and hasattr(row["expires_at"], "isoformat") else None

        from app.agent.runtime.events import AgentEvent
        from app.agent.runtime.state import AgentRunState

        state = AgentRunState.model_validate(state_data)
        events = [AgentEvent.model_validate(e) for e in events_data]

        cp = AgentCheckpoint(
            format_version=row["format_version"],
            checkpoint_id=row["checkpoint_id"],
            run_id=row["run_id"],
            created_at=created_str,
            reason=row["reason"],
            state=state,
            events=events,
            expires_at=expires_str,
            state_version=row["state_version"],
            recovery_cursor=row["recovery_cursor"],
        )
        return cp

    # ---------------------------------------------------------------------------
    # Human Interrupts & Approvals
    # ---------------------------------------------------------------------------

    async def save_interrupt(self, interrupt: HumanInterrupt) -> None:
        pool = self._ensure_pool()
        created_dt = parse_iso(interrupt.created_at)
        expires_dt = parse_iso(interrupt.expires_at)

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Ensure run exists
                await conn.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, created_at, updated_at, lifecycle, goal
                    ) VALUES ($1, $2, $2, 'waiting_for_user', 'Human interrupt in progress')
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    interrupt.run_id,
                    created_dt,
                )

                await conn.execute(
                    """
                    INSERT INTO human_interrupts (
                        interrupt_id, run_id, checkpoint_id, reason, status, description,
                        observation_id, world_state_version, subgoal_id, required_action,
                        target_identity, semantic_id, created_at, expires_at, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb)
                    ON CONFLICT (interrupt_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        description = EXCLUDED.description,
                        checkpoint_id = EXCLUDED.checkpoint_id,
                        metadata = EXCLUDED.metadata
                    """,
                    interrupt.interrupt_id,
                    interrupt.run_id,
                    interrupt.checkpoint_id,
                    interrupt.reason.value,
                    interrupt.status.value,
                    interrupt.description,
                    interrupt.observation_id,
                    interrupt.world_state_version,
                    interrupt.subgoal_id,
                    interrupt.required_action,
                    interrupt.target_identity,
                    interrupt.semantic_id,
                    created_dt,
                    expires_dt,
                    json.dumps(interrupt.metadata),
                )

                # Record audit
                await conn.execute(
                    """
                    INSERT INTO hitl_audit_events (run_id, event_type, payload, timestamp)
                    VALUES ($1, $2, $3::jsonb, $4)
                    """,
                    interrupt.run_id,
                    "INTERRUPT_CREATED",
                    json.dumps({
                        "interrupt_id": interrupt.interrupt_id,
                        "reason": interrupt.reason.value,
                        "status": interrupt.status.value,
                        "observation_id": interrupt.observation_id,
                    }),
                    created_dt,
                )

    async def get_interrupt(self, interrupt_id: str) -> HumanInterrupt | None:
        pool = self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT i.*, a.approval_id, a.requested_action as a_action, a.target_identity as a_target,
                   a.semantic_id as a_sem, a.world_state_version as a_ws_ver, a.observation_id as a_obs,
                   a.created_at as a_created, a.expires_at as a_expires, a.approved_by, a.metadata as a_meta
            FROM human_interrupts i
            LEFT JOIN approval_bindings a ON i.interrupt_id = a.interrupt_id
            WHERE i.interrupt_id = $1
            """,
            interrupt_id,
        )
        if not row:
            return None
        return self._row_to_interrupt(row)

    async def get_latest_interrupt_for_run(self, run_id: str) -> HumanInterrupt | None:
        pool = self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT i.*, a.approval_id, a.requested_action as a_action, a.target_identity as a_target,
                   a.semantic_id as a_sem, a.world_state_version as a_ws_ver, a.observation_id as a_obs,
                   a.created_at as a_created, a.expires_at as a_expires, a.approved_by, a.metadata as a_meta
            FROM human_interrupts i
            LEFT JOIN approval_bindings a ON i.interrupt_id = a.interrupt_id
            WHERE i.run_id = $1
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        if not row:
            return None
        return self._row_to_interrupt(row)

    def _row_to_interrupt(self, row: asyncpg.Record) -> HumanInterrupt:
        created_str = row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"])
        expires_str = row["expires_at"].isoformat() if hasattr(row["expires_at"], "isoformat") else str(row["expires_at"])
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

        approval_binding = None
        if row.get("approval_id"):
            a_created = row["a_created"].isoformat() if hasattr(row["a_created"], "isoformat") else str(row["a_created"])
            a_expires = row["a_expires"].isoformat() if hasattr(row["a_expires"], "isoformat") else str(row["a_expires"])
            a_meta = json.loads(row["a_meta"]) if isinstance(row["a_meta"], str) else row["a_meta"]
            approval_binding = ApprovalBinding(
                approval_id=row["approval_id"],
                run_id=row["run_id"],
                interrupt_id=row["interrupt_id"],
                requested_action=row["a_action"],
                target_identity=row["a_target"],
                semantic_id=row["a_sem"],
                world_state_version=row["a_ws_ver"],
                observation_id=row["a_obs"],
                created_at=a_created,
                expires_at=a_expires,
                approved_by=row["approved_by"],
                metadata=a_meta or {},
            )

        return HumanInterrupt(
            interrupt_id=row["interrupt_id"],
            run_id=row["run_id"],
            checkpoint_id=row["checkpoint_id"],
            reason=InterruptReason(row["reason"]),
            status=InterruptStatus(row["status"]),
            description=row["description"],
            observation_id=row["observation_id"],
            world_state_version=row["world_state_version"],
            subgoal_id=row["subgoal_id"],
            required_action=row["required_action"],
            target_identity=row["target_identity"],
            semantic_id=row["semantic_id"],
            created_at=created_str,
            expires_at=expires_str,
            metadata=meta or {},
            approval_binding=approval_binding,
        )

    async def update_interrupt_status(
        self,
        interrupt_id: str,
        status: InterruptStatus,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        pool = self._ensure_pool()
        current = await self.get_interrupt(interrupt_id)
        if not current:
            raise KeyError(f"Interrupt {interrupt_id} not found")

        validate_transition(current.status, status)

        meta = dict(current.metadata)
        if metadata_update:
            meta.update(metadata_update)

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE human_interrupts
                    SET status = $1, metadata = $2::jsonb
                    WHERE interrupt_id = $3
                    """,
                    status.value,
                    json.dumps(meta),
                    interrupt_id,
                )

                await conn.execute(
                    """
                    INSERT INTO hitl_audit_events (run_id, event_type, payload, timestamp)
                    VALUES ($1, $2, $3::jsonb, NOW())
                    """,
                    current.run_id,
                    f"INTERRUPT_{status.value.upper()}",
                    json.dumps({
                        "interrupt_id": interrupt_id,
                        "status": status.value,
                        "metadata": metadata_update or {},
                    }),
                )

    async def save_approval(self, approval: ApprovalBinding) -> None:
        pool = self._ensure_pool()
        created_dt = parse_iso(approval.created_at)
        expires_dt = parse_iso(approval.expires_at)

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO approval_bindings (
                        approval_id, interrupt_id, run_id, requested_action, target_identity,
                        semantic_id, world_state_version, observation_id, created_at, expires_at,
                        approved_by, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
                    ON CONFLICT (approval_id) DO UPDATE SET
                        expires_at = EXCLUDED.expires_at,
                        metadata = EXCLUDED.metadata
                    """,
                    approval.approval_id,
                    approval.interrupt_id,
                    approval.run_id,
                    approval.requested_action,
                    approval.target_identity,
                    approval.semantic_id,
                    approval.world_state_version,
                    approval.observation_id,
                    created_dt,
                    expires_dt,
                    approval.approved_by,
                    json.dumps(approval.metadata),
                )

                # Update interrupt status to APPROVED
                await conn.execute(
                    """
                    UPDATE human_interrupts
                    SET status = 'approved'
                    WHERE interrupt_id = $1 AND status IN ('pending', 'waiting_for_user', 'invalidated')
                    """,
                    approval.interrupt_id,
                )

                await conn.execute(
                    """
                    INSERT INTO hitl_audit_events (run_id, event_type, payload, timestamp)
                    VALUES ($1, $2, $3::jsonb, NOW())
                    """,
                    approval.run_id,
                    "APPROVAL_GRANTED",
                    json.dumps({
                        "approval_id": approval.approval_id,
                        "interrupt_id": approval.interrupt_id,
                        "requested_action": approval.requested_action,
                        "target_identity": approval.target_identity,
                        "world_state_version": approval.world_state_version,
                    }),
                )

    async def get_approval_for_interrupt(self, interrupt_id: str) -> ApprovalBinding | None:
        pool = self._ensure_pool()
        row = await pool.fetchrow(
            """
            SELECT * FROM approval_bindings WHERE interrupt_id = $1
            """,
            interrupt_id,
        )
        if not row:
            return None
        created_str = row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"])
        expires_str = row["expires_at"].isoformat() if hasattr(row["expires_at"], "isoformat") else str(row["expires_at"])
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

        return ApprovalBinding(
            approval_id=row["approval_id"],
            run_id=row["run_id"],
            interrupt_id=row["interrupt_id"],
            requested_action=row["requested_action"],
            target_identity=row["target_identity"],
            semantic_id=row["semantic_id"],
            world_state_version=row["world_state_version"],
            observation_id=row["observation_id"],
            created_at=created_str,
            expires_at=expires_str,
            approved_by=row["approved_by"],
            metadata=meta or {},
        )

    # ---------------------------------------------------------------------------
    # Concurrency / Atomic Resume Locking
    # ---------------------------------------------------------------------------

    async def acquire_resume_lock(
        self, run_id: str, worker_id: str, lease_duration_seconds: float = 30.0
    ) -> tuple[bool, int]:
        """Atomically acquire mutual exclusion lock with fencing token using PostgreSQL upsert.

        - If no lock: inserts with fencing_token = 1.
        - If held by same worker: extends lease.
        - If held and expired: updates lease and increments fencing_token.
        - If held and active by different worker: fails closed (0 rows returned).
        """
        pool = self._ensure_pool()
        lease_secs = float(lease_duration_seconds)

        query = """
        INSERT INTO resume_locks (run_id, worker_id, acquired_at, expires_at, fencing_token)
        VALUES ($1, $2, NOW(), NOW() + make_interval(secs => $3), 1)
        ON CONFLICT (run_id) DO UPDATE
        SET worker_id = $2,
            acquired_at = NOW(),
            expires_at = NOW() + make_interval(secs => $3),
            fencing_token = resume_locks.fencing_token + 1
        WHERE resume_locks.expires_at < NOW() OR resume_locks.worker_id = $2
        RETURNING fencing_token;
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id, worker_id, lease_secs)
            if row:
                token = row["fencing_token"]
                await self.record_audit_event(
                    run_id=run_id,
                    event_type="RESUME_LOCK_ACQUIRED",
                    payload={"worker_id": worker_id, "token": token, "lease_seconds": lease_secs},
                )
                return True, token
            else:
                await self.record_audit_event(
                    run_id=run_id,
                    event_type="RESUME_LOCK_CONFLICT",
                    payload={"worker_id": worker_id},
                )
                return False, 0

    async def release_resume_lock(self, run_id: str, worker_id: str) -> bool:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM resume_locks WHERE run_id = $1 AND worker_id = $2",
                run_id,
                worker_id,
            )
            released = "DELETE 1" in res
            if released:
                await self.record_audit_event(
                    run_id=run_id,
                    event_type="RESUME_LOCK_RELEASED",
                    payload={"worker_id": worker_id},
                )
            return released

    async def expire_records(self, now: datetime | None = None) -> int:
        pool = self._ensure_pool()
        check_time = now or datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE human_interrupts
                SET status = 'expired'
                WHERE expires_at < $1 AND status NOT IN ('expired', 'resumed', 'rejected', 'cancelled')
                """,
                check_time,
            )
            count = 0
            if "UPDATE " in res:
                count = int(res.split(" ")[1])
            return count

    async def record_audit_event(
        self, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        pool = self._ensure_pool()
        # Phase 15 H6: defense-in-depth redaction aligned with the Phase 11
        # trace patterns (trace.py::_SENSITIVE_KEY_PATTERNS). The payload is
        # redacted again at the durable boundary even though upstream layers
        # already scrub — persisted audit rows must never carry secrets.
        from app.agent.persistence.redaction import filter_sensitive_payload

        safe_payload = filter_sensitive_payload(payload)
        await pool.execute(
            """
            INSERT INTO hitl_audit_events (run_id, event_type, payload, timestamp)
            VALUES ($1, $2, $3::jsonb, NOW())
            """,
            run_id,
            event_type,
            json.dumps(safe_payload),
        )

    async def list_pending_interrupts(
        self, run_id: str | None = None
    ) -> list[HumanInterrupt]:
        pool = self._ensure_pool()
        if run_id:
            rows = await pool.fetch(
                """
                SELECT i.*, a.approval_id, a.requested_action as a_action, a.target_identity as a_target,
                       a.semantic_id as a_sem, a.world_state_version as a_ws_ver, a.observation_id as a_obs,
                       a.created_at as a_created, a.expires_at as a_expires, a.approved_by, a.metadata as a_meta
                FROM human_interrupts i
                LEFT JOIN approval_bindings a ON i.interrupt_id = a.interrupt_id
                WHERE i.run_id = $1 AND i.status IN ('pending', 'waiting_for_user')
                ORDER BY i.created_at ASC
                """,
                run_id,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT i.*, a.approval_id, a.requested_action as a_action, a.target_identity as a_target,
                       a.semantic_id as a_sem, a.world_state_version as a_ws_ver, a.observation_id as a_obs,
                       a.created_at as a_created, a.expires_at as a_expires, a.approved_by, a.metadata as a_meta
                FROM human_interrupts i
                LEFT JOIN approval_bindings a ON i.interrupt_id = a.interrupt_id
                WHERE i.status IN ('pending', 'waiting_for_user')
                ORDER BY i.created_at ASC
                """
            )
        return [self._row_to_interrupt(r) for r in rows]

    async def get_audit_events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        pool = self._ensure_pool()
        if run_id:
            rows = await pool.fetch(
                "SELECT * FROM hitl_audit_events WHERE run_id = $1 ORDER BY timestamp ASC",
                run_id,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM hitl_audit_events ORDER BY timestamp ASC"
            )
        events = []
        for r in rows:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            ts = r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else str(r["timestamp"])
            events.append({
                "id": r["id"],
                "run_id": r["run_id"],
                "event_type": r["event_type"],
                "payload": p,
                "timestamp": ts,
            })
        return events
