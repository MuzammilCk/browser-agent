"""Vault manager — load/save user vault and document registry.

Audit B6 fix: vault data is now encrypted at rest using Fernet symmetric
encryption. The encryption key is derived from the VAULT_ENCRYPTION_KEY
environment variable. If no key is provided, falls back to plaintext JSON
with a logged warning (for development/testing only).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.vault.resolver import DocumentRef, DocumentRegistry, UserVault

logger = logging.getLogger(__name__)


def _derive_fernet_key(passphrase: str) -> bytes:
    """Derive a Fernet-compatible 32-byte key from a passphrase using SHA-256."""
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class VaultManager:
    """Manages loading and saving of UserVault and DocumentRegistry.

    Audit B6 fix: vault data is encrypted at rest when VAULT_ENCRYPTION_KEY
    is set. Sensitive values (Aadhaar, PAN, bank details) are protected
    against unauthorized filesystem access.

    Without a key, falls back to plaintext with a warning (dev/test only).
    """

    def __init__(self, vault_dir: str | Path = "data/vault") -> None:
        self.vault_dir = Path(vault_dir)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._vault: UserVault | None = None
        self._registry: DocumentRegistry | None = None
        self._fernet: Any = None  # Fernet instance if encryption is enabled
        self._init_encryption()

    def _init_encryption(self) -> None:
        """Initialize Fernet encryption if VAULT_ENCRYPTION_KEY is set."""
        key = os.environ.get("VAULT_ENCRYPTION_KEY", "")
        if key:
            try:
                from cryptography.fernet import Fernet
                derived = _derive_fernet_key(key)
                self._fernet = Fernet(derived)
                logger.info("Vault encryption enabled (Fernet)")
            except ImportError:
                logger.warning(
                    "cryptography package not installed; vault will be stored as plaintext. "
                    "Install with: pip install cryptography"
                )
            except Exception as e:
                logger.warning("Failed to initialize vault encryption: %s", e)
        else:
            logger.warning(
                "VAULT_ENCRYPTION_KEY not set — vault stored as plaintext. "
                "Set this env var to enable encryption at rest for sensitive data."
            )

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
        """Encrypt data if Fernet is available."""
        if self._fernet:
            return self._fernet.encrypt(plaintext.encode("utf-8"))
        return plaintext.encode("utf-8")

    def _decrypt(self, data: bytes) -> str:
        """Decrypt data if Fernet is available."""
        if self._fernet:
            return self._fernet.decrypt(data).decode("utf-8")
        return data.decode("utf-8")

    def _is_encrypted(self, data: bytes) -> bool:
        """Check if data is Fernet-encrypted (starts with 'gAAAAA')."""
        return data[:6] == b"gAAAAA"

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
        """Save user vault to file (encrypted if VAULT_ENCRYPTION_KEY is set)."""
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
