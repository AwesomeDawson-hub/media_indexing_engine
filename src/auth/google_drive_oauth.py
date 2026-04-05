"""Google Drive OAuth2 connector state management (P7-002).

Provides:
  - Drive connector state signing and verification (anti-CSRF, anti-replay)
  - Google Drive authorization URL builder

The state payload binds a one-time nonce (delivered via HTTP-only cookie) to the
authenticated user and source IDs so the callback can trust the round-trip.

State format (URL parameter):
    ``{user_id}|{source_id}|{nonce}.{unix_ts}.{hmac_hex}``

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
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

DRIVE_STATE_COOKIE = "gdrive_connector_state"
DRIVE_STATE_MAX_AGE = 600  # 10 minutes — must match cookie max_age


# ---------------------------------------------------------------------------
# Nonce generation
# ---------------------------------------------------------------------------

def generate_nonce() -> str:
    """Generate a cryptographically random nonce to store in the browser cookie."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# State signing and verification
# ---------------------------------------------------------------------------

def sign_state(user_id: str, source_id: str, nonce: str, secret: str) -> str:
    """Return a signed, timestamped state parameter safe to embed in the OAuth redirect URL.

    Format: ``{user_id}|{source_id}|{nonce}.{unix_ts}.{hmac_hex}``

    The nonce must also be stored in the browser's HTTP-only cookie so the
    callback can prove the request originated from this browser session.
    """
    ts = str(int(time.time()))
    raw_state = f"{user_id}|{source_id}|{nonce}"
    msg = f"{raw_state}:{ts}".encode()
    sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
    return f"{raw_state}.{ts}.{sig}"


def verify_state(signed_state: str, cookie_nonce: str, secret: str) -> tuple[str, str]:
    """Verify a signed Drive connector state parameter and return ``(user_id, source_id)``.

    Checks:
    - Correct format (4-part payload after splitting on last two dots)
    - HMAC signature valid
    - Timestamp not older than DRIVE_STATE_MAX_AGE seconds
    - Embedded nonce matches the browser cookie (anti-replay)

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

        # Unpack payload: user_id|source_id|nonce
        payload_parts = raw_state.split("|", 2)
        if len(payload_parts) != 3:
            raise ValueError("malformed state: wrong payload format")
        user_id, source_id, nonce = payload_parts

        # Verify nonce matches browser cookie (constant-time)
        if not hmac.compare_digest(nonce, cookie_nonce):
            raise ValueError("nonce mismatch")

        return user_id, source_id

    except (ValueError, AttributeError):
        raise
    except Exception as exc:
        raise ValueError(f"state verification failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------

def build_auth_url(client_id: str, redirect_uri: str, signed_state: str) -> str:
    """Return the full Google authorization URL to redirect the user's browser to.

    Requests offline access so a refresh token is issued, and forces consent
    so we always receive a fresh refresh token on reconnect.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "state": signed_state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_DRIVE_AUTH_URL}?{urlencode(params)}"
