"""Google Drive connector implementation (P7-002, P7-007).

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

When no folder is scoped (``folder_id=None``), all images in My Drive are
returned via a single paginated query.  When a folder is scoped (P7-007),
the connector recursively traverses the entire sub-folder tree so that images
nested at any depth are included, up to ``_MAX_FOLDER_DEPTH`` levels.
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
_MAX_FOLDER_DEPTH = 10  # guard against pathologically deep / circular trees


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
        """Return the Files API query string, scoped to the target folder if set.

        NOTE: This returns a *flat* (single-level) query.  ``list_objects`` uses
        the recursive helpers instead whenever ``_folder_id`` is set; this method
        is preserved for backward-compatible unit tests.
        """
        if self._folder_id:
            return f"'{self._folder_id}' in parents and {_BASE_QUERY}"
        return _BASE_QUERY

    async def list_objects(self, max_keys: int = 1000) -> list[RemoteObject]:
        """List image files accessible to this connector, up to *max_keys*.

        When no folder is scoped (My Drive root), performs a single paginated
        search across all of My Drive.

        When a folder is scoped (P7-007), recursively traverses the entire
        sub-folder tree so that images nested at any depth within the selected
        folder are included.

        ``get_access_token`` is called with ``None`` (no DB session) because
        token refresh commits can only happen when called from ``sync_service``
        via ``validate(db)`` first.
        """
        access_token = await self._tm.get_access_token(None)
        results: list[RemoteObject] = []

        if self._folder_id is None:
            # Unscoped: flat search across all of My Drive
            await self._list_in_folder(access_token, None, results, max_keys)
        else:
            # Folder-scoped: BFS recursive traversal from the target folder
            await self._collect_recursive(
                access_token, self._folder_id, results, max_keys, depth=0
            )

        return results

    async def _list_in_folder(
        self,
        access_token: str,
        folder_id: str | None,
        results: list[RemoteObject],
        max_keys: int,
    ) -> None:
        """Append image RemoteObjects from one folder level (no sub-folder recursion).

        ``folder_id=None`` means My Drive root (no ``in parents`` filter).
        """
        query = f"'{folder_id}' in parents and {_BASE_QUERY}" if folder_id else _BASE_QUERY
        page_token: str | None = None

        async with httpx.AsyncClient() as client:
            while len(results) < max_keys:
                params: dict = {
                    "q": query,
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
                    if len(results) >= max_keys:
                        return
                    results.append(self._build_remote_object(item))

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

    async def _collect_recursive(
        self,
        access_token: str,
        folder_id: str,
        results: list[RemoteObject],
        max_keys: int,
        depth: int,
    ) -> None:
        """Recursively collect images from *folder_id* and all its sub-folders.

        Uses a BFS-style depth-first approach: first collects images at the
        current level, then lists direct sub-folders and recurses into each.
        Stops if ``max_keys`` is reached or ``_MAX_FOLDER_DEPTH`` is exceeded.
        """
        if depth > _MAX_FOLDER_DEPTH or len(results) >= max_keys:
            return

        # Collect images at this folder level
        await self._list_in_folder(access_token, folder_id, results, max_keys)

        if len(results) >= max_keys:
            return

        # List direct sub-folders and recurse
        sub_query = (
            f"'{folder_id}' in parents"
            " and mimeType='application/vnd.google-apps.folder'"
            " and trashed=false"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                DRIVE_FILES_URL,
                params={
                    "q": sub_query,
                    "fields": "nextPageToken,files(id,name)",
                    "pageSize": 200,
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        for subfolder in data.get("files", []):
            if len(results) >= max_keys:
                break
            await self._collect_recursive(
                access_token, subfolder["id"], results, max_keys, depth + 1
            )

    @staticmethod
    def _build_remote_object(item: dict) -> RemoteObject:
        """Build a RemoteObject from a Drive Files API listing item dict."""
        modified_raw = item.get("modifiedTime")
        try:
            last_modified = (
                datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
                if modified_raw
                else None
            )
        except ValueError:
            last_modified = None

        size_raw = item.get("size")
        return RemoteObject(
            key=item["id"],
            display_name=item.get("name") or item["id"],
            version=item.get("version"),
            last_modified_at=last_modified,
            size=int(size_raw) if size_raw is not None else None,
        )

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
