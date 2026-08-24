"""Sensitive field classification.

Per SAFETY.md and context.md:
- R2 (sensitive) fields require stronger validation
- Government IDs, financial data, health info are sensitive
- The LLM should NOT receive raw sensitive values
"""

from __future__ import annotations

from enum import Enum


class SensitivityLevel(str, Enum):
    """Field sensitivity classification."""

    PUBLIC = "public"        # Safe to send to LLM (e.g., state, gender)
    INTERNAL = "internal"    # Used internally only (e.g., internal IDs)
    SENSITIVE = "sensitive"  # Government IDs, financial (e.g., Aadhaar, PAN)
    SECRET = "secret"        # Never expose (e.g., passwords, OTP)


# Sensitivity classification for all USER fields
FIELD_SENSITIVITY: dict[str, SensitivityLevel] = {
    # Identity — mostly public but some sensitive
    "full_name": SensitivityLevel.PUBLIC,
    "first_name": SensitivityLevel.PUBLIC,
    "last_name": SensitivityLevel.PUBLIC,
    "date_of_birth": SensitivityLevel.SENSITIVE,  # Identity verification
    "gender": SensitivityLevel.PUBLIC,
    "nationality": SensitivityLevel.PUBLIC,
    "age": SensitivityLevel.PUBLIC,

    # Contact
    "mobile": SensitivityLevel.SENSITIVE,  # PII
    "email": SensitivityLevel.INTERNAL,

    # Address
    "address": SensitivityLevel.INTERNAL,
    "permanent_address": SensitivityLevel.INTERNAL,
    "state": SensitivityLevel.PUBLIC,
    "district": SensitivityLevel.PUBLIC,
    "block": SensitivityLevel.PUBLIC,
    "pincode": SensitivityLevel.PUBLIC,
    "village": SensitivityLevel.PUBLIC,

    # Government IDs — always sensitive
    "aadhaar_number": SensitivityLevel.SENSITIVE,  # Government ID
    "aadhaar_name": SensitivityLevel.PUBLIC,  # Name as per Aadhaar (not the number)
    "pan_number": SensitivityLevel.SENSITIVE,  # Financial ID
    "voter_id": SensitivityLevel.SENSITIVE,  # Government ID

    # Education — mostly public
    "education": SensitivityLevel.PUBLIC,
    "degree": SensitivityLevel.PUBLIC,
    "institution": SensitivityLevel.PUBLIC,

    # Employment
    "occupation": SensitivityLevel.PUBLIC,
    "employer": SensitivityLevel.INTERNAL,
    "annual_income": SensitivityLevel.SENSITIVE,  # Financial

    # Financial — sensitive
    "bank_name": SensitivityLevel.INTERNAL,
    "account_number": SensitivityLevel.SENSITIVE,  # Financial
    "ifsc_code": SensitivityLevel.INTERNAL,

    # Family
    "father_name": SensitivityLevel.PUBLIC,
    "mother_name": SensitivityLevel.PUBLIC,
    "spouse_name": SensitivityLevel.PUBLIC,
    "guardian_name": SensitivityLevel.PUBLIC,

    # Category
    "category": SensitivityLevel.PUBLIC,
    "religion": SensitivityLevel.PUBLIC,
    "marital_status": SensitivityLevel.PUBLIC,
}


def get_field_sensitivity(field_name: str) -> SensitivityLevel:
    """Get the sensitivity level for a field."""
    return FIELD_SENSITIVITY.get(field_name, SensitivityLevel.INTERNAL)


def is_sensitive(field_name: str) -> bool:
    """Check if a field is sensitive or secret."""
    level = get_field_sensitivity(field_name)
    return level in (SensitivityLevel.SENSITIVE, SensitivityLevel.SECRET)


def get_safe_fields() -> list[str]:
    """Get fields safe to send to LLM (public only)."""
    return [k for k, v in FIELD_SENSITIVITY.items() if v == SensitivityLevel.PUBLIC]


def get_sensitive_fields() -> list[str]:
    """Get all sensitive/secret fields."""
    return [k for k, v in FIELD_SENSITIVITY.items() if v in (SensitivityLevel.SENSITIVE, SensitivityLevel.SECRET)]
