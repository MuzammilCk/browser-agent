"""Canonical reference registry — single source of truth for all semantic references.

Per audit issues #5, #6, #11, #37:
- FieldMapper, ValueResolver, DocumentResolver, prompts, policy
  ALL derive their allowed references from this registry.
- NEVER maintain separate hardcoded reference lists again.
- LLM output is validated against this registry before execution.

Architecture:
    ReferenceRegistry
        ├── USER.* references
        ├── DOCUMENT.* references
        ├── sensitivity classification
        ├── resolver mapping
        └── validation
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReferenceType(str, Enum):
    """Type of semantic reference."""

    USER = "user"
    DOCUMENT = "document"


class ReferenceSensitivity(str, Enum):
    """Sensitivity level for a reference — controls LLM visibility."""

    PUBLIC = "public"        # Safe to show to LLM (e.g., state, gender)
    INTERNAL = "internal"    # Used internally only
    SENSITIVE = "sensitive"  # Government IDs, financial (e.g., Aadhaar, PAN)
    SECRET = "secret"        # Never expose (e.g., passwords, OTP)


class ReferenceDefinition(BaseModel):
    """Definition of a single semantic reference."""

    key: str = Field(
        description="Full reference key (e.g., 'USER.full_name')"
    )
    ref_type: ReferenceType = Field(
        description="Whether this is a user or document reference"
    )
    vault_attribute: str = Field(
        description="Attribute name on UserVault or DocumentRegistry"
    )
    sensitivity: ReferenceSensitivity = Field(
        default=ReferenceSensitivity.PUBLIC,
        description="Sensitivity classification"
    )
    llm_visible: bool = Field(
        default=True,
        description="Whether the LLM should see this reference"
    )
    confirmation_policy: str = Field(
        default="none",
        description="none | sensitive_confirm | always_confirm"
    )
    display_name: str = Field(
        default="",
        description="Human-readable name for prompts"
    )


# ============================================================
# Canonical reference definitions
# ============================================================

_USER_REFS: list[dict[str, Any]] = [
    # Identity
    {"key": "USER.full_name", "vault_attribute": "full_name",
     "sensitivity": "public", "display_name": "Full Name"},
    {"key": "USER.first_name", "vault_attribute": "first_name",
     "sensitivity": "public", "display_name": "First Name"},
    {"key": "USER.last_name", "vault_attribute": "last_name",
     "sensitivity": "public", "display_name": "Last Name"},
    {"key": "USER.date_of_birth", "vault_attribute": "date_of_birth",
     "sensitivity": "sensitive", "display_name": "Date of Birth"},
    {"key": "USER.gender", "vault_attribute": "gender",
     "sensitivity": "public", "display_name": "Gender"},
    {"key": "USER.nationality", "vault_attribute": "nationality",
     "sensitivity": "public", "display_name": "Nationality"},
    {"key": "USER.age", "vault_attribute": "age",
     "sensitivity": "public", "display_name": "Age"},
    # Contact
    {"key": "USER.mobile", "vault_attribute": "mobile",
     "sensitivity": "sensitive", "display_name": "Mobile Number"},
    {"key": "USER.email", "vault_attribute": "email",
     "sensitivity": "internal", "display_name": "Email Address"},
    # Address
    {"key": "USER.address", "vault_attribute": "address",
     "sensitivity": "internal", "display_name": "Address"},
    {"key": "USER.permanent_address", "vault_attribute": "permanent_address",
     "sensitivity": "internal", "display_name": "Permanent Address"},
    {"key": "USER.state", "vault_attribute": "state",
     "sensitivity": "public", "display_name": "State"},
    {"key": "USER.district", "vault_attribute": "district",
     "sensitivity": "public", "display_name": "District"},
    {"key": "USER.block", "vault_attribute": "block",
     "sensitivity": "public", "display_name": "Block"},
    {"key": "USER.village", "vault_attribute": "village",
     "sensitivity": "public", "display_name": "Village/Town"},
    {"key": "USER.pincode", "vault_attribute": "pincode",
     "sensitivity": "public", "display_name": "Pincode"},
    # Government IDs
    {"key": "USER.aadhaar_number", "vault_attribute": "aadhaar_number",
     "sensitivity": "sensitive", "display_name": "Aadhaar Number"},
    {"key": "USER.aadhaar_name", "vault_attribute": "aadhaar_name",
     "sensitivity": "public", "display_name": "Name as per Aadhaar"},
    {"key": "USER.pan_number", "vault_attribute": "pan_number",
     "sensitivity": "sensitive", "display_name": "PAN Number"},
    {"key": "USER.voter_id", "vault_attribute": "voter_id",
     "sensitivity": "sensitive", "display_name": "Voter ID"},
    # Education
    {"key": "USER.education", "vault_attribute": "education",
     "sensitivity": "public", "display_name": "Education"},
    {"key": "USER.degree", "vault_attribute": "degree",
     "sensitivity": "public", "display_name": "Degree"},
    {"key": "USER.institution", "vault_attribute": "institution",
     "sensitivity": "public", "display_name": "Institution"},
    # Employment
    {"key": "USER.occupation", "vault_attribute": "occupation",
     "sensitivity": "public", "display_name": "Occupation"},
    {"key": "USER.employer", "vault_attribute": "employer",
     "sensitivity": "internal", "display_name": "Employer"},
    {"key": "USER.annual_income", "vault_attribute": "annual_income",
     "sensitivity": "sensitive", "display_name": "Annual Income"},
    # Financial
    {"key": "USER.bank_name", "vault_attribute": "bank_name",
     "sensitivity": "internal", "display_name": "Bank Name"},
    {"key": "USER.account_number", "vault_attribute": "account_number",
     "sensitivity": "sensitive", "display_name": "Account Number"},
    {"key": "USER.bank_account", "vault_attribute": "account_number",
     "sensitivity": "sensitive", "display_name": "Bank Account Number"},
    {"key": "USER.ifsc_code", "vault_attribute": "ifsc_code",
     "sensitivity": "internal", "display_name": "IFSC Code"},
    # Family
    {"key": "USER.father_name", "vault_attribute": "father_name",
     "sensitivity": "public", "display_name": "Father's Name"},
    {"key": "USER.mother_name", "vault_attribute": "mother_name",
     "sensitivity": "public", "display_name": "Mother's Name"},
    {"key": "USER.spouse_name", "vault_attribute": "spouse_name",
     "sensitivity": "public", "display_name": "Spouse Name"},
    {"key": "USER.guardian_name", "vault_attribute": "guardian_name",
     "sensitivity": "public", "display_name": "Guardian Name"},
    # Category
    {"key": "USER.category", "vault_attribute": "category",
     "sensitivity": "public", "display_name": "Category"},
    {"key": "USER.religion", "vault_attribute": "religion",
     "sensitivity": "public", "display_name": "Religion"},
    {"key": "USER.marital_status", "vault_attribute": "marital_status",
     "sensitivity": "public", "display_name": "Marital Status"},
]

_DOC_REFS: list[dict[str, Any]] = [
    {"key": "DOCUMENT.aadhaar", "vault_attribute": "aadhaar",
     "sensitivity": "sensitive", "display_name": "Aadhaar Card"},
    {"key": "DOCUMENT.income_certificate", "vault_attribute": "income_certificate",
     "sensitivity": "internal", "display_name": "Income Certificate"},
    {"key": "DOCUMENT.degree_certificate", "vault_attribute": "degree_certificate",
     "sensitivity": "internal", "display_name": "Degree Certificate"},
    {"key": "DOCUMENT.photo", "vault_attribute": "photo",
     "sensitivity": "internal", "display_name": "Passport Photo"},
    {"key": "DOCUMENT.signature", "vault_attribute": "signature",
     "sensitivity": "internal", "display_name": "Signature"},
    {"key": "DOCUMENT.voter_id", "vault_attribute": "voter_id_doc",
     "sensitivity": "sensitive", "display_name": "Voter ID Document"},
    {"key": "DOCUMENT.pan_card", "vault_attribute": "pan_card",
     "sensitivity": "sensitive", "display_name": "PAN Card"},
]


class ReferenceRegistry:
    """Canonical registry of all semantic references.

    Every consumer (FieldMapper, ValueResolver, DocumentResolver,
    prompts, policy) imports from this registry.
    """

    def __init__(self) -> None:
        self._refs: dict[str, ReferenceDefinition] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load the canonical reference definitions."""
        for ref_data in _USER_REFS:
            ref = ReferenceDefinition(
                key=ref_data["key"],
                ref_type=ReferenceType.USER,
                vault_attribute=ref_data["vault_attribute"],
                sensitivity=ReferenceSensitivity(ref_data["sensitivity"]),
                display_name=ref_data.get("display_name", ""),
            )
            self._refs[ref.key] = ref

        for ref_data in _DOC_REFS:
            ref = ReferenceDefinition(
                key=ref_data["key"],
                ref_type=ReferenceType.DOCUMENT,
                vault_attribute=ref_data["vault_attribute"],
                sensitivity=ReferenceSensitivity(ref_data["sensitivity"]),
                display_name=ref_data.get("display_name", ""),
            )
            self._refs[ref.key] = ref

    def validate(self, binding: str) -> bool:
        """Check if a binding string is a valid reference."""
        return binding in self._refs

    def get(self, key: str) -> ReferenceDefinition | None:
        """Get a reference definition by key."""
        return self._refs.get(key)

    def get_user_refs(self, visible_only: bool = True) -> dict[str, str]:
        """Get all USER.* references as {key: display_name}.

        Args:
            visible_only: If True, exclude references not visible to LLM.
        """
        result = {}
        for key, ref in self._refs.items():
            if ref.ref_type != ReferenceType.USER:
                continue
            if visible_only and not ref.llm_visible:
                continue
            result[key] = ref.display_name
        return result

    def get_doc_refs(self) -> dict[str, str]:
        """Get all DOCUMENT.* references as {key: display_name}."""
        return {
            key: ref.display_name
            for key, ref in self._refs.items()
            if ref.ref_type == ReferenceType.DOCUMENT
        }

    def get_all_refs(self, visible_only: bool = True) -> dict[str, str]:
        """Get all references as {key: display_name}."""
        result = {}
        for key, ref in self._refs.items():
            if visible_only and not ref.llm_visible:
                continue
            result[key] = ref.display_name
        return result

    def get_vault_attribute(self, key: str) -> str | None:
        """Get the vault attribute name for a reference key."""
        ref = self._refs.get(key)
        return ref.vault_attribute if ref else None

    def get_sensitivity(self, key: str) -> ReferenceSensitivity:
        """Get the sensitivity level for a reference."""
        ref = self._refs.get(key)
        return ref.sensitivity if ref else ReferenceSensitivity.INTERNAL

    def is_sensitive(self, key: str) -> bool:
        """Check if a reference is sensitive or secret."""
        return self.get_sensitivity(key) in (
            ReferenceSensitivity.SENSITIVE,
            ReferenceSensitivity.SECRET,
        )

    def get_confirmation_policy(self, key: str) -> str:
        """Get the confirmation policy for a reference."""
        ref = self._refs.get(key)
        return ref.confirmation_policy if ref else "none"

    def add_reference(self, ref: ReferenceDefinition) -> None:
        """Add a custom reference (for extensions)."""
        self._refs[ref.key] = ref

    def list_keys(self) -> list[str]:
        """List all reference keys."""
        return sorted(self._refs.keys())

    def __len__(self) -> int:
        return len(self._refs)

    def __contains__(self, key: str) -> bool:
        return key in self._refs


# Module-level singleton for convenience
_registry: ReferenceRegistry | None = None


def get_registry() -> ReferenceRegistry:
    """Get the global reference registry singleton."""
    global _registry
    if _registry is None:
        _registry = ReferenceRegistry()
    return _registry
