"""Tests for vault encryption formats (audit C9) and document policy roots (audit C8).

Vault:
- Current format: VLT1 magic + salt + Fernet token; roundtrips
- Legacy unsalted format still readable, upgraded on next save
- No passphrase → plaintext fallback

DocumentPolicy:
- allowed_roots confinement actually blocks files outside roots
- empty roots disables confinement
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.manager import VaultManager, _MAGIC, _derive_fernet_key_legacy
from app.policy.document_policy import DocumentPolicy


class TestVaultEncryptionFormats:
    def _vault(self, tmp_path, key=None):
        return VaultManager(vault_dir=tmp_path, encryption_key=key)

    def test_roundtrip_encrypted(self, tmp_path):
        from app.vault.resolver import UserVault
        mgr = self._vault(tmp_path, key="correct horse battery staple")
        v = UserVault(full_name="Test User", aadhaar_number="1234 5678 9012")
        mgr.save_vault(v)

        raw = (tmp_path / "user_vault.json").read_bytes()
        assert raw[:4] == _MAGIC  # current scrypt+salted format

        mgr2 = self._vault(tmp_path, key="correct horse battery staple")
        loaded = mgr2.load_vault()
        assert loaded.full_name == "Test User"
        assert loaded.aadhaar_number == "1234 5678 9012"

    def test_wrong_passphrase_fails_to_decrypt(self, tmp_path):
        from cryptography.fernet import InvalidToken
        from app.vault.resolver import UserVault
        mgr = self._vault(tmp_path, key="right-key")
        mgr.save_vault(UserVault(full_name="Secret"))

        mgr2 = self._vault(tmp_path, key="wrong-key")
        # Load failure falls back to an empty vault rather than crashing
        loaded = mgr2.load_vault()
        assert loaded.full_name == ""

    def test_legacy_unsaltered_format_still_readable(self, tmp_path):
        from cryptography.fernet import Fernet
        from app.vault.resolver import UserVault

        fernet = Fernet(_derive_fernet_key_legacy("old-key"))
        token = fernet.encrypt(b'{"full_name": "Legacy User"}')
        (tmp_path / "user_vault.json").write_bytes(token)

        mgr = self._vault(tmp_path, key="old-key")
        loaded = mgr.load_vault()
        assert loaded.full_name == "Legacy User"

    def test_plaintext_without_key(self, tmp_path):
        from app.vault.resolver import UserVault
        mgr = self._vault(tmp_path, key=None)
        mgr.save_vault(UserVault(full_name="Plain"))
        assert (tmp_path / "user_vault.json").read_bytes().startswith(b"{")
        assert self._vault(tmp_path).load_vault().full_name == "Plain"


class TestDocumentPolicyRoots:
    def _file_under(self, root: Path, name: str = "doc.pdf") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        p = root / name
        p.write_bytes(b"%PDF-1.4 fake")
        return p

    def test_file_inside_allowed_root_passes_confinement(self, tmp_path):
        root = tmp_path / "docs"
        f = self._file_under(root)
        policy = DocumentPolicy(allowed_roots=[root])
        result = policy.validate_upload(str(f), "aadhaar")
        assert result.allowed is True

    def test_file_outside_allowed_root_blocked(self, tmp_path):
        outside = tmp_path / "elsewhere"
        f = self._file_under(outside)
        policy = DocumentPolicy(allowed_roots=[tmp_path / "docs"])
        result = policy.validate_upload(str(f), "aadhaar")
        assert result.allowed is False
        assert "allowed directories" in result.reason

    def test_empty_roots_disable_confinement(self, tmp_path):
        outside = tmp_path / "anywhere"
        f = self._file_under(outside)
        policy = DocumentPolicy()  # no roots configured
        assert policy.validate_upload(str(f), "aadhaar").allowed is True

    def test_magic_bytes_still_enforced_with_roots(self, tmp_path):
        root = tmp_path / "docs"
        root.mkdir(parents=True, exist_ok=True)
        fake_pdf = root / "payload.pdf"
        fake_pdf.write_bytes(b"MZ\x90\x00 this is not a pdf")
        policy = DocumentPolicy(allowed_roots=[root])
        result = policy.validate_upload(str(fake_pdf), "aadhaar")
        assert result.allowed is False
        assert "magic bytes" in result.reason or "renamed" in result.reason
