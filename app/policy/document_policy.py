"""Document policy — validates uploads before execution.

Per audit #19:
- Allowed file types
- File size limits
- MIME type validation (audit B7 fix: magic bytes enforcement)
- Document category matching
- Path safety (no arbitrary filesystem paths)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# Document policy configuration
# ============================================================

# Allowed file extensions per document type
ALLOWED_EXTENSIONS: dict[str, list[str]] = {
    "aadhaar": [".pdf", ".jpg", ".jpeg", ".png"],
    "income_certificate": [".pdf"],
    "degree_certificate": [".pdf"],
    "photo": [".jpg", ".jpeg", ".png"],
    "signature": [".jpg", ".jpeg", ".png"],
    "voter_id_doc": [".pdf", ".jpg", ".jpeg", ".png"],
    "pan_card": [".pdf", ".jpg", ".jpeg", ".png"],
}

# Max file size in bytes (default 5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Max file size per document type (overrides default)
MAX_FILE_SIZES: dict[str, int] = {
    "photo": 2 * 1024 * 1024,      # 2MB for photos
    "signature": 1 * 1024 * 1024,  # 1MB for signature
}

# Sentinel returned when an extension has registered signatures but the
# file header matches none of them — i.e. the content contradicts the
# declared type (classic renamed-file spoof).
MISMATCH = "__mismatch__"

# Audit B7: Magic byte signatures for MIME validation
# Maps file extension → (magic_bytes_prefix, mime_type)
MAGIC_BYTES: dict[str, list[tuple[bytes, str]]] = {
    ".pdf": [(b"%PDF", "application/pdf")],
    ".jpg": [
        (b"\xff\xd8\xff\xe0", "image/jpeg"),  # JFIF
        (b"\xff\xd8\xff\xe1", "image/jpeg"),  # EXIF
        (b"\xff\xd8\xff\xdb", "image/jpeg"),  # Raw JPEG
        (b"\xff\xd8\xff", "image/jpeg"),      # Generic JPEG SOI+marker
    ],
    ".jpeg": [
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"\xff\xd8\xff\xe1", "image/jpeg"),
        (b"\xff\xd8\xff\xdb", "image/jpeg"),
        (b"\xff\xd8\xff", "image/jpeg"),
    ],
    ".png": [(b"\x89PNG\r\n\x1a\n", "image/png")],
}

# Allowed MIME types per document type
ALLOWED_MIMES: dict[str, list[str]] = {
    "aadhaar": ["application/pdf", "image/jpeg", "image/png"],
    "income_certificate": ["application/pdf"],
    "degree_certificate": ["application/pdf"],
    "photo": ["image/jpeg", "image/png"],
    "signature": ["image/jpeg", "image/png"],
    "voter_id_doc": ["application/pdf", "image/jpeg", "image/png"],
    "pan_card": ["application/pdf", "image/jpeg", "image/png"],
}


class DocumentPolicyResult:
    """Result of a document policy check."""

    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        file_type: str = "",
        file_size: int = 0,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.file_type = file_type
        self.file_size = file_size

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def __repr__(self) -> str:
        return f"DocumentPolicyResult(allowed={self.allowed}, reason='{self.reason}')"


class DocumentPolicy:
    """Validates document uploads against policy.

    Per audit #19: file type, size, MIME, path safety.
    """

    def __init__(
        self,
        allowed_extensions: dict[str, list[str]] | None = None,
        allowed_mimes: dict[str, list[str]] | None = None,
        magic_bytes: dict[str, list[tuple[bytes, str]]] | None = None,
        max_file_size: int = MAX_FILE_SIZE,
        max_file_sizes: dict[str, int] | None = None,
        allowed_roots: list[Path] | None = None,
    ) -> None:
        self.allowed_extensions = allowed_extensions or ALLOWED_EXTENSIONS
        self.allowed_mimes = allowed_mimes or ALLOWED_MIMES
        self.magic_bytes = magic_bytes or MAGIC_BYTES
        self.max_file_size = max_file_size
        self.max_file_sizes = max_file_sizes or MAX_FILE_SIZES
        # Audit C8: real path confinement. When roots are configured,
        # uploads must resolve inside one of them; empty list disables
        # confinement (documents may come from anywhere the user registered).
        self.allowed_roots = [Path(r).resolve() for r in (allowed_roots or [])]

    def _detect_mime_by_magic_bytes(self, file_path: Path) -> str | None:
        """Detect MIME type by reading file header magic bytes.

        Audit B7 fix: actual content-based validation instead of
        relying solely on file extension (which is spoofable).

        Returns:
            - the detected MIME string on match
            - None if the extension has no registered signatures
              (cannot validate — other checks still apply)
            - MISMATCH sentinel when signatures exist for this extension
              but none matched (declared type contradicts content —
              treated as a renamed/spoofed file)
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
        except OSError:
            return MISMATCH

        ext = file_path.suffix.lower()
        signatures = self.magic_bytes.get(ext, [])
        if not signatures:
            return None  # unknown extension type — nothing to compare
        for prefix, mime in signatures:
            if header[:len(prefix)] == prefix:
                return mime
        return MISMATCH

    def validate_upload(
        self,
        file_path: str,
        document_type: str,
    ) -> DocumentPolicyResult:
        """Validate a document upload against policy.

        Args:
            file_path: Path to the file to upload
            document_type: Document type (e.g., 'aadhaar', 'photo')

        Returns:
            DocumentPolicyResult with validation outcome
        """
        path = Path(file_path)

        # Check file exists
        if not path.exists():
            return DocumentPolicyResult(
                allowed=False,
                reason=f"File does not exist: {file_path}",
            )

        # Check file extension
        ext = path.suffix.lower()
        allowed_exts = self.allowed_extensions.get(document_type, [])
        if allowed_exts and ext not in allowed_exts:
            return DocumentPolicyResult(
                allowed=False,
                reason=f"File type '{ext}' not allowed for {document_type}. "
                       f"Allowed: {', '.join(allowed_exts)}",
                file_type=ext,
            )

        # Audit B7: Validate MIME type via magic bytes (not just extension)
        detected_mime = self._detect_mime_by_magic_bytes(path)
        if detected_mime == MISMATCH:
            return DocumentPolicyResult(
                allowed=False,
                reason=f"File content does not match its '{ext}' extension "
                       f"— file may have been renamed from a different type.",
                file_type=ext,
            )
        if detected_mime is not None:
            allowed_mimes = self.allowed_mimes.get(document_type, [])
            if allowed_mimes and detected_mime not in allowed_mimes:
                return DocumentPolicyResult(
                    allowed=False,
                    reason=f"File content is {detected_mime} (by magic bytes), "
                           f"but {document_type} requires: {', '.join(allowed_mimes)}. "
                           f"File may have been renamed from a different type.",
                    file_type=ext,
                )

        # Check file size
        try:
            file_size = path.stat().st_size
        except OSError as e:
            return DocumentPolicyResult(
                allowed=False,
                reason=f"Could not read file size: {e}",
            )

        max_size = self.max_file_sizes.get(document_type, self.max_file_size)
        if file_size > max_size:
            max_mb = max_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            return DocumentPolicyResult(
                allowed=False,
                reason=f"File too large: {actual_mb:.1f}MB exceeds limit of {max_mb:.1f}MB "
                       f"for {document_type}",
                file_size=file_size,
            )

        # Audit C8: enforce configured allowed roots (the previous check
        # compared a path against its own parent — always true, never fired).
        if self.allowed_roots:
            try:
                resolved = path.resolve()
                if not any(
                    resolved.is_relative_to(root) for root in self.allowed_roots
                ):
                    return DocumentPolicyResult(
                        allowed=False,
                        reason="File path resolves outside the configured "
                               "allowed directories for uploads",
                    )
            except OSError as e:
                return DocumentPolicyResult(
                    allowed=False,
                    reason=f"Could not resolve file path: {e}",
                )

        return DocumentPolicyResult(
            allowed=True,
            reason="Document policy check passed",
            file_type=ext,
            file_size=file_size,
        )
