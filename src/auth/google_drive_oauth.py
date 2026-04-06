"""Google Drive OAuth2 connector state management (P7-002 / P7-004).

Provides:
  - Drive connector state signing and verification (anti-CSRF, anti-replay)
  - Google Drive authorization URL builder (read-only scope and writable scope)

The state payload binds a one-time nonce (delivered via HTTP-only cookie) to the
authenticated user and source IDs so the callback can trust the round-trip.

State format (URL parameter):
    ``{user_id}|{source_id}|{mode}|{nonce}.{unix_ts}.{hmac_hex}``

  ``mode`` is ``connect`` for the initial authorization or ``upgrade`` for a
  scope-upgrade re-consent flow. The mode is embedded in the signed state so
  the callback can apply the correct post-authorization logic.

Cookie:
    Name: ``gdrive_connector_state``
    Value: raw nonce (must match nonce embedded in state parameter)
    Scope: path=/api/v1/connectors/google-drive/callback, HTTP-only, SameSite=Lax
    Max-age: DRIVE_STATE_MAX_AGE seconds
"""

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

GOOGLE_DRIVE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# P7-002 legacy read-only scope
DRIVE_SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
# P7-004 writable scope (required for rename and metadata write-back)
DRIVE_SCOPE_READWRITE = "https://www.googleapis.com/auth/drive"

# Backward-compatibility alias — existing connectors authorised with this scope
# are classified as blocked_writeback until they reauthorise with DRIVE_SCOPE_READWRITE.
DRIVE_SCOPE = DRIVE_SCOPE_READWRITE  # New authorizations always request writable scope.

DRIVE_STATE_COOKIE = "gdrive_connector_state"
DRIVE_STATE_MAX_AGE = 600  # 10 minutes — must match cookie max_age


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def scope_has_write(granted_scopes: str | None) -> bool:
    """Return True if the granted scope string includes the Drive writable scope.

    A NULL/empty granted_scopes value is treated as legacy read-only (returns False).
    """
    if not granted_scopes:
        return False
    return DRIVE_SCOPE_READWRITE in granted_scopes.split()


# ---------------------------------------------------------------------------
# Nonce generation
# ---------------------------------------------------------------------------

def generate_nonce() -> str:
    """Generate a cryptographically random nonce to store in the browser cookie."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# State signing and verification
# ---------------------------------------------------------------------------

def sign_state(user_id: str, source_id: str, nonce: str, secret: str, mode: str = "connect") -> str:
    """Return a signed, timestamped state parameter safe to embed in the OAuth redirect URL.

    Format: ``{user_id}|{source_id}|{mode}|{nonce}.{unix_ts}.{hmac_hex}``

    Args:
        mode: ``connect`` (initial auth) or ``upgrade`` (scope upgrade re-consent).

    The nonce must also be stored in the browser's HTTP-only cookie so the
    callback can prove the request originated from this browser session.
    """
    ts = str(int(time.time()))
    raw_state = f"{user_id}|{source_id}|{mode}|{nonce}"
    msg = f"{raw_state}:{ts}".encode()
    sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
    return f"{raw_state}.{ts}.{sig}"


def verify_state(signed_state: str, cookie_nonce: str, secret: str) -> tuple[str, str, str]:
    """Verify a signed Drive connector state parameter and return ``(user_id, source_id, mode)``.

    Checks:
    - Correct format (4-part payload after splitting on last two dots)
    - HMAC signature valid
    - Timestamp not older than DRIVE_STATE_MAX_AGE seconds
    - Embedded nonce matches the browser cookie (anti-replay)

    Returns:
        ``(user_id, source_id, mode)`` where mode is ``connect`` or ``upgrade``.

    Raises ``ValueError`` on any validation failure so callers can issue a clean
    error redirect.
    """
    try:
        dot_parts = signed_state.rsplit(".", 2)
        if len(dot_parts) != 3:
            raise ValueError("malformed state: wrong number of parts")
        raw_state, ts_str, sig = dot_parts

        # Verify HMAC first to avoid processing attacker-controlled data
        msg = f"{raw_state}:{ts_str}".encode()
        expected_sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("invalid signature")

        # Check age
        ts = int(ts_str)
        if int(time.time()) - ts > DRIVE_STATE_MAX_AGE:
            raise ValueError("state expired")

        # Unpack payload: user_id|source_id|mode|nonce (4 pipe-separated parts)
        payload_parts = raw_state.split("|", 3)
        if len(payload_parts) == 3:
            # Legacy 3-part state (P7-002) — treat mode as "connect"
            user_id, source_id, nonce = payload_parts
            mode = "connect"
        elif len(payload_parts) == 4:
            user_id, source_id, mode, nonce = payload_parts
        else:
            raise ValueError("malformed state: wrong payload format")

        # Verify nonce matches browser cookie (constant-time)
        if not hmac.compare_digest(nonce, cookie_nonce):
            raise ValueError("nonce mismatch")

        return user_id, source_id, mode

    except (ValueError, AttributeError):
        raise
    except Exception as exc:
        raise ValueError(f"state verification failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------

def build_auth_url(
    client_id: str,
    redirect_uri: str,
    signed_state: str,
    scope: str = DRIVE_SCOPE_READWRITE,
) -> str:
    """Return the full Google authorization URL to redirect the user's browser to.

    Requests offline access so a refresh token is issued, and forces consent
    so we always receive a fresh refresh token on reconnect or scope upgrade.

    Args:
        scope: Drive scope to request. Defaults to writable (P7-004).
               Pass DRIVE_SCOPE_READONLY explicitly for read-only-only flows.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": signed_state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_DRIVE_AUTH_URL}?{urlencode(params)}"

