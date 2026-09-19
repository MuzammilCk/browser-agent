"""Real-Chromium enterprise acceptance tests — Phase 13.

Acceptance scenario 1 (full flow):
    Client/API → authentication → Workflow Service → durable run → queue
    → Execution Worker → AgentRuntime → real Chromium → ToolRegistry
    → PolicyEngine → BrowserExecutor → verification → WorldState
    → checkpoint/audit → workflow completion.

Acceptance scenario 2 (crash/recovery):
    Worker A claims → executes → "crashes" → lease expires → Worker B
    claims → loads checkpoint → revalidates → re-observes → resumes.

Uses the real agent stack with a deterministic MockDecisionModel (the
same pattern as the Phase 12 evaluation tests — no API key needed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agent.reasoning import MockDecisionModel
from app.agent.evaluation.trace import TraceEventType, TraceRecorder
from app.config.settings import Settings
from app.enterprise import worker as worker_module
from app.enterprise.audit import AuditService
from app.enterprise.engine import EngineOutcome
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    Identity,
    Role,
    RunStatus,
    Workflow,
)
from app.enterprise.postgres_store import PostgresEnterpriseStore
from app.enterprise.workflow_service import WorkflowService

SYNTHETIC_PAGES_DIR = (
    Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
)
SIMPLE_URI = (SYNTHETIC_PAGES_DIR / "simple.html").as_uri()


def _fill_script(name_value: str) -> list[dict]:
    """Decision script: observe → fill fullName → complete."""
    return [
        {"decision_type": "tool_call", "tool_name": "observe_page",
         "arguments": {}, "reason": "look", "question": "", "plan": [],
         "confidence": None},
        {"decision_type": "tool_call", "tool_name": "fill_field",
         "arguments": {},
         "action": {"action": "fill", "target_ref": "e1",
                    "literal_value": name_value},
         "reason": "fill name", "question": "", "plan": [],
         "confidence": None},
        {"decision_type": "complete", "tool_name": "", "arguments": {},
         "reason": "done", "question": "", "plan": [], "confidence": None},
    ]


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


class TestFullEnterpriseFlowChromium:
    """Acceptance 1: API → workflow → queue → worker → real Chromium."""

    @pytest.mark.asyncio
    async def test_api_to_chromium_completion(self, settings):
        store = InMemoryEnterpriseStore()
        audit = AuditService(store)
        service = WorkflowService(store, audit)

        user = Identity(
            actor_type=ActorType.USER, tenant_id="tenant-acceptance",
            subject_id="citizen-1", role=Role.USER,
        )

        # 1-2. Authenticated client creates workflow + run through the
        #      Workflow Service (authorization enforced server-side).
        wf = await service.create_workflow(
            user,
            goal="Fill the fullName field on the form",
            metadata={"start_url": SIMPLE_URI},
        )
        run = await service.create_run(user, wf.workflow_id)
        assert run.status is RunStatus.QUEUED

        # 3-5. Execution Worker claims from the durable queue and acquires
        #      a lease with a fencing token.
        worker = worker_module.ExecutionWorker(
            worker_id="worker_acceptance",
            store=store,
            service=service,
            settings=settings,
            lease_seconds=120.0,
        )
        claimed = await worker.claim_next_run()
        assert claimed is not None
        assert claimed.run_id == run.run_id
        lease = await store.get_lease(run.run_id)
        assert lease is not None and lease.state.value == "active"
        assert lease.fencing_token >= 1

        # 6-12. Worker drives the REAL AgentRuntime → ToolRegistry →
        #       PolicyEngine → BrowserExecutor → Chromium → verification.
        model = MockDecisionModel(_fill_script("Asha Kumar"))
        outcome = await worker.run_claimed_run(
            claimed,
            goal="Fill the fullName field on the form",
            start_url=SIMPLE_URI,
            model=model,
        )

        # Workflow completion is durable and audited.
        assert outcome is EngineOutcome.COMPLETED
        final = await store.get_run(run.run_id)
        assert final.status is RunStatus.COMPLETED

        all_events = await audit.read(identity=user)
        event_types = [e.event_type for e in all_events]
        assert "WORKFLOW_CREATED" in event_types
        assert "RUN_QUEUED" in event_types
        run_events = await audit.read(identity=user, run_id=run.run_id)
        assert "RUN_COMPLETED" in [e.event_type for e in run_events]

        # Lease released after completion.
        lease = await store.get_lease(run.run_id)
        assert lease.state.value == "released"

    @pytest.mark.asyncio
    async def test_worker_uses_real_runtime_trace(self, settings):
        """The engine ran the real agent loop: the durable checkpoint
        records WorldState + full event log from the actual stack."""
        from app.agent.runtime.checkpoint import InMemoryCheckpointStore

        store = InMemoryEnterpriseStore()
        service = WorkflowService(store, AuditService(store))
        wf = Workflow(
            tenant_id="t_trace", user_id="u1",
            metadata={"goal": "g", "start_url": SIMPLE_URI},
        )
        await store.create_workflow(wf)
        from app.enterprise.models import WorkflowRun
        run = WorkflowRun(workflow_id=wf.workflow_id, tenant_id="t_trace", user_id="u1")
        await store.create_run(run)
        await store.enqueue_run(run)

        cp_store = InMemoryCheckpointStore()
        worker = worker_module.ExecutionWorker(
            worker_id="worker_trace",
            store=store,
            service=service,
            checkpoint_store=cp_store,
            settings=settings,
            lease_seconds=120.0,
        )
        claimed = await worker.claim_next_run()
        model = MockDecisionModel(_fill_script("Trace User"))
        outcome = await worker.run_claimed_run(
            claimed, goal="g", start_url=SIMPLE_URI, model=model,
        )
        assert outcome is EngineOutcome.COMPLETED
        # The engine used the real stack — the durable checkpoint has
        # WorldState and the full runtime event log.
        run_record = await store.get_run(run.run_id)
        assert run_record.checkpoint_id is not None
        cp = cp_store.load(run_record.checkpoint_id)
        assert cp is not None
        assert cp.state.agent_world_state is not None
        event_types = [e.event_type.value for e in cp.events]
        assert "run_started" in event_types
        assert "checkpoint_created" in event_types


class TestWorkerCrashRecoveryChromium:
    """Acceptance 2: Worker A executes, crashes; Worker B resumes safely."""

    @pytest.mark.asyncio
    async def test_worker_a_crashes_worker_b_resumes(self, settings):
        store = InMemoryEnterpriseStore()
        service = WorkflowService(store, AuditService(store))
        user = Identity(
            actor_type=ActorType.USER, tenant_id="t_crash",
            subject_id="u1", role=Role.USER,
        )
        wf = await service.create_workflow(
            user, goal="Fill the fullName field",
            metadata={"start_url": SIMPLE_URI},
        )
        run = await service.create_run(user, wf.workflow_id)

        # Worker A claims and begins execution (short lease simulating
        # an imminent crash).
        worker_a = worker_module.ExecutionWorker(
            worker_id="worker_A", store=store, service=service,
            settings=settings, lease_seconds=0.3,
            renewal_interval_seconds=0.05,
        )
        claimed_a = await worker_a.claim_next_run()
        assert claimed_a is not None

        # Worker A "crashes" mid-execution: no release, no finalization.
        await asyncio.sleep(0.5)

        # Lease reaper: expires lease, flags RECOVERY_REQUIRED, requeues.
        reaped = await store.reap_expired_leases()
        assert reaped == 1
        recovered = await service.recover_run(run.run_id)
        assert recovered is True

        # Worker B claims the same run, acquires a HIGHER fencing token,
        # and completes the workflow through the real stack.
        worker_b = worker_module.ExecutionWorker(
            worker_id="worker_B", store=store, service=service,
            settings=settings, lease_seconds=120.0,
        )
        claimed_b = await worker_b.claim_next_run()
        assert claimed_b is not None
        assert claimed_b.run_id == run.run_id
        lease_b = await store.get_lease(run.run_id)
        assert lease_b.fencing_token >= 2  # strictly higher than A's token

        model = MockDecisionModel(_fill_script("Asha Kumar"))
        outcome = await worker_b.run_claimed_run(
            claimed_b, goal="Fill the fullName field",
            start_url=SIMPLE_URI, model=model,
        )
        assert outcome is EngineOutcome.COMPLETED
        final = await store.get_run(run.run_id)
        assert final.status is RunStatus.COMPLETED
        assert final.worker_id == "worker_B"

    @pytest.mark.asyncio
    async def test_stale_worker_a_cannot_corrupt_completed_run(
        self, settings,
    ):
        """After Worker B takes over, a resurrected Worker A's fenced
        writes are rejected by the store (fail closed)."""
        store = InMemoryEnterpriseStore()
        service = WorkflowService(store, AuditService(store))
        wf = Workflow(
            tenant_id="t_stale", user_id="u1",
            metadata={"goal": "g", "start_url": SIMPLE_URI},
        )
        await store.create_workflow(wf)
        from app.enterprise.models import WorkflowRun
        run = WorkflowRun(workflow_id=wf.workflow_id, tenant_id="t_stale", user_id="u1")
        await store.create_run(run)
        await store.enqueue_run(run)

        claimed_a = await store.claim_next_run("worker_A", lease_seconds=0.3)
        token_a = claimed_a[1].fencing_token
        await asyncio.sleep(0.5)
        await store.reap_expired_leases()
        await service.recover_run(run.run_id)
        claimed_b = await store.claim_next_run("worker_B", lease_seconds=30)
        assert claimed_b is not None

        # Zombie A completes its view of the run:
        stale = claimed_a[0]
        stale.status = RunStatus.COMPLETED
        ok = await store.save_run_with_fencing(stale, token_a)
        assert ok is False
        # B's authoritative view is intact.
        fresh = await store.get_run(run.run_id)
        assert fresh.worker_id == "worker_B"


class TestPhase12Compatibility:
    """Phase 12 evaluation continues to run the real AgentRuntime."""

    @pytest.mark.asyncio
    async def test_evaluation_scenario_runner_still_works(self, settings):
        from app.agent.evaluation.models import (
            EvaluationScenario,
            EvaluationStatus,
            ScenarioCategory,
            SafetyConstraintKind,
            SafetyConstraintSpec,
            SuccessCriterionKind,
            SuccessCriterionSpec,
        )
        from app.agent.evaluation.runner import ScenarioRunner

        scenario = EvaluationScenario(
            scenario_id="p13_compat_1",
            name="Phase 13 Compatibility",
            description="Evaluation runs the real runtime after enterprise additions",
            category=ScenarioCategory.BASIC_FORM,
            page_url=SIMPLE_URI,
            task_goal="Fill fullName",
            success_criteria=[
                SuccessCriterionSpec(
                    kind=SuccessCriterionKind.DOM_FIELD_VALUE,
                    description="Name filled",
                    selector="#fullName",
                    expected_value="Asha Kumar",
                ),
            ],
            safety_constraints=[
                SafetyConstraintSpec(
                    kind=SafetyConstraintKind.ZERO_UNAUTHORIZED_MUTATIONS,
                    description="Zero unauthorized actions",
                ),
            ],
        )
        runner = ScenarioRunner(
            scenario, model=MockDecisionModel(_fill_script("Asha Kumar")),
            settings=settings,
        )
        result, recorder = await runner.run()
        assert result.status is EvaluationStatus.SUCCESS
        assert result.safety_pass is True

    @pytest.mark.asyncio
    async def test_engine_matches_scenariorunner_conventions(self, settings):
        """The enterprise engine executes the SAME real stack as the
        Phase 12 ScenarioRunner (no alternative execution path)."""
        from app.agent.evaluation.trace import TraceRecorder
        from app.agent.runtime.checkpoint import InMemoryCheckpointStore
        from app.enterprise.engine import WorkerRunEngine

        engine = WorkerRunEngine(
            model=MockDecisionModel(_fill_script("Engine User")),
            settings=settings,
            checkpoint_store=InMemoryCheckpointStore(),
        )
        result = await engine.execute(
            goal="Fill the fullName field",
            start_url=SIMPLE_URI,
        )
        assert result.outcome is EngineOutcome.COMPLETED
        assert result.checkpoint_id is not None
