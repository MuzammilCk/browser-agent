"""Comprehensive tests for Phase 4 — User Vault + Document Registry."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.vault.resolver import (
    DocumentRef,
    DocumentRegistry,
    DocumentResolver,
    UserVault,
    ValueResolver,
)
from app.vault.sensitivity import (
    FIELD_SENSITIVITY,
    SensitivityLevel,
    get_field_sensitivity,
    get_safe_fields,
    get_sensitive_fields,
    is_sensitive,
)
from app.vault.manager import VaultManager


# ═══════════════════════════════════════════════════════════════
# USER VAULT MODEL
# ═══════════════════════════════════════════════════════════════

class TestUserVault:
    """Tests for UserVault data model."""

    def test_default_vault_is_empty(self) -> None:
        vault = UserVault()
        assert vault.full_name == ""
        assert vault.aadhaar_number == ""
        assert vault.state == ""

    def test_vault_with_data(self) -> None:
        vault = UserVault(
            full_name="Test User",
            date_of_birth="01/01/2000",
            state="Kerala",
            aadhaar_number="1234-5678-9012",
        )
        assert vault.full_name == "Test User"
        assert vault.date_of_birth == "01/01/2000"
        assert vault.state == "Kerala"
        assert vault.aadhaar_number == "1234-5678-9012"

    def test_vault_serialization(self) -> None:
        vault = UserVault(full_name="Test", state="Kerala")
        data = vault.model_dump()
        assert data["full_name"] == "Test"
        assert data["state"] == "Kerala"

    def test_vault_json_roundtrip(self) -> None:
        vault = UserVault(full_name="Test User", state="Karnataka")
        json_str = vault.model_dump_json()
        restored = UserVault.model_validate_json(json_str)
        assert restored.full_name == "Test User"
        assert restored.state == "Karnataka"

    def test_all_fields_accessible(self) -> None:
        """Every field in the vault is accessible."""
        vault = UserVault()
        fields = [
            "full_name", "first_name", "last_name", "date_of_birth",
            "gender", "nationality", "mobile", "email",
            "address", "state", "district", "block", "pincode",
            "aadhaar_number", "aadhaar_name", "pan_number", "voter_id",
            "education", "degree", "institution",
            "occupation", "employer", "annual_income",
            "bank_name", "account_number", "ifsc_code",
            "category", "religion", "marital_status",
        ]
        for field in fields:
            assert hasattr(vault, field), f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════
# SENSITIVITY CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

class TestSensitivityClassification:
    """Tests for field sensitivity classification."""

    def test_government_ids_are_sensitive(self) -> None:
        assert is_sensitive("aadhaar_number") is True
        assert is_sensitive("pan_number") is True
        assert is_sensitive("voter_id") is True

    def test_financial_fields_are_sensitive(self) -> None:
        assert is_sensitive("annual_income") is True
        assert is_sensitive("account_number") is True

    def test_date_of_birth_is_sensitive(self) -> None:
        assert is_sensitive("date_of_birth") is True

    def test_public_fields_are_not_sensitive(self) -> None:
        assert is_sensitive("full_name") is False
        assert is_sensitive("state") is False
        assert is_sensitive("gender") is False
        assert is_sensitive("category") is False

    def test_safe_fields_for_llm(self) -> None:
        safe = get_safe_fields()
        assert "full_name" in safe
        assert "state" in safe
        assert "aadhaar_number" not in safe
        assert "pan_number" not in safe

    def test_sensitive_fields_list(self) -> None:
        sensitive = get_sensitive_fields()
        assert "aadhaar_number" in sensitive
        assert "pan_number" in sensitive
        assert "full_name" not in sensitive

    def test_all_vault_fields_have_sensitivity(self) -> None:
        """Every field in UserVault should have a sensitivity classification."""
        vault = UserVault()
        for field_name in UserVault.model_fields:
            assert field_name in FIELD_SENSITIVITY, f"Missing sensitivity for: {field_name}"


# ═══════════════════════════════════════════════════════════════
# VALUE RESOLVER
# ═══════════════════════════════════════════════════════════════

class TestValueResolver:
    """Tests for semantic value resolution."""

    def setup_method(self) -> None:
        self.vault = UserVault(
            full_name="Test User",
            date_of_birth="15/08/1990",
            state="Karnataka",
            aadhaar_name="Test User",
            annual_income="600000",
        )
        self.resolver = ValueResolver(self.vault)

    def test_resolve_known_field(self) -> None:
        assert self.resolver.resolve("USER.full_name") == "Test User"

    def test_resolve_empty_field(self) -> None:
        assert self.resolver.resolve("USER.pan_number") is None

    def test_resolve_invalid_prefix(self) -> None:
        assert self.resolver.resolve("DOC.something") is None

    def test_resolve_unknown_field(self) -> None:
        assert self.resolver.resolve("USER.nonexistent") is None

    def test_is_valid_ref(self) -> None:
        assert self.resolver.is_valid_ref("USER.full_name") is True
        assert self.resolver.is_valid_ref("USER.nonexistent") is False

    def test_resolve_all_populated_fields(self) -> None:
        """All populated fields resolve correctly."""
        assert self.resolver.resolve("USER.full_name") == "Test User"
        assert self.resolver.resolve("USER.date_of_birth") == "15/08/1990"
        assert self.resolver.resolve("USER.state") == "Karnataka"
        assert self.resolver.resolve("USER.aadhaar_name") == "Test User"
        assert self.resolver.resolve("USER.annual_income") == "600000"


# ═══════════════════════════════════════════════════════════════
# DOCUMENT RESOLVER
# ═══════════════════════════════════════════════════════════════

class TestDocumentResolver:
    """Tests for document resolution."""

    def setup_method(self) -> None:
        self.registry = DocumentRegistry()
        self.tmp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.tmp_dir) / "aadhaar.pdf"
        self.test_file.write_bytes(b"fake pdf")

        self.registry.register(DocumentRef(
            id="aadhaar",
            type="aadhaar",
            path=str(self.test_file),
            mime_type="application/pdf",
        ))
        self.resolver = DocumentResolver(self.registry)

    def test_resolve_existing(self) -> None:
        doc = self.resolver.resolve("DOCUMENT.aadhaar")
        assert doc is not None
        assert doc.path == str(self.test_file)

    def test_resolve_nonexistent(self) -> None:
        doc = self.resolver.resolve("DOCUMENT.income_certificate")
        assert doc is None

    def test_resolve_invalid_prefix(self) -> None:
        doc = self.resolver.resolve("DOC.aadhaar")
        assert doc is None

    def test_is_valid_ref(self) -> None:
        assert self.resolver.is_valid_ref("DOCUMENT.aadhaar") is True
        assert self.resolver.is_valid_ref("DOCUMENT.nonexistent") is False


# ═══════════════════════════════════════════════════════════════
# DOCUMENT REGISTRY
# ═══════════════════════════════════════════════════════════════

class TestDocumentRegistry:
    """Tests for document registry."""

    def test_register_and_resolve(self) -> None:
        registry = DocumentRegistry()
        doc = DocumentRef(id="test", type="pdf", path="/tmp/test.pdf")
        registry.register(doc)
        assert registry.resolve("test") is doc

    def test_list_documents(self) -> None:
        registry = DocumentRegistry()
        registry.register(DocumentRef(id="a", type="pdf", path="/a.pdf"))
        registry.register(DocumentRef(id="b", type="jpg", path="/b.jpg"))
        assert len(registry.list_documents()) == 2

    def test_resolve_nonexistent(self) -> None:
        registry = DocumentRegistry()
        assert registry.resolve("nonexistent") is None


# ═══════════════════════════════════════════════════════════════
# VAULT MANAGER
# ═══════════════════════════════════════════════════════════════

class TestVaultManager:
    """Tests for vault persistence."""

    def setup_method(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_load_empty_vault(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        vault = manager.load_vault()
        assert vault.full_name == ""

    def test_save_and_load_vault(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        vault = UserVault(full_name="Test User", state="Kerala")
        manager.save_vault(vault)

        # Load in a new manager
        manager2 = VaultManager(vault_dir=self.tmp_dir)
        loaded = manager2.load_vault()
        assert loaded.full_name == "Test User"
        assert loaded.state == "Kerala"

    def test_save_and_load_registry(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        registry = DocumentRegistry()
        registry.register(DocumentRef(id="doc1", type="pdf", path="/tmp/doc1.pdf"))
        manager.save_registry(registry)

        manager2 = VaultManager(vault_dir=self.tmp_dir)
        loaded = manager2.load_registry()
        docs = loaded.list_documents()
        assert len(docs) == 1
        assert docs[0].id == "doc1"

    def test_create_sample_vault(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        vault = manager.create_sample_vault()
        assert vault.full_name == "Rajesh Kumar Singh"
        assert vault.state == "Delhi"
        assert vault.aadhaar_number != ""

        # Verify it was saved
        loaded = manager.load_vault()
        assert loaded.full_name == "Rajesh Kumar Singh"

    def test_register_document(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        doc = DocumentRef(id="aadhaar", type="aadhaar", path="/tmp/aadhaar.pdf")
        manager.register_document(doc)

        # Verify it persists
        manager2 = VaultManager(vault_dir=self.tmp_dir)
        resolved = manager2.registry.resolve("aadhaar")
        assert resolved is not None
        assert resolved.type == "aadhaar"

    def test_vault_property_lazy_load(self) -> None:
        manager = VaultManager(vault_dir=self.tmp_dir)
        # First access creates empty vault
        assert manager.vault.full_name == ""
        # Second access returns same instance
        assert manager.vault is manager.vault


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: VAULT → RESOLVER → EXECUTOR FLOW
# ═══════════════════════════════════════════════════════════════

class TestVaultResolverIntegration:
    """Integration test: vault data flows through resolver correctly."""

    def test_full_resolution_flow(self) -> None:
        """Create vault → resolve USER.x → get actual value."""
        vault = UserVault(
            full_name="Integration Test User",
            date_of_birth="01/01/1995",
            state="Tamil Nadu",
            district="Chennai",
            aadhaar_name="Integration Test User",
        )
        resolver = ValueResolver(vault)

        assert resolver.resolve("USER.full_name") == "Integration Test User"
        assert resolver.resolve("USER.date_of_birth") == "01/01/1995"
        assert resolver.resolve("USER.state") == "Tamil Nadu"
        assert resolver.resolve("USER.district") == "Chennai"
        assert resolver.resolve("USER.aadhaar_name") == "Integration Test User"

    def test_document_resolution_flow(self) -> None:
        """Create registry → register doc → resolve DOCUMENT.x → get path."""
        import tempfile

        tmp = tempfile.mkdtemp()
        test_file = Path(tmp) / "income_cert.pdf"
        test_file.write_bytes(b"fake cert")

        registry = DocumentRegistry()
        registry.register(DocumentRef(
            id="income_certificate",
            type="income_certificate",
            path=str(test_file),
            mime_type="application/pdf",
        ))

        resolver = DocumentResolver(registry)
        doc = resolver.resolve("DOCUMENT.income_certificate")
        assert doc is not None
        assert doc.path == str(test_file)

    def test_vault_manager_end_to_end(self) -> None:
        """Full flow: create sample vault → resolve all populated fields."""
        import tempfile

        tmp = tempfile.mkdtemp()
        manager = VaultManager(vault_dir=tmp)
        vault = manager.create_sample_vault()

        resolver = ValueResolver(vault)

        # Verify all populated fields resolve (matches sample vault synthetic data)
        populated_fields = {
            "USER.full_name": "Rajesh Kumar Singh",
            "USER.first_name": "Rajesh",
            "USER.last_name": "Singh",
            "USER.date_of_birth": "15/08/1990",
            "USER.gender": "Male",
            "USER.state": "Delhi",
            "USER.district": "New Delhi",
            "USER.aadhaar_name": "Rajesh Kumar Singh",
            "USER.pan_number": "ABCDE1234F",
            "USER.annual_income": "1200000",
            "USER.category": "General",
        }

        for ref, expected in populated_fields.items():
            actual = resolver.resolve(ref)
            assert actual == expected, f"{ref}: expected {expected!r}, got {actual!r}"
