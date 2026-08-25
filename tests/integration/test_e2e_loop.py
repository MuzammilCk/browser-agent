"""End-to-end test — proves the full agent loop works.

Audit issue #43: Synthetic government form test.
Audit issue #44: Contract tests.

Tests the complete pipeline:
    BrowserManager → PageObserver → FieldMapper → LLM → BrowserAction
    → PolicyEngine → BrowserExecutor → ActionVerifier → WorkflowState

All LLM calls are mocked for deterministic CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.field_mapper import FieldMapper
from app.agent.field_mapper_models import (
    FieldBinding,
    MappingConfidence,
    MappingResult,
    MappingStrategy,
)
from app.agent.registry import ReferenceRegistry, get_registry
from app.agent.runner import AgentRunner
from app.browser.executor import ActionResult
from app.browser.observer import PageObservation, PageObserver
from app.models.actions import BrowserAction
from app.models.page_state import (
    ElementState,
    PageObservation as PageObs,
    PageState,
)
from app.models.workflow_state import WorkflowState, WorkflowStatus
from app.policy.engine import PolicyEngine
from app.vault.resolver import UserVault


# ============================================================
# Helpers
# ============================================================

SYNTHETIC_FORM_PATH = (
    Path(__file__).parent.parent / "synthetic_forms" / "pages" / "government_form.html"
)


def _make_element(ref: str, **kwargs) -> ElementState:
    defaults = {
        "ref": ref,
        "role": "textbox",
        "accessible_name": "",
    }
    defaults.update(kwargs)
    return ElementState(**defaults)


def _make_observation(
    elements: list[ElementState],
    *,
    url: str = "https://scholarships.gov.in/apply",
    page_type: str = "form",
    obs_id: str = "obs_001",
    auth_detected: bool = False,
    auth_type: str | None = None,
) -> PageObs:
    from app.models.page_state import AuthenticationState
    auth = AuthenticationState(
        detected=auth_detected,
        challenge_type=auth_type,
        confidence=0.95 if auth_detected else 0.0,
    )
    page_state = PageState(
        url=url,
        title="Post-Matric Scholarship Application",
        page_type=page_type,
        elements=elements,
        authentication=auth,
    )
    return PageObs(
        page_state=page_state,
        aria_snapshot="",
        observation_id=obs_id,
    )


def _all_form_elements() -> list[ElementState]:
    """All elements from the synthetic government form."""
    return [
        _make_element("e1", accessible_name="Applicant Full Name as per Aadhaar", role="textbox", input_type="text"),
        _make_element("e2", accessible_name="Date of Birth as per Aadhaar", role="textbox", input_type="date"),
        _make_element("e3", accessible_name="Father's Full Name", role="textbox", input_type="text"),
        _make_element("e4", accessible_name="Mother's Full Name", role="textbox", input_type="text"),
        _make_element("e5", accessible_name="Spouse Name (if married)", role="textbox", input_type="text"),
        _make_element("e6", accessible_name="Gender Selection", role="radiogroup"),
        _make_element("e7", accessible_name="Social Category", role="combobox"),
        _make_element("e8", accessible_name="Marital Status", role="combobox"),
        _make_element("e9", accessible_name="10-digit Mobile Number", role="textbox", input_type="tel"),
        _make_element("e10", accessible_name="Email Address", role="textbox", input_type="email"),
        _make_element("e11", accessible_name="State of Residence", role="combobox"),
        _make_element("e12", accessible_name="District", role="combobox"),
        _make_element("e13", accessible_name="Village or Town Name", role="textbox", input_type="text"),
        _make_element("e14", accessible_name="6-digit Pincode", role="textbox", input_type="text"),
        _make_element("e15", accessible_name="Complete Postal Address", role="textbox"),
        _make_element("e16", accessible_name="Highest Educational Qualification", role="combobox"),
        _make_element("e17", accessible_name="Occupation Type", role="combobox"),
        _make_element("e18", accessible_name="Annual Family Income in Rupees", role="textbox", input_type="text"),
        _make_element("e19", accessible_name="12-digit Aadhaar Number", role="textbox", input_type="text"),
        _make_element("e20", accessible_name="PAN Card Number", role="textbox", input_type="text"),
        _make_element("e21", accessible_name="Bank Account Number", role="textbox", input_type="text"),
        _make_element("e22", accessible_name="Bank IFSC Code", role="textbox", input_type="text"),
        _make_element("e23", accessible_name="Upload Aadhaar Card PDF or Image", role="file", input_type="file"),
        _make_element("e24", accessible_name="Upload Income Certificate PDF", role="file", input_type="file"),
        _make_element("e25", accessible_name="Upload Passport Size Photo", role="file", input_type="file"),
        _make_element("e26", accessible_name="Upload Signature Image", role="file", input_type="file"),
        _make_element("e27", accessible_name="I hereby declare", role="checkbox"),
        _make_element("e28", accessible_name="I agree to the Terms", role="checkbox"),
        _make_element("e29", accessible_name="Submit Application →", role="button"),
        _make_element("e30", accessible_name="Save Draft", role="button"),
        _make_element("e31", accessible_name="← Back", role="button"),
    ]


# ============================================================
# E2E Test 1: Field Mapper Against Full Form
# ============================================================


class TestFieldMapperE2E:
    """Test field mapper against the comprehensive government form."""

    @pytest.mark.asyncio
    async def test_maps_all_text_fields(self):
        """Every text field should map to a USER.* reference."""
        mapper = FieldMapper()
        elements = _all_form_elements()
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)

        # Should map most fields
        assert result.mapped_count >= 20
        assert result.total_fields == 31

        # Check specific mappings
        bindings_by_ref = {b.field_ref: b for b in result.bindings}

        # Personal fields
        assert bindings_by_ref["e1"].binding == "USER.full_name"
        assert bindings_by_ref["e2"].binding == "USER.date_of_birth"
        assert bindings_by_ref["e3"].binding == "USER.father_name"
        assert bindings_by_ref["e4"].binding == "USER.mother_name"
        assert bindings_by_ref["e5"].binding == "USER.spouse_name"

        # Contact fields
        assert bindings_by_ref["e9"].binding == "USER.mobile"
        assert bindings_by_ref["e10"].binding == "USER.email"

        # Address fields
        assert bindings_by_ref["e11"].binding == "USER.state"
        assert bindings_by_ref["e12"].binding == "USER.district"
        assert bindings_by_ref["e13"].binding == "USER.village"
        assert bindings_by_ref["e14"].binding == "USER.pincode"
        assert bindings_by_ref["e15"].binding == "USER.address"

        # Financial fields
        assert bindings_by_ref["e18"].binding == "USER.annual_income"
        assert bindings_by_ref["e19"].binding == "USER.aadhaar_number"
        assert bindings_by_ref["e20"].binding == "USER.pan_number"
        assert bindings_by_ref["e22"].binding == "USER.ifsc_code"

    @pytest.mark.asyncio
    async def test_maps_document_uploads(self):
        """Document upload fields should map to DOCUMENT.* references."""
        mapper = FieldMapper()
        elements = _all_form_elements()
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)
        bindings_by_ref = {b.field_ref: b for b in result.bindings}

        assert bindings_by_ref["e23"].binding == "DOCUMENT.aadhaar"
        assert bindings_by_ref["e24"].binding == "DOCUMENT.income_certificate"
        assert bindings_by_ref["e25"].binding == "DOCUMENT.photo"
        assert bindings_by_ref["e26"].binding == "DOCUMENT.signature"

    @pytest.mark.asyncio
    async def test_all_bindings_valid(self):
        """Every binding must be valid in the ReferenceRegistry."""
        mapper = FieldMapper()
        elements = _all_form_elements()
        observation = _make_observation(elements)

        result = await mapper.map_fields(observation)
        registry = get_registry()

        for binding in result.bindings:
            if binding.binding:
                assert registry.validate(binding.binding), (
                    f"Binding '{binding.binding}' for ref '{binding.field_ref}' "
                    f"not found in ReferenceRegistry"
                )

    @pytest.mark.asyncio
    async def test_bindings_have_observation_id(self):
        """All bindings must have observation_id."""
        mapper = FieldMapper()
        elements = _all_form_elements()
        observation = _make_observation(elements, obs_id="obs_e2e")

        result = await mapper.map_fields(observation)

        for binding in result.bindings:
            assert binding.observation_id == "obs_e2e"


# ============================================================
# E2E Test 2: Full Agent Loop with Mocked LLM
# ============================================================


class TestAgentLoopE2E:
    """Test the full agent loop with mocked LLM and page."""

    @pytest.mark.asyncio
    async def test_full_loop_fills_form(self):
        """Prove the full loop: observe → map → plan → execute → verify."""
        mock_llm = MagicMock()
        mock_page = MagicMock()

        # LLM returns a sequence of actions
        llm_responses = [
            {"action": "fill", "target_ref": "e1", "value_ref": "USER.full_name", "confidence": 0.95},
            {"action": "fill", "target_ref": "e3", "value_ref": "USER.father_name", "confidence": 0.95},
            {"action": "fill", "target_ref": "e10", "literal_value": "test@example.com", "confidence": 0.9},
            {"action": "select", "target_ref": "e11", "option": "Kerala", "confidence": 0.95},
            {"action": "click", "target_ref": "e29", "confidence": 0.8},
        ]

        call_idx = 0

        async def mock_complete(**kwargs):
            nonlocal call_idx
            resp = MagicMock()
            if call_idx < len(llm_responses):
                resp.parsed = llm_responses[call_idx]
                call_idx += 1
            else:
                resp.parsed = {"action": "stop"}
            resp.usage = MagicMock(total_tokens=100)
            return resp

        mock_llm.complete = AsyncMock(side_effect=mock_complete)

        # Mock observer to return form elements
        elements = _all_form_elements()
        observation = _make_observation(elements)

        async def mock_execute(page, action, obs):
            result = MagicMock()
            result.success = True
            result.user_action_required = False
            result.recovery_required = False
            result.verification = MagicMock()
            result.verification.status.value = "success"
            result.post_observation = obs
            result.message = "OK"
            return result

        with patch.object(PageObserver, "observe", return_value=observation):
            runner = AgentRunner(llm=mock_llm, max_iterations=10)
            with patch.object(runner._executor, "execute", side_effect=mock_execute):
                workflow = await runner.run(
                    mock_page,
                    task="Fill the scholarship application form",
                    domain="scholarships.gov.in",
                )

        # Verify workflow completed
        assert workflow.workflow_id != ""
        assert workflow.domain == "scholarships.gov.in"
        assert workflow.task_description == "Fill the scholarship application form"

        # Verify actions were taken
        assert workflow.total_actions >= 2
        assert workflow.successful_actions >= 2

        # Verify specific action types were executed
        action_types = [a.action_type for a in workflow.actions_taken]
        assert "fill" in action_types or "select" in action_types

    @pytest.mark.asyncio
    async def test_loop_handles_captcha(self):
        """Prove the loop stops at CAPTCHA."""
        mock_page = MagicMock()

        # CAPTCHA page observed immediately
        captcha_elements = [
            _make_element("e1", accessible_name="Enter CAPTCHA code", role="textbox"),
        ]
        captcha_obs = _make_observation(
            captcha_elements,
            url="https://scholarships.gov.in/captcha",
            page_type="captcha",
            obs_id="obs_captcha",
            auth_detected=True,
            auth_type="captcha",
        )

        with patch.object(PageObserver, "observe", return_value=captcha_obs):
            runner = AgentRunner(llm=None, max_iterations=10)
            workflow = await runner.run(
                mock_page,
                task="Fill form with CAPTCHA",
                domain="scholarships.gov.in",
            )

        # Should stop at CAPTCHA (detected by runner, not executor).
        # Audit C10: CAPTCHA now gets its own precise status.
        assert workflow.status == WorkflowStatus.WAITING_FOR_CAPTCHA
        assert "captcha" in workflow.checkpoints

    @pytest.mark.asyncio
    async def test_loop_records_all_actions(self):
        """Prove every action is recorded in WorkflowState."""
        mock_page = MagicMock()

        elements = [
            _make_element("e1", accessible_name="Full Name", role="textbox"),
            _make_element("e2", accessible_name="Submit", role="button"),
        ]
        observation = _make_observation(elements)

        bindings = [
            FieldBinding(
                field_ref="e1", binding="USER.full_name",
                confidence=MappingConfidence.HIGH,
                strategy=MappingStrategy.DETERMINISTIC,
                field_type="textbox",
            ),
        ]
        mapping_result = MappingResult(
            bindings=bindings,
            unmapped_fields=[],
            total_fields=2,
            mapped_count=1,
        )

        with patch.object(PageObserver, "observe", return_value=observation):
            with patch("app.agent.runner.FieldMapper.map_fields", return_value=mapping_result):
                async def mock_execute(page, action, obs):
                    result = MagicMock()
                    result.success = True
                    result.user_action_required = False
                    result.recovery_required = False
                    result.verification = MagicMock()
                    result.verification.status.value = "success"
                    result.post_observation = obs
                    result.message = "OK"
                    return result

                runner = AgentRunner(
                    llm=None, max_iterations=5,
                    vault=UserVault(full_name="Test User"),
                )
                with patch.object(runner._executor, "execute", side_effect=mock_execute):
                    workflow = await runner.run(mock_page, task="Test recording")

        # Every action should be recorded
        assert workflow.total_actions >= 1
        for record in workflow.actions_taken:
            assert record.action_type != ""
            assert record.observation_id != ""


# ============================================================
# E2E Test 3: Contract Tests
# ============================================================


class TestContractTests:
    """Contract tests per audit #44."""

    def test_all_field_mapper_refs_in_registry(self):
        """Every FieldMapper deterministic rule must be in ReferenceRegistry."""
        from app.agent.field_mapper import DETERMINISTIC_RULES
        registry = get_registry()
        for binding_key in DETERMINISTIC_RULES:
            assert registry.validate(binding_key), (
                f"FieldMapper rule '{binding_key}' not in ReferenceRegistry"
            )

    def test_all_registry_refs_resolve(self):
        """Every USER.* reference must resolve through ValueResolver."""
        from app.vault.resolver import UserVault, ValueResolver
        vault = UserVault(
            full_name="Test User",
            father_name="Father",
            mother_name="Mother",
            spouse_name="Spouse",
            guardian_name="Guardian",
            date_of_birth="01/01/2000",
            gender="Male",
            mobile="9876543210",
            email="test@example.com",
            address="Test Address",
            permanent_address="Permanent Address",
            state="Kerala",
            district="Thiruvananthapuram",
            village="Test Village",
            pincode="695001",
            aadhaar_number="123456789012",
            aadhaar_name="Test User",
            pan_number="ABCDE1234F",
            voter_id="VOT1234567",
            education="Graduate",
            degree="B.Sc",
            institution="Test College",
            occupation="Student",
            employer="",
            annual_income="200000",
            bank_name="SBI",
            account_number="1234567890",
            ifsc_code="SBIN0001234",
            category="General",
            religion="Hindu",
            marital_status="Single",
            age="25",
            block="Test Block",
        )
        registry = get_registry()
        resolver = ValueResolver(vault, registry)

        for key in registry.list_keys():
            if key.startswith("USER."):
                # Should be able to check validity
                assert resolver.is_valid_ref(key), f"ValueResolver cannot validate '{key}'"

    def test_action_schema_valid(self):
        """All valid action types must satisfy schema."""
        # Valid actions
        valid_actions = [
            {"action": "fill", "target_ref": "e1", "literal_value": "test"},
            {"action": "click", "target_ref": "e1"},
            {"action": "select", "target_ref": "e1", "option": "Kerala"},
            {"action": "check", "target_ref": "e1"},
            {"action": "uncheck", "target_ref": "e1"},
            {"action": "scroll", "direction": "down"},
            {"action": "scroll_to", "target_ref": "e1"},
            {"action": "press", "key": "Enter"},
            {"action": "wait"},
            {"action": "go_back"},
            {"action": "stop"},
            {"action": "request_user_action", "reason": "Need OTP"},
        ]
        for action_data in valid_actions:
            action = BrowserAction(**action_data)
            assert action.action != ""

    def test_invalid_actions_rejected(self):
        """Invalid action combinations must be rejected."""
        invalid_actions = [
            # fill without value
            {"action": "fill", "target_ref": "e1"},
            # select without option
            {"action": "select", "target_ref": "e1"},
            # click without target
            {"action": "click"},
            # upload without document_ref
            {"action": "upload", "target_ref": "e1"},
            # press without key
            {"action": "press"},
            # request_user_action without reason
            {"action": "request_user_action"},
        ]
        for action_data in invalid_actions:
            with pytest.raises(Exception):
                BrowserAction(**action_data)

    def test_sensitive_literal_value_rejected(self):
        """Sensitive patterns in literal_value must be rejected."""
        # Aadhaar pattern
        with pytest.raises(Exception):
            BrowserAction(action="fill", target_ref="e1", literal_value="1234 5678 9012")

        # PAN pattern
        with pytest.raises(Exception):
            BrowserAction(action="fill", target_ref="e1", literal_value="ABCDE1234F")

    def test_policy_classifies_all_actions(self):
        """Every action type must be classified by PolicyEngine."""
        engine = PolicyEngine()
        actions = [
            BrowserAction(action="fill", target_ref="e1", literal_value="test"),
            BrowserAction(action="click", target_ref="e1"),
            BrowserAction(action="select", target_ref="e1", option="test"),
            BrowserAction(action="check", target_ref="e1"),
            BrowserAction(action="uncheck", target_ref="e1"),
            BrowserAction(action="scroll", direction="down"),
            BrowserAction(action="scroll_to", target_ref="e1"),
            BrowserAction(action="press", key="Enter"),
            BrowserAction(action="wait"),
            BrowserAction(action="go_back"),
            BrowserAction(action="stop"),
            BrowserAction(action="upload", target_ref="e1", document_ref="DOCUMENT.aadhaar"),
        ]
        for action in actions:
            result = engine.evaluate(action)
            assert result.decision is not None
            assert result.risk_level is not None

    def test_authentication_blocks_all_actions(self):
        """When CAPTCHA detected, ALL actions must be blocked."""
        engine = PolicyEngine()
        page_state = PageState(
            authentication={"detected": True, "challenge_type": "captcha", "confidence": 0.95},
        )
        actions = [
            BrowserAction(action="fill", target_ref="e1", literal_value="test"),
            BrowserAction(action="click", target_ref="e1"),
            BrowserAction(action="select", target_ref="e1", option="test"),
        ]
        for action in actions:
            result = engine.evaluate(action, page_state)
            assert result.needs_user, f"Action {action.action} not blocked during CAPTCHA"
