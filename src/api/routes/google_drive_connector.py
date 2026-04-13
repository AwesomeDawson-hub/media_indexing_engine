"""Google Drive connector OAuth and management endpoints (P7-002).

Endpoints:
  POST   /api/v1/sources/{source_id}/connector/google-drive/start  — initiate OAuth flow
  GET    /api/v1/connectors/google-drive/callback                   — OAuth callback (browser redirect)
  DELETE /api/v1/sources/{source_id}/connector/google-drive         — disconnect (logical deauth)

The start endpoint is authenticated (bearer token).
The callback endpoint is unauthenticated — it is reached via a browser redirect from Google.
The disconnect endpoint is authenticated.

Callback redirect contract (to frontend):
  Success: {frontend_url}/add-media?connector=google_drive&source_id={id}&connector_result=connected
  Error:   {frontend_url}/add-media?connector=google_drive&source_id={id}&connector_result=error&error_code={code}

Error codes: access_denied, invalid_state, state_expired_or_replayed, exchange_failed,
             connector_disabled, source_not_found, source_archived, account_snapshot_failed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import (
    ConnectorDriveStartResponse,
    ConnectorDriveQuickConnectRequest,
    ConnectorDriveConfigureRequest,
    ConnectorResponse,
    DriveFolderItem,
    DriveFoldersResponse,
)
from src.analysis.source_capability_service import upsert_drive_capability_snapshot
from src.auth.google_drive_oauth import (
    DRIVE_STATE_COOKIE,
    DRIVE_STATE_MAX_AGE,
    DRIVE_SCOPE_READWRITE,
    build_auth_url,
    generate_nonce,
    scope_has_write,
    sign_state,
    verify_state,
)
from src.config import settings
from src.connectors.google_drive_tokens import DriveTokenError, exchange_code, fetch_account_snapshot
from src.connectors.secrets import encrypt_credentials, MissingEncryptionKeyError
from src.models import Collection, Source, SourceConnector, SourceObject

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["google-drive-connector"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _set_drive_state_cookie(response: Response, nonce: str) -> None:
    """Set the HTTP-only Drive connector state cookie scoped to the callback path."""
    is_secure = not settings.auth.dev_mode
    response.set_cookie(
        key=DRIVE_STATE_COOKIE,
        value=nonce,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=DRIVE_STATE_MAX_AGE,
        path="/api/v1/connectors/google-drive/callback",
    )


def _error_redirect(frontend_url: str, source_id: str | None, error_code: str) -> RedirectResponse:
    """Return a 302 redirect to the frontend error page."""
    sid_param = f"&source_id={source_id}" if source_id else ""
    url = (
        f"{frontend_url}/add-media"
        f"?connector=google_drive{sid_param}"
        f"&connector_result=error"
        f"&error_code={error_code}"
    )
    return RedirectResponse(url=url, status_code=302)


async def _require_owned_source(
    source_id: str, user_id: str, db: AsyncSession
) -> Source:
    """Return the Source or raise 404. Never returns another user's source."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


# ---------------------------------------------------------------------------
# POST /api/v1/sources/{source_id}/connector/google-drive/start
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/connector/google-drive/start", status_code=200)
async def google_drive_start(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorDriveStartResponse:
    """Initiate the Google Drive OAuth flow for a source.

    Returns the Google authorization URL. The caller (SPA) must redirect the
    browser to that URL; on return, Google will call the callback endpoint.
    The Drive connector must be enabled in settings.
    """
    if not settings.google_drive.is_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Google Drive connector is not enabled.",
                "error_code": "connector_disabled",
            },
        )
    if not settings.connector.credentials_key:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Connector credentials encryption key is not configured.",
                "error_code": "connector_unavailable",
            },
        )

    source = await _require_owned_source(source_id, user_id, db)
    if source.archived_at is not None:
        raise HTTPException(status_code=409, detail="Cannot connect a Drive account to an archived source")

    nonce = generate_nonce()
    signed_state = sign_state(
        user_id=user_id,
        source_id=source_id,
        nonce=nonce,
        secret=settings.auth.secret_key,
    )
    auth_url = build_auth_url(
        client_id=settings.google_drive.client_id,
        redirect_uri=settings.google_drive.redirect_uri,
        signed_state=signed_state,
    )

    response = Response(media_type="application/json")
    _set_drive_state_cookie(response, nonce)

    # FastAPI does not support mixing Response + return type; return JSONResponse directly
    from fastapi.responses import JSONResponse
    json_response = JSONResponse(
        content={"authorization_url": auth_url},
        status_code=200,
    )
    _set_drive_state_cookie(json_response, nonce)
    return json_response


# ---------------------------------------------------------------------------
# POST /api/v1/sources/{source_id}/connector/google-drive/upgrade-scope/start
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/connector/google-drive/upgrade-scope/start", status_code=200)
async def google_drive_upgrade_scope_start(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorDriveStartResponse:
    """Initiate a Drive scope-upgrade re-consent flow (P7-004).

    Used when an existing Drive connector was authorised with the read-only
    scope (pre-P7-004) and the user needs to grant the writable scope so
    source mutation (rename + metadata write-back) can proceed.

    Any items currently classified as ``blocked_writeback`` due to a missing
    writable scope will be reclassified to ``pending_writeback`` after the
    upgrade callback completes and the connector has the writable grant.
    """
    if not settings.google_drive.is_ready:
        raise HTTPException(
            status_code=503,
            detail={"message": "Google Drive connector is not enabled.", "error_code": "connector_disabled"},
        )
    if not settings.connector.credentials_key:
        raise HTTPException(
            status_code=503,
            detail={"message": "Connector credentials key not configured.", "error_code": "connector_unavailable"},
        )

    source = await _require_owned_source(source_id, user_id, db)
    if source.archived_at is not None:
        raise HTTPException(status_code=409, detail="Cannot upgrade scope on an archived source")

    # Existing connector must exist — you can only upgrade, not create via this endpoint
    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
            SourceConnector.connector_type == "google_drive",
        )
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="No Google Drive connector configured for this source")

    nonce = generate_nonce()
    signed_state = sign_state(
        user_id=user_id,
        source_id=source_id,
        nonce=nonce,
        secret=settings.auth.secret_key,
        mode="upgrade",
    )
    auth_url = build_auth_url(
        client_id=settings.google_drive.client_id,
        redirect_uri=settings.google_drive.redirect_uri,
        signed_state=signed_state,
        scope=DRIVE_SCOPE_READWRITE,
    )

    from fastapi.responses import JSONResponse
    json_response = JSONResponse(
        content={"authorization_url": auth_url},
        status_code=200,
    )
    _set_drive_state_cookie(json_response, nonce)
    return json_response


# ---------------------------------------------------------------------------
# POST /api/v1/connectors/google-drive/quick-connect
# ---------------------------------------------------------------------------

@router.post("/connectors/google-drive/quick-connect", status_code=200)
async def google_drive_quick_connect(
    body: ConnectorDriveQuickConnectRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorDriveStartResponse:
    """Create a Source automatically and initiate Google Drive OAuth in one step.

    Removes the requirement for the user to pre-create a Source before
    starting OAuth. Used by the Add Media page.
    """
    if not settings.google_drive.is_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Google Drive connector is not enabled.",
                "error_code": "connector_disabled",
            },
        )
    if not settings.connector.credentials_key:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Connector credentials encryption key is not configured.",
                "error_code": "connector_unavailable",
            },
        )

    source_name = (body.source_name.strip() if body and body.source_name else None) or "Google Drive"
    new_source = Source(user_id=user_id, name=source_name, source_type="manual")
    db.add(new_source)
    await db.flush()
    source_id = new_source.id

    nonce = generate_nonce()
    signed_state = sign_state(
        user_id=user_id,
        source_id=source_id,
        nonce=nonce,
        secret=settings.auth.secret_key,
    )
    auth_url = build_auth_url(
        client_id=settings.google_drive.client_id,
        redirect_uri=settings.google_drive.redirect_uri,
        signed_state=signed_state,
    )

    await db.commit()

    from fastapi.responses import JSONResponse
    json_response = JSONResponse(
        content={"authorization_url": auth_url},
        status_code=200,
    )
    _set_drive_state_cookie(json_response, nonce)
    return json_response


# ---------------------------------------------------------------------------
# GET /api/v1/connectors/google-drive/callback
# ---------------------------------------------------------------------------

@router.get("/connectors/google-drive/callback")
async def google_drive_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the OAuth callback redirect from Google.

    This endpoint is reached by the user's browser after Google authorization.
    It is NOT authenticated via bearer token — identity is established by
    verifying the signed state parameter and nonce cookie.
    """
    frontend_url = settings.google_drive.frontend_url or settings.email.app_url

    # ------------------------------------------------------------------
    # Step 1: reject early if connector is disabled (misconfiguration guard)
    # ------------------------------------------------------------------
    if not settings.google_drive.is_ready:
        return _error_redirect(frontend_url, None, "connector_disabled")

    # ------------------------------------------------------------------
    # Step 2: extract query params
    # ------------------------------------------------------------------
    query_params = dict(request.query_params)
    error_param = query_params.get("error")
    code = query_params.get("code")
    signed_state = query_params.get("state")

    if error_param == "access_denied":
        return _error_redirect(frontend_url, None, "access_denied")

    if not code or not signed_state:
        return _error_redirect(frontend_url, None, "invalid_state")

    # ------------------------------------------------------------------
    # Step 3: read nonce cookie and verify state
    # ------------------------------------------------------------------
    cookie_nonce = request.cookies.get(DRIVE_STATE_COOKIE)
    if not cookie_nonce:
        return _error_redirect(frontend_url, None, "invalid_state")

    try:
        user_id, source_id, oauth_mode = verify_state(signed_state, cookie_nonce, settings.auth.secret_key)
    except ValueError as exc:
        err_str = str(exc)
        if "expired" in err_str:
            return _error_redirect(frontend_url, None, "state_expired_or_replayed")
        return _error_redirect(frontend_url, None, "invalid_state")

    # ------------------------------------------------------------------
    # Step 4: verify source still exists and is not archived
    # ------------------------------------------------------------------
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        return _error_redirect(frontend_url, source_id, "source_not_found")
    if source.archived_at is not None:
        return _error_redirect(frontend_url, source_id, "source_archived")

    # ------------------------------------------------------------------
    # Step 5: exchange code for tokens
    # ------------------------------------------------------------------
    try:
        token_data = await exchange_code(
            code=code,
            redirect_uri=settings.google_drive.redirect_uri,
            client_id=settings.google_drive.client_id,
            client_secret=settings.google_drive.client_secret,
        )
    except DriveTokenError as exc:
        logger.warning("Drive code exchange failed for source %s: %s", source_id, exc)
        return _error_redirect(frontend_url, source_id, "exchange_failed")

    # ------------------------------------------------------------------
    # Step 6: fetch authorized account snapshot
    # ------------------------------------------------------------------
    try:
        snapshot = await fetch_account_snapshot(token_data["access_token"])
    except DriveTokenError as exc:
        logger.warning("Drive account snapshot failed for source %s: %s", source_id, exc)
        return _error_redirect(frontend_url, source_id, "account_snapshot_failed")

    # ------------------------------------------------------------------
    # Step 7: encrypt and store credentials
    # ------------------------------------------------------------------
    try:
        credentials_payload = {
            "refresh_token": token_data["refresh_token"],
            "refresh_token_issued_at": datetime.now(timezone.utc).isoformat(),
            "granted_scopes": token_data["granted_scopes"],
        }
        encrypted = encrypt_credentials(credentials_payload)
    except MissingEncryptionKeyError:
        logger.error("Connector credentials key not configured; cannot store Drive credentials")
        return _error_redirect(frontend_url, source_id, "exchange_failed")

    # ------------------------------------------------------------------
    # Step 8: handle reconnect — detect account switch
    # ------------------------------------------------------------------
    existing_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
        )
    )
    existing_connector = existing_result.scalar_one_or_none()

    is_different_account = (
        existing_connector is not None
        and existing_connector.connector_type == "google_drive"
        and existing_connector.authorized_account_provider_id is not None
        and existing_connector.authorized_account_provider_id != snapshot["provider_id"]
    )

    if is_different_account:
        # Different Google account: purge prior SourceObject rows so stale file IDs
        # from the old account are not presented as existing objects.
        await db.execute(
            delete(SourceObject).where(SourceObject.source_id == source_id)
        )
        logger.info(
            "Drive connector reconnected with different account for source %s — "
            "cleared prior SourceObject rows",
            source_id,
        )

    # -------------------------------------------------------------------
    # Step 9: upsert SourceConnector
    # -------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    granted_scopes_str = " ".join(token_data.get("granted_scopes") or [])
    if existing_connector is None:
        connector = SourceConnector(
            source_id=source_id,
            user_id=user_id,
            connector_type="google_drive",
            remote_container_id="root",
            remote_container_label="My Drive",
            prefix=None,
            region=None,
            endpoint_url=None,
            credentials_encrypted=encrypted,
            authorized_account_provider_id=snapshot["provider_id"],
            authorized_account_email=snapshot["email"],
            authorized_account_display_name=snapshot["display_name"],
            config_validated_at=now,
            last_validation_error=None,
            granted_scopes=granted_scopes_str,
        )
        db.add(connector)
    else:
        existing_connector.connector_type = "google_drive"
        existing_connector.remote_container_id = "root"
        existing_connector.remote_container_label = "My Drive"
        existing_connector.credentials_encrypted = encrypted
        existing_connector.authorized_account_provider_id = snapshot["provider_id"]
        existing_connector.authorized_account_email = snapshot["email"]
        existing_connector.authorized_account_display_name = snapshot["display_name"]
        existing_connector.config_validated_at = now
        existing_connector.last_validation_error = None
        existing_connector.granted_scopes = granted_scopes_str
        existing_connector.updated_at = now

    source.source_type = "google_drive"
    source.connector_status = "configured"
    source.updated_at = now
    await upsert_drive_capability_snapshot(db, existing_connector or connector)
    await db.commit()

    # ------------------------------------------------------------------
    # Step 10: respond with success redirect
    # ------------------------------------------------------------------
    connector_result = "upgraded" if oauth_mode == "upgrade" else "connected"
    connector_result = "upgraded" if oauth_mode == "upgrade" else "connected"
    success_url = (
        f"{frontend_url}/add-media"
        f"?connector=google_drive"
        f"&source_id={source_id}"
        f"&connector_result={connector_result}"
    )
    return RedirectResponse(url=success_url, status_code=302)


# ---------------------------------------------------------------------------
# DELETE /api/v1/sources/{source_id}/connector/google-drive
# ---------------------------------------------------------------------------

@router.delete("/sources/{source_id}/connector/google-drive", status_code=204)
async def google_drive_disconnect(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Logically disconnect the Google Drive connector.

    Clears stored credentials and marks the connector as disconnected.
    SourceObject rows and sync_run history are preserved. The authorized
    account snapshot is also preserved for display in the UI.
    """
    await _require_owned_source(source_id, user_id, db)

    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
            SourceConnector.connector_type == "google_drive",
        )
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=404, detail="No Google Drive connector configured for this source"
        )

    now = datetime.now(timezone.utc)
    connector.credentials_encrypted = encrypt_credentials({})
    connector.updated_at = now

    # Reflect disconnected state on the source
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = source_result.scalar_one_or_none()
    if source:
        source.connector_status = "disconnected"
        source.updated_at = now

    await db.commit()


# ---------------------------------------------------------------------------
# GET /api/v1/sources/{source_id}/connector/google-drive/folders
# ---------------------------------------------------------------------------

@router.get("/sources/{source_id}/connector/google-drive/folders")
async def google_drive_list_folders(
    source_id: str,
    parent_id: str = "root",
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> DriveFoldersResponse:
    """Browse Google Drive folders for the connected source.

    Lists immediate child folders of `parent_id` (default: Drive root).
    Requires an active (non-disconnected) Google Drive connector on the source.
    """
    await _require_owned_source(source_id, user_id, db)

    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
            SourceConnector.connector_type == "google_drive",
        )
    )
    connector_row = conn_result.scalar_one_or_none()
    if connector_row is None:
        raise HTTPException(status_code=404, detail="No Google Drive connector configured for this source")

    from src.connectors.secrets import decrypt_credentials
    from src.connectors.google_drive_tokens import DriveTokenManager
    import httpx

    credentials = decrypt_credentials(connector_row.credentials_encrypted)
    if not credentials.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Google Drive connector is disconnected")

    token_manager = DriveTokenManager(
        connector_row=connector_row,
        credentials=credentials,
        client_id=settings.google_drive.client_id,
        client_secret=settings.google_drive.client_secret,
        redirect_uri=settings.google_drive.redirect_uri,
    )
    access_token = await token_manager.get_access_token(db)

    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    params = {
        "q": q,
        "fields": "files(id,name),nextPageToken",
        "pageSize": 200,
        "orderBy": "name",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch Drive folders")

    data = resp.json()
    folders = [
        DriveFolderItem(id=f["id"], name=f["name"])
        for f in data.get("files", [])
    ]
    return DriveFoldersResponse(parent_id=parent_id, folders=folders)


# ---------------------------------------------------------------------------
# POST /api/v1/sources/{source_id}/connector/google-drive/configure
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/connector/google-drive/configure", status_code=200)
async def google_drive_configure(
    source_id: str,
    body: ConnectorDriveConfigureRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorResponse:
    """Set (or update) the target folder and/or collection for a Drive connector.

    - target_folder_id=None means sync from My Drive root.
    - target_collection_id=None means do not auto-add to any collection.
    Can be called after initial OAuth or any time to change the scope.
    """
    source = await _require_owned_source(source_id, user_id, db)

    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
            SourceConnector.connector_type == "google_drive",
        )
    )
    connector_row = conn_result.scalar_one_or_none()
    if connector_row is None:
        raise HTTPException(status_code=404, detail="No Google Drive connector configured for this source")

    if body.target_collection_id is not None:
        coll_result = await db.execute(
            select(Collection).where(
                Collection.id == body.target_collection_id,
                Collection.user_id == user_id,
            )
        )
        if coll_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Collection not found")

    now = datetime.now(timezone.utc)
    connector_row.target_folder_id = body.target_folder_id or None
    connector_row.target_folder_label = body.target_folder_label or None
    connector_row.target_collection_id = body.target_collection_id or None
    connector_row.updated_at = now
    source.name = body.target_folder_label or "Google Drive"
    source.updated_at = now
    await db.commit()
    await db.refresh(connector_row)
    return ConnectorResponse.model_validate(connector_row)
