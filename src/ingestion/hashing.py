"""SHA256 content hashing for media identity (ADR-001)."""

import hashlib


def compute_sha256(file_bytes: bytes) -> str:
    """Return the SHA256 hex digest of the given bytes."""
    return hashlib.sha256(file_bytes).hexdigest()
