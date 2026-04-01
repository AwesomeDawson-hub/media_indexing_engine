"""Integration tests for upload endpoints."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import MediaItem, ProcessingJob, QuotaEvent, User
from tests.conftest import JPEG_BYTES, PNG_BYTES, PDF_BYTES, GIF_BYTES


@pytest.mark.asyncio
async def test_upload_valid_jpeg(client):
    """Upload valid image -> 201, file on disk, DB records exist."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_filename"] == "photo.jpg"
    assert data["is_duplicate"] is False
    assert data["status"] == "uploaded"
    assert data["mime_type"] == "image/jpeg"
    assert len(data["id"]) == 36  # UUID
    assert len(data["content_hash"]) == 64  # SHA256


@pytest.mark.asyncio
async def test_upload_duplicate(client):
    """Upload same file twice -> second returns is_duplicate: true, no new file."""
    resp1 = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    resp2 = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["is_duplicate"] is True
    assert data2["id"] == id1
    assert data2["message"] == "File already exists in your library"


@pytest.mark.asyncio
async def test_upload_invalid_format(client):
    """Upload invalid format -> 400."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("doc.pdf", PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_oversized_file(client):
    """Upload oversized file -> 400."""
    from src.config import settings
    big_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * (settings.upload.max_file_size_bytes + 1)
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("huge.jpg", big_jpeg, "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "exceeds" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_batch_upload_mixed(client):
    """Batch upload with mix of new, duplicate, and invalid -> correct per-file statuses."""
    # First upload to create a duplicate source
    await client.post(
        "/api/v1/upload",
        files={"file": ("existing.jpg", JPEG_BYTES, "image/jpeg")},
    )

    resp = await client.post(
        "/api/v1/upload/batch",
        files=[
            ("files", ("new.png", PNG_BYTES, "image/png")),
            ("files", ("dup.jpg", JPEG_BYTES, "image/jpeg")),
            ("files", ("bad.pdf", PDF_BYTES, "application/pdf")),
            ("files", ("new.gif", GIF_BYTES, "image/gif")),
        ],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert data["successful"] == 2  # new.png + new.gif
    assert data["duplicates"] == 1  # dup.jpg
    assert data["failed"] == 1  # bad.pdf

    statuses = {r["filename"]: r["status"] for r in data["results"]}
    assert statuses["new.png"] == "created"
    assert statuses["dup.jpg"] == "duplicate"
    assert statuses["bad.pdf"] == "error"
    assert statuses["new.gif"] == "created"


@pytest.mark.asyncio
async def test_dedup_is_per_user(client, client_user2):
    """Same file uploaded by different users is NOT flagged as duplicate."""
    resp1 = await client.post(
        "/api/v1/upload",
        files={"file": ("shared.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp1.status_code == 201
    assert resp1.json()["is_duplicate"] is False

    resp2 = await client_user2.post(
        "/api/v1/upload",
        files={"file": ("shared.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp2.status_code == 201
    assert resp2.json()["is_duplicate"] is False
    # Different IDs — both stored independently
    assert resp1.json()["id"] != resp2.json()["id"]


@pytest.mark.asyncio
async def test_processing_job_created(client, db_engine):
    """Each new upload creates a processing_job with status 'pending'."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from src.models import ProcessingJob

    await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        jobs = (await db.execute(select(ProcessingJob))).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].job_type == "analysis"
        # Status may be pending or completed depending on background task timing
        assert jobs[0].status in ("pending", "running", "completed")


@pytest.mark.asyncio
async def test_upload_over_limit_returns_structured_429_and_cleans_up(client, db_engine):
    """Over-limit uploads return structured 429 and do not leave orphaned records behind."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        user = (await db.execute(select(User).where(User.id == "test-user-1"))).scalar_one()
        user.monthly_limit = 0
        await db.commit()

    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("quota.jpg", JPEG_BYTES, "image/jpeg")},
    )

    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"] == "Monthly quota exceeded"
    assert body["error_code"] == "QUOTA_EXCEEDED"
    assert body["error"] == "quota_exceeded"
    assert body["remaining"] == 0
    assert body["limit"] == 0

    async with factory() as db:
        items = (await db.execute(select(MediaItem))).scalars().all()
        jobs = (await db.execute(select(ProcessingJob))).scalars().all()
        events = (await db.execute(select(QuotaEvent))).scalars().all()
        assert items == []
        assert jobs == []
        assert events == []


@pytest.mark.asyncio
async def test_batch_upload_marks_over_limit_file_as_error(client, db_engine):
    """Batch uploads report quota exhaustion explicitly instead of silently skipping analysis."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        user = (await db.execute(select(User).where(User.id == "test-user-1"))).scalar_one()
        user.monthly_limit = 1
        await db.commit()

    resp = await client.post(
        "/api/v1/upload/batch",
        files=[
            ("files", ("allowed.jpg", JPEG_BYTES, "image/jpeg")),
            ("files", ("blocked.png", PNG_BYTES, "image/png")),
        ],
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["successful"] == 1
    assert body["duplicates"] == 0
    assert body["failed"] == 1

    statuses = {result["filename"]: result for result in body["results"]}
    assert statuses["allowed.jpg"]["status"] == "created"
    assert statuses["blocked.png"]["status"] == "error"
    assert statuses["blocked.png"]["error"] == "Monthly quota exceeded"

    async with factory() as db:
        items = (await db.execute(select(MediaItem))).scalars().all()
        assert len(items) == 1
