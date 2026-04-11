"""Durable write-back operation helpers for P9-004."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import MediaItem, MediaMetadata, OriginAssetRef, Source, SourceConnector, SourceMutationHistory, SourceObject, WriteBackOperation

OP_STATE_PENDING = "pending"
OP_STATE_APPLIED = "applied"
OP_STATE_FAILED = "failed"
OP_STATE_BLOCKED = "blocked"


def operation_state_to_mirror_state(state: str) -> str:
    if state == OP_STATE_APPLIED:
        return "fully_applied"
    if state == OP_STATE_BLOCKED:
        return "blocked_writeback"
    return "pending_writeback"


def metadata_payload_hash(payload: str | None) -> str | None:
    if payload is None:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_origin_asset_ref(db: AsyncSession, media_item_id: str) -> OriginAssetRef | None:
    result = await db.execute(
        select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
    )
    return result.scalar_one_or_none()


async def ensure_origin_asset_ref(db: AsyncSession, media_item: MediaItem) -> OriginAssetRef | None:
    origin_asset_ref = await get_origin_asset_ref(db, media_item.id)
    if origin_asset_ref is not None:
        return origin_asset_ref

    provider_type = "app_upload"
    provider_object_id: str | None = None
    locator_snapshot: str | None = None
    revision_marker: str | None = None
    app_storage_path: str | None = media_item.storage_path
    local_file_fingerprint: str | None = None
    source_object_id: str | None = None

    source: Source | None = None
    if media_item.source_id:
        source_result = await db.execute(
            select(Source).where(Source.id == media_item.source_id)
        )
        source = source_result.scalar_one_or_none()

    connector = await get_source_connector(db, media_item)
    if connector is not None:
        provider_type = connector.connector_type
        source_object_result = await db.execute(
            select(SourceObject).where(
                SourceObject.source_id == media_item.source_id,
                SourceObject.last_imported_media_item_id == media_item.id,
            )
        )
        source_object = source_object_result.scalar_one_or_none()
        if source_object is not None:
            source_object_id = source_object.id
            provider_object_id = source_object.external_object_key
            locator_snapshot = source_object.external_object_key
            revision_marker = source_object.external_version
        app_storage_path = None
    elif source is not None and source.source_type == "local_folder":
        provider_type = "local_folder"
        app_storage_path = None
        local_file_fingerprint = media_item.source_file_fingerprint

    origin_asset_ref = OriginAssetRef(
        media_item_id=media_item.id,
        user_id=media_item.user_id,
        source_id=media_item.source_id,
        source_object_id=source_object_id,
        provider_type=provider_type,
        provider_object_id=provider_object_id,
        locator_snapshot=locator_snapshot,
        revision_marker=revision_marker,
        app_storage_path=app_storage_path,
        local_file_fingerprint=local_file_fingerprint,
    )
    db.add(origin_asset_ref)
    await db.flush()
    return origin_asset_ref


async def get_writeback_operation(
    db: AsyncSession,
    *,
    media_item_id: str,
    operation_type: str,
) -> WriteBackOperation | None:
    result = await db.execute(
        select(WriteBackOperation).where(
            WriteBackOperation.media_item_id == media_item_id,
            WriteBackOperation.operation_type == operation_type,
        )
    )
    return result.scalar_one_or_none()


async def get_source_connector(db: AsyncSession, media_item: MediaItem) -> SourceConnector | None:
    if not media_item.source_id:
        return None
    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == media_item.source_id,
            SourceConnector.user_id == media_item.user_id,
        )
    )
    return result.scalar_one_or_none()


async def ensure_writeback_operation(
    db: AsyncSession,
    *,
    media_item: MediaItem,
    origin_asset_ref: OriginAssetRef,
    operation_type: str,
    provider_type: str,
    source_connector_id: str | None,
    requested_filename: str | None = None,
    requested_metadata_payload: str | None = None,
) -> WriteBackOperation:
    now = datetime.now(timezone.utc)
    operation = await get_writeback_operation(
        db,
        media_item_id=media_item.id,
        operation_type=operation_type,
    )
    payload_hash = metadata_payload_hash(requested_metadata_payload)

    if operation is None:
        operation = WriteBackOperation(
            media_item_id=media_item.id,
            origin_asset_ref_id=origin_asset_ref.id,
            user_id=media_item.user_id,
            source_id=media_item.source_id,
            source_connector_id=source_connector_id,
            provider_type=provider_type,
            operation_type=operation_type,
            state=OP_STATE_PENDING,
            requested_filename=requested_filename,
            requested_metadata_payload=requested_metadata_payload,
            requested_metadata_payload_hash=payload_hash,
            attempt_count=0,
        )
        db.add(operation)
        return operation

    operation.origin_asset_ref_id = origin_asset_ref.id
    operation.user_id = media_item.user_id
    operation.source_id = media_item.source_id
    operation.source_connector_id = source_connector_id
    operation.provider_type = provider_type
    if requested_filename is not None:
        operation.requested_filename = requested_filename
    if requested_metadata_payload is not None:
        operation.requested_metadata_payload = requested_metadata_payload
        operation.requested_metadata_payload_hash = payload_hash
    operation.updated_at = now
    return operation


def apply_writeback_operation_to_mirror(
    media_item: MediaItem,
    operation: WriteBackOperation,
) -> None:
    media_item.mutation_state = operation_state_to_mirror_state(operation.state)
    media_item.last_mutation_error_code = operation.last_error_code
    media_item.last_mutation_error_message = operation.last_error_message
    media_item.last_mutation_attempted_at = operation.last_attempted_at
    if operation.operation_type == "rename" and operation.state == OP_STATE_APPLIED:
        media_item.source_filename_applied_at = operation.applied_at
    if operation.operation_type == "metadata_write" and operation.state == OP_STATE_APPLIED:
        media_item.last_writeback_at = operation.applied_at


async def _latest_history_filename(
    db: AsyncSession,
    *,
    media_item_id: str,
    operation_type: str,
) -> str | None:
    result = await db.execute(
        select(SourceMutationHistory.new_filename)
        .where(
            SourceMutationHistory.media_item_id == media_item_id,
            SourceMutationHistory.operation_type == operation_type,
            SourceMutationHistory.new_filename.is_not(None),
        )
        .order_by(desc(SourceMutationHistory.attempted_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def bootstrap_writeback_operation_from_mirror(
    db: AsyncSession,
    *,
    media_item: MediaItem,
    operation_type: str = "rename",
) -> WriteBackOperation | None:
    origin_asset_ref = await ensure_origin_asset_ref(db, media_item)
    if origin_asset_ref is None:
        return None

    connector = await get_source_connector(db, media_item)
    requested_filename = await _latest_history_filename(
        db,
        media_item_id=media_item.id,
        operation_type=operation_type,
    )
    requested_metadata_payload = None

    if requested_filename is None and operation_type == "rename":
        meta_result = await db.execute(
            select(MediaMetadata).where(MediaMetadata.media_item_id == media_item.id)
        )
        metadata = meta_result.scalar_one_or_none()
        if metadata is not None:
            from src.analysis.drive_mutation_service import _target_filename

            requested_filename = _target_filename(metadata.title, media_item.original_filename)

    if operation_type == "metadata_write":
        meta_result = await db.execute(
            select(MediaMetadata).where(MediaMetadata.media_item_id == media_item.id)
        )
        metadata = meta_result.scalar_one_or_none()
        if metadata is not None:
            requested_metadata_payload = json.dumps(
                {
                    "title": metadata.title,
                    "description": metadata.description,
                    "tags": metadata.tags,
                    "objects": metadata.objects,
                    "scenes": metadata.scenes,
                    "context": metadata.context,
                    "mood": metadata.mood,
                    "people": metadata.people,
                    "people_count": metadata.people_count,
                    "orientation": metadata.orientation,
                    "colors": metadata.colors,
                    "location_hint": metadata.location_hint,
                    "quality_notes": metadata.quality_notes,
                },
                sort_keys=True,
            )

    operation = await ensure_writeback_operation(
        db,
        media_item=media_item,
        origin_asset_ref=origin_asset_ref,
        operation_type=operation_type,
        provider_type=origin_asset_ref.provider_type,
        source_connector_id=connector.id if connector else None,
        requested_filename=requested_filename,
        requested_metadata_payload=requested_metadata_payload,
    )

    if media_item.mutation_state == "fully_applied":
        operation.state = OP_STATE_APPLIED
    elif media_item.mutation_state == "blocked_writeback":
        operation.state = OP_STATE_BLOCKED
    elif media_item.mutation_state == "pending_writeback":
        operation.state = OP_STATE_FAILED if media_item.last_mutation_attempted_at else OP_STATE_PENDING
    else:
        operation.state = OP_STATE_PENDING

    operation.last_attempted_at = media_item.last_mutation_attempted_at
    operation.applied_at = media_item.source_filename_applied_at if operation_type == "rename" else media_item.last_writeback_at
    operation.last_error_code = media_item.last_mutation_error_code
    operation.last_error_message = media_item.last_mutation_error_message

    count_result = await db.execute(
        select(func.count(SourceMutationHistory.id)).where(
            SourceMutationHistory.media_item_id == media_item.id,
            SourceMutationHistory.operation_type == operation_type,
        )
    )
    operation.attempt_count = int(count_result.scalar_one() or 0)
    operation.updated_at = datetime.now(timezone.utc)
    return operation