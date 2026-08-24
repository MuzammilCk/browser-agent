"""Tests for ReferenceRegistry — single source of truth for semantic references.

Audit issues covered: #5, #6, #11, #37
"""

from __future__ import annotations

import pytest

from app.agent.registry import (
    ReferenceDefinition,
    ReferenceRegistry,
    ReferenceSensitivity,
    ReferenceType,
    get_registry,
)


class TestReferenceRegistry:
    """Test ReferenceRegistry core functionality."""

    def test_registry_has_user_refs(self):
        registry = ReferenceRegistry()
        user_refs = registry.get_user_refs()
        assert "USER.full_name" in user_refs
        assert "USER.date_of_birth" in user_refs
        assert "USER.father_name" in user_refs
        assert "USER.mother_name" in user_refs
        assert "USER.spouse_name" in user_refs
        assert "USER.guardian_name" in user_refs
        assert "USER.aadhaar_number" in user_refs

    def test_registry_has_doc_refs(self):
        registry = ReferenceRegistry()
        doc_refs = registry.get_doc_refs()
        assert "DOCUMENT.aadhaar" in doc_refs
        assert "DOCUMENT.income_certificate" in doc_refs
        assert "DOCUMENT.photo" in doc_refs
        assert "DOCUMENT.signature" in doc_refs

    def test_validate_known_ref(self):
        registry = ReferenceRegistry()
        assert registry.validate("USER.full_name") is True
        assert registry.validate("DOCUMENT.aadhaar") is True

    def test_validate_unknown_ref(self):
        registry = ReferenceRegistry()
        assert registry.validate("USER.unknown_field") is False
        assert registry.validate("INVALID.ref") is False
        assert registry.validate("") is False

    def test_sensitivity_classification(self):
        registry = ReferenceRegistry()
        # Sensitive
        assert registry.is_sensitive("USER.aadhaar_number") is True
        assert registry.is_sensitive("USER.pan_number") is True
        assert registry.is_sensitive("USER.date_of_birth") is True
        assert registry.is_sensitive("USER.annual_income") is True
        # Public
        assert registry.is_sensitive("USER.full_name") is False
        assert registry.is_sensitive("USER.state") is False
        assert registry.is_sensitive("USER.gender") is False

    def test_vault_attribute_mapping(self):
        registry = ReferenceRegistry()
        assert registry.get_vault_attribute("USER.full_name") == "full_name"
        assert registry.get_vault_attribute("USER.father_name") == "father_name"
        assert registry.get_vault_attribute("DOCUMENT.aadhaar") == "aadhaar"
        assert registry.get_vault_attribute("INVALID.ref") is None

    def test_get_all_refs(self):
        registry = ReferenceRegistry()
        all_refs = registry.get_all_refs()
        assert len(all_refs) > 30  # Should have 30+ references
        assert "USER.full_name" in all_refs
        assert "DOCUMENT.aadhaar" in all_refs

    def test_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_add_custom_reference(self):
        registry = ReferenceRegistry()
        custom = ReferenceDefinition(
            key="USER.custom_field",
            ref_type=ReferenceType.USER,
            vault_attribute="custom_field",
            sensitivity=ReferenceSensitivity.PUBLIC,
        )
        registry.add_reference(custom)
        assert registry.validate("USER.custom_field") is True
        assert registry.get_vault_attribute("USER.custom_field") == "custom_field"

    def test_list_keys_sorted(self):
        registry = ReferenceRegistry()
        keys = registry.list_keys()
        assert keys == sorted(keys)
        assert len(keys) > 30

    def test_len(self):
        registry = ReferenceRegistry()
        assert len(registry) > 30

    def test_contains(self):
        registry = ReferenceRegistry()
        assert "USER.full_name" in registry
        assert "INVALID.ref" not in registry


class TestRegistryConsistency:
    """Test that registry is consistent across consumers."""

    def test_all_user_refs_have_vault_attribute(self):
        registry = ReferenceRegistry()
        for key in registry.list_keys():
            if key.startswith("USER."):
                attr = registry.get_vault_attribute(key)
                assert attr is not None, f"USER ref '{key}' has no vault attribute"

    def test_all_doc_refs_have_vault_attribute(self):
        registry = ReferenceRegistry()
        for key in registry.list_keys():
            if key.startswith("DOCUMENT."):
                attr = registry.get_vault_attribute(key)
                assert attr is not None, f"DOCUMENT ref '{key}' has no vault attribute"

    def test_field_mapper_refs_in_registry(self):
        """Every FieldMapper deterministic rule must be in the registry."""
        from app.agent.field_mapper import DETERMINISTIC_RULES
        registry = ReferenceRegistry()
        for binding_key in DETERMINISTIC_RULES:
            assert registry.validate(binding_key), (
                f"FieldMapper rule '{binding_key}' not in ReferenceRegistry"
            )
