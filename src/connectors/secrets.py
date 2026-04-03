"""Encryption helpers for connector credential storage.

Uses Fernet symmetric encryption (from the `cryptography` package, already a
transitive dependency via python-jose[cryptography]).

The encryption key is read from settings.connector.credentials_key, which
must be a URL-safe base64-encoded 32-byte key — exactly what
`cryptography.fernet.Fernet.generate_key()` produces.

All connector create/update/sync paths call `require_encryption_key()` first
and abort with a clear error if the key is not configured.
"""

from __future__ import annotations

import json
import logging

from src.config import settings

logger = logging.getLogger(__name__)


class MissingEncryptionKeyError(Exception):
    """Raised when the connector credentials encryption key is not configured."""


def require_encryption_key() -> None:
    """Raise MissingEncryptionKeyError if CONNECTOR_CREDENTIALS_KEY is not set."""
    if not settings.connector.credentials_key:
        raise MissingEncryptionKeyError(
            "CONNECTOR_CREDENTIALS_KEY is not configured. "
            "Connector operations are disabled until this environment variable is set."
        )


def _get_fernet():
    """Return a Fernet instance using the configured key."""
    from cryptography.fernet import Fernet
    key = settings.connector.credentials_key.encode()
    return Fernet(key)


def encrypt_credentials(payload: dict) -> str:
    """Encrypt a credentials dict to a URL-safe base64 string.

    Args:
        payload: Dict containing sensitive fields (e.g. access_key_id, secret_access_key).

    Returns:
        Encrypted ciphertext as a str (UTF-8 encoded Fernet token).
    """
    require_encryption_key()
    fernet = _get_fernet()
    raw = json.dumps(payload).encode("utf-8")
    return fernet.encrypt(raw).decode("utf-8")


def decrypt_credentials(ciphertext: str) -> dict:
    """Decrypt an encrypted credentials payload back to a dict.

    Args:
        ciphertext: Fernet token previously produced by encrypt_credentials().

    Returns:
        The original credentials dict.

    Raises:
        MissingEncryptionKeyError: if key is not configured.
        cryptography.fernet.InvalidToken: if ciphertext is corrupt or key is wrong.
    """
    require_encryption_key()
    fernet = _get_fernet()
    raw = fernet.decrypt(ciphertext.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))
