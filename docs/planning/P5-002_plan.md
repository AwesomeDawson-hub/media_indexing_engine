# Workstream Plan: P5-002 — AI Best-Photo Selection

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P5-002 |
| **Phase** | Phase 5 — Smart Curation & Connected Ingestion |
| **Status** | In Progress |
| **Created** | 2026-04-02 |
| **Architect review required** | No — approved in phase plan; builds directly on P5-001 grouping model |
| **Estimated complexity** | M |
| **Dependencies** | P5-001 complete; `pHash`/`perceptual_hash` columns populated; `enable_duplicate_detection` gate exists |

---

## Objective

Within near-duplicate groups detected by P5-001, rank each member by AI-assessed quality and mark the strongest candidate as the recommended best pick. Users can see at a glance which photo in a burst or variant set is worth keeping, without any automatic deletion or hiding.

---

## Design Decisions

### 1. Per-item scoring, not per-group

Each `MediaItem` receives its own `CurationScore` row. The score represents the image's intrinsic technical and compositional quality and is independent of group membership. Groups are dynamic (as new uploads arrive, group membership changes); per-item scores remain stable.

**Rejected:** A per-group record with a single `best_pick_item_id`. This goes stale when group membership changes and is harder to query.

### 2. Best pick is computed at query time

No `is_best_pick` column is stored. When `/media/{id}/similar` is served, the API loads scores for the anchor + all similar items and marks the highest-scoring as the best pick in the response. This always reflects current scores without requiring a background reconciliation job.

### 3. Scoring is explicit and user-triggered

The endpoint `POST /api/v1/media/{id}/score-group` triggers scoring for all members of the near-duplicate group. Calling it again re-scores (idempotent upsert). No automatic re-scoring on group-membership changes in Phase 5.

### 4. Feature gate: `enable_ai_scoring`

Default OFF. Both `enable_duplicate_detection` AND `enable_ai_scoring` must be ON for score endpoints to be active. Gallery and upload flows are not gated — scores only appear in the similar panel and score endpoint.

### 5. AI prompt is quality-focused and concise

The scoring AI call uses the same provider as analysis (Anthropic Claude). The prompt asks for a `quality_score` (0.0–1.0) and a `rationale` (≤ 80 chars). The underlying analysis title is optionally provided for context.

### 6. Advisory only — no automatic delete/hide/archive

Best-pick flags are display hints. No automatic archival or deletion of lower-scoring items in this phase.

---

## Schema

### New table: `curation_scores`

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) PK | UUID |
| `media_item_id` | VARCHAR(36) FK → media_items | UNIQUE — one score per item |
| `user_id` | VARCHAR(36) FK → users | user-scoping for fast queries |
| `quality_score` | FLOAT | 0.0–1.0, higher = better |
| `rationale` | TEXT | ≤ 80-char explanation |
| `scoring_model` | VARCHAR(100) | e.g. `claude-sonnet-4-20250514` |
| `scored_at` | TIMESTAMPTZ | when AI ran |
| `created_at` | TIMESTAMPTZ | row insert time |

Indexes: `ix_curation_scores_media_item_id`, `ix_curation_scores_user_id`.

Alembic revision: `a1b2c3d4e5f6`, down_revision `f1e2d3c4b5a6`.

---

## Config

Add to `CurationConfig`:
```python
enable_ai_scoring: bool = False  # env: ENABLE_AI_SCORING
```

---

## Codebase Changes

### Files to create
- `alembic/versions/a1b2c3d4e5f6_curation_scores.py`
- `src/curation/scoring_service.py`
- `tests/test_scoring.py`

### Files to modify
- `src/models.py` — add `CurationScore` model; add `curation_score` relationship on `MediaItem`
- `src/config.py` — `CurationConfig.enable_ai_scoring`, `load_settings()` env override
- `src/api/schemas.py` — extend `SimilarItemResponse` (score fields); extend `SimilarItemsResponse` (anchor score); add `ScoreGroupResponse`
- `src/api/routes/media.py` — `/similar` includes scores when available; add `POST /media/{id}/score-group`
- `frontend/src/types/api.ts` — extend `SimilarItemResponse`, `SimilarItemsResponse`; add `ScoreGroupResponse`
- `frontend/src/api/client.ts` — add `scoreGroup(id: string)`
- `frontend/src/pages/MediaDetailPage.tsx` — score badges, crown icon, "Score group" button
- `frontend/src/index.css` — quality badge, best-pick crown styles

---

## API

### `GET /api/v1/media/{id}/similar` (extended)
- Existing behaviour preserved.
- When `enable_ai_scoring` is ON: load `CurationScore` rows for anchor + all similar items; compute `is_best_pick` (highest `quality_score` in group); attach to response.
- When scores not yet computed: score fields are `null` / `is_best_pick = false` for all items.

**Extended `SimilarItemResponse`:**
```json
{
  "id": "...",
  "hamming_distance": 3,
  "media_item": { ... },
  "quality_score": 0.82,
  "rationale": "Sharp focus, good exposure, well composed",
  "is_best_pick": true
}
```

**Extended `SimilarItemsResponse`:**
```json
{
  "anchor_id": "...",
  "similar": [...],
  "anchor_quality_score": 0.65,
  "anchor_rationale": "Slightly overexposed",
  "anchor_is_best_pick": false
}
```

### `POST /api/v1/media/{id}/score-group`
- Gate: `enable_ai_scoring` must be ON (else 404).
- Also requires `enable_duplicate_detection` to be ON (else 404).
- Fetches anchor + all similar items.
- Calls AI for each item to obtain `quality_score` + `rationale`.
- Upserts `CurationScore` rows.
- Returns `ScoreGroupResponse`.

**`ScoreGroupResponse`:**
```json
{
  "anchor_id": "...",
  "scored_count": 3,
  "best_pick_id": "...",
  "message": "Scored 3 images. Best pick: img_A.jpg"
}
```

---

## Test Coverage

| # | Test | File |
|---|---|---|
| 1 | `test_score_single_item_returns_score` | test_scoring.py |
| 2 | `test_score_unsupported_mime_returns_none` | test_scoring.py |
| 3 | `test_score_ai_failure_is_non_fatal` | test_scoring.py |
| 4 | `test_score_deterministic_within_threshold` | test_scoring.py |
| 5 | `test_find_best_pick_returns_highest_score` | test_scoring.py |
| 6 | `test_find_best_pick_empty_scores` | test_scoring.py |
| 7 | `test_score_group_endpoint_gate_off_returns_404` | test_scoring.py |
| 8 | `test_score_group_endpoint_scores_group` | test_scoring.py |
| 9 | `test_score_group_is_idempotent` | test_scoring.py |
| 10 | `test_score_group_cross_user_isolation` | test_scoring.py |
| 11 | `test_similar_endpoint_includes_scores_when_gate_on` | test_scoring.py |
| 12 | `test_similar_endpoint_scores_null_when_not_scored` | test_scoring.py |
| 13 | `test_best_pick_is_highest_score_in_group` | test_scoring.py |
| 14 | `test_anchor_is_best_pick_when_highest` | test_scoring.py |

---

## Acceptance Criteria Traceability

| Criterion | Implementation |
|---|---|
| Eligible near-duplicate groups can be scored asynchronously | `POST /media/{id}/score-group` triggers synchronous AI scoring for the group |
| One image in a group can be marked as the recommended best pick | `is_best_pick: bool` computed at query time based on `quality_score` |
| Gallery and/or Media Detail can display the recommendation and a brief rationale | `MediaDetailPage` similar strip shows quality badge + rationale + crown icon |
| Scoring is cached/persisted so repeated view loads do not re-trigger AI work | `CurationScore` table; `/similar` reads from DB, does not re-trigger AI |
| Failed or skipped scoring does not block the duplicate-group experience | `scoring_service.py` returns `None` on error; all failures are logged, non-fatal |
| Tests cover group eligibility rules, persistence, display payloads, and failure handling | 14 tests across all areas |
