"""Tests for document policy and trusted domain registry — Phase B.

Audit issues covered: #19, #36
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.policy.document_policy import DocumentPolicy, DocumentPolicyResult
from app.sites.registry import DomainEntry, TrustedDomainRegistry


# ============================================================
# Document Policy Tests
# ============================================================


class TestDocumentPolicy:
    """Test document upload validation."""

    def test_valid_pdf_upload(self):
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test content")
            path = f.name
        try:
            result = policy.validate_upload(path, "aadhaar")
            assert result.allowed is True
        finally:
            os.unlink(path)

    def test_invalid_extension(self):
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"%PDF-1.4 test content")
            path = f.name
        try:
            result = policy.validate_upload(path, "aadhaar")
            assert result.allowed is False
            assert ".exe" in result.reason
        finally:
            os.unlink(path)

    def test_photo_jpg_allowed(self):
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0 jpeg-content")
            path = f.name
        try:
            result = policy.validate_upload(path, "photo")
            assert result.allowed is True
        finally:
            os.unlink(path)

    def test_income_cert_only_pdf(self):
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0 jpeg-content")
            path = f.name
        try:
            result = policy.validate_upload(path, "income_certificate")
            assert result.allowed is False
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        policy = DocumentPolicy()
        result = policy.validate_upload("/nonexistent/file.pdf", "aadhaar")
        assert result.allowed is False
        assert "does not exist" in result.reason

    def test_file_too_large(self):
        policy = DocumentPolicy()
        # Create a file larger than 2MB limit for photos (valid JPEG header)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"x" * (3 * 1024 * 1024))  # 3MB
            path = f.name
        try:
            result = policy.validate_upload(path, "photo")
            assert result.allowed is False
            assert "too large" in result.reason.lower()
        finally:
            os.unlink(path)

    def test_normal_file_size_ok(self):
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 " + b"x" * 1000)  # ~1KB valid PDF header
            path = f.name
        try:
            result = policy.validate_upload(path, "aadhaar")
            assert result.allowed is True
        finally:
            os.unlink(path)

    def test_renamed_exe_as_pdf_blocked_by_magic_bytes(self):
        """Audit B7/C12: content contradicting the extension is blocked."""
        policy = DocumentPolicy()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"MZ\x90\x00 fake executable renamed to pdf")
            path = f.name
        try:
            result = policy.validate_upload(path, "aadhaar")
            assert result.allowed is False
            assert "renamed" in result.reason or "does not match" in result.reason
        finally:
            os.unlink(path)


# ============================================================
# Trusted Domain Registry Tests
# ============================================================


class TestTrustedDomainRegistry:
    """Test trusted government domain registry."""

    def test_known_gov_in_domain(self):
        registry = TrustedDomainRegistry()
        assert registry.is_trusted("https://pmkisan.gov.in/some/path") is True

    def test_unknown_domain_not_trusted(self):
        registry = TrustedDomainRegistry()
        assert registry.is_trusted("https://random-website.com/form") is False

    def test_get_entry(self):
        registry = TrustedDomainRegistry()
        entry = registry.get_entry("https://pmkisan.gov.in/form")
        assert entry is not None
        assert entry.domain == "pmkisan.gov.in"
        assert entry.official_name == "PM-KISAN"
        assert entry.government_level == "central"

    def test_get_constraints(self):
        registry = TrustedDomainRegistry()
        constraints = registry.get_constraints("https://pmkisan.gov.in/form")
        assert isinstance(constraints, list)

    def test_list_domains(self):
        registry = TrustedDomainRegistry()
        domains = registry.list_domains()
        assert len(domains) > 10
        assert "pmkisan.gov.in" in domains

    def test_register_new_domain(self):
        registry = TrustedDomainRegistry()
        entry = DomainEntry(
            domain="custom.gov.in",
            official_name="Custom Service",
            category="Test",
            government_level="state",
        )
        registry.register(entry)
        assert registry.is_trusted("https://custom.gov.in/form") is True

    def test_is_known(self):
        registry = TrustedDomainRegistry()
        assert registry.is_known("https://pmkisan.gov.in") is True
        assert registry.is_known("https://unknown.com") is False

    def test_www_prefix_stripped(self):
        registry = TrustedDomainRegistry()
        assert registry.is_trusted("https://www.pmkisan.gov.in") is True

    def test_len(self):
        registry = TrustedDomainRegistry()
        assert len(registry) > 10

    def test_contains(self):
        registry = TrustedDomainRegistry()
        assert "pmkisan.gov.in" in registry
        assert "unknown.com" not in registry

