"""Vault manager — load/save user vault and document registry."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.vault.resolver import DocumentRef, DocumentRegistry, UserVault

logger = logging.getLogger(__name__)


class VaultManager:
    """Manages loading and saving of UserVault and DocumentRegistry.

    Vault data is stored as JSON files in a configurable directory.
    Sensitive values are stored locally — never sent to the LLM.
    """

    def __init__(self, vault_dir: str | Path = "data/vault") -> None:
        self.vault_dir = Path(vault_dir)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._vault: UserVault | None = None
        self._registry: DocumentRegistry | None = None

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

    def load_vault(self) -> UserVault:
        """Load user vault from JSON file."""
        vault_path = self.vault_dir / "user_vault.json"
        if vault_path.exists():
            try:
                data = json.loads(vault_path.read_text(encoding="utf-8"))
                self._vault = UserVault(**data)
                logger.info("Loaded user vault from %s", vault_path)
                return self._vault
            except Exception as e:
                logger.warning("Failed to load vault from %s: %s", vault_path, e)

        # Return empty vault
        self._vault = UserVault()
        return self._vault

    def save_vault(self, vault: UserVault | None = None) -> None:
        """Save user vault to JSON file."""
        vault = vault or self.vault
        vault_path = self.vault_dir / "user_vault.json"
        vault_path.write_text(
            vault.model_dump_json(indent=2),
            encoding="utf-8",
        )
        self._vault = vault
        logger.info("Saved user vault to %s", vault_path)

    def load_registry(self) -> DocumentRegistry:
        """Load document registry from JSON file."""
        registry_path = self.vault_dir / "documents.json"
        registry = DocumentRegistry()

        if registry_path.exists():
            try:
                data = json.loads(registry_path.read_text(encoding="utf-8"))
                for doc_data in data.get("documents", []):
                    registry.register(DocumentRef(**doc_data))
                logger.info("Loaded %d documents from %s", len(registry.list_documents()), registry_path)
            except Exception as e:
                logger.warning("Failed to load registry from %s: %s", registry_path, e)

        self._registry = registry
        return registry

    def save_registry(self, registry: DocumentRegistry | None = None) -> None:
        """Save document registry to JSON file."""
        registry = registry or self.registry
        registry_path = self.vault_dir / "documents.json"
        data = {
            "documents": [doc.model_dump() for doc in registry.list_documents()]
        }
        registry_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        self._registry = registry
        logger.info("Saved document registry to %s", registry_path)

    def register_document(self, doc: DocumentRef) -> None:
        """Register a document and save."""
        self.registry.register(doc)
        self.save_registry()

    def create_sample_vault(self) -> UserVault:
        """Create a sample vault with realistic Indian government form data."""
        vault = UserVault(
            full_name="Rajesh Kumar Sharma",
            first_name="Rajesh",
            last_name="Sharma",
            date_of_birth="15/08/1990",
            gender="Male",
            nationality="Indian",
            mobile="9876543210",
            email="rajesh.sharma@example.gov.in",
            address="123, MG Road, Near Central Library",
            state="Karnataka",
            district="Bangalore Urban",
            block="Bangalore North",
            pincode="560001",
            aadhaar_number="1234-5678-9012",
            aadhaar_name="Rajesh Kumar Sharma",
            pan_number="ABCTS1234K",
            voter_id="ABC1234567",
            education="Graduate",
            degree="B.Sc Computer Science",
            institution="Bangalore University",
            occupation="Software Engineer",
            employer="Tech Solutions Pvt Ltd",
            annual_income="600000",
            bank_name="State Bank of India",
            account_number="12345678901",
            ifsc_code="SBIN0001234",
            category="General",
            religion="Hindu",
            marital_status="Single",
        )
        self._vault = vault
        self.save_vault(vault)
        return vault
