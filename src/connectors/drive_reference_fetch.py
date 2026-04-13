"""Shared Drive reference-fetch service (P10-001).

Provides ``fetch_drive_reference_bytes``: a single entry point for transiently
fetching the bytes of a Drive-backed ``storage_mode='reference'`` MediaItem.

Contract:
  - Verifies the item is a Google Drive reference item.
  - Loads ``OriginAssetRef`` and ``SourceConnector`` for the item.
  - Obtains a Drive access token and calls ``connector.download_object()``.
  - Maps all failure modes to the locked P10-001 error contract (see table below).
  - Returns raw bytes only — never writes to ``file_store`` or persists anything.

Error contract (locked — P10-001 Q4):
  | Condition                                    | HTTP | error_code              |
  |----------------------------------------------|------|-------------------------|
  | Drive file deleted / trashed / missing       |  404 | drive_file_not_found    |
  | Token failure / missing refresh / auth error |  409 | drive_auth_expired      |
  | Rate limit / quota throttling                |  429 | drive_rate_limited      |
  | Fetch timeout                                |  504 | drive_fetch_timeout     |
  | Other upstream failures                      |  502 | drive_fetch_failed      |
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.connectors.factory import build_connector
from src.connectors.google_drive_tokens import DriveTokenError
from src.connectors.secrets import decrypt_credentials
from src.models import MediaItem, OriginAssetRef, SourceConnector

# ---------------------------------------------------------------------------
# Public error codes (kept as module-level constants for test assertions)
# ---------------------------------------------------------------------------

ERR_DRIVE_FILE_NOT_FOUND = "drive_file_not_found"
ERR_DRIVE_AUTH_EXPIRED = "drive_auth_expired"
ERR_DRIVE_RATE_LIMITED = "drive_rate_limited"
ERR_DRIVE_FETCH_TIMEOUT = "drive_fetch_timeout"
ERR_DRIVE_FETCH_FAILED = "drive_fetch_failed"


async def fetch_drive_reference_bytes(
    db: AsyncSession,
    item: MediaItem,
    user_id: str,
) -> bytes:
    """Transiently fetch the bytes of a Drive-backed reference MediaItem.

    Args:
        db: Active async database session.
        item: The ``MediaItem`` to fetch.  Must have ``storage_mode='reference'``
              and a ``google_drive`` ``OriginAssetRef``.
        user_id: The owning user's ID — used to scope the connector lookup.

    Returns:
        Raw bytes from the Drive file.

    Raises:
        HTTPException 404 ``drive_file_not_found``: Drive file is gone.
        HTTPException 409 ``drive_auth_expired``: Token failure or auth rejection.
        HTTPException 429 ``drive_rate_limited``: Drive API rate/quota limit hit.
        HTTPException 504 ``drive_fetch_timeout``: Network timeout on the fetch.
        HTTPException 502 ``drive_fetch_failed``: Any other upstream failure, including
            missing/inconsistent item state (missing OAR, non-Drive OAR, missing
            provider_object_id, missing SourceConnector) — these are treated as
            internal precondition failures, not client validation errors.
    """
    # Load OriginAssetRef — must exist and be a Google Drive item
    oar_result = await db.execute(
        select(OriginAssetRef).where(OriginAssetRef.media_item_id == item.id)
    )
    oar = oar_result.scalar_one_or_none()
    if oar is None or oar.provider_type != "google_drive" or not oar.provider_object_id:
        raise HTTPException(
            status_code=502,
            detail={"error_code": ERR_DRIVE_FETCH_FAILED, "message": "Item is not a Drive-backed reference item"},
        )

    # Load SourceConnector scoped to the item's source and the owning user
    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == item.source_id,
            SourceConnector.user_id == user_id,
        )
    )
    connector_row = conn_result.scalar_one_or_none()
    if connector_row is None:
        raise HTTPException(
            status_code=502,
            detail={"error_code": ERR_DRIVE_FETCH_FAILED, "message": "No connector found for this item"},
        )

    # Build connector and download
    try:
        credentials = decrypt_credentials(connector_row.credentials_encrypted)
        connector = build_connector(connector_row, credentials)
        file_bytes: bytes = await connector.download_object(oar.provider_object_id)
    except DriveTokenError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": ERR_DRIVE_AUTH_EXPIRED, "message": str(exc)},
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail={"error_code": ERR_DRIVE_FETCH_TIMEOUT, "message": "Drive fetch timed out"},
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            raise HTTPException(
                status_code=404,
                detail={"error_code": ERR_DRIVE_FILE_NOT_FOUND, "message": "Drive file not found or deleted"},
            ) from exc
        if status == 429:
            raise HTTPException(
                status_code=429,
                detail={"error_code": ERR_DRIVE_RATE_LIMITED, "message": "Drive API rate limit exceeded"},
            ) from exc
        raise HTTPException(
            status_code=502,
            detail={"error_code": ERR_DRIVE_FETCH_FAILED, "message": f"Drive returned HTTP {status}"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error_code": ERR_DRIVE_FETCH_FAILED, "message": f"Drive fetch failed: {exc}"},
        ) from exc

    return file_bytes
