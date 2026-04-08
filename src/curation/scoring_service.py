"""AI quality scoring service for near-duplicate group best-photo selection (P5-002).

For each image in a near-duplicate group, this service calls the configured AI
vision provider with a quality-focused prompt and stores the response in the
``curation_scores`` table. Scores are per-item and independent of group
membership so that adding new similar photos never invalidates existing scores.

The "best pick" within a group is computed at query time: the item (including
the anchor) with the highest ``quality_score`` is flagged ``is_best_pick``.

All failures are non-fatal: if an individual item cannot be scored (unsupported
MIME, AI error, decode error), scoring is skipped for that item and the rest of
the group continues normally.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.image_prep import prepare_image
from src.config import settings
from src.curation.phash_service import PHASH_THRESHOLD, find_similar
from src.models import CurationScore, MediaItem
from src.storage.file_store import FileStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

SCORING_SYSTEM_PROMPT = """\
You are evaluating the technical and compositional quality of a single photograph.
Return ONLY a JSON object — no markdown fences, no explanation:

{
  "quality_score": <float 0.0–1.0>,
  "rationale": "<one concise sentence, max 80 characters>"
}

Scoring criteria (weight equally):
- Sharpness and focus clarity
- Exposure and brightness balance
- Composition and framing
- Motion blur or camera shake
- Noise, grain, or artefacts

1.0 = technically excellent photo with strong composition
0.5 = usable but has noticeable issues
0.0 = severely degraded (heavily blurred, massively over/under-exposed)

If an AI-generated title is provided, also consider whether the image captures
the subject moment well (expression, action, timing).
"""

# MIME types we will attempt to score (must be decodable by image_prep)
_SCORABLE_MIME_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
    "image/bmp",
    "image/avif",
})


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class ScoreResult:
    """Raw AI scoring output for a single media item."""
    quality_score: float
    rationale: str
    scoring_model: str


@dataclass
class GroupScoreResult:
    """Aggregated scoring output returned from ``score_group``."""
    anchor_id: str
    scored_count: int
    failed_count: int
    best_pick_id: str | None


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _clamp(value: float) -> float:
    """Clamp a float to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


async def _call_ai_score(
    file_bytes: bytes,
    mime_type: str,
    title_hint: str | None,
    model: str,
) -> ScoreResult | None:
    """Prepare the image and call the AI provider for a quality score.

    Returns ``None`` when:
    - The MIME type is not scorable.
    - Image preparation fails.
    - The AI call fails.
    - The response cannot be parsed.

    All failures are logged at WARNING level.
    """
    if mime_type not in _SCORABLE_MIME_TYPES:
        logger.debug("Scoring skipped: unsupported MIME %s", mime_type)
        return None

    try:
        image_b64, media_type = await prepare_image(file_bytes, mime_type)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scoring failed during image prep (mime=%s): %s", mime_type, exc)
        return None

    # Build the user message
    user_text = "Evaluate the quality of this photograph and return the JSON score."
    if title_hint:
        user_text += f'\n\nImage title for context: "{title_hint}"'

    # Import here to avoid circular imports at module load time
    from anthropic import AsyncAnthropic, APIError, APITimeoutError, AuthenticationError
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("Scoring skipped: ANTHROPIC_API_KEY not set")
        return None

    client = AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            system=SCORING_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
            timeout=settings.analysis.timeout_seconds,
        )
    except (AuthenticationError, APITimeoutError, APIError) as exc:
        logger.warning("AI scoring API error: %s", exc)
        return None

    raw_text = response.content[0].text.strip()
    logger.debug("Scoring raw response: %s", raw_text[:300])

    try:
        data = json.loads(raw_text)
        score = _clamp(float(data["quality_score"]))
        rationale = str(data["rationale"])[:120]  # guard against oversized rationale
        return ScoreResult(
            quality_score=score,
            rationale=rationale,
            scoring_model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse AI scoring response: %s — raw: %s", exc, raw_text[:200])
        return None


async def _upsert_score(
    db: AsyncSession,
    media_item: MediaItem,
    result: ScoreResult,
) -> CurationScore:
    """Insert or update the CurationScore row for the given media item."""
    now = datetime.now(timezone.utc)
    existing_result = await db.execute(
        select(CurationScore).where(CurationScore.media_item_id == media_item.id)
    )
    score_row = existing_result.scalar_one_or_none()

    if score_row is not None:
        score_row.quality_score = result.quality_score
        score_row.rationale = result.rationale
        score_row.scoring_model = result.scoring_model
        score_row.scored_at = now
    else:
        score_row = CurationScore(
            media_item_id=media_item.id,
            user_id=media_item.user_id,
            quality_score=result.quality_score,
            rationale=result.rationale,
            scoring_model=result.scoring_model,
            scored_at=now,
        )
        db.add(score_row)

    await db.flush()
    return score_row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_best_pick(scores: dict[str, float]) -> str | None:
    """Return the item_id with the highest quality score.

    ``scores`` maps item_id → quality_score (float 0.0–1.0).
    Returns ``None`` when the dict is empty.
    """
    if not scores:
        return None
    return max(scores, key=lambda k: scores[k])


async def score_group(
    anchor_id: str,
    user_id: str,
    db: AsyncSession,
    file_store: FileStore,
) -> GroupScoreResult:
    """Score all members of the near-duplicate group anchored at ``anchor_id``.

    Fetches the anchor and all similar items (within PHASH_THRESHOLD), calls the
    AI provider for each, upserts CurationScore rows, and commits.

    Members that cannot be scored (unsupported MIME, AI failure, missing file)
    are counted in ``failed_count`` and do not abort the rest of the group.

    Returns a ``GroupScoreResult`` with the ID of the best-pick item (highest
    quality_score across the whole group including the anchor).
    """
    # Load anchor
    anchor_result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.analysis_metadata))
        .where(
            MediaItem.id == anchor_id,
            MediaItem.user_id == user_id,
        )
    )
    anchor = anchor_result.scalar_one_or_none()
    if anchor is None:
        raise ValueError(f"Media item {anchor_id!r} not found for user {user_id!r}")

    # Identify group members (similar items) via pHash
    group_items: list[MediaItem] = [anchor]
    if anchor.perceptual_hash:
        hashes_result = await db.execute(
            select(MediaItem.id, MediaItem.perceptual_hash)
            .where(
                MediaItem.user_id == user_id,
                MediaItem.id != anchor_id,
                MediaItem.perceptual_hash.isnot(None),
            )
        )
        candidates: list[tuple[str, str]] = list(hashes_result.all())
        similar_pairs = find_similar(candidates, anchor.perceptual_hash, PHASH_THRESHOLD)
        if similar_pairs:
            similar_ids = [sid for sid, _ in similar_pairs]
            items_result = await db.execute(
                select(MediaItem)
                .options(selectinload(MediaItem.analysis_metadata))
                .where(
                    MediaItem.id.in_(similar_ids),
                    MediaItem.user_id == user_id,
                )
            )
            group_items.extend(items_result.scalars().all())

    model = settings.analysis.model
    scored_ids: dict[str, float] = {}
    failed_count = 0

    for item in group_items:
        try:
            file_bytes = await file_store.read(item.storage_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scoring: cannot read file for item=%s: %s", item.id, exc)
            failed_count += 1
            continue

        # Provide title hint if analysis metadata is available
        title_hint: str | None = None
        if item.analysis_metadata:
            title_hint = item.analysis_metadata.title

        result = await _call_ai_score(file_bytes, item.mime_type, title_hint, model)
        if result is None:
            failed_count += 1
            continue

        await _upsert_score(db, item, result)
        scored_ids[item.id] = result.quality_score
        logger.info(
            "Scored item=%s score=%.3f rationale=%r",
            item.id,
            result.quality_score,
            result.rationale,
        )

    await db.commit()

    best_pick_id = find_best_pick(scored_ids)

    return GroupScoreResult(
        anchor_id=anchor_id,
        scored_count=len(scored_ids),
        failed_count=failed_count,
        best_pick_id=best_pick_id,
    )


async def load_scores_for_items(
    db: AsyncSession,
    item_ids: list[str],
) -> dict[str, CurationScore]:
    """Bulk-load CurationScore rows for a list of item IDs.

    Returns a dict mapping media_item_id → CurationScore.
    Items without scores are absent from the dict (not an error).
    """
    if not item_ids:
        return {}
    result = await db.execute(
        select(CurationScore).where(CurationScore.media_item_id.in_(item_ids))
    )
    return {row.media_item_id: row for row in result.scalars().all()}
