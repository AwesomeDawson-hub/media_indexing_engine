"""Google Drive token management for the connector (P7-002).

Handles:
  - Authorization code exchange (returns access + refresh tokens and granted scopes)
  - Authorized account snapshot (permissionId, email, displayName from Drive API)
  - Access token refresh with automatic refresh-token rotation and credential re-encryption

Credentials stored in ``SourceConnector.credentials_encrypted`` (JSON):
    {
        "refresh_token": "<opaque Google refresh token>",
        "refresh_token_issued_at": "<ISO-8601 UTC>",
        "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"]
    }

Access tokens are cached on the ``DriveTokenManager`` instance for the duration
of a single sync run.  They are never persisted to the database.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"

# Buffer in seconds: refresh the access token this many seconds before it expires.
_EXPIRY_BUFFER = 60


class DriveTokenError(Exception):
    """Raised when a Drive token operation fails."""


# ---------------------------------------------------------------------------
# Standalone helpers (used during the OAuth callback)
# ---------------------------------------------------------------------------

async def exchange_code(
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Exchange an authorization code for tokens.

    Returns a dict with keys:
        ``access_token``, ``refresh_token``, ``granted_scopes`` (list[str]),
        ``expires_in`` (int, seconds).

    Raises ``DriveTokenError`` on any failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise DriveTokenError(
            f"code exchange failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    data = resp.json()
    if "refresh_token" not in data:
        raise DriveTokenError(
            "no refresh_token in exchange response — "
            "ensure prompt=consent and access_type=offline are set"
        )

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "granted_scopes": data.get("scope", "").split(),
        "expires_in": int(data.get("expires_in", 3600)),
    }


async def fetch_account_snapshot(access_token: str) -> dict:
    """Fetch the authorized account identity from the Drive API.

    Returns a dict with keys:
        ``provider_id`` (Drive permissionId), ``email``, ``display_name``.

    Raises ``DriveTokenError`` on any failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DRIVE_ABOUT_URL}?fields=user",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        raise DriveTokenError(
            f"account snapshot failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    user = resp.json().get("user", {})
    provider_id = user.get("permissionId", "")
    if not provider_id:
        raise DriveTokenError("account snapshot missing permissionId")

    return {
        "provider_id": provider_id,
        "email": user.get("emailAddress", ""),
        "display_name": user.get("displayName", ""),
    }


# ---------------------------------------------------------------------------
# Per-connector token manager (used during sync)
# ---------------------------------------------------------------------------

class DriveTokenManager:
    """Manages Drive access tokens for a single connector during a sync run.

    Access tokens are cached in memory and refreshed automatically.
    When Google issues a new refresh token, the credentials are re-encrypted
    and persisted to the database.

    Args:
        connector_row: The ``SourceConnector`` ORM row (mutable — refresh
            rotation writes directly to ``credentials_encrypted``).
        credentials: Decrypted credentials dict from ``decrypt_credentials()``.
        client_id: Google OAuth client ID.
        client_secret: Google OAuth client secret.
        redirect_uri: Redirect URI registered with the OAuth client.
    """

    def __init__(
        self,
        connector_row,  # SourceConnector — avoid circular import
        credentials: dict,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self._connector_row = connector_row
        self._credentials = dict(credentials)
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    async def get_access_token(self, db) -> str:
        """Return a valid access token, refreshing if necessary.

        Args:
            db: An ``AsyncSession`` needed only when a token refresh triggers
                refresh-token rotation (rare; occurs ~every 6 months per Google policy).
        """
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        return await self._refresh_access_token(db)

    async def _refresh_access_token(self, db) -> str:
        refresh_token = self._credentials.get("refresh_token")
        if not refresh_token:
            raise DriveTokenError("no refresh token stored; connector must be reconnected")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )

        if resp.status_code != 200:
            raise DriveTokenError(
                f"token refresh failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        data = resp.json()
        new_access_token = data.get("access_token")
        if not new_access_token:
            raise DriveTokenError("token refresh returned no access_token")

        self._access_token = new_access_token
        self._token_expires_at = time.time() + int(data.get("expires_in", 3600)) - _EXPIRY_BUFFER

        # Rotate refresh token if Google issued a new one (uncommon but must be handled)
        if "refresh_token" in data and data["refresh_token"] != refresh_token:
            self._credentials["refresh_token"] = data["refresh_token"]
            self._credentials["refresh_token_issued_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            from src.connectors.secrets import encrypt_credentials
            self._connector_row.credentials_encrypted = encrypt_credentials(self._credentials)
            await db.commit()

        return self._access_token
