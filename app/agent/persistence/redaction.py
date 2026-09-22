"""Shared sensitive-key filtering for durable audit-event payloads — Phase 15 H6.

Defense in depth: the trace recorder redacts before the event is built, but
the durable stores must not blindly trust payload values either. The key
patterns here are aligned with the Phase 11 trace redaction patterns
(app/agent/evaluation/trace.py) so an audit row can never persist a value
under a key that the trace layer would consider secret-bearing.
"""

from __future__ import annotations

import re
from typing import Any

# Keep aligned with app/agent/evaluation/trace.py::_SENSITIVE_KEY_PATTERNS.
_SENSITIVE_KEY_PATTERNS = [
    re.compile(r"(password|passwd|pwd)", re.IGNORECASE),
    re.compile(r"(otp|one_time_password|totp)", re.IGNORECASE),
    re.compile(r"(pin|pincode_secret|mpin)", re.IGNORECASE),
    re.compile(r"(cvv|cvc|card_security_code)", re.IGNORECASE),
    re.compile(r"(token|auth_token|access_token|refresh_token|bearer)", re.IGNORECASE),
    re.compile(r"(cookie|session_cookie|session_id)", re.IGNORECASE),
    re.compile(r"(private_key|secret_key|api_key)", re.IGNORECASE),
    re.compile(r"(authorization|auth_header)", re.IGNORECASE),
    # Below the trace set: audit payloads also carry identity/document
    # references whose raw values must never be persisted.
    re.compile(r"(credential|secret)", re.IGNORECASE),
    re.compile(r"(aadhaar|pan|passport|voter_id)", re.IGNORECASE),
]

_REDACTED = "[REDACTED:restricted_secret]"


def is_sensitive_key(key: str) -> bool:
    """True when the payload key is secret-bearing and must be dropped."""
    return any(pat.search(key) for pat in _SENSITIVE_KEY_PATTERNS)


def filter_sensitive_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop secret-bearing keys (recursively) from an audit payload."""
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if is_sensitive_key(str(key)):
            safe[key] = _REDACTED
            continue
        if isinstance(value, dict):
            safe[key] = filter_sensitive_payload(value)
        elif isinstance(value, list):
            safe[key] = [
                filter_sensitive_payload(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            safe[key] = value
    return safe
