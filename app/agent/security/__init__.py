"""Security Hardening subsystem — Phase 11.

Public Exports:
- Models: TrustDomain, SensitivityLevel, RuntimeProvenance, SecurityViolationCode, SecurityViolation
- Budget: RuntimeBudget, RuntimeBudgetTracker
- Envelopes: wrap_web_content, wrap_specialist_advice, wrap_document_data, escape_envelope_delimiters
- Approval Guard: ApprovalIntegrityGuard
- Policy Guard: PolicyIntegrityGuard, is_trusted_domain, validate_navigation_destination
"""

from app.agent.security.models import (
    RuntimeProvenance,
    SecurityViolation,
    SecurityViolationCode,
    SensitivityLevel,
    TrustDomain,
    compute_arguments_hash,
)
from app.agent.security.budget import RuntimeBudget, RuntimeBudgetTracker
from app.agent.security.envelope import (
    escape_envelope_delimiters,
    wrap_document_data,
    wrap_specialist_advice,
    wrap_web_content,
)
from app.agent.security.approval_guard import ApprovalIntegrityGuard
from app.agent.security.policy_guard import (
    PolicyIntegrityGuard,
    is_trusted_domain,
    validate_navigation_destination,
)

__all__ = [
    "TrustDomain",
    "SensitivityLevel",
    "RuntimeProvenance",
    "SecurityViolationCode",
    "SecurityViolation",
    "compute_arguments_hash",
    "RuntimeBudget",
    "RuntimeBudgetTracker",
    "escape_envelope_delimiters",
    "wrap_web_content",
    "wrap_specialist_advice",
    "wrap_document_data",
    "ApprovalIntegrityGuard",
    "PolicyIntegrityGuard",
    "is_trusted_domain",
    "validate_navigation_destination",
]
