"""Vault manager — load/save user vault and document registry.

Audit B6 fix: vault data is encrypted at rest using Fernet symmetric
encryption. The encryption key is derived from a passphrase via salted
scrypt (audit C9). If no key is provided, falls back to plaintext JSON
with a logged warning (for development/testing only).

On-disk formats:
    Encrypted (current):  b"VLT1" + 16-byte salt + Fernet token
    Encrypted (legacy):   raw Fernet token starting with b"gAAAAA"
                          (readable for backward compatibility; re-saved
                          in current format on next save)
    Plaintext:            raw UTF-8 JSON
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from app.vault.resolver import DocumentRef, DocumentRegistry, UserVault

logger = logging.getLogger(__name__)

# Current encrypted-file header: magic + salt length + salt
_MAGIC = b"VLT1"
_SALT_LEN = 16
# scrypt parameters (moderate: ~64MB memory, well within OWASP guidance)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def _derive_fernet_key_scrypt(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible 32-byte key from passphrase + salt via scrypt."""
    digest = hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return base64.urlsafe_b64encode(digest)


def _derive_fernet_key_legacy(passphrase: str) -> bytes:
    """Legacy derivation (unsalted SHA-256) — only for reading old files."""
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class VaultManager:
    """Manages loading and saving of UserVault and DocumentRegistry.

    Audit B6 fix: vault data is encrypted at rest when an encryption
    passphrase is provided. Sensitive values (Aadhaar, PAN, bank details)
    are protected against unauthorized filesystem access.

    The passphrase is taken from (in order):
      1. The explicit ``encryption_key`` constructor argument (preferred —
         pass ``settings.vault_encryption_key`` here so .env works)
      2. The ``VAULT_ENCRYPTION_KEY`` environment variable

    Without a key, falls back to plaintext with a warning (dev/test only).
    """

    def __init__(
        self,
        vault_dir: str | Path = "data/vault",
        encryption_key: str | None = None,
    ) -> None:
        self.vault_dir = Path(vault_dir)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._vault: UserVault | None = None
        self._registry: DocumentRegistry | None = None
        self._fernet: Any = None  # Fernet instance if encryption is enabled
        self._init_encryption(encryption_key)

    def _init_encryption(self, encryption_key: str | None) -> None:
        """Initialize Fernet encryption if a passphrase is available."""
        key = encryption_key or os.environ.get("VAULT_ENCRYPTION_KEY", "")
        if key:
            try:
                from cryptography.fernet import Fernet
                # Instance key materialized lazily per file (salt is stored
                # alongside the data); this placeholder enables encryption mode.
                self._fernet = "enabled"
                self._passphrase = key
                logger.info("Vault encryption enabled (Fernet + scrypt KDF)")
            except ImportError:
                logger.warning(
                    "cryptography package not installed; vault will be stored as plaintext. "
                    "Install with: pip install cryptography"
                )
            except Exception as e:
                logger.warning("Failed to initialize vault encryption: %s", e)
        else:
            logger.warning(
                "No vault encryption passphrase set — vault stored as plaintext. "
                "Set vault_encryption_key (settings) or VAULT_ENCRYPTION_KEY (env) "
                "to enable encryption at rest for sensitive data."
            )

    def _new_fernet(self, salt: bytes) -> Any:
        from cryptography.fernet import Fernet
        return Fernet(_derive_fernet_key_scrypt(self._passphrase, salt))

    @property
    def vault(self) -> UserVault:
        """Get the user vault (lazy-loaded)."""
        if self._vault is None:
            self._vault = self.load_vault()
        return self._vault

    @property
    def registry(self) -> DocumentRegistry:
        """Get the document registry (lazy-loaded)."""
        if self._registry is None:
            self._registry = self.load_registry()
        return self._registry

    def _encrypt(self, plaintext: str) -> bytes:
        """Encrypt data with a freshly generated salt (current format)."""
        if self._fernet:
            salt = secrets.token_bytes(_SALT_LEN)
            token = self._new_fernet(salt).encrypt(plaintext.encode("utf-8"))
            return _MAGIC + salt + token
        return plaintext.encode("utf-8")

    def _decrypt(self, data: bytes) -> str:
        """Decrypt data in any supported format (current, legacy, plaintext)."""
        if self._fernet and data[:4] == _MAGIC:
            salt = data[4:4 + _SALT_LEN]
            token = data[4 + _SALT_LEN:]
            return self._new_fernet(salt).decrypt(token).decode("utf-8")
        if self._fernet and data[:6] == b"gAAAAA":
            # Legacy unsalted format — decryptable, re-saved in new format.
            from cryptography.fernet import Fernet
            fernet = Fernet(_derive_fernet_key_legacy(self._passphrase))
            logger.info("Vault file uses legacy unsalted encryption; will upgrade on next save")
            return fernet.decrypt(data).decode("utf-8")
        return data.decode("utf-8")

    def _is_encrypted(self, data: bytes) -> bool:
        """Check if data is encrypted in either the current or legacy format."""
        return data[:4] == _MAGIC or data[:6] == b"gAAAAA"

    def load_vault(self) -> UserVault:
        """Load user vault from file (encrypted or plaintext)."""
        vault_path = self.vault_dir / "user_vault.json"
        if vault_path.exists():
            try:
                raw = vault_path.read_bytes()
                if self._is_encrypted(raw):
                    decrypted = self._decrypt(raw)
                    data = json.loads(decrypted)
                    logger.info("Loaded encrypted vault from %s", vault_path)
                else:
                    data = json.loads(raw.decode("utf-8"))
                    logger.info("Loaded plaintext vault from %s (consider encrypting)", vault_path)
                self._vault = UserVault(**data)
                return self._vault
            except Exception as e:
                logger.warning("Failed to load vault from %s: %s", vault_path, e)

        # Return empty vault
        self._vault = UserVault()
        return self._vault

    def save_vault(self, vault: UserVault | None = None) -> None:
        """Save user vault to file (encrypted if a passphrase is configured)."""
        vault = vault or self.vault
        vault_path = self.vault_dir / "user_vault.json"
        plaintext = vault.model_dump_json(indent=2)

        if self._fernet:
            encrypted = self._encrypt(plaintext)
            vault_path.write_bytes(encrypted)
            logger.info("Saved encrypted vault to %s", vault_path)
        else:
            vault_path.write_text(plaintext, encoding="utf-8")
            logger.info("Saved plaintext vault to %s (consider encrypting)", vault_path)

        self._vault = vault

    def load_registry(self) -> DocumentRegistry:
        """Load document registry from JSON file."""
        registry_path = self.vault_dir / "documents.json"
        registry = DocumentRegistry()

        if registry_path.exists():
            try:
                raw = registry_path.read_bytes()
                if self._is_encrypted(raw):
                    decrypted = self._decrypt(raw)
                    data = json.loads(decrypted)
                else:
                    data = json.loads(raw.decode("utf-8"))
                for doc_data in data.get("documents", []):
                    registry.register(DocumentRef(**doc_data))
                logger.info("Loaded %d documents from %s", len(registry.list_documents()), registry_path)
            except Exception as e:
                logger.warning("Failed to load registry from %s: %s", registry_path, e)

        self._registry = registry
        return registry

    def save_registry(self, registry: DocumentRegistry | None = None) -> None:
        """Save document registry to JSON file (encrypted if key available)."""
        registry = registry or self.registry
        registry_path = self.vault_dir / "documents.json"
        data = {
            "documents": [doc.model_dump() for doc in registry.list_documents()]
        }
        plaintext = json.dumps(data, indent=2)

        if self._fernet:
            encrypted = self._encrypt(plaintext)
            registry_path.write_bytes(encrypted)
        else:
            registry_path.write_text(plaintext, encoding="utf-8")

        self._registry = registry
        logger.info("Saved document registry to %s", registry_path)

    def register_document(self, doc: DocumentRef) -> None:
        """Register a document and save."""
        self.registry.register(doc)
        self.save_registry()

    def create_sample_vault(self) -> UserVault:
        """Create a sample vault with synthetic test data.

        NOTE: All data below is synthetic/fake — not real Aadhaar/PAN/bank details.
        """
        vault = UserVault(
            full_name="Rajesh Kumar Singh",
            first_name="Rajesh",
            last_name="Singh",
            date_of_birth="15/08/1990",
            gender="Male",
            nationality="Indian",
            age="36",
            mobile="9876543210",
            email="rajesh.singh@example.com",
            address="42, Gandhi Nagar, New Delhi - 110031",
            permanent_address="42, Gandhi Nagar, New Delhi - 110031",
            state="Delhi",
            district="New Delhi",
            block="Central",
            village="",
            pincode="110031",
            # Synthetic IDs — NOT real Aadhaar/PAN numbers
            aadhaar_number="1234 5678 9012",
            aadhaar_name="Rajesh Kumar Singh",
            pan_number="ABCDE1234F",
            voter_id="DL/01/123456",
            education="Bachelor of Technology",
            degree="B.Tech Computer Science",
            institution="Delhi Technological University",
            occupation="Software Engineer",
            employer="Tata Consultancy Services",
            annual_income="1200000",
            # Synthetic financial data
            bank_name="State Bank of India",
            account_number="30123456789",
            ifsc_code="SBIN0001234",
            father_name="Ram Singh",
            mother_name="Sita Singh",
            spouse_name="",
            guardian_name="",
            category="General",
            religion="Hindu",
            marital_status="Married",
        )
        self.save_vault(vault)
        logger.info("Created sample vault with synthetic test data")
        return vault
