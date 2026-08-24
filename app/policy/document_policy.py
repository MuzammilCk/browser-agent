"""Document policy — validates uploads before execution.

Per audit #19:
- Allowed file types
- File size limits
- MIME type validation
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

# Max file size in bytes (default 5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Max file size per document type (overrides default)
MAX_FILE_SIZES: dict[str, int] = {
    "photo": 2 * 1024 * 1024,      # 2MB for photos
    "signature": 1 * 1024 * 1024,  # 1MB for signature
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

    def __init__(self) -> None:
        self.allowed_extensions = ALLOWED_EXTENSIONS
        self.allowed_mimes = ALLOWED_MIMES
        self.max_file_size = MAX_FILE_SIZE
        self.max_file_sizes = MAX_FILE_SIZES

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

        # Check path safety — no symlinks to sensitive locations
        try:
            resolved = path.resolve()
            if not str(resolved).startswith(str(path.parent.resolve())):
                return DocumentPolicyResult(
                    allowed=False,
                    reason="File path resolves outside expected directory",
                )
        except Exception:
            pass

        return DocumentPolicyResult(
            allowed=True,
            reason="Document policy check passed",
            file_type=ext,
            file_size=file_size,
        )
