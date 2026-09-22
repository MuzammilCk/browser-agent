"""Phase 15 H3/H4 regression tests — enterprise engine loop hardening.

H3: the engine must (a) surface model ASK_USER decisions as durable HITL
    pauses (never silent iteration burn), (b) enforce the replan budget,
    (c) enforce the tool-call budget, (d) persist budget mutations into
    run_state so checkpoints carry the true consumed budget.
H4: a fresh worker process must be able to resume a run whose checkpoint
    lives only in the async store (PostgreSQL semantics: the runtime's
    sync load() is cache-only there). Resume fails closed on unknown
    checkpoints, unchanged.

Real-Chromium tests use the synthetic simple.html page with the
deterministic MockDecisionModel (same pattern as the Phase 13
acceptance tests — no API key needed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.reasoning import MockDecisionModel
from app.config.settings import Settings
from app.enterprise.engine import EngineOutcome, WorkerRunEngine

SYNTHETIC_PAGES_DIR = (
    Path(__file__).resolve().parent.parent / "synthetic_forms" / "pages"
)
SIMPLE_URI = (SYNTHETIC_PAGES_DIR / "simple.html").as_uri()


def _decision(d: dict) -> dict:
    """Full canonical decision-dict shape used by the mock model."""
    base = {
        "tool_name": "",
        "arguments": {},
        "action": None,
        "question": "",
        "plan": [],
        "confidence": None,
    }
    base.update(d)
    return base


def _fill(ref: str = "e1", value: str = "Asha Kumar") -> dict:
    return _decision({
        "decision_type": "tool_call",
        "tool_name": "fill_field",
        "action": {"action": "fill", "target_ref": ref, "literal_value": value},
        "reason": "fill",
    })


class AsyncOnlyCheckpointStore:
    """Mimics PostgresCheckpointStore's process semantics: the async
    surface is the "database"; the sync surface is a per-process cache
    that starts empty in a fresh process."""

    def __init__(self) -> None:
        self._db: dict = {}
        self._sync_cache: dict = {}

    def fork_new_process(self) -> "AsyncOnlyCheckpointStore":
        """A store as seen from a fresh process: same database, empty cache."""
        clone = AsyncOnlyCheckpointStore()
        clone._db = self._db
        return clone

    # Sync surface (runtime-side cache, Postgres-like)
    def save(self, checkpoint) -> None:
        self._sync_cache[checkpoint.checkpoint_id] = checkpoint

    def load(self, checkpoint_id: str):
        return self._sync_cache.get(checkpoint_id)

    def list_for_run(self, run_id: str) -> list[str]:
        return [
            c.checkpoint_id for c in self._sync_cache.values()
            if c.run_id == run_id
        ]

    # Async surface (the real database)
    async def save_checkpoint(self, checkpoint) -> None:
        import copy
        self._db[checkpoint.checkpoint_id] = copy.deepcopy(checkpoint)

    async def load_checkpoint(self, checkpoint_id: str):
        import copy
        cp = self._db.get(checkpoint_id)
        return copy.deepcopy(cp) if cp is not None else None


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


class TestAskUserDurablePause:
    async def test_ask_user_pauses_with_durable_interrupt(self, settings):
        """The model deciding to ask the human must pause the run
        durably (PAUSED_HITL + persisted interrupt) — never burn
        iterations in a silent loop (Phase 15 H3a)."""
        from app.agent.persistence.in_memory_store import InMemoryCheckpointStore

        cp_store = InMemoryCheckpointStore()
        engine = WorkerRunEngine(
            model=MockDecisionModel([
                _decision({
                    "decision_type": "ask_user",
                    "question": "Which regional office should the form use?",
                    "reason": "ambiguous form variant",
                }),
            ]),
            settings=settings,
            checkpoint_store=cp_store,
            max_iterations=5,
        )
        result = await engine.execute(
            goal="Fill the form",
            start_url=SIMPLE_URI,
        )
        assert result.outcome is EngineOutcome.PAUSED_HITL
        assert result.iterations == 1  # consumed exactly one iteration

        # The interrupt is durably checkpointed with the run.
        cp = await cp_store.load_checkpoint(result.checkpoint_id)
        assert cp is not None
        assert cp.human_interrupt is not None
        assert cp.human_interrupt.reason.value == "user_clarification_required"
        assert "regional office" in cp.human_interrupt.description

    async def test_ask_user_interrupt_survives_resume(self, settings):
        """Resuming after an ASK_USER pause restores the same run."""
        from app.agent.persistence.in_memory_store import InMemoryCheckpointStore

        cp_store = InMemoryCheckpointStore()
        engine = WorkerRunEngine(
            model=MockDecisionModel([
                _decision({
                    "decision_type": "ask_user",
                    "question": "Confirm the applicant's office?",
                    "reason": "confirmation needed",
                }),
            ]),
            settings=settings,
            checkpoint_store=cp_store,
        )
        paused = await engine.execute(goal="Fill", start_url=SIMPLE_URI)
        assert paused.outcome is EngineOutcome.PAUSED_HITL

        resumed = await engine.execute(
            goal="Fill",
            start_url=SIMPLE_URI,
            agent_run_id=paused.agent_run_id,
            checkpoint_id=paused.checkpoint_id,
        )
        assert resumed.agent_run_id == paused.agent_run_id


class TestReplanBudgetEnforced:
    async def test_replans_beyond_budget_fail_closed(self, settings):
        """RuntimeBudget.max_replans (default 5) is enforced in the
        enterprise loop — the 6th replan fails the run explicitly."""
        script = [
            _decision({"decision_type": "replan", "reason": f"r{i}"})
            for i in range(6)
        ]
        engine = WorkerRunEngine(
            model=MockDecisionModel(script),
            settings=settings,
            max_iterations=15,
        )
        result = await engine.execute(goal="Fill", start_url=SIMPLE_URI)
        assert result.outcome is EngineOutcome.FAILED
        assert result.error is not None
        assert "budget exhausted" in result.error
        assert "replans" in result.error

    async def test_replans_within_budget_continue(self, settings):
        """Two replans then complete: within budget, run completes."""
        script = [
            _decision({"decision_type": "replan", "reason": "r1"}),
            _decision({"decision_type": "replan", "reason": "r2"}),
            _decision({"decision_type": "complete", "reason": "done"}),
        ]
        engine = WorkerRunEngine(
            model=MockDecisionModel(script),
            settings=settings,
        )
        result = await engine.execute(goal="Fill", start_url=SIMPLE_URI)
        assert result.outcome is EngineOutcome.COMPLETED


class TestToolCallBudgetEnforced:
    async def test_tool_calls_beyond_budget_fail_closed(self, settings):
        """max_tool_calls is enforced at the engine boundary (H3c)."""
        engine = WorkerRunEngine(
            model=MockDecisionModel([_fill(value="a"), _fill(value="b")]),
            settings=settings,
            max_tool_calls=1,
        )
        result = await engine.execute(goal="Fill", start_url=SIMPLE_URI)
        assert result.outcome is EngineOutcome.FAILED
        assert result.error is not None
        assert "budget exhausted" in result.error
        assert "tool calls" in result.error

    async def test_tool_call_count_persisted_to_checkpoint(self, settings):
        """Budget mutations reach run_state before the checkpoint, so the
        durable checkpoint carries the true consumed budget (H3d)."""
        from app.agent.persistence.in_memory_store import InMemoryCheckpointStore

        cp_store = InMemoryCheckpointStore()
        engine = WorkerRunEngine(
            model=MockDecisionModel([
                _fill(value="Asha Kumar"),
                _decision({"decision_type": "complete", "reason": "done"}),
            ]),
            settings=settings,
            checkpoint_store=cp_store,
        )
        result = await engine.execute(goal="Fill", start_url=SIMPLE_URI)
        assert result.outcome is EngineOutcome.COMPLETED

        cp = await cp_store.load_checkpoint(result.checkpoint_id)
        assert cp is not None
        assert cp.state.budget_state["tool_calls"] == 1
        assert cp.state.budget_state["iterations"] == 2


class TestCrossProcessResume:
    async def test_resume_from_async_only_store(self, settings):
        """H4: Worker A pauses; Worker B (fresh process, empty sync
        cache) resumes from the checkpoint that lives only in the async
        store — must restore and complete, not fail with 'not found'."""
        store_a = AsyncOnlyCheckpointStore()
        engine_a = WorkerRunEngine(
            model=MockDecisionModel([
                _fill(value="Asha Kumar"),
                _decision({
                    "decision_type": "ask_user",
                    "question": "Confirm office?",
                    "reason": "confirmation",
                }),
            ]),
            settings=settings,
            checkpoint_store=store_a,
        )
        paused = await engine_a.execute(goal="Fill", start_url=SIMPLE_URI)
        assert paused.outcome is EngineOutcome.PAUSED_HITL

        # Worker B: new process — same database, empty sync cache.
        store_b = store_a.fork_new_process()
        assert store_b.load(paused.checkpoint_id) is None  # cache-miss like Postgres

        engine_b = WorkerRunEngine(
            model=MockDecisionModel([
                _decision({"decision_type": "complete", "reason": "resumed done"}),
            ]),
            settings=settings,
            checkpoint_store=store_b,
        )
        result = await engine_b.execute(
            goal="Fill",
            start_url=SIMPLE_URI,
            agent_run_id=paused.agent_run_id,
            checkpoint_id=paused.checkpoint_id,
        )
        assert result.outcome is EngineOutcome.COMPLETED
        assert result.agent_run_id == paused.agent_run_id
        # Resumed run continued its iteration count (A used 2, B adds 1).
        assert result.iterations == 3

    async def test_unknown_checkpoint_still_fails_closed(self, settings):
        engine = WorkerRunEngine(
            model=MockDecisionModel([]),
            settings=settings,
            checkpoint_store=AsyncOnlyCheckpointStore(),
        )
        result = await engine.execute(
            goal="Fill",
            start_url=SIMPLE_URI,
            checkpoint_id="does-not-exist",
        )
        assert result.outcome is EngineOutcome.FAILED
        assert result.error is not None
        assert "not found" in result.error
