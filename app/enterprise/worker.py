"""ExecutionWorker — Phase 13 (invariants 1, 4, 6, 17).

Worker lifecycle: claim → lease+fencing token → verify executable →
load checkpoint → run/resume AgentRuntime → periodic renewal →
execute → checkpoint → release.

Fail-closed rules:
- Lease renewal failure stops browser execution immediately; the worker
  reports RECOVERY_REQUIRED (best effort, fenced) and exits without
  further mutation.
- A stale worker cannot corrupt state: completion/failure/pause writes
  are fencing-validated by the store.
- The worker NEVER bypasses the engine/AgentRuntime path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.persistence.store import CheckpointStore
from app.agent.evaluation.trace import TraceRecorder
from app.config.settings import Settings
from app.enterprise.engine import (
    EngineOutcome,
    LeaseGuard,
    LeaseLostError,
    WorkerRunEngine,
)
from app.enterprise.models import (
    AuthorizationError,
    Identity,
    RunStatus,
    WorkflowRun,
    validate_transition,
)
from app.enterprise.store import EnterpriseStore
from app.enterprise.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class ExecutionWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        store: EnterpriseStore,
        service: WorkflowService,
        checkpoint_store: CheckpointStore | None = None,
        settings: Settings | None = None,
        model_factory: Any = None,
        lease_seconds: float = 30.0,
        renewal_interval_seconds: float = 8.0,
        progress_interval_seconds: float = 5.0,
        metrics: Any = None,
    ) -> None:
        self.worker_id = worker_id
        self._store = store
        self._service = service
        self._checkpoint_store = checkpoint_store
        self._settings = settings or Settings(headless=True)
        self._model_factory = model_factory or (lambda: None)
        self._lease_seconds = lease_seconds
        self._renewal_interval = renewal_interval_seconds
        self._progress_interval = progress_interval_seconds
        self._metrics = metrics
        self._claimed: dict[str, LeaseGuard] = {}
        self._cancel_flag: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def identity(self) -> Identity:
        return Identity(
            actor_type=__import__(
                "app.enterprise.models", fromlist=["ActorType"]
            ).ActorType.WORKER,
            tenant_id="",
            subject_id=self.worker_id,
            role=__import__(
                "app.enterprise.models", fromlist=["Role"]
            ).Role.WORKER,
        )

    # ------------------------------------------------------------------
    # Claim / execute one run
    # ------------------------------------------------------------------

    async def claim_next_run(
        self, *, lease_seconds: float | None = None,
    ) -> WorkflowRun | None:
        result = await self._store.claim_next_run(
            self.worker_id,
            lease_seconds=lease_seconds or self._lease_seconds,
        )
        if result is None:
            return None
        run, lease, _item = result
        guard = LeaseGuard(renew=self._make_renewal(run.run_id, lease))
        self._claimed[run.run_id] = guard
        return run

    def _make_renewal(self, run_id: str, lease):
        async def _renew():
            return await self._store.renew_lease(
                run_id, self.worker_id, lease.fencing_token,
                self._lease_seconds,
            )
        return _renew

    async def run_claimed_run(
        self,
        run: WorkflowRun,
        *,
        goal: str,
        start_url: str,
        model: Any = None,
    ) -> EngineOutcome:
        """Execute one claimed run to a terminal/pause boundary.

        The caller (worker loop or test) supplies the task goal and start
        URL (from workflow metadata) — the worker itself never trusts
        client-controlled execution parameters beyond the durable record.
        """
        guard = self._claimed.get(run.run_id)
        if guard is None:
            raise RuntimeError(f"run {run.run_id} not claimed by this worker")

        engine = WorkerRunEngine(
            model=model if model is not None else self._model_factory(),
            settings=self._settings,
            checkpoint_store=self._checkpoint_store,
            recorder=TraceRecorder(
                run_id=run.run_id,
                scenario_id=f"enterprise:{run.workflow_id}",
            ),
            max_iterations=15,
            max_tool_calls=25,
        )

        # Dispatched → RUNNING (fenced write).
        run.status = RunStatus.RUNNING
        if not await self._store.save_run_with_fencing(
            run, run.fencing_token,
        ):
            logger.error(
                "run %s: fenced RUNNING write rejected — stale worker",
                run.run_id,
            )
            self._metrics_stale()
            self._claimed.pop(run.run_id, None)
            return EngineOutcome.LEASE_LOST

        lease_task = asyncio.create_task(
            self._renewal_loop(run.run_id, guard),
        )
        try:
            result = await engine.execute(
                goal=goal,
                start_url=start_url,
                agent_run_id=run.agent_run_id,
                checkpoint_id=run.checkpoint_id,
                lease_guard=guard,
                cancel_check=lambda: self._cancel_flag.get(run.run_id, False),
            )
        finally:
            lease_task.cancel()
            try:
                await lease_task
            except (asyncio.CancelledError, Exception):
                pass

        await self._finalize(run, result)
        self._claimed.pop(run.run_id, None)
        return result.outcome

    # ------------------------------------------------------------------
    # Renewal loop (invariant 6: renewal failure ⇒ fail closed)
    # ------------------------------------------------------------------

    async def _renewal_loop(self, run_id: str, guard: LeaseGuard) -> None:
        while True:
            await asyncio.sleep(self._renewal_interval)
            ok = await guard.renew()
            if not ok:
                logger.error(
                    "run %s: lease renewal failed — failing closed", run_id,
                )
                self._metrics_lease_expired()
                return

    # ------------------------------------------------------------------
    # Finalization per engine outcome
    # ------------------------------------------------------------------

    async def _finalize(
        self, run: WorkflowRun, result,
    ) -> None:
        token = run.fencing_token
        try:
            if result.outcome is EngineOutcome.COMPLETED:
                await self._service.complete_run(
                    self.identity, run.run_id,
                    fencing_token=token,
                    checkpoint_id=result.checkpoint_id,
                )
                await self._store.release_lease(
                    run.run_id, self.worker_id, token,
                )
            elif result.outcome is EngineOutcome.PAUSED_HITL:
                await self._service.report_pause(
                    self.identity, run.run_id,
                    fencing_token=token,
                    paused_hitl=True,
                    checkpoint_id=result.checkpoint_id,
                )
                # Release the lease: the run waits for the human and the
                # resume request requeues it for the (possibly different)
                # resuming worker.
                await self._store.release_lease(
                    run.run_id, self.worker_id, token,
                )
            elif result.outcome is EngineOutcome.CANCELLED:
                await self._store.cancel_queued_run(
                    run.run_id, tenant_id=run.tenant_id,
                )
            elif result.outcome is EngineOutcome.LEASE_LOST:
                # Best-effort durable marker; the fencing write may
                # legitimately fail (that is the point of fencing).
                await self._mark_recovery_required(run, token)
            else:  # FAILED
                await self._service.fail_run(
                    self.identity, run.run_id,
                    fencing_token=token,
                    failure_code=result.error or "engine_failed",
                    checkpoint_id=result.checkpoint_id,
                )
                await self._store.release_lease(
                    run.run_id, self.worker_id, token,
                )
        except AuthorizationError as exc:
            logger.error(
                "run %s: finalization rejected (%s) — stale worker",
                run.run_id, exc,
            )
            self._metrics_stale()

    async def _mark_recovery_required(self, run: WorkflowRun, token: int) -> None:
        try:
            fresh = await self._store.get_run(run.run_id)
            if fresh is None or fresh.is_terminal():
                return
            if fresh.status is not RunStatus.RECOVERY_REQUIRED:
                validate_transition(fresh.status, RunStatus.RECOVERY_REQUIRED)
                fresh.status = RunStatus.RECOVERY_REQUIRED
                await self._store.save_run(fresh)
            await self._store.release_lease(run.run_id, self.worker_id, token)
        except Exception:
            logger.exception(
                "run %s: recovery marker failed", run.run_id,
            )

    # ------------------------------------------------------------------
    # Metrics helpers (tolerate metrics=None in tests)
    # ------------------------------------------------------------------

    def _metrics_stale(self) -> None:
        if self._metrics is not None:
            self._metrics.stale_worker_rejected()

    def _metrics_lease_expired(self) -> None:
        if self._metrics is not None:
            self._metrics.lease_expired()

    # ------------------------------------------------------------------
    # Cancellation flag cache (polled at safe boundaries)
    # ------------------------------------------------------------------

    async def refresh_cancellation_flags(self) -> None:
        """Reload cancellation_requested for claimed runs (the engine
        polls the in-memory flag at safe boundaries; the durable flag is
        refreshed from the store periodically)."""
        for run_id in list(self._cancel_flag.keys()):
            run = await self._store.get_run(run_id)
            if run is None or run.cancellation_requested:
                self._cancel_flag[run_id] = True

    def note_cancellation_flag(self, run_id: str) -> None:
        self._cancel_flag[run_id] = True
