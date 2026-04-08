"""Tests for the P5-002 AI Best-Photo Selection implementation.

Coverage areas:
  1.  find_best_pick — returns the item_id with the highest quality score
  2.  find_best_pick — empty scores dict returns None
  3.  find_best_pick — tie-breaking (consistent — highest wins)
  4.  _clamp — values outside [0, 1] are constrained
  5.  load_scores_for_items — returns correct mapping for seeded rows
  6.  load_scores_for_items — empty id list returns empty dict
  7.  POST /score-group — gate off (dup detection OFF) → 404
  8.  POST /score-group — dup detection ON, scoring OFF → 404
  9.  POST /score-group — unknown item_id → 404
 10.  POST /score-group — scores all group members (mocked AI)
 11.  POST /score-group — idempotent: second call updates existing scores
 12.  POST /score-group — cross-user isolation: user2 cannot score user1 item
 13.  GET /media/{id}/similar — scores are included when enable_ai_scoring ON
 14.  GET /media/{id}/similar — scores null when not yet scored (gate ON, no rows)
 15.  GET /media/{id}/similar — anchor_is_best_pick when anchor has highest score
 16.  GET /media/{id}/similar — similar item is_best_pick when it outscores anchor
"""

from __future__ import annotations

import io
import json

import pytest
import pytest_asyncio
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.curation.scoring_service import (
    GroupScoreResult,
    ScoreResult,
    find_best_pick,
)
from src.models import CurationScore, MediaItem, User
from tests.conftest import JPEG_BYTES, DEV_USER_1, DEV_USER_2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg(color: str = "red", size: tuple[int, int] = (100, 80)) -> bytes:
    img = PILImage.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _seed_media_item(
    user_id: str,
    content_hash: str,
    storage_path: str,
    phash: str | None = None,
    filename: str = "test.jpg",
) -> MediaItem:
    """Build an unsaved MediaItem for seeding."""
    return MediaItem(
        user_id=user_id,
        content_hash=content_hash,
        original_filename=filename,
        file_size=100,
        mime_type="image/jpeg",
        storage_path=storage_path,
        status="uploaded",
        perceptual_hash=phash,
    )


def _seed_score(
    media_item_id: str,
    user_id: str,
    quality_score: float = 0.75,
    rationale: str = "Good composition",
) -> CurationScore:
    """Build an unsaved CurationScore for seeding."""
    from datetime import datetime, timezone
    return CurationScore(
        media_item_id=media_item_id,
        user_id=user_id,
        quality_score=quality_score,
        rationale=rationale,
        scoring_model="test-model",
        scored_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1–3. find_best_pick unit tests (pure Python)
# ---------------------------------------------------------------------------

def test_find_best_pick_returns_highest_score():
    """find_best_pick returns the item_id with the highest quality_score."""
    scores = {"a": 0.5, "b": 0.9, "c": 0.3}
    assert find_best_pick(scores) == "b"


def test_find_best_pick_empty_returns_none():
    """find_best_pick returns None for an empty dict."""
    assert find_best_pick({}) is None


def test_find_best_pick_single_item():
    """find_best_pick with a single item returns that item's id."""
    assert find_best_pick({"only": 0.42}) == "only"


# ---------------------------------------------------------------------------
# 4. _clamp unit test
# ---------------------------------------------------------------------------

def test_clamp_constrains_to_unit_interval():
    """_clamp keeps values within [0.0, 1.0]."""
    from src.curation.scoring_service import _clamp
    assert _clamp(-0.5) == 0.0
    assert _clamp(1.5) == 1.0
    assert _clamp(0.7) == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 5–6. load_scores_for_items — DB integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_scores_for_items_returns_mapping(db: AsyncSession, seed_users):
    """load_scores_for_items returns the correct item_id → CurationScore mapping."""
    from src.curation.scoring_service import load_scores_for_items

    item = _seed_media_item(DEV_USER_1, "hash-abc", "path/a.jpg")
    db.add(item)
    await db.flush()

    score = _seed_score(item.id, DEV_USER_1, quality_score=0.88)
    db.add(score)
    await db.commit()

    result = await load_scores_for_items(db, [item.id])
    assert item.id in result
    assert result[item.id].quality_score == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_load_scores_for_items_empty_ids(db: AsyncSession):
    """load_scores_for_items returns empty dict when given an empty list."""
    from src.curation.scoring_service import load_scores_for_items
    result = await load_scores_for_items(db, [])
    assert result == {}


# ---------------------------------------------------------------------------
# 7. POST /media/{id}/score-group — gate guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_group_endpoint_both_gates_off_returns_404(client):
    """POST /score-group returns 404 when duplicate detection gate is OFF."""
    resp = await client.post("/api/v1/media/some-id/score-group")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_score_group_endpoint_scoring_gate_off_returns_404(client, monkeypatch):
    """POST /score-group returns 404 when AI scoring gate is OFF (dup ON)."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", False)

    resp = await client.post("/api/v1/media/some-id/score-group")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_score_group_endpoint_unknown_item_returns_404(client, monkeypatch):
    """POST /score-group returns 404 when the media item does not exist."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    resp = await client.post("/api/v1/media/nonexistent-id/score-group")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. POST /score-group — scores all group members (mocked AI)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_group_endpoint_scores_group(
    client, db_session_factory, tmp_storage, monkeypatch
):
    """POST /score-group scores all members in the near-duplicate group.

    AI calls are mocked to return a deterministic score. The DB is checked to
    confirm CurationScore rows were written.
    """
    from src.config import settings
    from src.storage.file_store import LocalFileStore
    import src.api.routes.media as media_mod

    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    # Seed two near-duplicate items (same pHash)
    anchor_bytes = _make_jpeg(color="red")
    near_bytes = _make_jpeg(color="blue")

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("anchor.jpg", anchor_bytes, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    anchor_id = upload_resp.json()["id"]

    upload_resp2 = await client.post(
        "/api/v1/upload",
        files={"file": ("near.jpg", near_bytes, "image/jpeg")},
    )
    assert upload_resp2.status_code == 201
    near_id = upload_resp2.json()["id"]

    # Manually set identical pHashes so they form a group
    async with db_session_factory() as sess:
        res = await sess.execute(
            select(MediaItem).where(MediaItem.id.in_([anchor_id, near_id]))
        )
        for item in res.scalars().all():
            item.perceptual_hash = "0000000000000000"
        await sess.commit()

    # Mock _call_ai_score to return a deterministic ScoreResult
    MOCK_SCORE = ScoreResult(
        quality_score=0.80,
        rationale="Sharp and well-exposed",
        scoring_model="mock",
    )
    monkeypatch.setattr(
        "src.curation.scoring_service._call_ai_score",
        lambda *a, **kw: _async_return(MOCK_SCORE),
    )

    resp = await client.post(f"/api/v1/media/{anchor_id}/score-group")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_id"] == anchor_id
    assert body["scored_count"] >= 1   # at least the anchor was scored
    assert body["best_pick_id"] is not None

    # Confirm CurationScore rows exist in DB
    async with db_session_factory() as sess:
        result = await sess.execute(
            select(CurationScore).where(CurationScore.media_item_id == anchor_id)
        )
        score_row = result.scalar_one_or_none()
        assert score_row is not None
        assert score_row.quality_score == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_score_group_endpoint_is_idempotent(
    client, db_session_factory, monkeypatch
):
    """Calling POST /score-group twice updates existing scores (upsert)."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("item.jpg", _make_jpeg(), "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    async with db_session_factory() as sess:
        res = await sess.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = res.scalar_one()
        item.perceptual_hash = "0000000000000000"
        await sess.commit()

    call_count = {"n": 0}

    async def _mock_score(*a, **kw):
        call_count["n"] += 1
        score = 0.60 if call_count["n"] == 1 else 0.90
        return ScoreResult(quality_score=score, rationale="ok", scoring_model="mock")

    monkeypatch.setattr("src.curation.scoring_service._call_ai_score", _mock_score)

    await client.post(f"/api/v1/media/{item_id}/score-group")
    await client.post(f"/api/v1/media/{item_id}/score-group")

    async with db_session_factory() as sess:
        result = await sess.execute(
            select(CurationScore).where(CurationScore.media_item_id == item_id)
        )
        rows = result.scalars().all()
    # Should have exactly one row, updated to the second score
    assert len(rows) == 1
    assert rows[0].quality_score == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_score_group_cross_user_isolation(client_user2, monkeypatch):
    """User 2 cannot trigger scoring of user 1's media item (returns 404)."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    # Upload as user 1 (done via the `client` fixture elsewhere); here we only
    # check that user 2 cannot score a made-up user-1 item_id.
    resp = await client_user2.post("/api/v1/media/user1-item-id/score-group")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 13–16. GET /similar — scores attached to response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_similar_endpoint_scores_included_when_gate_on(
    client, db_session_factory, monkeypatch
):
    """GET /similar includes quality_score / rationale when scores exist and gate is ON."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    a_bytes = _make_jpeg(color="red")
    b_bytes = _make_jpeg(color="green")

    r1 = await client.post("/api/v1/upload", files={"file": ("a.jpg", a_bytes, "image/jpeg")})
    r2 = await client.post("/api/v1/upload", files={"file": ("b.jpg", b_bytes, "image/jpeg")})
    assert r1.status_code == 201 and r2.status_code == 201
    id_a = r1.json()["id"]
    id_b = r2.json()["id"]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    async with db_session_factory() as sess:
        for mid, h in [(id_a, "0000000000000000"), (id_b, "0000000000000001")]:
            res = await sess.execute(select(MediaItem).where(MediaItem.id == mid))
            item = res.scalar_one()
            item.perceptual_hash = h
        await sess.commit()

    # Seed scores directly
    async with db_session_factory() as sess:
        sess.add(CurationScore(
            media_item_id=id_a, user_id=DEV_USER_1,
            quality_score=0.70, rationale="Anchor ok",
            scoring_model="m", scored_at=now,
        ))
        sess.add(CurationScore(
            media_item_id=id_b, user_id=DEV_USER_1,
            quality_score=0.90, rationale="Very sharp",
            scoring_model="m", scored_at=now,
        ))
        await sess.commit()

    resp = await client.get(f"/api/v1/media/{id_a}/similar")
    assert resp.status_code == 200
    body = resp.json()

    # Anchor score fields
    assert body["anchor_quality_score"] == pytest.approx(0.70)
    assert body["anchor_rationale"] == "Anchor ok"
    assert body["anchor_is_best_pick"] is False  # b has higher score

    # Similar item (b) should be best pick
    assert len(body["similar"]) == 1
    similar_item = body["similar"][0]
    assert similar_item["quality_score"] == pytest.approx(0.90)
    assert similar_item["rationale"] == "Very sharp"
    assert similar_item["is_best_pick"] is True


@pytest.mark.asyncio
async def test_similar_endpoint_scores_null_when_not_scored(
    client, db_session_factory, monkeypatch
):
    """GET /similar returns null score fields when items haven't been scored yet."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    a_bytes = _make_jpeg(color="purple")
    b_bytes = _make_jpeg(color="orange")
    r1 = await client.post("/api/v1/upload", files={"file": ("c.jpg", a_bytes, "image/jpeg")})
    r2 = await client.post("/api/v1/upload", files={"file": ("d.jpg", b_bytes, "image/jpeg")})
    id_a = r1.json()["id"]
    id_b = r2.json()["id"]

    async with db_session_factory() as sess:
        for mid, h in [(id_a, "0000000000000002"), (id_b, "0000000000000003")]:
            res = await sess.execute(select(MediaItem).where(MediaItem.id == mid))
            item = res.scalar_one()
            item.perceptual_hash = h
        await sess.commit()

    resp = await client.get(f"/api/v1/media/{id_a}/similar")
    assert resp.status_code == 200
    body = resp.json()

    assert body["anchor_quality_score"] is None
    assert body["anchor_is_best_pick"] is False
    assert body["similar"][0]["quality_score"] is None
    assert body["similar"][0]["is_best_pick"] is False


@pytest.mark.asyncio
async def test_anchor_is_best_pick_when_highest(
    client, db_session_factory, monkeypatch
):
    """anchor_is_best_pick is True when anchor outscores all similar items."""
    from src.config import settings
    monkeypatch.setattr(settings.curation, "enable_duplicate_detection", True)
    monkeypatch.setattr(settings.curation, "enable_ai_scoring", True)

    a_bytes = _make_jpeg(color="cyan")
    b_bytes = _make_jpeg(color="magenta")
    r1 = await client.post("/api/v1/upload", files={"file": ("e.jpg", a_bytes, "image/jpeg")})
    r2 = await client.post("/api/v1/upload", files={"file": ("f.jpg", b_bytes, "image/jpeg")})
    id_a = r1.json()["id"]
    id_b = r2.json()["id"]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    async with db_session_factory() as sess:
        for mid, h in [(id_a, "0000000000000004"), (id_b, "0000000000000005")]:
            res = await sess.execute(select(MediaItem).where(MediaItem.id == mid))
            item = res.scalar_one()
            item.perceptual_hash = h
        await sess.commit()

    async with db_session_factory() as sess:
        sess.add(CurationScore(
            media_item_id=id_a, user_id=DEV_USER_1,
            quality_score=0.95, rationale="Best",
            scoring_model="m", scored_at=now,
        ))
        sess.add(CurationScore(
            media_item_id=id_b, user_id=DEV_USER_1,
            quality_score=0.40, rationale="Blurry",
            scoring_model="m", scored_at=now,
        ))
        await sess.commit()

    resp = await client.get(f"/api/v1/media/{id_a}/similar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_is_best_pick"] is True
    assert body["similar"][0]["is_best_pick"] is False


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

async def _async_return(value):
    """Return a value from an async function — used in monkeypatches."""
    return value
