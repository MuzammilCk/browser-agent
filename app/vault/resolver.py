"""Value resolver and document resolver.

Uses ReferenceRegistry as single source of truth per audit #5, #6, #37.
- LLM emits value_ref like "USER.full_name" → resolver resolves locally
- LLM emits document_ref like "DOCUMENT.aadhaar" → resolver resolves locally
- Sensitive values are never sent through the LLM
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agent.registry import ReferenceRegistry, ReferenceSensitivity, get_registry

logger = logging.getLogger(__name__)


class UserVault(BaseModel):
    """Typed user data model with semantic references.

    Must stay in sync with ReferenceRegistry _USER_REFS.
    """

    # Identity
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    gender: str = ""
    nationality: str = ""
    age: str = ""

    # Contact
    mobile: str = ""
    email: str = ""

    # Address
    address: str = ""
    permanent_address: str = ""
    state: str = ""
    district: str = ""
    block: str = ""
    village: str = ""
    pincode: str = ""

    # Government IDs
    aadhaar_number: str = ""
    aadhaar_name: str = ""
    pan_number: str = ""
    voter_id: str = ""

    # Education
    education: str = ""
    degree: str = ""
    institution: str = ""

    # Employment
    occupation: str = ""
    employer: str = ""
    annual_income: str = ""

    # Financial
    bank_name: str = ""
    account_number: str = ""
    ifsc_code: str = ""

    # Family
    father_name: str = ""
    mother_name: str = ""
    spouse_name: str = ""
    guardian_name: str = ""

    # Category
    category: str = ""
    religion: str = ""
    marital_status: str = ""


class DocumentRef(BaseModel):
    """Reference to a document file."""

    id: str
    type: str
    path: str
    mime_type: str = ""
    original_filename: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRegistry:
    """Local document registry."""

    def __init__(self) -> None:
        self._documents: dict[str, DocumentRef] = {}

    def register(self, doc: DocumentRef) -> None:
        self._documents[doc.id] = doc

    def resolve(self, ref: str) -> DocumentRef | None:
        return self._documents.get(ref)

    def list_documents(self) -> list[DocumentRef]:
        return list(self._documents.values())


class ValueResolver:
    """Resolves semantic value references to actual values.

    Uses ReferenceRegistry as single source of truth.
    LLM emits: {"value_ref": "USER.full_name"}
    Resolver maps: "USER.full_name" -> "Rahul Sharma"

    This keeps sensitive values out of the LLM context.
    """

    def __init__(
        self,
        vault: UserVault,
        registry: ReferenceRegistry | None = None,
    ) -> None:
        self._vault = vault
        self._registry = registry or get_registry()
        # Build lookup from registry
        self._user_fields: dict[str, str] = {}
        for key in self._registry.list_keys():
            attr = self._registry.get_vault_attribute(key)
            if attr and key.startswith("USER."):
                self._user_fields[key] = attr

    def resolve(self, value_ref: str) -> str | None:
        """Resolve a USER.x reference to its actual value.

        Returns None if the reference is invalid or the value is empty.
        """
        if not value_ref:
            return None

        if not value_ref.startswith("USER."):
            logger.warning("Invalid value_ref prefix: %s", value_ref)
            return None

        # Validate against registry
        if not self._registry.validate(value_ref):
            logger.warning("Unknown value_ref (not in registry): %s", value_ref)
            return None

        field_attr = self._user_fields.get(value_ref)
        if field_attr is None:
            logger.warning("No vault attribute for: %s", value_ref)
            return None

        value = getattr(self._vault, field_attr, None)
        if not value:
            logger.debug("Empty value for %s", value_ref)
            return None

        return str(value)

    def is_valid_ref(self, value_ref: str) -> bool:
        """Check if a value reference is valid."""
        return self._registry.validate(value_ref)

    def can_resolve(self, value_ref: str) -> bool:
        """Check if a value reference can be resolved (valid + has value)."""
        return self.resolve(value_ref) is not None


class DocumentResolver:
    """Resolves document references to local file paths.

    Uses ReferenceRegistry as single source of truth.
    LLM emits: {"document_ref": "DOCUMENT.aadhaar"}
    Resolver maps to actual file path.
    """

    def __init__(
        self,
        registry: DocumentRegistry | None = None,
        ref_registry: ReferenceRegistry | None = None,
    ) -> None:
        self._doc_registry = registry or DocumentRegistry()
        self._ref_registry = ref_registry or get_registry()
        # Build lookup from registry
        self._doc_fields: dict[str, str] = {}
        for key in self._ref_registry.list_keys():
            attr = self._ref_registry.get_vault_attribute(key)
            if attr and key.startswith("DOCUMENT."):
                self._doc_fields[key] = attr

    def resolve(self, document_ref: str) -> DocumentRef | None:
        """Resolve a DOCUMENT.x reference to a DocumentRef."""
        if not document_ref or not document_ref.startswith("DOCUMENT."):
            return None

        # Validate against registry
        if not self._ref_registry.validate(document_ref):
            logger.warning("Unknown document_ref (not in registry): %s", document_ref)
            return None

        doc_id = self._doc_fields.get(document_ref)
        if doc_id is None:
            logger.warning("No vault attribute for: %s", document_ref)
            return None

        doc = self._doc_registry.resolve(doc_id)
        if doc is None:
            logger.warning("Document not found: %s (ref=%s)", doc_id, document_ref)
            return None

        # Validate file exists
        if not Path(doc.path).exists():
            logger.warning("Document file does not exist: %s", doc.path)
            return None

        return doc

    def is_valid_ref(self, document_ref: str) -> bool:
        """Check if a document reference is valid."""
        return self._ref_registry.validate(document_ref)

    def can_resolve(self, document_ref: str) -> bool:
        """Check if a document reference can be resolved (valid + exists)."""
        return self.resolve(document_ref) is not None
