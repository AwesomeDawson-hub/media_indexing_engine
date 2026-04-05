"""Google OAuth2 / OpenID Connect integration (P6-001).

Provides:
  - State generation, signing, and verification (anti-CSRF)
  - OIDC nonce generation
  - Google authorization URL builder
  - Authorization code exchange + ID token validation using Authlib
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from authlib.jose import jwt as authlib_jwt

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_VALID_ISSUERS = frozenset([
    "https://accounts.google.com",
    "accounts.google.com",
])

# Must match cookie max_age in the start route.
STATE_MAX_AGE_SECONDS = 600  # 10 minutes


@dataclass
class GoogleClaims:
    """Validated identity claims extracted from a Google ID token."""
    sub: str                  # Google user ID — stable, canonical identity key
    email: str                # normalized to lowercase
    email_verified: bool
    name: str | None = None
    picture: str | None = None


# ---------------------------------------------------------------------------
# State / nonce generation
# ---------------------------------------------------------------------------

def generate_state() -> str:
    """Generate a cryptographically random raw state value stored in the cookie."""
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """Generate a cryptographically random OIDC nonce stored in the cookie."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# State signing and verification
# ---------------------------------------------------------------------------

def sign_state(raw_state: str, secret: str) -> str:
    """Return a signed, timestamped state parameter safe to include in the OAuth redirect.

    Format: ``{raw_state}.{unix_ts}.{hmac_hex}``

    The raw state (from the browser cookie) is embedded in the signed value so
    it can be verified on callback without server-side session storage.
    """
    ts = str(int(time.time()))
    msg = f"{raw_state}:{ts}".encode()
    sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
    return f"{raw_state}.{ts}.{sig}"


def verify_state(signed_state: str, cookie_state: str, secret: str) -> bool:
    """Verify the signed state parameter from callback against the browser cookie.

    Returns ``False`` (never raises) so callers can issue a clean error redirect.
    Checks: correct format, token matches cookie (constant-time), timestamp not
    older than STATE_MAX_AGE_SECONDS, HMAC signature valid.
    """
    try:
        parts = signed_state.split(".", 2)
        if len(parts) != 3:
            return False
        token, ts_str, sig = parts
        if not hmac.compare_digest(token, cookie_state):
            return False
        ts = int(ts_str)
        if int(time.time()) - ts > STATE_MAX_AGE_SECONDS:
            return False
        msg = f"{token}:{ts_str}".encode()
        expected_sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
        return hmac.compare_digest(sig, expected_sig)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------

def build_auth_url(client_id: str, redirect_uri: str, state: str, nonce: str) -> str:
    """Return the full Google authorization URL to redirect the user's browser to."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Code exchange + ID token validation
# ---------------------------------------------------------------------------

async def _fetch_google_jwks() -> dict:
    """Fetch Google's public JSON Web Key Set for ID token signature verification."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(GOOGLE_JWKS_URL, timeout=10.0)
        resp.raise_for_status()
        return resp.json()


async def exchange_code_and_validate(
    code: str,
    redirect_uri: str,
    nonce: str,
    client_id: str,
    client_secret: str,
) -> GoogleClaims:
    """Exchange an authorization code for tokens and return validated Google identity.

    Raises:
        ValueError: with a descriptive key on any claim or nonce validation failure.
            Keys: ``no_id_token``, ``id_token_invalid``, ``nonce_mismatch``,
            ``missing_email``, ``unverified_email``.
        httpx.HTTPStatusError: on HTTP error from Google's token endpoint.
        httpx.RequestError: on network failure.
    """
    # Step 1 — exchange authorization code for token response
    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise ValueError("no_id_token")

    # Step 2 — fetch JWKS and decode + validate the ID token with Authlib
    jwks = await _fetch_google_jwks()

    claims_options = {
        "iss": {"essential": True, "values": list(GOOGLE_VALID_ISSUERS)},
        "aud": {"essential": True, "value": client_id},
        "exp": {"essential": True},
    }

    try:
        claims = authlib_jwt.decode(id_token_str, jwks, claims_options=claims_options)
        claims.validate()
    except Exception as exc:
        raise ValueError(f"id_token_invalid: {exc}") from exc

    # Step 3 — validate nonce (not a standard JWT claim; checked manually)
    if claims.get("nonce") != nonce:
        raise ValueError("nonce_mismatch")

    # Step 4 — require a verified email address
    email_verified = bool(claims.get("email_verified", False))
    email = str(claims.get("email") or "").lower().strip()
    if not email:
        raise ValueError("missing_email")
    if not email_verified:
        raise ValueError("unverified_email")

    return GoogleClaims(
        sub=str(claims["sub"]),
        email=email,
        email_verified=email_verified,
        name=str(claims["name"]) if claims.get("name") else None,
        picture=str(claims["picture"]) if claims.get("picture") else None,
    )
