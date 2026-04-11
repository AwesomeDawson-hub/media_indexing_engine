from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from scripts.backfill_p9_004_capabilities_writeback import backfill
from src.api.schemas import ConnectorResponse
from src.auth.google_drive_oauth import DRIVE_SCOPE_READONLY, DRIVE_SCOPE_READWRITE
from src.analysis.source_capability_service import upsert_drive_capability_snapshot
from src.models import (
    MediaItem,
    MediaMetadata,
    OriginAssetRef,
    Source,
    SourceCapabilitySnapshot,
    SourceConnector,
    SourceMutationHistory,
    WriteBackOperation,
)
from tests.conftest import DEV_USER_1, JPEG_BYTES

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encrypt_credentials(creds: dict) -> str:
    f = Fernet(_TEST_FERNET_KEY.encode("utf-8"))
    return f.encrypt(json.dumps(creds).encode("utf-8")).decode("utf-8")


async def _make_drive_item(db, *, mutation_state: str | None = None, granted_scopes: str = DRIVE_SCOPE_READWRITE):
    source = Source(id=_new_id(), user_id=DEV_USER_1, name="Drive", source_type="google_drive")
    db.add(source)
    connector = SourceConnector(
        id=_new_id(),
        source_id=source.id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        remote_container_id="root",
        remote_container_label="My Drive",
        credentials_encrypted=_encrypt_credentials({"refresh_token": "rt"}),
        granted_scopes=granted_scopes,
    )
    db.add(connector)
    item = MediaItem(
        id=_new_id(),
        user_id=DEV_USER_1,
        content_hash=_new_id().replace("-", ""),
        original_filename="photo.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=None,
        status="completed",
        source_id=source.id,
        mutation_state=mutation_state,
    )
    db.add(item)
    db.add(OriginAssetRef(
        id=_new_id(),
        media_item_id=item.id,
        user_id=DEV_USER_1,
        source_id=source.id,
        provider_type="google_drive",
        provider_object_id="drive-file-id",
        locator_snapshot="drive-file-id",
    ))
    db.add(MediaMetadata(
        id=_new_id(),
        media_item_id=item.id,
        title="Golden Gate",
        description="desc",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="ctx",
        mood="calm",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors="[]",
        ai_provider="mock",
        ai_model="mock",
        analyzed_at=_now(),
    ))
    await db.flush()
    return source, connector, item


async def _get_origin_asset_ref(db, media_item_id: str) -> OriginAssetRef:
    result = await db.execute(select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_backfill_capability_snapshot_readonly_scope(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, connector, _item = await _make_drive_item(db, granted_scopes=DRIVE_SCOPE_READONLY)
        await db.commit()

    stats = await backfill(_db_factory=db_session_factory)
    assert stats["capability_backfilled"] == 1

    async with db_session_factory() as db:
        result = await db.execute(select(SourceCapabilitySnapshot).where(SourceCapabilitySnapshot.source_connector_id == connector.id))
        snapshot = result.scalar_one()
        assert snapshot.can_write is False
        assert snapshot.scope_tier == "read_only"


@pytest.mark.asyncio
async def test_backfill_capability_snapshot_writable_scope(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, connector, _item = await _make_drive_item(db, granted_scopes=DRIVE_SCOPE_READWRITE)
        await db.commit()

    await backfill(_db_factory=db_session_factory)

    async with db_session_factory() as db:
        result = await db.execute(select(SourceCapabilitySnapshot).where(SourceCapabilitySnapshot.source_connector_id == connector.id))
        snapshot = result.scalar_one()
        assert snapshot.can_write is True
        assert snapshot.scope_tier == "writable"


@pytest.mark.asyncio
async def test_capability_snapshot_upsert_updates_existing_row(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, connector, _item = await _make_drive_item(db, granted_scopes=DRIVE_SCOPE_READONLY)
        first = await upsert_drive_capability_snapshot(db, connector)
        await db.flush()
        first_id = first.id

        connector.granted_scopes = DRIVE_SCOPE_READWRITE
        second = await upsert_drive_capability_snapshot(db, connector)
        await db.commit()

    async with db_session_factory() as db:
        snapshots = (await db.execute(select(SourceCapabilitySnapshot).where(SourceCapabilitySnapshot.source_connector_id == connector.id))).scalars().all()
        assert len(snapshots) == 1
        assert snapshots[0].id == first_id
        assert second.id == first_id
        assert snapshots[0].can_write is True
        assert snapshots[0].scope_tier == "writable"


def test_connector_response_prefers_snapshot_value():
    connector = SourceConnector(
        id=_new_id(),
        source_id=_new_id(),
        user_id=DEV_USER_1,
        connector_type="google_drive",
        remote_container_id="root",
        remote_container_label="My Drive",
        credentials_encrypted="encrypted",
        granted_scopes=DRIVE_SCOPE_READWRITE,
        created_at=_now(),
        updated_at=_now(),
    )
    response = ConnectorResponse.from_connector(connector, has_write_scope=False)
    assert response.has_write_scope is False


@pytest.mark.asyncio
async def test_drive_rename_creates_applied_operation(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "cid")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "secret")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", "http://localhost/callback")

    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        await db.commit()

        patch_resp = MagicMock()
        patch_resp.status_code = 200
        patch_resp.json.return_value = {"id": "drive-file-id", "name": "golden_gate.jpg"}
        with (
            patch("src.connectors.google_drive_tokens.DriveTokenManager.get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=patch_resp),
        ):
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()

    async with db_session_factory() as db:
        result = await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))
        operation = result.scalar_one()
        assert operation.state == "applied"
        assert operation.requested_filename == "golden_gate.jpg"


@pytest.mark.asyncio
async def test_drive_rename_transient_failure_marks_failed_operation(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "cid")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "secret")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", "http://localhost/callback")

    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        await db.commit()

        patch_resp = MagicMock()
        patch_resp.status_code = 500
        patch_resp.text = "boom"
        with (
            patch("src.connectors.google_drive_tokens.DriveTokenManager.get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=patch_resp),
        ):
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))).scalar_one()
        refreshed_item = (await db.execute(select(MediaItem).where(MediaItem.id == item.id))).scalar_one()
        assert operation.state == "failed"
        assert refreshed_item.mutation_state == "pending_writeback"


@pytest.mark.asyncio
async def test_capability_gate_marks_blocked_without_patch_call(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db, granted_scopes=DRIVE_SCOPE_READONLY)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=False,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="read_only",
            verification_state="current",
        ))
        await db.commit()

        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))).scalar_one()
        assert operation.state == "blocked"
        mock_patch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error_code"),
    [
        (403, "drive_permission_denied"),
        (404, "drive_file_not_found"),
    ],
)
async def test_drive_rename_blocking_errors_preserve_history(
    db_session_factory,
    seed_users,
    monkeypatch,
    status_code: int,
    expected_error_code: str,
):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "cid")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "secret")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", "http://localhost/callback")

    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        await db.commit()

        patch_resp = MagicMock()
        patch_resp.status_code = status_code
        patch_resp.text = "blocked"
        with (
            patch("src.connectors.google_drive_tokens.DriveTokenManager.get_access_token", new_callable=AsyncMock, return_value="token"),
            patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=patch_resp),
        ):
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))).scalar_one()
        history_rows = (await db.execute(select(SourceMutationHistory).where(SourceMutationHistory.media_item_id == item.id, SourceMutationHistory.operation_type == "rename"))).scalars().all()
        assert operation.state == "blocked"
        assert operation.last_error_code == expected_error_code
        assert len(history_rows) == 1
        assert history_rows[0].error_code == expected_error_code


@pytest.mark.asyncio
async def test_drive_rename_missing_refresh_token_records_history(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        connector.credentials_encrypted = _encrypt_credentials({"access_token": "at"})
        await db.commit()

        await attempt_drive_rename_after_analysis(db, item)
        await db.commit()

    async with db_session_factory() as db:
        history_rows = (await db.execute(select(SourceMutationHistory).where(SourceMutationHistory.media_item_id == item.id, SourceMutationHistory.operation_type == "rename"))).scalars().all()
        assert len(history_rows) == 1
        assert history_rows[0].error_code == "drive_auth_expired"


@pytest.mark.asyncio
async def test_drive_rename_missing_drive_file_id_records_history(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "cid")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "secret")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", "http://localhost/callback")

    async with db_session_factory() as db:
        source, connector, item = await _make_drive_item(db)
        origin = await _get_origin_asset_ref(db, item.id)
        origin.provider_object_id = None
        origin.locator_snapshot = None
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        await db.commit()

        with patch("src.connectors.google_drive_tokens.DriveTokenManager.get_access_token", new_callable=AsyncMock, return_value="token"):
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()

    async with db_session_factory() as db:
        history_rows = (await db.execute(select(SourceMutationHistory).where(SourceMutationHistory.media_item_id == item.id, SourceMutationHistory.operation_type == "rename"))).scalars().all()
        assert len(history_rows) == 1
        assert history_rows[0].error_code == "no_drive_file_id"


@pytest.mark.asyncio
async def test_retry_endpoint_bootstraps_missing_operation(client, db_session_factory):
    async with db_session_factory() as db:
        _source, _connector, item = await _make_drive_item(db, mutation_state="pending_writeback")
        item.mutation_state = "pending_writeback"
        await db.commit()
        item_id = item.id

    async def _mock_attempt(db, media_item):
        media_item.mutation_state = "fully_applied"

    with patch("src.api.routes.media.attempt_drive_rename_after_analysis", side_effect=_mock_attempt):
        resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")

    assert resp.status_code == 200
    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item_id, WriteBackOperation.operation_type == "rename"))).scalar_one_or_none()
        assert operation is not None


@pytest.mark.asyncio
async def test_retry_endpoint_rejects_non_drive_pending_item(client, db_session_factory):
    upload_resp = await client.post("/api/v1/upload", files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")})
    item_id = upload_resp.json()["id"]

    async with db_session_factory() as db:
        item = (await db.execute(select(MediaItem).where(MediaItem.id == item_id))).scalar_one()
        item.mutation_state = "pending_writeback"
        await db.commit()

    resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")
    assert resp.status_code == 422

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item_id, WriteBackOperation.operation_type == "rename"))).scalar_one_or_none()
        assert operation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "failed"])
async def test_retry_endpoint_accepts_existing_retryable_operation(client, db_session_factory, state: str):
    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db, mutation_state="pending_writeback")
        origin = await _get_origin_asset_ref(db, item.id)
        db.add(WriteBackOperation(
            id=_new_id(),
            media_item_id=item.id,
            origin_asset_ref_id=origin.id,
            user_id=item.user_id,
            source_id=item.source_id,
            source_connector_id=connector.id,
            provider_type="google_drive",
            operation_type="rename",
            state=state,
            attempt_count=1,
        ))
        await db.commit()
        item_id = item.id

    async def _mock_attempt(db, media_item):
        media_item.mutation_state = "fully_applied"

    with patch("src.api.routes.media.attempt_drive_rename_after_analysis", side_effect=_mock_attempt):
        resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_backfill_pending_attempted_maps_to_failed(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, _connector, item = await _make_drive_item(db, mutation_state="pending_writeback")
        item.last_mutation_attempted_at = _now()
        db.add(SourceMutationHistory(
            media_item_id=item.id,
            user_id=item.user_id,
            operation_type="rename",
            new_filename="golden_gate.jpg",
            succeeded=False,
            attempted_at=_now(),
        ))
        await db.commit()

    await backfill(_db_factory=db_session_factory)

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))).scalar_one()
        assert operation.state == "failed"


@pytest.mark.asyncio
async def test_backfill_blocked_maps_to_blocked(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        _source, _connector, item = await _make_drive_item(db, mutation_state="blocked_writeback")
        await db.commit()

    await backfill(_db_factory=db_session_factory)

    async with db_session_factory() as db:
        operation = (await db.execute(select(WriteBackOperation).where(WriteBackOperation.media_item_id == item.id, WriteBackOperation.operation_type == "rename"))).scalar_one()
        assert operation.state == "blocked"


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session_factory, seed_users, monkeypatch):
    import src.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    async with db_session_factory() as db:
        await _make_drive_item(db, mutation_state="pending_writeback")
        await db.commit()

    stats1 = await backfill(_db_factory=db_session_factory)
    stats2 = await backfill(_db_factory=db_session_factory)
    assert stats1["writeback_backfilled"] == 1
    assert stats2["writeback_backfilled"] == 0


# ---------------------------------------------------------------------------
# Auditor remediation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drive_rename_decrypt_failure_records_history(db_session_factory, seed_users, monkeypatch):
    """Credential decryption failure (InvalidToken) writes SourceMutationHistory with drive_auth_expired.

    Finding 2 / Finding 4: blocked exits must record per-attempt audit rows.
    """
    import src.config as cfg_mod
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    async with db_session_factory() as db:
        _source, connector, item = await _make_drive_item(db)
        db.add(SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type="google_drive",
            can_read=True,
            can_write=True,
            can_refetch=True,
            scope_text=connector.granted_scopes,
            scope_tier="writable",
            verification_state="current",
        ))
        # Encrypt with a different key so decryption with _TEST_FERNET_KEY raises InvalidToken.
        wrong_key = Fernet.generate_key()
        wrong_fernet = Fernet(wrong_key)
        connector.credentials_encrypted = wrong_fernet.encrypt(
            json.dumps({"refresh_token": "rt"}).encode()
        ).decode()
        await db.commit()

        await attempt_drive_rename_after_analysis(db, item)
        await db.commit()

    async with db_session_factory() as db:
        history_rows = (await db.execute(
            select(SourceMutationHistory).where(
                SourceMutationHistory.media_item_id == item.id,
                SourceMutationHistory.operation_type == "rename",
            )
        )).scalars().all()
        assert len(history_rows) == 1
        assert history_rows[0].error_code == "drive_auth_expired"
        assert history_rows[0].succeeded is False


@pytest.mark.asyncio
async def test_local_mutation_result_does_not_create_writeback_operation(client, db_session_factory):
    """POST mutation-result stays within locked P7-004 scope.

    Finding 3: the local-browser mutation path must not create durable
    WriteBackOperation rows.  Write-back operations are a P9-004 Drive-only
    concept and must not be expanded to local-browser flows.
    """
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={"succeeded": True, "new_filename": "renamed.jpg"},
    )
    assert resp.status_code == 200

    async with db_session_factory() as db:
        operation = (await db.execute(
            select(WriteBackOperation).where(WriteBackOperation.media_item_id == item_id)
        )).scalar_one_or_none()

    assert operation is None, (
        "POST /mutation-result must not create WriteBackOperation rows for "
        "local-browser flows (P9-004 scope boundary)"
    )


@pytest.mark.asyncio
async def test_retry_endpoint_rejects_non_drive_item_with_existing_operation(client, db_session_factory):
    """Retry endpoint rejects non-Drive items even when a backfill WriteBackOperation row exists.

    Finding 1: the compatibility bootstrap guard must apply unconditionally,
    not just when the operation row is absent.  A non-Drive item must never
    enter a no-op retry flow via a pre-existing operation row.
    """
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    async with db_session_factory() as db:
        item = (await db.execute(
            select(MediaItem).where(MediaItem.id == item_id)
        )).scalar_one()
        item.mutation_state = "pending_writeback"
        # P9-003 creates an OriginAssetRef on upload; use it directly.
        origin = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == item_id)
        )).scalar_one()
        # Simulate a backfill-created WriteBackOperation for a non-Drive item.
        op = WriteBackOperation(
            id=_new_id(),
            media_item_id=item.id,
            origin_asset_ref_id=origin.id,
            user_id=item.user_id,
            provider_type="app_upload",
            operation_type="rename",
            state="pending",
            attempt_count=0,
        )
        db.add(op)
        await db.commit()

    resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")

    assert resp.status_code == 422