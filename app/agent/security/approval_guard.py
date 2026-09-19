"""HITL Approval Guard — Phase 11 Security Hardening.

Key Architectural Invariants:
1. USER_VERIFIED means explicit human authorization via verified HITL channel.
   Local vault credentials do NOT count as user approval!
2. Approval binds exact:
   - tool / action name
   - arguments hash (SHA-256)
   - target identity / semantic_id
   - world_state_version
   - run_id & session_id
   - origin URL & domain
   - policy_decision (e.g. REQUIRE_CONFIRMATION)
3. Any material change (origin change, target change, arguments change, state change)
   immediately invalidates the approval fail-closed.
4. DOM claims (e.g. <div data-approved="true">), specialist advice, or model claims
   can NEVER satisfy or forge an approval.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Any

from app.agent.interrupts.models import ApprovalBinding
from app.agent.security.models import (
    SecurityViolation,
    SecurityViolationCode,
    TrustDomain,
    compute_arguments_hash,
)

logger = logging.getLogger(__name__)


class ApprovalIntegrityGuard:
    """Deterministic validation gate for human approvals."""

    @staticmethod
    def validate_approval_for_execution(
        approval: ApprovalBinding | None,
        *,
        current_run_id: str,
        current_session_id: str | None = None,
        current_action: str,
        current_tool_name: str | None = None,
        current_arguments: dict[str, Any] | None = None,
        current_target_identity: str,
        current_semantic_id: str | None = None,
        current_world_state_version: int,
        current_origin_url: str | None = None,
        current_policy_decision: str = "require_confirmation",
    ) -> None:
        """Verify that an active approval strictly authorizes the current execution context.
        
        Raises SecurityViolation if invalid, mismatched, or forged.
        """
        if approval is None:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                "Action requires explicit human confirmation but no approval was provided",
                {"action": current_action, "target": current_target_identity},
            )

        # 1. Origin Authority Check: approval must come from explicit human interaction
        # Local vault credentials or DOM spoofing cannot grant approvals!
        approved_by = getattr(approval, "approved_by", "")
        if approved_by not in ("user", TrustDomain.USER_VERIFIED.value):
            raise SecurityViolation(
                SecurityViolationCode.UNTRUSTED_APPROVAL_SPOOF,
                f"Approval granted by untrusted entity '{approved_by}'. "
                f"Approvals must originate from explicit human interaction.",
                {"approved_by": approved_by},
            )

        # 2. Run / Session Binding
        if approval.run_id != current_run_id:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval run_id mismatch: approved for '{approval.run_id}', current is '{current_run_id}'",
                {"approval_run_id": approval.run_id, "current_run_id": current_run_id},
            )

        session_id = getattr(approval, "session_id", None)
        if session_id and current_session_id and session_id != current_session_id:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval session_id mismatch: approved for '{session_id}', current is '{current_session_id}'",
                {"approval_session_id": session_id, "current_session_id": current_session_id},
            )

        # 3. Action and Tool Name Binding
        if approval.requested_action != current_action:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval action mismatch: approved for '{approval.requested_action}', requested '{current_action}'",
                {"approval_action": approval.requested_action, "current_action": current_action},
            )

        bound_tool = getattr(approval, "tool_name", None)
        if bound_tool and current_tool_name and bound_tool != current_tool_name:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval tool mismatch: approved for tool '{bound_tool}', requested '{current_tool_name}'",
                {"approval_tool": bound_tool, "current_tool": current_tool_name},
            )

        # 4. Target Binding
        if approval.target_identity != current_target_identity:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval target mismatch: approved for '{approval.target_identity}', current is '{current_target_identity}'",
                {"approval_target": approval.target_identity, "current_target": current_target_identity},
            )

        if approval.semantic_id and current_semantic_id and approval.semantic_id != current_semantic_id:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval semantic_id mismatch: approved for '{approval.semantic_id}', current is '{current_semantic_id}'",
                {"approval_semantic_id": approval.semantic_id, "current_semantic_id": current_semantic_id},
            )

        # 5. WorldState Version Binding
        if approval.world_state_version != current_world_state_version:
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval state version invalid: approved for state v{approval.world_state_version}, "
                f"current state is v{current_world_state_version}",
                {
                    "approval_state_version": approval.world_state_version,
                    "current_state_version": current_world_state_version,
                },
            )

        # 6. Origin / Domain Context Binding
        bound_origin = getattr(approval, "origin_url", None)
        if bound_origin and current_origin_url:
            bound_host = urlparse(bound_origin).netloc.lower()
            current_host = urlparse(current_origin_url).netloc.lower()
            if bound_host != current_host:
                raise SecurityViolation(
                    SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                    f"Approval origin domain mismatch: approved on '{bound_host}', current origin is '{current_host}'",
                    {"bound_origin": bound_origin, "current_origin": current_origin_url},
                )

        # 7. Exact Arguments Hash Binding
        bound_args_hash = getattr(approval, "arguments_hash", None)
        if bound_args_hash and current_arguments is not None:
            computed_hash = compute_arguments_hash(current_arguments)
            if bound_args_hash != computed_hash:
                raise SecurityViolation(
                    SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                    "Approval arguments tampered: tool arguments do not match approved hash",
                    {"bound_args_hash": bound_args_hash, "current_args_hash": computed_hash},
                )

        # 8. Expiration Check
        if approval.is_expired():
            raise SecurityViolation(
                SecurityViolationCode.APPROVAL_BINDING_MISMATCH,
                f"Approval expired at {approval.expires_at}",
                {"expires_at": approval.expires_at},
            )
