"""Tests for task instruction sanitization (audit C6).

CAPTCHA/OTP steps must be stripped from instructions before they reach
the LLM planner — the PolicyEngine forbids automating them.
"""

from __future__ import annotations

from app.sites.registry import sanitize_task_instructions


class TestSanitizeTaskInstructions:
    def test_strips_captcha_sentence(self):
        raw = (
            "Navigate to uidai.gov.in. Enter the 12-digit Aadhaar number. "
            "Solve the CAPTCHA by typing the characters shown. Click Verify."
        )
        cleaned = sanitize_task_instructions(raw)
        assert "CAPTCHA" not in cleaned.replace("CAPTCHA/OTP", "")
        assert "Enter the 12-digit Aadhaar number." in cleaned
        assert "manually by the user" in cleaned

    def test_strips_otp_sentence(self):
        raw = (
            "Click Send OTP. Wait for the OTP to arrive on the registered "
            "mobile number. Enter the 6-digit OTP in the OTP field. Click Download."
        )
        cleaned = sanitize_task_instructions(raw)
        assert "6-digit OTP" not in cleaned
        assert "Click Download." in cleaned
        assert "manually by the user" in cleaned

    def test_clean_instructions_get_note_appended_only_when_filtered(self):
        raw = "Open the portal. Click on Services. Fill the application form."
        cleaned = sanitize_task_instructions(raw)
        assert cleaned == raw.strip()
        assert "manually" not in cleaned

    def test_empty_input_passthrough(self):
        assert sanitize_task_instructions("") == ""
        assert sanitize_task_instructions(None) is None
