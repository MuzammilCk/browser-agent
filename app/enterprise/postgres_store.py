"""PostgreSQL EnterpriseStore — Phase 13.

Production durable state for the enterprise runtime on the SAME PostgreSQL
database the Phase 8 checkpoint store already uses (invariant 7: no second
state database without justification — there is none).

Key atomic operations:
- claim_next_run: SKIP LOCKED queue claim + lease acquisition in ONE
  transaction (two workers can never claim the same run).
- acquire/renew/release lease: conditional upserts; fencing tokens are
  monotonic per run and enforced server-side on fenced writes.
- put_idempotency_if_absent: INSERT ... ON CONFLICT DO NOTHING.
- append_audit: INSERT only — the service never exposes an UPDATE path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.enterprise.models import (
    AuditEvent,
    ExecutionQueueItem,
    IdempotencyRecord,
    InvalidRunTransition,
    LeaseState,
    QueueItemState,
    RunStatus,
    WorkerLease,
    Workflow,
    WorkflowRun,
    validate_transition,
    utc_now_iso,
)
from app.enterprise.schema import apply_enterprise_schema


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class PostgresEnterpriseStore:
    def __init__(
        self, dsn: str, min_connections: int = 1, max_connections: int = 10,
    ) -> None:
        self._dsn = dsn
        self._min = min_connections
        self._max = max_connections
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn, min_size=self._min, max_size=self._max,
            )
            await self.initialize_schema()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def initialize_schema(self) -> None:
        pool = self._ensure_pool()
        await apply_enterprise_schema(pool)

    def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresEnterpriseStore not connected. Call connect().")
        return self._pool

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_row(row: asyncpg.Record) -> WorkflowRun:
        return WorkflowRun(
            run_id=row["run_id"],
            workflow_id=row["workflow_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            status=RunStatus(row["status"]),
            worker_id=row["worker_id"],
            lease_id=row["lease_id"],
            fencing_token=int(row["fencing_token"]),
            checkpoint_id=row["checkpoint_id"],
            agent_run_id=row["agent_run_id"],
            created_at=row["created_at"].isoformat(),
            started_at=row["started_at"].isoformat() if row["started_at"] else None,
            updated_at=row["updated_at"].isoformat(),
            completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
            cancellation_requested=bool(row["cancellation_requested"]),
            failure_code=row["failure_code"],
            dispatch_attempts=int(row["dispatch_attempts"]),
            max_dispatch_attempts=int(row["max_dispatch_attempts"]),
            version=int(row["version"]),
        )

    @staticmethod
    def _lease_row(row: asyncpg.Record) -> WorkerLease:
        return WorkerLease(
            run_id=row["run_id"],
            worker_id=row["worker_id"],
            lease_id=row["lease_id"],
            fencing_token=int(row["fencing_token"]),
            acquired_at=row["acquired_at"].isoformat(),
            expires_at=row["expires_at"].isoformat(),
            renewed_at=row["renewed_at"].isoformat(),
            state=LeaseState(row["state"]),
        )

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def create_workflow(self, workflow: Workflow) -> Workflow:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO workflows (workflow_id, tenant_id, user_id, status,
                                           current_run_id, metadata, version,
                                           created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $8)
                    """,
                    workflow.workflow_id, workflow.tenant_id, workflow.user_id,
                    workflow.status, workflow.current_run_id,
                    json.dumps(workflow.metadata), workflow.version,
                    datetime.now(timezone.utc),
                )
        return workflow

    async def get_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> Workflow | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            if tenant_id is not None:
                row = await conn.fetchrow(
                    "SELECT * FROM workflows WHERE workflow_id = $1 AND tenant_id = $2",
                    workflow_id, tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM workflows WHERE workflow_id = $1", workflow_id,
                )
        if row is None:
            return None
        return Workflow(
            workflow_id=row["workflow_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            status=row["status"],
            current_run_id=row["current_run_id"],
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            version=int(row["version"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    async def save_workflow(self, workflow: Workflow) -> Workflow:
        pool = self._ensure_pool()
        workflow.updated_at = utc_now_iso()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflows SET status = $2, current_run_id = $3,
                       metadata = $4::jsonb, version = version + 1, updated_at = $5
                WHERE workflow_id = $1
                """,
                workflow.workflow_id, workflow.status, workflow.current_run_id,
                json.dumps(workflow.metadata), datetime.now(timezone.utc),
            )
        return workflow

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO workflow_runs (run_id, workflow_id, tenant_id, user_id,
                        status, worker_id, lease_id, fencing_token, checkpoint_id,
                        agent_run_id, created_at, started_at, updated_at, completed_at,
                        cancellation_requested, failure_code, dispatch_attempts,
                        max_dispatch_attempts, version)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            COALESCE($11, NOW()), $12, NOW(), $13, $14, $15, $16, $17, $18)
                    """,
                    run.run_id, run.workflow_id, run.tenant_id, run.user_id,
                    run.status.value, run.worker_id, run.lease_id,
                    run.fencing_token, run.checkpoint_id, run.agent_run_id,
                    _parse(run.created_at),
                    _parse(run.started_at),
                    _parse(run.completed_at),
                    run.cancellation_requested, run.failure_code,
                    run.dispatch_attempts, run.max_dispatch_attempts, run.version,
                )
        return run

    async def get_run(
        self, run_id: str, *, tenant_id: str | None = None,
    ) -> WorkflowRun | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            if tenant_id is not None:
                row = await conn.fetchrow(
                    "SELECT * FROM workflow_runs WHERE run_id = $1 AND tenant_id = $2",
                    run_id, tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM workflow_runs WHERE run_id = $1", run_id,
                )
        return self._run_row(row) if row else None

    async def save_run(self, run: WorkflowRun) -> WorkflowRun:
        pool = self._ensure_pool()
        run.updated_at = utc_now_iso()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs SET status = $2, worker_id = $3, lease_id = $4,
                       fencing_token = $5, checkpoint_id = $6, agent_run_id = $7,
                       started_at = COALESCE($8, started_at),
                       updated_at = $9, completed_at = $10,
                       cancellation_requested = $11, failure_code = $12,
                       dispatch_attempts = $13, max_dispatch_attempts = $14,
                       version = version + 1
                WHERE run_id = $1
                """,
                run.run_id, run.status.value, run.worker_id, run.lease_id,
                run.fencing_token, run.checkpoint_id, run.agent_run_id,
                _parse(run.started_at), datetime.now(timezone.utc),
                _parse(run.completed_at), run.cancellation_requested,
                run.failure_code, run.dispatch_attempts,
                run.max_dispatch_attempts,
            )
        return run

    async def save_run_with_fencing(self, run: WorkflowRun, fencing_token: int) -> bool:
        pool = self._ensure_pool()
        run.updated_at = utc_now_iso()
        async with pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE workflow_runs SET status = $2, worker_id = $3, lease_id = $4,
                       fencing_token = $5, checkpoint_id = $6, agent_run_id = $7,
                       started_at = COALESCE($8, started_at), updated_at = $9,
                       completed_at = $10, cancellation_requested = $11,
                       failure_code = $12, dispatch_attempts = $13, version = version + 1
                WHERE run_id = $1
                  AND EXISTS (
                        SELECT 1 FROM worker_leases l
                        WHERE l.run_id = workflow_runs.run_id
                          AND l.worker_id = $3
                          AND l.fencing_token = $14
                          AND l.state = 'active'
                  )
                """,
                run.run_id, run.status.value, run.worker_id, run.lease_id,
                run.fencing_token, run.checkpoint_id, run.agent_run_id,
                _parse(run.started_at), datetime.now(timezone.utc),
                _parse(run.completed_at), run.cancellation_requested,
                run.failure_code, run.dispatch_attempts, fencing_token,
            )
        return res == "UPDATE 1"

    async def list_runs_for_workflow(
        self, workflow_id: str, *, tenant_id: str | None = None,
    ) -> list[WorkflowRun]:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workflow_runs WHERE workflow_id = $1
                AND ($2::text IS NULL OR tenant_id = $2)
                ORDER BY created_at ASC
                """,
                workflow_id, tenant_id,
            )
        return [self._run_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    async def enqueue_run(self, run: WorkflowRun) -> ExecutionQueueItem:
        pool = self._ensure_pool()
        payload = {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "agent_run_id": run.agent_run_id,
            # References only — never secrets/handles/checkpoints (invariant 5).
        }
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO execution_queue (queue_id, run_id, workflow_id, tenant_id,
                        user_id, state, payload, available_at, attempts, created_at)
                    VALUES ($1, $2, $3, $4, $5, 'queued', $6::jsonb, NOW(), 0, NOW())
                    ON CONFLICT (run_id) DO UPDATE SET
                        state = CASE WHEN execution_queue.state = 'dead'
                                     THEN 'dead' ELSE 'queued' END,
                        available_at = NOW(),
                        claimed_by = NULL,
                        claim_expires_at = NULL
                    WHERE execution_queue.state <> 'dead'
                       OR execution_queue.state = 'dead'  -- requeue allowed
                    RETURNING queue_id
                    """,
                    f"q_{run.run_id}", run.run_id, run.workflow_id,
                    run.tenant_id, run.user_id, json.dumps(payload),
                )
                if row is None:
                    item = await self.get_queue_item(run.run_id)
                    assert item is not None
                    return item
                return await self.get_queue_item(run.run_id)  # type: ignore[return-value]

    async def claim_next_run(
        self, worker_id: str, *, lease_seconds: float,
        tenant_id: str | None = None,
    ) -> tuple[WorkflowRun, WorkerLease, ExecutionQueueItem] | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT queue_id FROM execution_queue
                    WHERE (
                        (state = 'queued' AND available_at <= NOW())
                        OR (state = 'claimed' AND claim_expires_at < NOW())
                    )
                    AND ($1::text IS NULL OR tenant_id = $1)
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    tenant_id,
                )
                if row is None:
                    return None
                item = await conn.fetchrow(
                    "SELECT * FROM execution_queue WHERE queue_id = $1 FOR UPDATE",
                    row["queue_id"],
                )
                assert item is not None
                # Lease inside the same transaction (mutual exclusion).
                lease = await self._acquire_lease_conn(
                    conn, item["run_id"], worker_id, lease_seconds,
                )
                if lease is None:
                    return None
                run_row = await conn.fetchrow(
                    "SELECT * FROM workflow_runs WHERE run_id = $1 FOR UPDATE",
                    item["run_id"],
                )
                if run_row is None:
                    await self._release_lease_conn(
                        conn, item["run_id"], worker_id, lease.fencing_token,
                    )
                    return None
                run = self._run_row(run_row)
                if run.is_terminal():
                    await self._release_lease_conn(
                        conn, item["run_id"], worker_id, lease.fencing_token,
                    )
                    return None
                now = datetime.now(timezone.utc)
                await conn.execute(
                    """
                    UPDATE execution_queue SET state = 'claimed', claimed_by = $1,
                           claim_expires_at = $2, attempts = attempts + 1
                    WHERE queue_id = $3
                    """,
                    worker_id, now + timedelta(seconds=lease_seconds),
                    row["queue_id"],
                )
                run.worker_id = worker_id
                run.lease_id = lease.lease_id
                run.fencing_token = lease.fencing_token
                run.dispatch_attempts += 1
                if run.status is RunStatus.QUEUED:
                    run.status = RunStatus.DISPATCHED
                    run.started_at = now.isoformat()
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET status = $2, worker_id = $3,
                               lease_id = $4, fencing_token = $5,
                               dispatch_attempts = $6, started_at = $7,
                               updated_at = NOW(), version = version + 1
                        WHERE run_id = $1
                        """,
                        run.run_id, run.status.value, run.worker_id,
                        run.lease_id, run.fencing_token,
                        run.dispatch_attempts, now,
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET worker_id = $2, lease_id = $3,
                               fencing_token = $4, dispatch_attempts = $5,
                               updated_at = NOW(), version = version + 1
                        WHERE run_id = $1
                        """,
                        run.run_id, run.worker_id, run.lease_id,
                        run.fencing_token, run.dispatch_attempts,
                    )
                item_full = await conn.fetchrow(
                    "SELECT * FROM execution_queue WHERE queue_id = $1", row["queue_id"],
                )
                assert item_full is not None
                return (
                    run,
                    lease,
                    ExecutionQueueItem(
                        queue_id=item_full["queue_id"],
                        run_id=item_full["run_id"],
                        workflow_id=item_full["workflow_id"],
                        tenant_id=item_full["tenant_id"],
                        user_id=item_full["user_id"],
                        state=QueueItemState(item_full["state"]),
                        payload=json.loads(item_full["payload"]) if isinstance(item_full["payload"], str) else item_full["payload"],
                        available_at=item_full["available_at"].isoformat(),
                        claimed_by=item_full["claimed_by"],
                        claim_expires_at=item_full["claim_expires_at"].isoformat() if item_full["claim_expires_at"] else None,
                        attempts=int(item_full["attempts"]),
                        max_attempts=int(item_full["max_attempts"]),
                        created_at=item_full["created_at"].isoformat(),
                    ),
                )

    async def requeue_run(self, run_id: str, *, delay_seconds: float = 0.0) -> None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                res = await conn.execute(
                    """
                    UPDATE execution_queue SET state = 'queued',
                           available_at = NOW() + make_interval(secs => $1),
                           claimed_by = NULL, claim_expires_at = NULL
                    WHERE run_id = $2 AND state <> 'dead' AND attempts < max_attempts
                    """,
                    delay_seconds, run_id,
                )
                if res == "UPDATE 0":
                    await conn.execute(
                        "UPDATE execution_queue SET state = 'dead' WHERE run_id = $1",
                        run_id,
                    )

    async def dead_letter_run(self, run_id: str, reason: str) -> None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE execution_queue SET state = 'dead',
                       payload = payload || $2::jsonb
                WHERE run_id = $1
                """,
                run_id, json.dumps({"dead_letter_reason": reason}),
            )

    async def get_queue_item(self, run_id: str) -> ExecutionQueueItem | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM execution_queue WHERE run_id = $1", run_id,
            )
        if row is None:
            return None
        return ExecutionQueueItem(
            queue_id=row["queue_id"],
            run_id=row["run_id"],
            workflow_id=row["workflow_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            state=QueueItemState(row["state"]),
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            available_at=row["available_at"].isoformat(),
            claimed_by=row["claimed_by"],
            claim_expires_at=row["claim_expires_at"].isoformat() if row["claim_expires_at"] else None,
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            created_at=row["created_at"].isoformat(),
        )

    # ------------------------------------------------------------------
    # Leases (fenced, monotonic tokens)
    # ------------------------------------------------------------------

    async def _acquire_lease_conn(
        self, conn: asyncpg.Connection, run_id: str, worker_id: str,
        lease_seconds: float,
    ) -> WorkerLease | None:
        row = await conn.fetchrow(
            """
            INSERT INTO worker_leases (run_id, worker_id, lease_id, fencing_token,
                                       acquired_at, expires_at, renewed_at, state)
            VALUES ($1, $2, $3, 1, NOW(), NOW() + make_interval(secs => $4), NOW(), 'active')
            ON CONFLICT (run_id) DO UPDATE SET
                worker_id = $2,
                lease_id = $3,
                fencing_token = CASE WHEN worker_leases.worker_id = $2
                    THEN worker_leases.fencing_token
                    ELSE worker_leases.fencing_token + 1 END,
                acquired_at = NOW(),
                expires_at = NOW() + make_interval(secs => $4),
                renewed_at = NOW(),
                state = 'active'
            WHERE worker_leases.worker_id = $2
               OR worker_leases.state <> 'active'
               OR worker_leases.expires_at < NOW()
            RETURNING *
            """,
            run_id, worker_id, f"lease_{run_id}_{worker_id}",
            lease_seconds,
        )
        return self._lease_row(row) if row else None

    async def acquire_lease(
        self, run_id: str, worker_id: str, lease_seconds: float,
    ) -> WorkerLease | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await self._acquire_lease_conn(
                    conn, run_id, worker_id, lease_seconds,
                )

    async def renew_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
        lease_seconds: float,
    ) -> WorkerLease | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE worker_leases SET expires_at = NOW() + make_interval(secs => $4),
                       renewed_at = NOW()
                WHERE run_id = $1 AND worker_id = $2 AND fencing_token = $3
                  AND state = 'active' AND expires_at > NOW()
                RETURNING *
                """,
                run_id, worker_id, fencing_token, lease_seconds,
            )
        return self._lease_row(row) if row else None

    async def release_lease(
        self, run_id: str, worker_id: str, fencing_token: int,
    ) -> bool:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE worker_leases SET state = 'released'
                WHERE run_id = $1 AND worker_id = $2 AND fencing_token = $3
                """,
                run_id, worker_id, fencing_token,
            )
        return res == "UPDATE 1"

    async def get_lease(self, run_id: str) -> WorkerLease | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM worker_leases WHERE run_id = $1", run_id,
            )
        return self._lease_row(row) if row else None

    async def count_active_leases(self) -> int:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM worker_leases WHERE state = 'active' AND expires_at > NOW()",
            )
        return int(row["n"]) if row else 0

    async def reap_expired_leases(self, now: datetime | None = None) -> int:
        pool = self._ensure_pool()
        reaped = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    UPDATE worker_leases SET state = 'expired'
                    WHERE state = 'active' AND expires_at < NOW()
                    RETURNING run_id
                    """,
                )
                for row in rows:
                    reaped += 1
                    run_row = await conn.fetchrow(
                        "SELECT status FROM workflow_runs WHERE run_id = $1 FOR UPDATE",
                        row["run_id"],
                    )
                    if run_row is None:
                        continue
                    current = RunStatus(run_row["status"])
                    if current in TERMINAL_OR_RECOVERY:
                        continue
                    validate_transition(current, RunStatus.RECOVERY_REQUIRED)
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET status = 'recovery_required',
                               updated_at = NOW(), version = version + 1
                        WHERE run_id = $1
                        """,
                        row["run_id"],
                    )
                    await conn.execute(
                        """
                        UPDATE execution_queue SET state = 'queued',
                               available_at = NOW(), claimed_by = NULL,
                               claim_expires_at = NULL
                        WHERE run_id = $1 AND state <> 'dead' AND attempts < max_attempts
                        """,
                        row["run_id"],
                    )
        return reaped

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def put_idempotency_if_absent(
        self, record: IdempotencyRecord,
    ) -> IdempotencyRecord | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO idempotency_keys (key, tenant_id, operation, request_hash,
                                              status_code, response, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
                ON CONFLICT (key, tenant_id) DO NOTHING
                RETURNING *
                """,
                record.key, record.tenant_id, record.operation,
                record.request_hash, record.status_code,
                json.dumps(record.response),
            )
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            tenant_id=row["tenant_id"],
            operation=row["operation"],
            request_hash=row["request_hash"],
            status_code=int(row["status_code"]),
            response=json.loads(row["response"]) if isinstance(row["response"], str) else row["response"],
            created_at=row["created_at"].isoformat(),
        )

    async def get_idempotency(
        self, key: str, tenant_id: str,
    ) -> IdempotencyRecord | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM idempotency_keys WHERE key = $1 AND tenant_id = $2",
                key, tenant_id,
            )
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            tenant_id=row["tenant_id"],
            operation=row["operation"],
            request_hash=row["request_hash"],
            status_code=int(row["status_code"]),
            response=json.loads(row["response"]) if isinstance(row["response"], str) else row["response"],
            created_at=row["created_at"].isoformat(),
        )

    async def update_idempotency_response(
        self, key: str, tenant_id: str, status_code: int,
        response: dict[str, Any],
    ) -> None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE idempotency_keys SET status_code = $3, response = $4::jsonb
                WHERE key = $1 AND tenant_id = $2
                """,
                key, tenant_id, status_code, json.dumps(response),
            )

    # ------------------------------------------------------------------
    # Audit (append-only: INSERT is the only path)
    # ------------------------------------------------------------------

    async def append_audit(self, event: AuditEvent) -> AuditEvent:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (event_id, parent_event_id, tenant_id, user_id,
                    workflow_id, run_id, worker_id, event_type, actor_type, actor_id,
                    action, policy_result, hitl_result, security_event, payload, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                        $15::jsonb, NOW())
                """,
                event.event_id, event.parent_event_id, event.tenant_id, event.user_id,
                event.workflow_id, event.run_id, event.worker_id, event.event_type,
                event.actor_type, event.actor_id, event.action, event.policy_result,
                event.hitl_result, event.security_event, json.dumps(event.payload),
            )
        return event

    async def list_audit(
        self, *, tenant_id: str, workflow_id: str | None = None,
        run_id: str | None = None, limit: int = 100,
    ) -> list[AuditEvent]:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_events
                WHERE tenant_id = $1
                  AND ($2::text IS NULL OR workflow_id = $2)
                  AND ($3::text IS NULL OR run_id = $3)
                ORDER BY created_at ASC LIMIT $4
                """,
                tenant_id, workflow_id, run_id, limit,
            )
        events: list[AuditEvent] = []
        for row in rows:
            events.append(AuditEvent(
                event_id=row["event_id"],
                parent_event_id=row["parent_event_id"],
                tenant_id=row["tenant_id"],
                user_id=row["user_id"],
                workflow_id=row["workflow_id"],
                run_id=row["run_id"],
                worker_id=row["worker_id"],
                event_type=row["event_type"],
                actor_type=row["actor_type"],
                actor_id=row["actor_id"],
                action=row["action"],
                policy_result=row["policy_result"],
                hitl_result=row["hitl_result"],
                security_event=row["security_event"],
                payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
                created_at=row["created_at"].isoformat(),
            ))
        return events

    async def count_audit(self, *, tenant_id: str | None = None) -> int:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            if tenant_id is None:
                row = await conn.fetchrow("SELECT COUNT(*) AS n FROM audit_events")
            else:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM audit_events WHERE tenant_id = $1",
                    tenant_id,
                )
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def request_cancellation(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None:
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM workflow_runs WHERE run_id = $1::text AND tenant_id = $2::text FOR UPDATE",
                    run_id, tenant_id,
                )
                if row is None:
                    return None
                run = self._run_row(row)
                if run.is_terminal():
                    return run
                if run.status is RunStatus.QUEUED:
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET status = 'cancelled',
                               cancellation_requested = TRUE, completed_at = NOW(),
                               updated_at = NOW(), version = version + 1
                        WHERE run_id = $1
                        """,
                        run_id,
                    )
                elif run.status in CANCELLABLE_FOR_REQUEST:
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET status = 'cancellation_requested',
                               cancellation_requested = TRUE, updated_at = NOW(),
                               version = version + 1
                        WHERE run_id = $1
                        """,
                        run_id,
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE workflow_runs SET cancellation_requested = TRUE,
                               updated_at = NOW(), version = version + 1
                        WHERE run_id = $1
                        """,
                        run_id,
                    )
                updated = await conn.fetchrow(
                    "SELECT * FROM workflow_runs WHERE run_id = $1", run_id,
                )
                assert updated is not None
                return self._run_row(updated)

    async def cancel_queued_run(
        self, run_id: str, *, tenant_id: str,
    ) -> WorkflowRun | None:
        return await self.request_cancellation(run_id, tenant_id=tenant_id)


# Terminal statuses that must never be reaped into recovery, and statuses
# from which a cancellation REQUEST is legal.
from app.enterprise.models import TERMINAL_RUN_STATUSES  # noqa: E402

TERMINAL_OR_RECOVERY = frozenset(
    set(TERMINAL_RUN_STATUSES) | {RunStatus.RECOVERY_REQUIRED}
)
CANCELLABLE_FOR_REQUEST = frozenset({
    RunStatus.DISPATCHED,
    RunStatus.RUNNING,
    RunStatus.PAUSED_HITL,
    RunStatus.PAUSED_RECOVERY,
})
