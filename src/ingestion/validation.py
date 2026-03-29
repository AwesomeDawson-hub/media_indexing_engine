"""File validation: format whitelist and size limits."""

from dataclasses import dataclass

from src.config import settings

# Magic bytes for supported image formats
_MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP — we check the WEBP part separately
    "image/tiff": [b"II\x2a\x00", b"MM\x00\x2a"],
    "image/bmp": [b"BM"],
    "image/avif": [b"ftyp"],  # ISOBMFF — ftyp at offset 4, brand check below
}


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None


def detect_mime_type(file_bytes: bytes) -> str | None:
    """Detect MIME type from file content using magic bytes."""
    # Check AVIF first (ftyp at offset 4, brand at offset 8)
    if len(file_bytes) >= 12 and file_bytes[4:8] == b"ftyp":
        brand = file_bytes[8:12]
        if brand in (b"avif", b"avis", b"mif1"):
            return "image/avif"

    for mime, signatures in _MAGIC_SIGNATURES.items():
        if mime == "image/avif":
            continue  # Already handled above
        for sig in signatures:
            if file_bytes[:len(sig)] == sig:
                # Extra check for WebP: RIFF header must contain WEBP at offset 8
                if mime == "image/webp" and file_bytes[8:12] != b"WEBP":
                    continue
                return mime
    return None


def validate_file(filename: str, file_bytes: bytes) -> ValidationResult:
    """Validate file format and size against configured limits.

    Checks MIME type from file content (not extension) and file size.
    """
    # Check size
    if len(file_bytes) > settings.upload.max_file_size_bytes:
        max_mb = settings.upload.max_file_size_mb
        actual_mb = len(file_bytes) / (1024 * 1024)
        return ValidationResult(
            valid=False,
            error=f"File exceeds maximum size of {max_mb} MB ({actual_mb:.1f} MB)",
        )

    # Check empty
    if len(file_bytes) == 0:
        return ValidationResult(valid=False, error="File is empty")

    # Detect and check MIME type
    mime_type = detect_mime_type(file_bytes)
    if mime_type is None or mime_type not in settings.upload.allowed_mime_types:
        return ValidationResult(
            valid=False,
            error=f"Unsupported file format. Allowed: JPEG, PNG, WebP, TIFF, BMP, GIF, AVIF",
        )

    return ValidationResult(valid=True)
