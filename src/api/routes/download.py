"""Download endpoints: single file, batch ZIP, and convert-to-PNG."""

import io
import json
import os
import re
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import BatchDownloadRequest, ConvertResponse
import src.api.routes.upload as upload_mod
from src.api.storage_guards import assert_original_accessible
from src.analysis.schemas import MediaMetadataResult
from src.config import settings
from src.enrichment.embedder import MetadataEmbedder
from src.ingestion.hashing import compute_sha256
from src.models import MediaItem, MediaMetadata, ProcessingJob

router = APIRouter(prefix="/api/v1", tags=["download"])

_embedder = MetadataEmbedder()

# Preferred extensions per MIME type (reliable, platform-independent)
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/tiff": ".tiff",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _ext_for_mime(mime_type: str, fallback_filename: str) -> str:
    """Return a clean file extension for the given MIME type."""
    return _MIME_TO_EXT.get(mime_type) or os.path.splitext(fallback_filename)[1]


def _metadata_to_result(meta: MediaMetadata) -> MediaMetadataResult:
    """Convert DB MediaMetadata to a MediaMetadataResult for the embedder."""
    return MediaMetadataResult(
        title=meta.title,
        description=meta.description,
        tags=json.loads(meta.tags),
        objects=json.loads(meta.objects),
        scenes=json.loads(meta.scenes),
        context=meta.context,
        mood=meta.mood,
        people=json.loads(meta.people),
        people_count=meta.people_count,
        orientation=meta.orientation,
        colors=json.loads(meta.colors),
        location_hint=meta.location_hint,
        quality_notes=meta.quality_notes,
    )


def _sanitize_filename(title: str, extension: str) -> str:
    """Build a filesystem-safe filename from an AI title."""
    if not title or not title.strip():
        return None
    # Replace non-alphanumeric (except spaces, hyphens, underscores) with underscores
    sanitized = re.sub(r"[^\w\s\-]", "_", title, flags=re.UNICODE)
    # Replace spaces with underscores
    sanitized = sanitized.replace(" ", "_")
    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Truncate to 60 chars
    sanitized = sanitized[:60]
    if not sanitized:
        return None
    return f"{sanitized}{extension}"


@router.get("/media/{media_id}/download")
async def download_file(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Download a metadata-enriched image file."""
    # Load media item
    result = await db.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    # P9-002: original must be in app storage to embed metadata and serve enriched file
    assert_original_accessible(item)

    # Load metadata
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_id)
    )
    meta = meta_result.scalar_one_or_none()
    if meta is None:
        raise HTTPException(status_code=409, detail="Analysis not yet completed")

    # Read original file
    file_bytes = await upload_mod._file_store.read(item.storage_path)
    metadata_result = _metadata_to_result(meta)

    # Embed metadata
    enrichment = _embedder.embed(file_bytes, item.mime_type, metadata_result, item.original_filename)

    # Always use AI title as download filename
    ext = _ext_for_mime(enrichment.output_mime_type, item.original_filename)
    download_name = _sanitize_filename(meta.title, ext) or item.original_filename

    return Response(
        content=enrichment.enriched_bytes,
        media_type=enrichment.output_mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.post("/media/download-batch")
async def download_batch(
    body: BatchDownloadRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Download multiple enriched files as a ZIP."""
    if not body.media_ids:
        raise HTTPException(status_code=400, detail="media_ids list is required")

    max_batch = settings.download.max_batch_size
    if len(body.media_ids) > max_batch:
        raise HTTPException(status_code=400, detail=f"Batch size exceeds maximum of {max_batch}")

    # Load items belonging to user
    items_result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(body.media_ids),
            MediaItem.user_id == user_id,
        )
    )
    items = {item.id: item for item in items_result.scalars().all()}

    if not items:
        raise HTTPException(status_code=404, detail="No accessible media items found")

    # Load metadata for these items
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id.in_(list(items.keys())))
    )
    metas = {m.media_item_id: m for m in meta_result.scalars().all()}

    # Build ZIP
    zip_buffer = io.BytesIO()
    included = 0
    skipped = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: set[str] = set()

        for media_id in body.media_ids:
            item = items.get(media_id)
            if item is None:
                skipped += 1
                continue

            meta = metas.get(media_id)
            if meta is None:
                skipped += 1
                continue

            # P9-002: skip items whose original is not in app storage
            from src.api.storage_guards import original_is_accessible
            if not original_is_accessible(item):
                skipped += 1
                continue

            file_bytes = await upload_mod._file_store.read(item.storage_path)
            metadata_result = _metadata_to_result(meta)
            enrichment = _embedder.embed(file_bytes, item.mime_type, metadata_result, item.original_filename)

            # Use AI title as ZIP entry name
            ext = _ext_for_mime(enrichment.output_mime_type, item.original_filename)
            title_name = _sanitize_filename(meta.title, ext)
            zip_name = title_name if title_name else item.original_filename
            base_name, base_ext = os.path.splitext(zip_name)
            counter = 1
            while zip_name in seen_names:
                zip_name = f"{base_name}_{counter}{base_ext}"
                counter += 1
            seen_names.add(zip_name)

            zf.writestr(zip_name, enrichment.enriched_bytes)
            included += 1

    if included == 0:
        raise HTTPException(status_code=404, detail="No analyzed media items found for download")

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="media_export.zip"',
            "X-Included-Count": str(included),
            "X-Skipped-Count": str(skipped),
        },
    )


@router.post("/media/{media_id}/convert-png", status_code=201)
async def convert_to_png(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConvertResponse:
    """Convert a BMP/GIF to PNG with embedded metadata. Creates a new media item."""
    # Load media item
    result = await db.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Verify format
    if item.mime_type not in ("image/bmp", "image/gif"):
        raise HTTPException(status_code=400, detail="Only BMP and GIF files can be converted (other formats support metadata natively)")

    # P9-002: conversion requires the original to be in app storage
    assert_original_accessible(item)

    # Load metadata
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_id)
    )
    meta = meta_result.scalar_one_or_none()
    if meta is None:
        raise HTTPException(status_code=409, detail="Analysis not yet completed")

    # Read and convert
    file_bytes = await upload_mod._file_store.read(item.storage_path)
    metadata_result = _metadata_to_result(meta)
    conversion = _embedder.convert_to_png_with_metadata(file_bytes, metadata_result, item.original_filename)

    # Compute hash and check dedup
    content_hash = compute_sha256(conversion.enriched_bytes)
    from src.ingestion.dedup import check_duplicate
    existing = await check_duplicate(db, user_id, content_hash)
    if existing is not None:
        return ConvertResponse(
            id=existing.id,
            original_filename=existing.original_filename,
            mime_type=existing.mime_type,
            status=existing.status,
            message="PNG version already exists",
        )

    # Store new PNG
    storage_path = await upload_mod._file_store.save(user_id, content_hash, conversion.output_filename, conversion.enriched_bytes)

    # Get dimensions
    from PIL import Image
    img = Image.open(io.BytesIO(conversion.enriched_bytes))
    width, height = img.size

    # Create new media item
    new_item = MediaItem(
        user_id=user_id,
        content_hash=content_hash,
        original_filename=conversion.output_filename,
        file_size=len(conversion.enriched_bytes),
        mime_type="image/png",
        storage_path=storage_path,
        status="completed",
        width=width,
        height=height,
    )
    db.add(new_item)
    await db.flush()

    # Copy metadata record
    new_meta = MediaMetadata(
        media_item_id=new_item.id,
        title=meta.title,
        description=meta.description,
        tags=meta.tags,
        objects=meta.objects,
        scenes=meta.scenes,
        context=meta.context,
        mood=meta.mood,
        people=meta.people,
        people_count=meta.people_count,
        orientation=meta.orientation,
        colors=meta.colors,
        location_hint=meta.location_hint,
        quality_notes=meta.quality_notes,
        ai_provider=meta.ai_provider,
        ai_model=meta.ai_model,
        analyzed_at=meta.analyzed_at,
    )
    db.add(new_meta)
    await db.commit()

    format_name = "GIF" if item.mime_type == "image/gif" else "BMP"
    return ConvertResponse(
        id=new_item.id,
        original_filename=new_item.original_filename,
        mime_type="image/png",
        status="completed",
        message=f"Converted from {format_name} to PNG with embedded metadata",
    )
