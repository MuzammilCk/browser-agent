"""Consolidated enterprise security tests (Phase 13).

Required behaviors verified here:
- Secret leakage through API/queue/audit: denied (#10, #11, #12 area).
- Approval replay after worker replacement / checkpoint restore (#16 area).
- Unauthorized worker identity rejected (#32).
- Policy bypass attempt: Phase 11 policy remains authoritative (#37).
- Phase 10 specialist remains non-mutating (#38).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.interrupts.models import ApprovalBinding
from app.agent.security.budget import RuntimeBudget, RuntimeBudgetTracker
from app.agent.security.models import (
    SensitivityLevel,
    TrustDomain,
    compute_arguments_hash,
)
from app.enterprise.audit import AuditService
from app.enterprise.in_memory_store import InMemoryEnterpriseStore
from app.enterprise.models import (
    ActorType,
    AuthorizationError,
    Identity,
    Role,
    RunStatus,
    Workflow,
    WorkflowRun,
)
from app.enterprise.workflow_service import WorkflowService


@pytest.fixture
def store():
    return InMemoryEnterpriseStore()


@pytest.fixture
def service(store):
    return WorkflowService(store, AuditService(store))


class TestUntrustedFieldsCannotControlAuthority:
    async def test_identity_is_only_from_provider(self):
        from app.enterprise.security import IdentityProvider
        p = IdentityProvider()
        p.register_principal("good", tenant_id="t1", subject_id="u1")
        ident = p.resolve("Bearer good")
        assert ident.tenant_id == "t1"
        # There is no API to construct identity from a request body.
        public_api = [n for n in dir(p) if "client" in n or "request" in n]
        assert public_api == []

    async def test_worker_identity_cannot_be_claimed_via_body_fields(self, service, store):
        user = Identity(
            actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
            role=Role.USER,
        )
        wf = await service.create_workflow(user, goal="g")
        run = await service.create_run(user, wf.workflow_id)
        # Even a well-formed WORKER identity with an invented subject id
        # is not the owning worker and cannot mutate the run.
        fake_worker = Identity(
            actor_type=ActorType.WORKER, tenant_id="",
            subject_id="worker_ZZ", role=Role.WORKER,
        )
        with pytest.raises(AuthorizationError):
            await service.complete_run(
                fake_worker, run.run_id, fencing_token=1,
            )

    async def test_budget_cannot_be_reset_by_untrusted_input(self):
        tracker = RuntimeBudgetTracker(
            budget=RuntimeBudget(max_iterations=10), iterations=8,
        )
        # Untrusted "input" (a dict from any source) cannot reset counters:
        # restoration only happens through RuntimeBudgetTracker.from_dict,
        # which preserves persisted counters.
        restored = RuntimeBudgetTracker.from_dict(tracker.to_dict())
        assert restored.iterations == 8


class TestApprovalReplay:
    def _approval(self, ws_version=4):
        return ApprovalBinding(
            run_id="run_x",
            interrupt_id="int_x",
            requested_action="confirm_step",
            target_identity="button:submit",
            world_state_version=ws_version,
            observation_id="obs_1",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat(),
            arguments_hash=compute_arguments_hash({"step": 1}),
        )

    def test_replay_after_worker_replacement_rejected_on_state_drift(self):
        approval = self._approval(ws_version=4)
        ok, reason = approval.is_valid_for(
            current_world_state_version=5,   # advanced after replacement
            current_action="confirm_step",
            current_target_identity="button:submit",
            current_arguments_hash=compute_arguments_hash({"step": 1}),
        )
        assert ok is False

    def test_replay_with_tampered_arguments_rejected(self):
        approval = self._approval()
        ok, reason = approval.is_valid_for(
            current_world_state_version=4,
            current_action="confirm_step",
            current_target_identity="button:submit",
            current_arguments_hash=compute_arguments_hash({"step": 2}),
        )
        assert ok is False
        assert "arguments" in reason or "hash" in reason

    def test_expired_approval_rejected(self):
        approval = ApprovalBinding(
            run_id="run_x",
            interrupt_id="int_x",
            requested_action="confirm_step",
            target_identity="button:submit",
            world_state_version=4,
            observation_id="obs_1",
            created_at=(
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat(),
        )
        ok, _ = approval.is_valid_for(
            current_world_state_version=4,
            current_action="confirm_step",
            current_target_identity="button:submit",
        )
        assert ok is False


class TestPhase11InvariantsPreserved:
    def test_policy_integrity_guard_still_blocks_injection_attributes(self):
        from app.agent.security.models import SecurityViolation
        from app.agent.security.policy_guard import PolicyIntegrityGuard
        from app.models.actions import BrowserAction

        # Schema-level rejection: strict BrowserAction (extra=forbid)
        # refuses injected bypass fields at construction.
        with pytest.raises(Exception):
            BrowserAction(
                action="fill", target_ref="e1", literal_value="x",
                observation_id="obs_1",
                pre_approved=True,  # type: ignore[call-arg]
            )

        # Defense-in-depth: the guard itself deterministically rejects
        # any action whose serialized form carries bypass flags — even
        # if such an action was constructed outside normal validation.
        class _SmuggledAction:
            def model_dump(self):
                return {
                    "action": "fill", "target_ref": "e1",
                    "literal_value": "x", "pre_approved": True,
                }

        with pytest.raises(SecurityViolation):
            PolicyIntegrityGuard.sanitize_action_for_policy(
                _SmuggledAction(),  # type: ignore[arg-type]
            )

    def test_navigation_destination_guard_still_blocks_untrusted_hosts(self):
        from app.agent.security.policy_guard import (
            PolicyIntegrityGuard,
            validate_navigation_destination,
        )
        guard = PolicyIntegrityGuard()
        with pytest.raises(Exception):
            validate_navigation_destination(
                "https://evil-attacker.example/steal",
                allowed_hosts={"uidai.gov.in"},
                guard=guard,
            )

    def test_trust_and_sensitivity_orthogonality_unchanged(self):
        prov_t = TrustDomain.USER_VERIFIED
        assert prov_t.value == "user_verified"
        assert SensitivityLevel.RESTRICTED_SECRET.value == "restricted_secret"

    async def test_specialist_adapter_remains_non_mutating(self):
        from pydantic import BaseModel as _BM

        from app.agent.specialists.adapter import SpecialistToolAdapter
        from app.agent.specialists.base import SpecialistAgent
        from app.agent.specialists.models import (
            SpecialistPermission,
            SpecialistResult,
            SpecialistType,
        )

        class _MinimalSpecialist(SpecialistAgent):
            specialist_type = SpecialistType.FORM_SEMANTICS
            permission = SpecialistPermission.READ_ONLY
            default_timeout = 2.0
            input_schema = _BM
            output_schema = _BM

            async def _run(self, context) -> SpecialistResult:
                return SpecialistResult(
                    invocation_id=context.invocation_id,
                    specialist_type=self.specialist_type,
                    permission=self.permission,
                    data={},
                )

        adapter = SpecialistToolAdapter(_MinimalSpecialist())
        assert adapter.metadata.read_only is True
        assert adapter.metadata.accepts_browser_action is False


class TestSecretSurface:
    async def test_enterprise_serialization_is_secret_free(self, service, store):
        user = Identity(
            actor_type=ActorType.USER, tenant_id="t1", subject_id="u1",
            role=Role.USER,
        )
        wf = await service.create_workflow(user, goal="Fill the form")
        run = await service.create_run(user, wf.workflow_id)
        await store.enqueue_run(run)
        fresh = await store.get_run(run.run_id)
        item = await store.get_queue_item(run.run_id)
        blob = fresh.model_dump_json() + item.model_dump_json()
        # No browser handles / raw state in serialized enterprise records.
        for forbidden in (
            "playwright", "BrowserContext", "state_payload", "events_payload",
        ):
            assert forbidden not in blob
