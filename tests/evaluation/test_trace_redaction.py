"""Unit tests for Trace Redaction and Secret Handling — Phase 12.

Tests:
1. Structural scrubbing of password, otp, pin, cvv, token, cookie, auth headers, private keys.
2. Content scrubbing for bearer tokens and OTP patterns.
3. Trace export produces zero raw secrets.
"""

from __future__ import annotations

import json
from app.agent.evaluation.trace import TraceEventType, TraceRecorder, redact_trace_value


def test_redact_trace_value_handles_all_secret_keys():
    """All sensitive structural keys are redacted with sensitivity markers."""
    payload = {
        "user_id": "usr_123",
        "password": "SuperSecretPassword123!",
        "login_otp": "948201",
        "pin": "1234",
        "cvv": "999",
        "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "session_cookie": "sess_cookie_abc",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        "authorization_header": "Bearer secret_api_key_xyz",
        "safe_field": "public_data",
    }

    cleaned = redact_trace_value(None, payload)
    assert cleaned["user_id"] == "usr_123"
    assert cleaned["safe_field"] == "public_data"

    # All secret fields must be masked
    assert cleaned["password"] == "[REDACTED:restricted_secret]"
    assert cleaned["login_otp"] == "[REDACTED:restricted_secret]"
    assert cleaned["pin"] == "[REDACTED:restricted_secret]"
    assert cleaned["cvv"] == "[REDACTED:restricted_secret]"
    assert cleaned["auth_token"] == "[REDACTED:restricted_secret]"
    assert cleaned["session_cookie"] == "[REDACTED:restricted_secret]"
    assert cleaned["private_key"] == "[REDACTED:restricted_secret]"
    assert cleaned["authorization_header"] == "[REDACTED:restricted_secret]"


def test_redact_trace_value_content_scrubbing_defense_in_depth():
    """Content strings matching bearer tokens or standalone OTPs are scrubbed."""
    text_with_token = "Authorization failed with header: Bearer abcdef1234567890xyz"
    scrubbed = redact_trace_value(None, text_with_token)
    assert "abcdef1234567890xyz" not in scrubbed
    assert "[REDACTED:AUTH_TOKEN]" in scrubbed

    text_with_otp = "Your verification OTP is 654321, valid for 5 mins."
    scrubbed_otp = redact_trace_value(None, text_with_otp)
    assert "654321" not in scrubbed_otp
    assert "[REDACTED:OTP_OR_PIN]" in scrubbed_otp


def test_trace_recorder_exports_contain_zero_raw_secrets():
    """Recorded trace events scrub payloads before adding to in-memory log or exporting."""
    recorder = TraceRecorder(run_id="run_sec", scenario_id="golden_sec")
    recorder.record(
        TraceEventType.TOOL_PROPOSAL,
        subsystem="tools",
        component="ToolRegistry",
        tool_name="fill_field",
        input_summary={"field": "password", "password": "SecretUserPassword123!"},
        output_summary={"token": "secret_session_token_12345"},
    )

    # Export to JSON
    exported_json = recorder.to_json()
    assert "SecretUserPassword123!" not in exported_json
    assert "secret_session_token_12345" not in exported_json
    assert "[REDACTED:restricted_secret]" in exported_json

    # Export to JSONL
    exported_jsonl = recorder.to_jsonl()
    assert "SecretUserPassword123!" not in exported_jsonl
    assert "secret_session_token_12345" not in exported_jsonl
