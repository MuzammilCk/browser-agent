"""Vault API — the way user data gets into the system (audit Z3).

Before this module there was no route, CLI, or onboarding path to
populate ``data/vault/user_vault.json``: every ``value_ref`` fill
resolved to None and runs stalled or failed with "No value provided".

Endpoints:
    GET  /api/vault — which fields are populated; NEVER their values.
    POST /api/vault — partial update of the vault (unknown fields are
                      rejected so typos fail loudly), persisted via
                      VaultManager so at-rest encryption settings apply.

Responses only ever contain field NAMES. Sensitive values go to disk
and stay there.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.routes import _require_api_token
from app.config.settings import get_settings
from app.vault.manager import VaultManager
from app.vault.resolver import UserVault

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["vault"],
    dependencies=[Depends(_require_api_token)],
)


class VaultUpdate(BaseModel):
    """Partial vault update.

    Every field is optional; supplied fields overwrite stored values.
    Unknown fields are forbidden so a mistyped field name fails loudly
    instead of silently doing nothing.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    nationality: str | None = None
    age: str | None = None
    mobile: str | None = None
    email: str | None = None
    address: str | None = None
    permanent_address: str | None = None
    state: str | None = None
    district: str | None = None
    block: str | None = None
    village: str | None = None
    pincode: str | None = None
    aadhaar_number: str | None = None
    aadhaar_name: str | None = None
    pan_number: str | None = None
    voter_id: str | None = None
    education: str | None = None
    degree: str | None = None
    institution: str | None = None
    occupation: str | None = None
    employer: str | None = None
    annual_income: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    father_name: str | None = None
    mother_name: str | None = None
    spouse_name: str | None = None
    guardian_name: str | None = None
    category: str | None = None
    religion: str | None = None
    marital_status: str | None = None


class VaultSummary(BaseModel):
    """Public view of the vault state — field names only, never values."""

    fields_filled: list[str]
    fields_empty: list[str]
    encrypted_at_rest: bool


def _get_vault_manager() -> VaultManager:
    settings = get_settings()
    return VaultManager(
        settings.data_dir / "vault",
        encryption_key=settings.vault_encryption_key,
    )


def _summarize(vault: UserVault) -> VaultSummary:
    manager = _get_vault_manager()
    data = vault.model_dump()
    return VaultSummary(
        fields_filled=sorted(k for k, v in data.items() if bool(v)),
        fields_empty=sorted(k for k, v in data.items() if not v),
        encrypted_at_rest=bool(manager._fernet),
    )


@router.get("/vault", response_model=VaultSummary)
async def get_vault_summary() -> VaultSummary:
    """Report which vault fields are populated. Values are never returned."""
    manager = _get_vault_manager()
    return _summarize(manager.vault)


@router.post("/vault", response_model=VaultSummary)
async def update_vault(update: VaultUpdate) -> VaultSummary:
    """Apply a partial vault update and persist it (encrypted when a
    passphrase is configured). Responds with field names only."""
    provided = update.model_dump(exclude_none=True)
    if not provided:
        logger.info("Vault POST with no fields — no changes made")

    manager = _get_vault_manager()
    vault = manager.vault
    for field, value in provided.items():
        setattr(vault, field, value)
    manager.save_vault(vault)
    logger.info("Vault updated (%d fields supplied)", len(provided))
    return _summarize(vault)
