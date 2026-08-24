"""Value resolver and document resolver.

Per audit #9 and #10:
- LLM emits value_ref like "USER.full_name" — resolver resolves locally
- LLM emits document_ref like "DOCUMENT.aadhaar" — resolver resolves locally
- Sensitive values are never sent through the LLM
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UserVault(BaseModel):
    """Typed user data model with semantic references."""

    # Identity
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    gender: str = ""
    nationality: str = ""

    # Contact
    mobile: str = ""
    email: str = ""

    # Address
    address: str = ""
    state: str = ""
    district: str = ""
    block: str = ""
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

    LLM emits: {"value_ref": "USER.full_name"}
    Resolver maps: "USER.full_name" -> "Rahul Sharma"

    This keeps sensitive values out of the LLM context.
    """

    # Allowed reference prefixes and their target attributes
    USER_FIELDS = {
        "USER.full_name": "full_name",
        "USER.first_name": "first_name",
        "USER.last_name": "last_name",
        "USER.date_of_birth": "date_of_birth",
        "USER.gender": "gender",
        "USER.nationality": "nationality",
        "USER.mobile": "mobile",
        "USER.email": "email",
        "USER.address": "address",
        "USER.state": "state",
        "USER.district": "district",
        "USER.block": "block",
        "USER.pincode": "pincode",
        "USER.aadhaar_name": "aadhaar_name",
        "USER.pan_number": "pan_number",
        "USER.voter_id": "voter_id",
        "USER.education": "education",
        "USER.degree": "degree",
        "USER.institution": "institution",
        "USER.occupation": "occupation",
        "USER.employer": "employer",
        "USER.annual_income": "annual_income",
        "USER.bank_name": "bank_name",
        "USER.account_number": "account_number",
        "USER.ifsc_code": "ifsc_code",
        "USER.category": "category",
        "USER.religion": "religion",
        "USER.marital_status": "marital_status",
    }

    def __init__(self, vault: UserVault) -> None:
        self._vault = vault

    def resolve(self, value_ref: str) -> str | None:
        """Resolve a USER.x reference to its actual value.

        Returns None if the reference is invalid or the value is empty.
        """
        if not value_ref:
            return None

        if not value_ref.startswith("USER."):
            logger.warning("Invalid value_ref prefix: %s", value_ref)
            return None

        field_attr = self.USER_FIELDS.get(value_ref)
        if field_attr is None:
            logger.warning("Unknown value_ref: %s", value_ref)
            return None

        value = getattr(self._vault, field_attr, None)
        if not value:
            logger.debug("Empty value for %s", value_ref)
            return None

        return str(value)

    def is_valid_ref(self, value_ref: str) -> bool:
        """Check if a value reference is valid."""
        return value_ref in self.USER_FIELDS


class DocumentResolver:
    """Resolves document references to local file paths.

    LLM emits: {"document_ref": "DOCUMENT.income_certificate"}
    Resolver maps to actual file path.
    """

    DOC_FIELDS = {
        "DOCUMENT.aadhaar": "aadhaar",
        "DOCUMENT.income_certificate": "income_certificate",
        "DOCUMENT.degree_certificate": "degree_certificate",
        "DOCUMENT.passport_photo": "passport_photo",
        "DOCUMENT.signature": "signature",
        "DOCUMENT.voter_id": "voter_id",
        "DOCUMENT.pan_card": "pan_card",
    }

    def __init__(self, registry: DocumentRegistry) -> None:
        self._registry = registry

    def resolve(self, document_ref: str) -> DocumentRef | None:
        """Resolve a DOCUMENT.x reference to a DocumentRef."""
        if not document_ref or not document_ref.startswith("DOCUMENT."):
            return None

        doc_id = self.DOC_FIELDS.get(document_ref)
        if doc_id is None:
            logger.warning("Unknown document_ref: %s", document_ref)
            return None

        doc = self._registry.resolve(doc_id)
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
        return document_ref in self.DOC_FIELDS
