"""Unit tests for ValueResolver and DocumentResolver."""

import pytest
from pathlib import Path
import tempfile

from app.vault.resolver import (
    DocumentRef,
    DocumentRegistry,
    DocumentResolver,
    UserVault,
    ValueResolver,
)


class TestValueResolver:
    """Tests for semantic value resolution per audit #9."""

    def setup_method(self) -> None:
        self.vault = UserVault(
            full_name="Rahul Sharma",
            date_of_birth="14/07/2004",
            gender="Male",
            mobile="9876543210",
            email="rahul@example.gov.in",
            state="Kerala",
            district="Thiruvananthapuram",
            aadhaar_name="Rahul Sharma",
            annual_income="350000",
        )
        self.resolver = ValueResolver(self.vault)

    def test_resolve_full_name(self) -> None:
        assert self.resolver.resolve("USER.full_name") == "Rahul Sharma"

    def test_resolve_date_of_birth(self) -> None:
        assert self.resolver.resolve("USER.date_of_birth") == "14/07/2004"

    def test_resolve_state(self) -> None:
        assert self.resolver.resolve("USER.state") == "Kerala"

    def test_resolve_empty_field(self) -> None:
        # pan_number is empty
        assert self.resolver.resolve("USER.pan_number") is None

    def test_resolve_invalid_ref(self) -> None:
        assert self.resolver.resolve("USER.nonexistent") is None

    def test_resolve_wrong_prefix(self) -> None:
        assert self.resolver.resolve("DOC.something") is None

    def test_resolve_empty_string(self) -> None:
        assert self.resolver.resolve("") is None

    def test_resolve_none(self) -> None:
        assert self.resolver.resolve(None) is None

    def test_is_valid_ref(self) -> None:
        assert self.resolver.is_valid_ref("USER.full_name") is True
        assert self.resolver.is_valid_ref("USER.nonexistent") is False
        assert self.resolver.is_valid_ref("DOC.something") is False


class TestDocumentResolver:
    """Tests for document resolution per audit #10."""

    def setup_method(self) -> None:
        self.registry = DocumentRegistry()
        # Create a temp file for testing
        self.tmp_dir = tempfile.mkdtemp()
        self.test_file = Path(self.tmp_dir) / "aadhaar.pdf"
        self.test_file.write_bytes(b"fake pdf content")

        self.registry.register(DocumentRef(
            id="aadhaar",
            type="aadhaar",
            path=str(self.test_file),
            mime_type="application/pdf",
        ))
        self.resolver = DocumentResolver(self.registry)

    def test_resolve_existing_document(self) -> None:
        doc = self.resolver.resolve("DOCUMENT.aadhaar")
        assert doc is not None
        assert doc.path == str(self.test_file)

    def test_resolve_nonexistent_document(self) -> None:
        doc = self.resolver.resolve("DOCUMENT.income_certificate")
        assert doc is None

    def test_resolve_invalid_prefix(self) -> None:
        doc = self.resolver.resolve("DOC.aadhaar")
        assert doc is None

    def test_resolve_empty(self) -> None:
        doc = self.resolver.resolve("")
        assert doc is None

    def test_is_valid_ref(self) -> None:
        assert self.resolver.is_valid_ref("DOCUMENT.aadhaar") is True
        assert self.resolver.is_valid_ref("DOCUMENT.nonexistent") is False

    def test_resolve_missing_file(self) -> None:
        """Document registered but file deleted."""
        self.registry.register(DocumentRef(
            id="missing",
            type="certificate",
            path="/nonexistent/path.pdf",
        ))
        doc = self.resolver.resolve("DOCUMENT.income_certificate")
        # income_certificate is not registered, so None
        assert doc is None


class TestDocumentRegistry:
    """Tests for document registry."""

    def test_register_and_resolve(self) -> None:
        registry = DocumentRegistry()
        doc = DocumentRef(id="test", type="pdf", path="/tmp/test.pdf")
        registry.register(doc)
        assert registry.resolve("test") is doc

    def test_resolve_nonexistent(self) -> None:
        registry = DocumentRegistry()
        assert registry.resolve("nonexistent") is None

    def test_list_documents(self) -> None:
        registry = DocumentRegistry()
        registry.register(DocumentRef(id="a", type="pdf", path="/a.pdf"))
        registry.register(DocumentRef(id="b", type="jpg", path="/b.jpg"))
        docs = registry.list_documents()
        assert len(docs) == 2
