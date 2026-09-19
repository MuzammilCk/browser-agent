"""Memory write policy and poisoning defense — Phase 9.

Implements deterministic policy enforcement over all memory persistence proposals:
LLM proposal / Runtime event
      ↓
MemoryCandidate
      ↓
MemoryWritePolicy
      ↓
validation / redaction / provenance check / trust validation
      ↓
MemoryStore
      ↓
Durable Memory

Security invariants:
- Memory is supporting context, never browser truth: CURRENT WORLDSTATE > MEMORY.
- Sensitive data is strictly prohibited from memory (passwords, OTPs, PINs, auth secrets, raw document bytes).
- Semantic references (e.g. USER.full_name, DOCUMENT.aadhaar) are enforced.
- Untrusted page content cannot create permanent rules or escalate permissions.
- Model inferences cannot masquerade as VERIFIED memory without deterministic verification evidence.
- Conflicting memories preserve historical provenance; newer verified facts supersede older facts without silent destruction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.agent.memory.models import (
    AuthorType,
    EpistemicStatus,
    MemoryCandidate,
    MemoryProvenance,
    MemoryType,
    SemanticMemoryItem,
    new_id,
    utc_now_iso,
)


class MemoryPolicyRejectionCode(str, Enum):
    """Machine-readable rejection codes for memory persistence candidates."""

    SENSITIVE_DATA_PROHIBITED = "sensitive_data_prohibited"
    UNTRUSTED_SOURCE_PRIVILEGE_ESCALATION = "untrusted_source_privilege_escalation"
    UNVERIFIED_STATUS_MASQUERADE = "unverified_status_masquerade"
    INSUFFICIENT_PROVENANCE = "insufficient_provenance"
    INVALID_SCHEMA = "invalid_schema"
    SUPERSEDED_BY_VERIFIED_FACT = "superseded_by_verified_fact"
    UNAUTHORIZED_WRITE = "unauthorized_write"


# Sensitive patterns: 12-digit Aadhaar, 10-char PAN, credit card numbers, passwords, OTPs, PINs
_RE_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_RE_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b")
_RE_OTP = re.compile(r"\b\d{6}\b")
_SENSITIVE_KEYWORDS = frozenset({
    "password", "passwd", "otp", "pin", "cvv", "card_number",
    "secret", "token", "auth_code", "private_key",
})

# Suspicious phrases indicating untrusted privilege escalation or prompt injection
_PRIVILEGE_ESCALATION_PHRASES = (
    "authorized unrestricted",
    "bypass policy",
    "bypass verification",
    "authorized payment",
    "auto submit",
    "disable safety",
    "skip otp",
    "skip captcha",
    "administrator access",
    "grant all permissions",
)


@dataclass
class PolicyVerdict:
    """Outcome of MemoryWritePolicy candidate evaluation."""

    allowed: bool
    rejection_code: MemoryPolicyRejectionCode | None = None
    reason: str = ""
    sanitized_candidate: MemoryCandidate | None = None
    epistemic_status: EpistemicStatus = EpistemicStatus.INFERRED
    confidence: float = 0.5


class MemoryWritePolicy:
    """Deterministic security gate and validator for memory persistence."""

    def __init__(self, allow_sensitive_references: bool = True) -> None:
        self._allow_references = allow_sensitive_references

    def _contains_sensitive_data(self, candidate: MemoryCandidate) -> tuple[bool, str]:
        """Check if candidate contains unredacted credentials, raw secrets, or sensitive identifiers."""
        val_str = str(candidate.value)
        subj_str = str(candidate.subject)
        pred_str = str(candidate.predicate)
        full_text = f"{subj_str} {pred_str} {val_str} {candidate.summary} {json.dumps(candidate.details)}".lower()

        # Prohibited credential keywords in value or subject
        val_lower = val_str.lower()
        subj_lower = subj_str.lower()
        for kw in _SENSITIVE_KEYWORDS:
            if kw in val_lower or kw in subj_lower:
                # Passwords, secrets, OTPs, PINs, auth credentials are NEVER allowed
                if any(k in kw for k in ("password", "passwd", "otp", "pin", "cvv", "private_key", "secret")):
                    return True, f"Prohibited sensitive credential keyword: '{kw}'"
                # For other tokens, allow only if value is strictly a semantic reference handle
                if not any(val_str.startswith(p) for p in ("USER.", "DOCUMENT.")):
                    return True, f"Prohibited sensitive keyword: '{kw}'"

        # Check raw 12-digit number pattern (raw Aadhaar)
        if _RE_AADHAAR.search(val_str) and not any(val_str.startswith(p) for p in ("USER.", "DOCUMENT.")):
            return True, "Prohibited raw 12-digit identity pattern detected in value"

        # Check raw OTP pattern (6-digit numeric) if context implies otp/code/secret
        if any(k in full_text for k in ("otp", "code", "pin")) and _RE_OTP.search(val_str):
            return True, "Prohibited raw 6-digit numeric credential pattern detected"

        return False, ""

    def evaluate(self, candidate: MemoryCandidate) -> PolicyVerdict:
        """Evaluate a memory persistence proposal against deterministic security rules."""
        # 1. Basic schema validation
        if not candidate.source:
            return PolicyVerdict(
                allowed=False,
                rejection_code=MemoryPolicyRejectionCode.INSUFFICIENT_PROVENANCE,
                reason="Candidate must specify an origin source.",
            )

        # 2. Check for prohibited sensitive data
        is_sensitive, sens_reason = self._contains_sensitive_data(candidate)
        if is_sensitive:
            return PolicyVerdict(
                allowed=False,
                rejection_code=MemoryPolicyRejectionCode.SENSITIVE_DATA_PROHIBITED,
                reason=f"Rejected sensitive data: {sens_reason}. Use semantic references instead.",
            )

        # 3. Memory Poisoning & Privilege Escalation Defense
        # Untrusted page content or unverified sources cannot escalate permissions or alter policy
        text_repr = (
            f"{candidate.subject} {candidate.predicate} {candidate.value} "
            f"{candidate.summary} {json.dumps(candidate.details)}"
        )
        lower_repr = text_repr.lower()
        for phrase in _PRIVILEGE_ESCALATION_PHRASES:
            if phrase in lower_repr:
                return PolicyVerdict(
                    allowed=False,
                    rejection_code=MemoryPolicyRejectionCode.UNTRUSTED_SOURCE_PRIVILEGE_ESCALATION,
                    reason=f"Rejected privilege escalation phrase in memory candidate: '{phrase}'.",
                )

        if candidate.author_type == AuthorType.UNTRUSTED_PAGE:
            # Untrusted pages can NEVER write permanent system rules or claims
            if candidate.memory_type in (MemoryType.EXPERIENCE, MemoryType.SEMANTIC):
                return PolicyVerdict(
                    allowed=False,
                    rejection_code=MemoryPolicyRejectionCode.UNTRUSTED_SOURCE_PRIVILEGE_ESCALATION,
                    reason="Untrusted webpage content cannot write durable semantic or experience memory.",
                )
            if candidate.proposed_status == EpistemicStatus.VERIFIED:
                return PolicyVerdict(
                    allowed=False,
                    rejection_code=MemoryPolicyRejectionCode.UNVERIFIED_STATUS_MASQUERADE,
                    reason="Untrusted page content cannot claim VERIFIED epistemic status.",
                )

        # 4. Epistemic Status Gate
        # Model inferences cannot claim VERIFIED status without deterministic runtime verification
        effective_status = candidate.proposed_status
        effective_confidence = min(candidate.confidence, 1.0)

        if candidate.author_type == AuthorType.MODEL_INFERRED:
            if effective_status == EpistemicStatus.VERIFIED:
                return PolicyVerdict(
                    allowed=False,
                    rejection_code=MemoryPolicyRejectionCode.UNVERIFIED_STATUS_MASQUERADE,
                    reason="Model inference cannot propose VERIFIED epistemic status without runtime proof.",
                )
            effective_status = EpistemicStatus.INFERRED
            effective_confidence = min(effective_confidence, 0.7)

        elif candidate.author_type == AuthorType.USER_EXPLICIT:
            # Explicit user statements regarding preferences or profile are treated as verified user facts
            effective_status = EpistemicStatus.VERIFIED
            effective_confidence = 1.0

        elif candidate.author_type == AuthorType.RUNTIME_VERIFIED:
            effective_status = EpistemicStatus.VERIFIED
            effective_confidence = 1.0

        # 5. Experience Memory Caps
        # A single anecdotal observation cannot create high-confidence experience memory
        if candidate.memory_type == MemoryType.EXPERIENCE:
            if candidate.author_type == AuthorType.MODEL_INFERRED:
                effective_confidence = min(effective_confidence, 0.5)

        sanitized = candidate.model_copy(deep=True)
        sanitized.proposed_status = effective_status
        sanitized.confidence = effective_confidence

        return PolicyVerdict(
            allowed=True,
            sanitized_candidate=sanitized,
            epistemic_status=effective_status,
            confidence=effective_confidence,
        )

    def resolve_conflict(
        self,
        existing: SemanticMemoryItem,
        candidate: MemoryCandidate,
    ) -> tuple[bool, str, EpistemicStatus]:
        """Resolve conflict between an existing semantic memory and a new candidate.

        Returns: (can_supersede: bool, reason: str, resulting_status: EpistemicStatus)

        Rules:
        - Higher trust cannot be silently superseded by lower trust:
          VERIFIED > OBSERVED > INFERRED > STALE.
        - A new VERIFIED fact supersedes an older VERIFIED or INFERRED fact.
        - An INFERRED candidate cannot supersede a VERIFIED existing fact.
        - Historical record is preserved via lineage (superseded_by, valid_until).
        """
        # Epistemic rank
        ranks = {
            EpistemicStatus.VERIFIED: 4,
            EpistemicStatus.OBSERVED: 3,
            EpistemicStatus.INFERRED: 2,
            EpistemicStatus.STALE: 1,
        }

        candidate_verdict = self.evaluate(candidate)
        if not candidate_verdict.allowed:
            return False, f"Candidate rejected by policy: {candidate_verdict.reason}", existing.epistemic_status

        existing_rank = ranks.get(existing.epistemic_status, 1)
        candidate_rank = ranks.get(candidate_verdict.epistemic_status, 1)

        if candidate_rank < existing_rank:
            return (
                False,
                f"Candidate with status '{candidate_verdict.epistemic_status.value}' cannot "
                f"supersede existing '{existing.epistemic_status.value}' fact.",
                existing.epistemic_status,
            )

        return True, "Candidate authorized to supersede existing memory.", candidate_verdict.epistemic_status
