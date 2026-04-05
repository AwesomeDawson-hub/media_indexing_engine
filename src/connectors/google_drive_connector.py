"""Google Drive connector implementation (P7-002).

Lists image files from the authorized user's root Drive ("My Drive") using the
Drive Files API v3.  Each file is identified by its stable Drive file ID (key)
and carries the filename as ``display_name``.

Scope: ``drive.readonly`` — read-only access, no write or delete operations.

Filtering:
  - Excludes trashed files
  - Excludes shortcuts (``application/vnd.google-apps.shortcut``)
  - Excludes all Google Workspace native types
    (``application/vnd.google-apps.*``) — these cannot be downloaded as raw bytes
  - Includes only files with MIME type containing ``image/``

All results come from "My Drive" root via Drive Files API pagination.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from src.connectors.base import ConnectorBase, ConnectorValidationError, RemoteObject

logger = logging.getLogger(__name__)

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"

# Base image-only filter (folder parent is added dynamically)
_BASE_QUERY = (
    "trashed=false"
    " and mimeType!='application/vnd.google-apps.shortcut'"
    " and not mimeType contains 'application/vnd.google-apps.'"
    " and mimeType contains 'image/'"
)
# Legacy alias kept for tests that import _LIST_QUERY directly
_LIST_QUERY = _BASE_QUERY
_LIST_FIELDS = "nextPageToken,files(id,name,version,mimeType,size,modifiedTime)"
_PAGE_SIZE = 100  # Drive API max per page


class GoogleDriveConnector(ConnectorBase):
    """ConnectorBase implementation for Google Drive (root / My Drive).

    Args:
        token_manager: A ``DriveTokenManager`` instance bound to the connector row.
    """

    connector_type = "google_drive"

    def __init__(self, token_manager, folder_id: str | None = None) -> None:
        self._tm = token_manager
        # None or "root" both mean My Drive root; store normalised value
        self._folder_id = folder_id if folder_id and folder_id != "root" else None

    def _build_query(self) -> str:
        """Return the Files API query string, scoped to the target folder if set."""
        if self._folder_id:
            return f"'{self._folder_id}' in parents and {_BASE_QUERY}"
        return _BASE_QUERY

    async def list_objects(self, max_keys: int = 1000) -> list[RemoteObject]:
        """List image files in My Drive up to *max_keys*.

        Paginates through Drive Files API results and stops once *max_keys* items
        have been collected.
        """
        # list_objects does not have a db session; get_access_token is called
        # with a sentinel None — refresh happens only if token is already cached.
        # We pass None here; a real refresh DB commit can only happen if called
        # from sync_service which passes the session through validate() first.
        access_token = await self._tm.get_access_token(None)
        results: list[RemoteObject] = []
        page_token: str | None = None

        async with httpx.AsyncClient() as client:
            while len(results) < max_keys:
                params: dict = {
                    "q": self._build_query(),
                    "fields": _LIST_FIELDS,
                    "pageSize": min(_PAGE_SIZE, max_keys - len(results)),
                    "orderBy": "modifiedTime desc",
                }
                if page_token:
                    params["pageToken"] = page_token

                resp = await client.get(
                    DRIVE_FILES_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("files", []):
                    modified_raw = item.get("modifiedTime")
                    try:
                        last_modified = datetime.fromisoformat(
                            modified_raw.replace("Z", "+00:00")
                        ) if modified_raw else None
                    except ValueError:
                        last_modified = None

                    size_raw = item.get("size")
                    results.append(
                        RemoteObject(
                            key=item["id"],
                            display_name=item.get("name") or item["id"],
                            version=item.get("version"),
                            last_modified_at=last_modified,
                            size=int(size_raw) if size_raw is not None else None,
                        )
                    )

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        return results

    async def download_object(self, key: str) -> bytes:
        """Download a Drive file by its file ID and return the raw bytes."""
        access_token = await self._tm.get_access_token(None)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DRIVE_FILES_URL}/{key}",
                params={"alt": "media"},
                headers={"Authorization": f"Bearer {access_token}"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content

    async def validate(self, db=None) -> None:
        """Verify connectivity by calling the Drive about endpoint.

        Passes *db* to ``get_access_token`` so that a token refresh that triggers
        refresh-token rotation can persist the new token.

        Raises:
            ConnectorValidationError: if the access token cannot be obtained or
                the Drive API returns an unexpected status.
        """
        try:
            access_token = await self._tm.get_access_token(db)
        except Exception as exc:
            raise ConnectorValidationError(
                f"Drive token refresh failed: {exc}"
            ) from exc

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DRIVE_ABOUT_URL}?fields=user",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if resp.status_code != 200:
            raise ConnectorValidationError(
                f"Drive API returned HTTP {resp.status_code} during validation"
            )
