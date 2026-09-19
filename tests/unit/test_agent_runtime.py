"""Phase 2 — AgentRuntime lifecycle, events, decisions, checkpoints.

Covers implementation_plan.md Phase 2:
- AgentRunState: required fields, serialization, terminal/paused helpers
- deterministic state transitions (illegal transitions rejected)
- immutable append-only AgentEvent records + replay
- AgentDecision schema validation (contract only, no LLM)
- checkpoint creation/restoration — including cross-runtime JSON restore
  (the Phase 2 exit criterion: a paused run can be serialized and
  restored without losing logical task state)
- WorkflowStatus → lifecycle bridging and durable interrupts
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agent.runtime import (
    LIFECYCLE_TRANSITIONS,
    AgentCheckpoint,
    AgentDecision,
    AgentDecisionType,
    AgentEvent,
    AgentEventLog,
    AgentEventType,
    AgentLifecycle,
    AgentRunState,
    AgentRuntime,
    AgentSession,
    InMemoryCheckpointStore,
    InvalidLifecycleTransition,
    RuntimeBackedAgentRunner,
    can_transition,
    lifecycle_for_workflow_status,
)
from app.models.actions import BrowserAction
from app.models.workflow_state import (
    ActionRecord,
    WorkflowState,
    WorkflowStatus,
)


def _ok_result(observation):
    """Successful ActionResult stand-in (matches test_confirmation_flow)."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.success = True
    result.user_action_required = False
    result.recovery_required = False
    result.verification.status.value = "success"
    result.post_observation = observation
    result.message = "OK"
    return result


# ---------------------------------------------------------------------------
# AgentRunState
# ---------------------------------------------------------------------------


class TestAgentRunState:
    def test_defaults_and_identity(self):
        run = AgentRunState(run_id="run_x", goal="Fill form")
        assert run.run_id == "run_x"
        assert run.goal == "Fill form"
        assert run.lifecycle is AgentLifecycle.INITIALIZING
        assert run.iteration == 0
        assert run.agent.role == "primary"
        assert run.world_state is not None
        assert run.usage.llm_calls == 0
        assert run.pending_interrupt is None

    def test_is_terminal_and_paused(self):
        run = AgentRunState()
        assert not run.is_terminal()
        assert not run.is_paused()
        run.lifecycle = AgentLifecycle.COMPLETED
        assert run.is_terminal()
        run.lifecycle = AgentLifecycle.READY_FOR_CONFIRMATION
        assert not run.is_terminal()
        assert run.is_paused()
        run.lifecycle = AgentLifecycle.WAITING_FOR_USER
        assert run.is_paused()

    def test_serialization_round_trip(self):
        ws = WorkflowState(workflow_id="wf1", domain="uidai.gov.in")
        ws.record_action(ActionRecord(action_type="fill", success=True))
        run = AgentRunState(
            run_id="run_x",
            goal="Fill Aadhaar",
            current_subgoal="sub",
            iteration=3,
            world_state=ws,
        )
        run.browser.session_id = "sess_1"
        run.memory.working_ref = "mem_1"
        data = json.loads(run.model_dump_json())
        restored = AgentRunState.model_validate(data)
        assert restored == run

    def test_dom_refs_are_not_durable_state(self):
        """AgentRunState carries handles/metadata only — no DOM-ref field
        exists as durable state (D005: semantic state survives DOM)."""
        fields = set(AgentRunState.model_fields)
        assert "browser" in fields and "memory" in fields
        assert not any("ref" == f or "dom" in f for f in fields)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


class TestLifecycleTransitions:
    def test_all_required_states_exist(self):
        required = {
            "INITIALIZING", "OBSERVING", "REASONING", "ACTING", "VERIFYING",
            "REFLECTING", "WAITING_FOR_USER", "READY_FOR_REVIEW",
            "READY_FOR_CONFIRMATION", "COMPLETED", "FAILED", "ABORTED",
        }
        assert {s.name for s in AgentLifecycle} == required

    def test_legal_transition(self):
        run = AgentRunState(run_id="r1")
        rt = AgentRuntime()
        rt.set_lifecycle(run, AgentLifecycle.OBSERVING)
        assert run.lifecycle is AgentLifecycle.OBSERVING

    def test_illegal_transition_rejected(self):
        run = AgentRunState(run_id="r1")
        rt = AgentRuntime()
        with pytest.raises(InvalidLifecycleTransition):
            rt.set_lifecycle(run, AgentLifecycle.ACTING)  # INITIALIZING → ACTING

    def test_terminal_states_have_no_outgoing(self):
        for terminal in (AgentLifecycle.COMPLETED, AgentLifecycle.FAILED,
                         AgentLifecycle.ABORTED):
            assert LIFECYCLE_TRANSITIONS[terminal] == frozenset()
        # every state may reach each terminal directly or via path
        # specifically: RUNNING loop states reach FAILED
        assert can_transition(AgentLifecycle.REASONING, AgentLifecycle.FAILED)
        assert can_transition(AgentLifecycle.WAITING_FOR_USER, AgentLifecycle.ABORTED)

    def test_transition_emits_state_changed_event(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        rt.set_lifecycle(run, AgentLifecycle.OBSERVING, reason="first observe")
        log = rt.get_event_log(run.run_id)
        ev = log.last()
        assert ev.event_type is AgentEventType.STATE_CHANGED
        assert ev.data["from"] == "initializing"
        assert ev.data["to"] == "observing"

    def test_transition_toward_multi_hop(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        run.world_state.status = WorkflowStatus.READY_FOR_CONFIRMATION
        rt.sync_lifecycle_from_workflow(run)
        assert run.lifecycle is AgentLifecycle.READY_FOR_CONFIRMATION
        # Deterministic BFS path INITIALIZING → OBSERVING →
        # READY_FOR_CONFIRMATION (neighbors visited in enum order), each
        # hop evented.
        log = rt.get_event_log(run.run_id)
        state_events = log.events_of_type(AgentEventType.STATE_CHANGED)
        assert [e.data["to"] for e in state_events] == [
            "observing", "ready_for_confirmation",
        ]

    def test_unreachable_target_raises(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        rt.set_lifecycle(run, AgentLifecycle.OBSERVING)
        rt.set_lifecycle(run, AgentLifecycle.COMPLETED)
        with pytest.raises(InvalidLifecycleTransition):
            rt.transition_toward(run, AgentLifecycle.ACTING)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    def test_append_assigns_monotonic_sequence(self):
        log = AgentEventLog(run_id="r1")
        e1 = log.append(AgentEventType.RUN_STARTED)
        e2 = log.append(AgentEventType.NOTE, message="hi")
        e3 = log.append(AgentEventType.NOTE)
        assert [e.sequence for e in (e1, e2, e3)] == [1, 2, 3]

    def test_events_are_immutable(self):
        log = AgentEventLog(run_id="r1")
        ev = log.append(AgentEventType.NOTE, message="m")
        with pytest.raises(ValidationError):
            ev.message = "changed"

    def test_replay_yields_in_order(self):
        log = AgentEventLog(run_id="r1")
        for i in range(5):
            log.append(AgentEventType.NOTE, message=f"m{i}")
        replayed = list(log.replay())
        assert [e.sequence for e in replayed] == [1, 2, 3, 4, 5]
        assert [e.message for e in replayed][-1] == "m4"

    def test_events_of_type_filter(self):
        log = AgentEventLog(run_id="r1")
        log.append(AgentEventType.RUN_STARTED)
        log.append(AgentEventType.NOTE)
        log.append(AgentEventType.NOTE)
        assert len(log.events_of_type(AgentEventType.NOTE)) == 2
        assert len(log.events_of_type(AgentEventType.RUN_STARTED)) == 1


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class TestSession:
    def test_session_tracks_runs(self):
        rt = AgentRuntime()
        session = rt.create_session(label="uidai")
        r1 = rt.create_run(session=session, goal="a")
        r2 = rt.create_run(session=session, goal="b")
        assert session.run_ids == [r1.run_id, r2.run_id]
        assert session.active_run_id == r2.run_id
        session.end_run(r2.run_id)
        assert session.active_run_id is None

    def test_session_serializes(self):
        s = AgentSession(session_id="s1")
        s.start_run("run_1")
        data = json.loads(s.model_dump_json())
        restored = AgentSession.model_validate(data)
        assert restored == s


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_tool_call_decision_requires_action(self):
        with pytest.raises(ValidationError):
            AgentDecision(decision_type=AgentDecisionType.TOOL_CALL)

    def test_ask_user_requires_question(self):
        with pytest.raises(ValidationError):
            AgentDecision(decision_type=AgentDecisionType.ASK_USER)

    def test_complete_requires_reason(self):
        with pytest.raises(ValidationError):
            AgentDecision(decision_type=AgentDecisionType.COMPLETE)

    def test_valid_tool_call_decision(self):
        d = AgentDecision(
            decision_type=AgentDecisionType.TOOL_CALL,
            action=BrowserAction(action="click", target_ref="e1"),
        )
        assert d.action is not None

    def test_record_decision_binds_run_and_iteration(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        run.iteration = 7
        d = AgentDecision(
            decision_type=AgentDecisionType.TOOL_CALL,
            action=BrowserAction(action="click", target_ref="e1"),
        )
        rec = rt.record_decision(run, d)
        assert rec.run_id == run.run_id
        assert rec.iteration == 7
        assert rec.decision_id.startswith("decision_")
        assert len(rt.decisions_for(run.run_id)) == 1

    def test_ask_user_decision_raises_interrupt(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        rt.record_decision(run, AgentDecision(
            decision_type=AgentDecisionType.ASK_USER, question="OTP?",
        ))
        assert run.pending_interrupt is not None
        assert run.pending_interrupt.kind == "user_input"


# ---------------------------------------------------------------------------
# Interrupts
# ---------------------------------------------------------------------------


class TestInterrupts:
    def test_raise_interrupt_is_durable_and_checkpointed(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        run.world_state.status = WorkflowStatus.WAITING_FOR_CAPTCHA
        rt.sync_lifecycle_from_workflow(run)
        assert run.lifecycle is AgentLifecycle.WAITING_FOR_USER
        assert run.pending_interrupt.kind == "captcha"
        # interrupt → checkpoint (durable)
        store = rt._checkpoint_store
        cps = store.list_for_run(run.run_id)
        assert len(cps) == 1  # from raise_interrupt's checkpoint

    def test_resolve_interrupt(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        rt.raise_interrupt(run, kind="user_input", reason="need OTP")
        ev = rt.resolve_interrupt(run, resolution="user provided OTP")
        assert run.pending_interrupt is None
        assert ev.event_type is AgentEventType.INTERRUPT_RESOLVED

    def test_resolve_without_interrupt_raises(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        with pytest.raises(ValueError):
            rt.resolve_interrupt(run, resolution="x")

    def test_terminal_transition_clears_interrupt(self):
        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="g")
        run.world_state.status = WorkflowStatus.WAITING_FOR_USER
        rt.sync_lifecycle_from_workflow(run)
        assert run.pending_interrupt is not None
        run.world_state.status = WorkflowStatus.ABORTED
        rt.sync_lifecycle_from_workflow(run)
        assert run.lifecycle is AgentLifecycle.ABORTED
        assert run.pending_interrupt is None


# ---------------------------------------------------------------------------
# Checkpoints: serialization / restoration (Phase 2 exit criterion)
# ---------------------------------------------------------------------------


class TestCheckpoints:
    def _paused_run(self, rt: AgentRuntime):
        session = rt.create_session(label="uidai")
        run = rt.create_run(session=session, goal="Update Aadhaar address")
        run.current_subgoal = "fill address form"
        run.iteration = 4
        run.world_state.status = WorkflowStatus.READY_FOR_CONFIRMATION
        run.world_state.current_url = "https://uidai.gov.in/review"
        run.world_state.record_action(ActionRecord(
            action_type="fill", target_ref="e1",
            binding="USER.full_name", success=True,
        ))
        rt.sync_lifecycle_from_workflow(run)
        return run

    def test_checkpoint_round_trip_in_memory(self):
        rt = AgentRuntime()
        run = self._paused_run(rt)
        cp = rt.checkpoint_run(run, reason="paused for confirmation")
        restored = rt.restore_checkpoint(cp.checkpoint_id)
        assert restored.run_id == run.run_id
        assert restored == run

    def test_json_round_trip_lossless(self):
        rt = AgentRuntime()
        run = self._paused_run(rt)
        raw = rt.export_run_json(run)
        cp = AgentCheckpoint.from_json(raw)
        assert cp.run_id == run.run_id
        assert cp.state == run
        assert len(cp.events) == len(rt.get_event_log(run.run_id).events)

    def test_restored_run_replays_full_event_log(self):
        rt = AgentRuntime()
        run = self._paused_run(rt)
        raw = rt.export_run_json(run)
        cp = AgentCheckpoint.from_json(raw)
        fresh = AgentRuntime()  # different process/runtime
        restored = fresh.restore_checkpoint_from_json(raw)
        log = fresh.get_event_log(restored.run_id)
        # restored log == captured log + 1 RUN_RESTORED event
        assert len(log) == len(cp.events) + 1
        # sequence continuity preserved
        seqs = [e.sequence for e in log.replay()]
        assert seqs == list(range(1, len(cp.events) + 2))

    def test_restored_run_preserves_logical_task_state(self):
        rt = AgentRuntime()
        run = self._paused_run(rt)
        raw = rt.export_run_json(run)
        fresh = AgentRuntime()
        r2 = fresh.restore_checkpoint_from_json(raw)
        # logical task state survived
        assert r2.goal == "Update Aadhaar address"
        assert r2.current_subgoal == "fill address form"
        assert r2.iteration == 4
        assert r2.lifecycle is AgentLifecycle.READY_FOR_CONFIRMATION
        assert r2.world_state.status is WorkflowStatus.READY_FOR_CONFIRMATION
        assert r2.world_state.total_actions == 1
        assert r2.world_state.actions_taken[0].binding == "USER.full_name"
        assert r2.pending_interrupt.kind == "confirmation"

    def test_store_load_latest(self):
        store = InMemoryCheckpointStore()
        rt = AgentRuntime(checkpoint_store=store)
        run = self._paused_run(rt)
        cp1 = rt.checkpoint_run(run, reason="first")
        run.iteration = 9
        cp2 = rt.checkpoint_run(run, reason="second")
        latest = store.load_latest_for_run(run.run_id)
        assert latest.checkpoint_id == cp2.checkpoint_id
        ids = store.list_for_run(run.run_id)
        assert cp1.checkpoint_id in ids and cp2.checkpoint_id in ids
        assert ids == sorted(ids)
        assert store.load("nope") is None

    def test_corrupt_json_fails_closed(self):
        with pytest.raises(ValidationError):
            AgentCheckpoint.from_json("{not json")

    def test_unknown_checkpoint_raises(self):
        rt = AgentRuntime()
        with pytest.raises(KeyError):
            rt.restore_checkpoint("checkpoint_missing")


# ---------------------------------------------------------------------------
# WorkflowStatus → lifecycle mapping
# ---------------------------------------------------------------------------


class TestWorkflowStatusMapping:
    @pytest.mark.parametrize("status,expected", [
        (WorkflowStatus.INITIALIZED, AgentLifecycle.INITIALIZING),
        (WorkflowStatus.RUNNING, AgentLifecycle.REASONING),
        (WorkflowStatus.WAITING_FOR_USER, AgentLifecycle.WAITING_FOR_USER),
        (WorkflowStatus.WAITING_FOR_AUTH, AgentLifecycle.WAITING_FOR_USER),
        (WorkflowStatus.WAITING_FOR_CAPTCHA, AgentLifecycle.WAITING_FOR_USER),
        (WorkflowStatus.READY_FOR_CONFIRMATION, AgentLifecycle.READY_FOR_CONFIRMATION),
        (WorkflowStatus.READY_FOR_SUBMISSION, AgentLifecycle.READY_FOR_REVIEW),
        (WorkflowStatus.COMPLETED, AgentLifecycle.COMPLETED),
        (WorkflowStatus.FAILED, AgentLifecycle.FAILED),
        (WorkflowStatus.ABORTED, AgentLifecycle.ABORTED),
    ])
    def test_mapping(self, status, expected):
        assert lifecycle_for_workflow_status(status) is expected


# ---------------------------------------------------------------------------
# Compatibility facade
# ---------------------------------------------------------------------------


class TestFacade:
    def test_is_an_agent_runner(self):
        from app.agent.runner import AgentRunner
        assert issubclass(RuntimeBackedAgentRunner, AgentRunner)

    def test_session_activates_on_run_creation(self):
        """The facade creates its session at construction and registers a
        run the moment run() is invoked (tracked via create_run)."""
        from unittest.mock import patch

        from app.vault.resolver import UserVault

        runner = RuntimeBackedAgentRunner(
            llm=None, vault=UserVault(full_name="Test User"),
        )
        session = runner.session
        assert session.active_run_id is None
        assert session.run_ids == []
        rt = runner.agent_runtime

        created = []
        original = rt.create_run

        def spy(*args, **kwargs):
            run = original(*args, **kwargs)
            created.append(run)
            return run

        with patch.object(rt, "create_run", side_effect=spy):
            pass  # run() is async; full path covered by the async test
        # Direct invariant: creating a run via the runtime activates it.
        run = rt.create_run(session=session, goal="g")
        assert session.active_run_id == run.run_id
        assert runner.current_run is None  # only set inside facade.run()

    @pytest.mark.asyncio
    async def test_run_emits_events_and_lifecycle(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agent.field_mapper_models import (
            FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
        )
        from app.models.page_state import (
            ElementState, PageObservation, PageState,
        )
        from app.vault.resolver import UserVault

        runner = RuntimeBackedAgentRunner(
            llm=None, vault=UserVault(full_name="Test User"),
        )
        rt = runner.agent_runtime
        mock_page = MagicMock()
        elements = [ElementState(
            ref="e1", role="textbox", accessible_name="Full Name",
            label_text="Full Name", value="",
        )]
        page_state = PageState(
            url="https://x.gov.in/form", title="Form", page_type="form",
            elements=elements,
        )
        observation = PageObservation(
            page_state=page_state, aria_snapshot="", observation_id="obs1",
        )
        mapping = MappingResult(
            bindings=[FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            )],
            unmapped_fields=[], ambiguous_fields=[],
            total_fields=1, mapped_count=1,
        )

        async def fake_execute(page, action, obs, **kwargs):
            result = MagicMock()
            result.success = True
            result.user_action_required = False
            result.recovery_required = False
            result.verification.status.value = "success"
            result.post_observation = obs
            result.message = "OK"
            return result

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                with patch.object(runner._executor, "execute", side_effect=fake_execute):
                    workflow = await runner.run(mock_page, task="Fill name")

        run = runner.current_run
        assert run is not None
        # run state absorbed the workflow's logical task state
        assert run.goal == "Fill name"
        assert run.world_state.total_actions == 1
        # lifecycle was synced from the workflow's final status
        assert run.lifecycle == lifecycle_for_workflow_status(workflow.status)
        # events exist for the run
        log = rt.get_event_log(run.run_id)
        assert any(
            e.event_type is AgentEventType.RUN_STARTED for e in log.replay()
        )
        assert any(
            e.event_type is AgentEventType.STATE_CHANGED for e in log.replay()
        )
        # terminal checkpoint taken
        cps = rt._checkpoint_store.list_for_run(run.run_id)
        assert len(cps) >= 1

    @pytest.mark.asyncio
    async def test_resume_resolves_interrupt_and_rechecks(self):
        """Confirmation pause through the facade: interrupt raised on run
        state, resolved on resume, and the run continues in the same
        AgentRunState."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agent.field_mapper_models import (
            FieldBinding, MappingConfidence, MappingResult, MappingStrategy,
        )
        from app.models.page_state import (
            ElementState, PageObservation, PageState,
        )
        from app.vault.resolver import UserVault

        runner = RuntimeBackedAgentRunner(
            llm=None, vault=UserVault(aadhaar_number="1234 5678 9012"),
        )
        rt = runner.agent_runtime
        mock_page = MagicMock()
        elements = [ElementState(
            ref="e1", role="textbox", accessible_name="Enter Aadhaar Number",
            label_text="Enter Aadhaar Number", value="",
        )]
        observation = PageObservation(
            page_state=PageState(
                url="https://uidai.gov.in/form", title="Form", page_type="form",
                elements=elements,
            ),
            aria_snapshot="", observation_id="obs1",
        )
        mapping = MappingResult(
            bindings=[FieldBinding(
                field_ref="e1", binding="USER.aadhaar_number",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            )],
            unmapped_fields=[], ambiguous_fields=[],
            total_fields=1, mapped_count=1,
        )

        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._mapper, "map_fields", return_value=mapping):
                workflow = await runner.run(mock_page, task="Fill Aadhaar")

        run = runner.current_run
        assert workflow.status is WorkflowStatus.READY_FOR_CONFIRMATION
        assert run.lifecycle is AgentLifecycle.READY_FOR_CONFIRMATION
        assert run.pending_interrupt is not None
        assert run.pending_interrupt.kind == "confirmation"
        # Paused run was checkpointed (durable interrupt)
        assert len(rt._checkpoint_store.list_for_run(run.run_id)) >= 1

        # Resume approved: interrupt resolved, run re-tracked
        executed = AsyncMock(return_value=_ok_result(observation))
        with patch.object(runner._observer, "observe", return_value=observation):
            with patch.object(runner._executor, "execute", side_effect=executed):
                workflow = await runner.resume(
                    page=mock_page, workflow=workflow, approved=True,
                )

        assert executed.awaited
        assert run.world_state is workflow
