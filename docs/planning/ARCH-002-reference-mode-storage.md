# Reference Mode Storage — Architecture Proposal

**Project:** Media Indexing Engine  
**Author:** Architect  
**Date:** 2026-04-05  
**Status:** Awaiting operator approval

---

## 1. Option Evaluation and Recommendation

### Option A — Lazy fetch, never store
Every image request (thumbnail, gallery view, analysis) re-fetches from origin. **Rejected.** Gallery loads would hammer Google Drive on every page view, latency is unacceptable, rate limits are a real risk, and access tokens must be valid on every HTTP request the user makes. Cannot hash or pHash at all without bytes. Not viable.

### Option B — Fetch-once for analysis, discard, proxy every serve
Downloads bytes once (hash + pHash + AI), then deletes from app S3. Every subsequent `GET /media/{id}/file` proxies from origin. **Rejected.** Origin dependency on every gallery request makes the app fragile. User revokes Drive → entire gallery breaks. Latency compounds on every page load.

### Option C — Thumbnail-only cache, redirect full-res to origin
Stores only a small resized thumbnail in app S3. Gallery serves thumbnail fast. Full-res downloads redirect to origin. Viable but: Google Drive has no public presigned URL equivalent. Full-res would still require a proxy fetch with a live token, adding a code path without recovering dedup/pHash/analysis (still need to download anyway).

### Option D — Fetch-once for analysis + thumbnail cache (Hybrid) ✅ RECOMMENDED

1. **At sync time**: download full bytes once → compute SHA-256, pHash, dimensions, MIME → run AI analysis → generate thumbnail → store thumbnail in app S3 → discard full bytes
2. **Gallery display**: serve thumbnail from app S3. Fast. No origin dependency. Token irrelevance for day-to-day use.
3. **Full-resolution download**: proxy from origin on demand. Infrequent, user-initiated, tolerable latency. Requires live token.

**Why this wins:** It preserves every existing capability (dedup, pHash, AI, gallery, semantic search) because bytes are available during the one-time import window. S3 storage cost drops to thumbnail size (~5–15 KB JPEG vs. 3–10 MB original). Gallery performance is unaffected. Full-res download degrades gracefully when Drive token expires rather than breaking the whole gallery.

---

## 2. Data Model Changes

### Additive columns on `media_items`

```python
# New columns — additive, non-breaking, existing rows default to "full"
storage_mode: Mapped[str] = mapped_column(
    String(20), nullable=False, default="full", server_default="full"
)
origin_type: Mapped[str | None] = mapped_column(
    String(20), nullable=True   # "google_drive" | "s3_connector" | None
)
origin_ref: Mapped[str | None] = mapped_column(
    String(500), nullable=True  # Drive file ID, or connector S3 key
)
```

### `storage_path` stays NON-NULL

For reference-mode items, `storage_path` holds the **thumbnail path** in app S3 (e.g., `{user_id}/{content_hash}/thumb.jpg`). It is never null. The existing unique constraint, all test fixtures, and all code paths that read `storage_path` continue to work without modification.

### Storage mode enum (application-level)

| Value | Meaning |
|---|---|
| `"full"` | Full file bytes in app S3. Current behavior. All browser uploads. |
| `"reference_thumbnail"` | Thumbnail in app S3 at `storage_path`. Full bytes at `origin_ref`. |

### `content_hash` dedup stays as-is

SHA-256 is computed from full bytes during the import window, before discard. The `(user_id, content_hash)` unique constraint remains intact. Cross-source dedup still works.

---

## 3. Pipeline Impact Map

| Stage | Current | Reference Mode (connector items only) |
|---|---|---|
| **Sync — download** | `connector.download_object(key)` → full bytes | Unchanged — still downloads full bytes during import |
| **SHA-256 hash** | Computed from full bytes in `upload_service` | Unchanged — computed from full bytes before discard |
| **MIME / dimensions** | PIL on full bytes | Unchanged |
| **pHash** | Computed from full bytes | Unchanged — computed before discard |
| **AI analysis** | `file_store.read(storage_path)` → bytes → Claude | Inlined into sync run before discard; bytes never written to app S3 |
| **Thumbnail generation** | Not done today | **New step**: `ThumbnailService.generate(bytes, max_px=1024)` → JPEG bytes |
| **`file_store.save`** | Saves full bytes | Saves thumbnail bytes only; sets `storage_mode="reference_thumbnail"`, `origin_ref=key` |
| **`GET /media/{id}/file`** | `file_store.read(storage_path)` | Unchanged — returns thumbnail bytes (suitable for gallery) |
| **`GET /media/{id}/download`** | *(new endpoint needed)* | Fetches from origin via `OriginFetcher`; for `full` items, falls back to `file_store.read` |
| **Delete** | `file_store.delete(storage_path)` | Deletes thumbnail from app S3. Does NOT touch origin. |
| **ProcessingJob / analysis queue** | `analyze_media_item` reads `file_store.read(storage_path)` | Analysis runs inline during sync **before** thumbnail-replaces-full. `ProcessingJob` record still created and marked completed. |

### Critical sequencing in sync for reference items

```
download_bytes
  → compute_sha256            (dedup check)
  → check_duplicate           (skip if duplicate)
  → detect_mime + dimensions
  → compute_phash
  → run_ai_analysis(bytes)    ← must happen BEFORE discard
  → generate_thumbnail(bytes) ← must happen BEFORE discard
  → file_store.save(thumbnail_bytes)
  → discard full bytes (GC)
  → create MediaItem(storage_mode="reference_thumbnail", origin_ref=key)
  → mark ProcessingJob completed
```

The analysis step moves from an async background job into the sync run itself for reference-mode items. If AI analysis fails, the sync marks the SourceObject `failed` and retries — same as today.

---

## 4. Token / Auth Dependency

### Risk profile

`DriveTokenManager` is currently instantiated per-sync-run. For full-res download via `OriginFetcher`, we need token access outside a sync run.

**New utility required:** `origin_fetcher.fetch_bytes(media_item, db)` — loads `SourceConnector` for `media_item.source_id`, decrypts credentials, instantiates a `DriveTokenManager` (or short-lived equivalent), refreshes token if stale, fetches the file. Called only from the full-res download endpoint.

### What breaks when Drive access is revoked

| Feature | Affected? | Behavior |
|---|---|---|
| Gallery display (thumbnails) | **No** | Thumbnail in app S3, no token needed |
| Semantic search | **No** | ChromaDB vectors, no token needed |
| AI metadata, tags, scores | **No** | Stored in DB, no token needed |
| Full-res download | **Yes** | `DriveTokenError` → HTTP 503 |
| Re-analysis (re-runs) | **Yes** | Can't re-fetch bytes → analysis fails |

**UX response for 503 on full-res download:**
```json
{
  "error": "origin_unavailable",
  "message": "Full-resolution download requires a valid Google Drive connection. Reconnect Drive in Settings, or the thumbnail version remains available."
}
```

**Risk mitigation:**
- Surface Drive connection status indicator in Settings (already possible via `SourceConnector` status fields)
- On `DriveTokenError` at download time, set `source.connector_status = "error"` to prompt re-auth
- Do not expose token refresh failures as 5xx unless retry also fails

---

## 5. Workstreams

### WS-1: Schema Migration — Small (1–2 days)
**Backend:** Alembic migration adding `storage_mode` (NOT NULL, default `"full"`), `origin_type` (nullable), `origin_ref` (nullable) to `media_items`.  
**Frontend:** None.  
**Dependencies:** None. Ship first.

---

### WS-2: Thumbnail Service — Small (1–2 days)
**Backend:** New `src/storage/thumbnail_service.py`. Takes `bytes + mime_type` → returns JPEG bytes at `max_longest_edge=1024`. Uses PIL (already a dependency).  
**Frontend:** None.  
**Dependencies:** WS-1.

---

### WS-3: Sync Service — Reference Ingest Path — Medium (3–4 days)
**Backend:** Modify `sync_service._run_sync` to branch when connector is reference-eligible. New path: download → hash → dedup → pHash → AI analysis inline → thumbnail → `file_store.save(thumbnail)` → `MediaItem(storage_mode="reference_thumbnail", origin_type=..., origin_ref=key)`. Mark `ProcessingJob` completed inline.  
**Frontend:** None.  
**Dependencies:** WS-1, WS-2.

---

### WS-4: Origin Fetcher — Medium (2–3 days)
**Backend:** New `src/storage/origin_fetcher.py`. Implements `fetch_bytes(media_item, db) → bytes` for `google_drive` and `s3_connector` origin types. For Drive: loads `SourceConnector`, decrypts, uses `DriveTokenManager`. For S3 connector: uses boto3 with connector credentials. Raises `OriginUnavailableError` on token failure.  
**Frontend:** None.  
**Dependencies:** WS-1.

---

### WS-5: Download Endpoint — Small (1 day)
**Backend:** Add `GET /api/v1/media/{id}/download` route. For `storage_mode="full"`: reads `file_store` (current behavior). For `storage_mode="reference_thumbnail"`: calls `origin_fetcher.fetch_bytes(item, db)`. Returns `OriginUnavailableError` as HTTP 503 with structured error body.  
**Frontend:** Wire the existing "Download original" UI action to `/download` instead of `/file`.  
**Dependencies:** WS-1, WS-4.

---

### WS-6: Delete Handling — Small (< 1 day)
**Backend:** Modify media delete logic — for `reference_thumbnail` items, skip any attempt to delete from origin. Only `file_store.delete(storage_path)` (removes thumbnail).  
**Frontend:** None.  
**Dependencies:** WS-1.

---

**Total estimated scope:** ~9–14 days engineering. All workstreams except WS-5 are backend-only.

---

## 6. What Does NOT Change

- **Browser upload pipeline** — `upload_service.process_upload()` untouched. `storage_mode` defaults to `"full"`.
- **`GET /media/{id}/file`** — continues to serve `storage_path` bytes (thumbnail for reference-mode items). Gallery display works without any frontend change.
- **Collections and tagging** — DB-only, no storage dependency.
- **Semantic search** — ChromaDB vectors stored independently.
- **pHash near-duplicate detection** — hash computed at import time, stored in `perceptual_hash`.
- **Quota system** — file size still recorded at import time.
- **AI analysis results** — stored in `media_metadata`. No re-fetch needed.
- **Auth system** — no changes to user auth.
- **The 254-test suite** — schema change is purely additive; `storage_path` remains NOT NULL.

---

## 7. ADR-009: Reference Mode Storage for Connector-Sourced Images

**Status:** Proposed

### Context
The system currently makes a full copy of every connector-sourced image (Google Drive, S3) into the application's own S3 bucket. This incurs storage costs proportional to total image volume across all connected sources. For large Drive collections this can become significant. Browser uploads cannot avoid a copy, but connector images already exist elsewhere.

### Decision
Adopt **Reference Mode (Hybrid)** for connector-sourced images: download full bytes once at sync time for hashing, pHash computation, dimension extraction, AI analysis, and thumbnail generation; store only the thumbnail in app S3; discard full bytes. Record the origin location (`origin_type`, `origin_ref`) on the `MediaItem`. Full-resolution download on user request is served by proxying from origin via `OriginFetcher`.

### Consequences

**Positive:**
- S3 storage cost for connector images drops to thumbnail size (~5–15 KB vs. 3–10 MB per image) — roughly 99% reduction for typical photos.
- Gallery and search remain fully available regardless of origin token validity.
- No capability regression for AI analysis, dedup, pHash, or semantic search.
- Schema change is additive; existing tests require no modification.

**Negative:**
- Full-resolution download requires a live origin token. If Drive access is revoked, download-original is unavailable.
- Sync runs are slightly slower per item: AI analysis runs inline rather than in a background job.
- Re-analysis requires re-fetching from origin for `reference_thumbnail` items.

**Risks:**
- Google Drive API rate limits on full-res downloads if many users simultaneously request originals. Mitigated by thumbnails serving all gallery views.
- Token expiry at download time produces a visible error. Mitigated by clear UX messaging and Drive connection status surface in Settings.

---

**Recommend approving WS-1 (schema migration) and WS-2 (thumbnail service) first as they are pure additions with zero risk.**
