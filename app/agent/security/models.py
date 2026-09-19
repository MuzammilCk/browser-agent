"""Core security models — Phase 11 Security Hardening.

Key Architectural Invariants:
1. Orthogonal Trust & Sensitivity:
   - TrustDomain: Who generated the data and has runtime verified it.
   - SensitivityLevel: How confidential/restricted is the data.
   - Local vault credentials do NOT count as user approval.
2. Provenance is Runtime-Owned:
   - Untrusted content cannot forge or escalate TrustDomain, verified=True,
     or verifier. RuntimeProvenance is immutable and runtime-issued.
3. Explicit Verifier for STATE_VERIFIED:
   - STATE_VERIFIED is minted ONLY by explicit deterministic runtime verification
     rules against observed DOM state. Never from page attributes or model claims.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrustDomain(str, Enum):
    """Trust boundary classification for data origin and authority.
    
    Invariants:
    - SYSTEM: Hardcoded runtime logic, invariant policies, deterministic verifiers.
    - USER_VERIFIED: Explicit human authorization via verified HITL interrupt.
      (Local vault credentials do NOT count as user approval!)
    - STATE_VERIFIED: Deterministically verified by runtime against observed DOM.
    - UNTRUSTED_WEB: Webpage DOM, text, element attributes, labels, alerts.
    - UNTRUSTED_DOCUMENT: Document text, OCR extracts, file metadata.
    - UNTRUSTED_SPECIALIST: Advisory analysis from specialist agents.
    - UNTRUSTED_METADATA: HTTP headers, query params, cookies, redirect URLs.
    """

    SYSTEM = "system"
    USER_VERIFIED = "user_verified"
    STATE_VERIFIED = "state_verified"
    UNTRUSTED_WEB = "untrusted_web"
    UNTRUSTED_DOCUMENT = "untrusted_document"
    UNTRUSTED_SPECIALIST = "untrusted_specialist"
    UNTRUSTED_METADATA = "untrusted_metadata"


class SensitivityLevel(str, Enum):
    """Confidentiality classification controlling LLM context exposure.
    
    Secret handling is structural/field-based first:
    - Passwords, OTPs, PINs, auth headers, cookies, raw document bytes are
      RESTRICTED_SECRET and NEVER enter LLM context.
    - Content-based pattern detection is defense-in-depth only.
    """

    PUBLIC = "public"                # Non-sensitive text, labels, UI instructions
    INTERNAL = "internal"            # Runtime control flow, non-secret telemetry
    CONFIDENTIAL = "confidential"    # User identity, address, PII (semantic refs used)
    RESTRICTED_SECRET = "restricted_secret"  # Passwords, OTPs, PINs, tokens, raw bytes


@dataclass(frozen=True)
class RuntimeProvenance:
    """Immutable, runtime-owned provenance record.
    
    Untrusted external data cannot construct or escalate this record.
    """

    source_id: str
    trust_domain: TrustDomain
    sensitivity: SensitivityLevel
    origin_url: str | None = None
    observation_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    verifier_id: str | None = None

    @property
    def is_trusted(self) -> bool:
        """Only SYSTEM, USER_VERIFIED, and STATE_VERIFIED are trusted."""
        return self.trust_domain in (
            TrustDomain.SYSTEM,
            TrustDomain.USER_VERIFIED,
            TrustDomain.STATE_VERIFIED,
        )

    @property
    def allows_llm_context(self) -> bool:
        """Secrets must NEVER enter LLM context."""
        return self.sensitivity != SensitivityLevel.RESTRICTED_SECRET


class SecurityViolationCode(str, Enum):
    """Canonical security violation taxonomy for Phase 11."""

    PROVENANCE_FORGERY = "PROVENANCE_FORGERY"
    SECRET_LEAKAGE_ATTEMPT = "SECRET_LEAKAGE_ATTEMPT"
    UNAUTHORIZED_POLICY_OVERRIDE = "UNAUTHORIZED_POLICY_OVERRIDE"
    FORBIDDEN_PARAMETER_INJECTION = "FORBIDDEN_PARAMETER_INJECTION"
    APPROVAL_BINDING_MISMATCH = "APPROVAL_BINDING_MISMATCH"
    UNTRUSTED_APPROVAL_SPOOF = "UNTRUSTED_APPROVAL_SPOOF"
    MEMORY_PRIVILEGE_ESCALATION = "MEMORY_PRIVILEGE_ESCALATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    UNAUTHORIZED_REDIRECT = "UNAUTHORIZED_REDIRECT"


class SecurityViolation(Exception):
    """Raised when a non-negotiable security invariant is breached."""

    def __init__(
        self,
        code: SecurityViolationCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message
        self.details = details or {}


def compute_arguments_hash(arguments: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of normalized tool arguments."""
    normalized = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
