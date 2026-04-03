# Workstream Plan: P5-001 — Near-Duplicate Detection Core

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P5-001 |
| **Phase** | Phase 5 — Smart Curation & Connected Ingestion |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 4 complete; Phase 5 plan approved |
| **Estimated Size** | Medium |
| **Created** | 2026-04-02 |
| **Status** | Draft — awaiting operator approval after audit fixes |

## Architect Decision

`P5-001` **should be the first approved implementation workstream**.

Reasoning:
- `P5-002` depends directly on a stable duplicate-group model and should not define grouping implicitly.
- `P5-003` is larger and riskier because it touches sync state, secrets, and ingestion behavior.
- Near-duplicate grouping delivers immediate beta-user value without reopening the broader operational surface that Phase 4 just stabilized.

## Objective

Add user-scoped near-duplicate detection so visually similar images can be grouped and surfaced in the Gallery without changing the existing exact-dedup upload rules. This workstream establishes the perceptual hash pipeline, duplicate-group query model, initial Gallery UX, and a safe backfill path for existing beta libraries.

## Scope

### In Scope

- Compute a perceptual hash (`pHash`) for image media
- Persist pHash data in the relational schema
- Expose a user-scoped grouping/query path for near-duplicates
- Surface duplicate-group indicators in the Gallery
- Provide a detail or expanded group view path so users can inspect similar images
- Backfill pHashes for existing images already in the system
- Reuse the existing ingestion pipeline and exact-dedup rules
- Local validation and AWS beta smoke validation

### Explicit Non-Goals

- No AI best-pick scoring or recommendation logic (`P5-002`)
- No cross-user similarity search
- No automatic archival, hiding, deletion, or merge actions for duplicate groups
- No video duplicate detection
- No connector or source-sync work (`P5-003`)
- No change to exact duplicate behavior based on content hash
- No framework or storage-layer replacement

## Exact Schema Placement for Perceptual Hash Data

### Decision

Store the perceptual hash directly on `media_items`, not in `media_metadata` and not in ChromaDB.

### Why

- pHash is an **asset-level technical fingerprint**, like file size or MIME type, not semantic AI output.
- It should exist even if AI analysis has not completed or is re-run later.
- It should be queryable with simple relational filters and joins to the owning `media_items` row.
- Keeping it out of `media_metadata` avoids coupling duplicate-grouping to the AI metadata contract from ADR-005.

### Recommended schema additions

Add the following nullable columns to `media_items` via Alembic:

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `perceptual_hash` | `VARCHAR(16)` | nullable, indexed | Fixed-width hex representation of a 64-bit pHash |
| `phash_version` | `VARCHAR(20)` | nullable | Allows future algorithm/version changes without silent incompatibility |
| `phash_computed_at` | `TIMESTAMP WITH TIME ZONE` | nullable | Distinguishes backfilled/computed state from missing state |

### Indexing note

The `perceptual_hash` index is **not** expected to accelerate Hamming-distance threshold matching by itself.

- Keep a normal index because it still helps operational queries such as backfill coverage checks, `IS NULL` / `IS NOT NULL` state inspection, and exact-row retrieval during diagnostics.
- Do **not** present the index as the duplicate-matching strategy.
- Phase 5 duplicate matching uses a bounded beta-time derived comparison flow described below.

### Why not a separate table in Phase 5

A separate `media_similarity` or `media_curation` table is not necessary for the core duplicate-detection phase. The smallest durable design is to store the pHash on `media_items`, then compute groups at query time. If later phases need persisted group IDs or scoring records, those can be added without moving the pHash itself.

## Canonical pHash Generation Contract

### Goal

Lock one deterministic decode-and-normalize contract so live ingest and backfill compute comparable hashes across environments.

### Phase 5 supported MIME types for pHash

- `image/jpeg`
- `image/png`
- `image/webp`
- `image/tiff`
- `image/bmp`
- `image/avif`

### Phase 5 excluded MIME types for pHash

- `image/gif`

Reasoning:
- GIF introduces animated-frame ambiguity that is not worth absorbing into the first duplicate-detection phase.
- GIF uploads remain supported by the product, but `perceptual_hash` stays null for GIF assets in Phase 5.

### Canonical normalization rules

- Read the stored original asset through the existing `FileStore`.
- Decode to a raster image using the same Python imaging stack in local and AWS environments.
- Apply EXIF orientation transpose before hashing.
- For images with alpha, composite onto a white background before grayscale conversion.
- Convert to grayscale.
- Resize to a fixed `32x32` raster using a deterministic resampling method.
- Compute a `64-bit` perceptual hash from that normalized raster and persist it as `16` lowercase hex characters.

### Failure behavior

- If a previously accepted upload cannot be decoded for hashing, the upload itself remains valid.
- Store no hash for that asset, leave `perceptual_hash` null, and log the failure for operator review.
- Backfill follows the same rule: skip the asset, count the failure, and continue unless the configured stop threshold is reached.

### Versioning rule

- `phash_version` must encode the canonicalization contract, not just the library name.
- Phase 5 should ship with an explicit version label such as `phash64-v1`.
- Any future change to MIME support, EXIF handling, alpha handling, resize rules, or hash width requires a new `phash_version` value and must not silently overwrite the meaning of existing hashes.

## Grouping / Query Design and User-Scoping Guarantees

### Core rule

All duplicate-group queries are scoped to a single authenticated user at the database layer, per ADR-012.

### Similarity model

- Use a 64-bit pHash representation
- Compare hashes by Hamming distance
- Start with one conservative backend constant threshold of `10` bits for Phase 5 beta validation
- Keep the threshold server-side and non-user-configurable in Phase 5

### Query behavior

- For a given media item, the backend compares only against that same user's other items with non-null `perceptual_hash`
- Candidate matching is restricted to `MediaItem.user_id == user_id`
- The result is a list of similar media IDs plus their distance from the anchor item
- Grouping is **derived**, not manually assigned in this phase

### Performance strategy lock for beta

- Phase 5 beta accepts a bounded derived-query approach rather than a persisted similarity graph.
- `GET /api/v1/media` remains the Gallery page source.
- For each paginated Gallery response, the backend may perform one additional batched comparison pass that loads the current user's non-null hashes once for that request and computes `has_similar` / `similar_count` only for the page of items being returned.
- The Gallery must **not** issue N+1 `/similar` calls per card.
- The backend must **not** imply that plain indexed string lookups solve threshold matching.
- This bounded page-summary approach is acceptable for Phase 5 beta while library size remains within current beta expectations; if profiling shows it is too slow, the feature gate stays off rather than redesigning the API mid-workstream.

### Locked API contract

- `GET /api/v1/media` remains the paginated Gallery source.
- Each returned item may include additive duplicate-summary fields:
  - `has_similar: boolean`
  - `similar_count: number`
- `GET /api/v1/media/{id}/similar` provides drill-down details for a single anchor item.
- The anchor lookup itself must be scoped by `MediaItem.id` plus `user_id`, and it must return `404` for missing or non-owned items.
- The Gallery uses list-endpoint summary fields for indicators and uses the anchor endpoint only for user drill-down.

### Candidate selection behavior

- Duplicate comparison runs only inside the authenticated user's library.
- Only rows with non-null `perceptual_hash` and matching `phash_version` participate in comparison.
- Phase 5 does not require a separate narrowing table or persisted group cache.
- The accepted beta tradeoff is a bounded per-request comparison pass for Gallery page summaries plus anchor-level comparison for drill-down.

### User-scoping guarantees

- Every duplicate query must include `MediaItem.user_id == user_id` in the SQL query itself
- No ChromaDB-based similarity search is used for duplicate grouping
- Similarity computation operates only on the current user's pHash-bearing rows
- No shared group IDs across users

## Gallery UI Approach for Duplicate Groups

### Goal

Expose duplicate groups without rewriting the Gallery's existing browse/search architecture.

### Recommended UX

- Add a subtle group indicator on Gallery items that have near-duplicates, such as:
  - `Similar photos (3)` badge/text
  - stacked thumbnail affordance
- Clicking the indicator opens the Media Detail page, which contains a `Similar photos` strip or panel fed by `GET /api/v1/media/{id}/similar`
- Keep grouped items visible in normal Gallery results. Do not hide them automatically.
- If `has_similar` / `similar_count` are unavailable because the duplicate feature flag is off, the Gallery renders no indicator rather than attempting fallback client-side queries.

### Scope boundary

- Phase 5 core grouping only identifies and surfaces similar images
- It does not yet pick the best one, collapse the whole library by default, or add bulk curation actions

### Why this approach

- It preserves the current Gallery mental model
- It minimizes risk to search, filters, and pagination
- It creates a clean foundation for `P5-002` to layer best-pick logic on top of the same UI surface

## Backfill Strategy for Existing Media

### Requirement

Existing beta-user libraries must participate in duplicate grouping; new uploads alone are insufficient.

### Recommended approach

- Add a backfill script under `scripts/`, for example `scripts/backfill_phash.py`
- Iterate existing `media_items` where:
  - `mime_type` is a supported image type
  - `perceptual_hash IS NULL`
- Read the original file through the existing `FileStore`
- Compute pHash
- Store `perceptual_hash`, `phash_version`, and `phash_computed_at`

### Operational behavior

- Run locally first against a copy/dev dataset
- Ship the duplicate UI behind a temporary feature gate that remains off through migration and initial validation
- Support a `--dry-run` mode that reports eligible rows without writing hashes
- Process records in fixed batches with a resumable cursor (for example by ordered `media_items.id`)
- Run in AWS beta manually after deploy and migration
- Make the script idempotent so interrupted runs can resume safely
- Log counts: processed, skipped, failed, unsupported
- Stop automatically if failures exceed a defined threshold for the run

### Partial-coverage behavior

- During initial AWS rollout, keep the Gallery duplicate indicator feature gate off until migration, smoke upload validation, and an initial backfill sample complete successfully.
- Once the feature gate is enabled, items with null `perceptual_hash` simply show no duplicate indicator and are omitted from similarity results.
- Phase 5 does not expose a separate user-facing `hash coverage` state; mixed coverage is treated as an operational rollout concern, not a new product feature.

### Why not compute everything at migration time

Migrations should change schema, not perform long-running file reads and image processing. Backfill belongs in an explicit operational step or script.

## Ordered Implementation Steps

### Step 1: Schema and Algorithm Decision Lock

**Goal:** lock the pHash storage shape and algorithm/version before implementation starts.

**Files:**
- `docs/DECISION_LOG.md` (ADR if needed at start or closeout)
- `src/models.py`
- `alembic/versions/<new_revision>.py`

**Outputs:**
- chosen pHash width/encoding
- chosen threshold constant (`10` bits unless validation proves it should be tightened before approval)
- chosen version label in `phash_version`

### Step 2: Add Schema Support via Alembic

**Files to modify/create:**
- `alembic/versions/<new_revision>_add_perceptual_hash_to_media_items.py`
- `src/models.py`

**Expected changes:**
- add `perceptual_hash`
- add `phash_version`
- add `phash_computed_at`
- add appropriate operational index(es), without implying they solve Hamming-distance search

### Step 3: Implement pHash Computation Service

**Files to create/modify:**
- `src/curation/__init__.py` (new)
- `src/curation/phash_service.py` (new)
- optionally small utility module under `src/utils/`

**Expected behavior:**
- load image bytes
- apply the canonical normalization contract defined above
- compute fixed-width pHash
- return hex string + version metadata

### Step 4: Wire pHash Generation into Ingestion / Post-Ingest Processing

**Files to modify:**
- `src/ingestion/upload_service.py` and/or post-ingest processing path
- possibly `src/analysis/processor.py` only if pHash is computed post-ingest rather than inline

**Architect preference:**
- compute pHash as close to ingest as practical, but keep failures non-fatal to the upload itself if needed
- do not block core ingestion on a fragile best-effort curation helper without explicit error handling

### Step 5: Add Similarity Query Surface

**Files to modify/create:**
- `src/api/routes/media.py` or new curation route module
- `src/api/schemas.py`
- `src/curation/grouping_service.py` (new, optional if logic should stay out of routes)

**Expected behavior:**
- extend `GET /api/v1/media` with `has_similar` and `similar_count`
- return near-duplicate matches for an anchor media item via `GET /api/v1/media/{id}/similar`
- scope anchor lookup by `id` plus `user_id`, returning `404` when not owned
- enforce `user_id` scoping in SQL
- expose enough metadata for Gallery/Detail presentation

### Step 6: Add Gallery / Detail UI for Duplicate Groups

**Files to modify:**
- `frontend/src/pages/GalleryPage.tsx`
- `frontend/src/pages/MediaDetailPage.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/api.ts`
- optionally one small dedicated component under `frontend/src/components/`

**Expected behavior:**
- show group indicator in Gallery
- allow user to inspect similar photos for an item
- do not auto-hide or auto-collapse items beyond the explicitly approved UI behavior

### Step 7: Add Backfill Script and Runbook

**Files to create/modify:**
- `scripts/backfill_phash.py`
- `README.md` or project deployment notes only if needed

**Expected behavior:**
- idempotent backfill for existing media
- resumable and safe for partial runs
- dry-run support, failure threshold, and batch/cursor controls

### Step 8: Closeout Docs

**Files to update at closeout:**
- `docs/DECISION_LOG.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/WORKSTREAMS.md`
- `docs/CURRENT_STATE.md`
- `docs/PROJECT_HANDOFF.md`
- `docs/PROJECT_MAP.md`

## Validation Checklist

### Backend / Data Validation

- [ ] Alembic migration applies cleanly to current head
- [ ] Existing exact-dedup upload behavior remains unchanged
- [ ] pHash is computed for supported image uploads
- [ ] GIF assets remain accepted but intentionally un-hashed in Phase 5
- [ ] Unsupported or unreadable images fail gracefully without corrupting ingest
- [ ] EXIF orientation, alpha handling, and resize normalization are deterministic across local and AWS environments
- [ ] Similarity queries are always user-scoped at the DB layer
- [ ] Hamming-distance threshold matching behaves consistently for known fixtures
- [ ] Backfill script is idempotent
- [ ] Gallery summary fields are produced without N+1 detail calls
- [ ] Feature gate keeps Gallery indicators off until rollout validation completes

### Frontend / UX Validation

- [ ] Gallery shows duplicate-group indicator only when similar items exist
- [ ] Users can inspect similar photos without losing the normal Gallery flow
- [ ] Search, filters, pagination, and existing Gallery state behavior are not regressed
- [ ] No best-pick or destructive curation behavior appears in this phase

### Test Requirements

- unit/integration tests for pHash computation determinism
- tests for user-scoped similarity queries
- tests for threshold true-positive / false-positive boundaries using controlled fixtures
- tests proving exact content-hash dedup behavior is unaffected
- tests for backfill skip/retry behavior
- frontend build pass and TypeScript clean

## Local Smoke Flow

1. Upload a small burst/variant set of visually similar photos
2. Confirm uploads still follow exact-dedup rules as before
3. Confirm pHash fields are populated for new items
4. Open Gallery and verify the duplicate-group indicator appears
5. Open one item and inspect its similar-photo group
6. Confirm unrelated images do not appear in the same group
7. Run the pHash backfill script against existing local data
8. Re-check Gallery grouping for backfilled items

## AWS Rollout Steps

### Pre-deploy

1. Complete local validation and full relevant tests
2. Create and review the Alembic migration
3. Ship the duplicate feature gate in the `off` state
4. **Back up the AWS PostgreSQL database before deploying any schema change**
5. Deploy application code to AWS beta
6. Run `alembic upgrade head`

### Post-deploy

1. Verify application health on `https://vyzindex.com`
2. Run a smoke upload of similar images
3. Confirm the new schema is present and new uploads populate pHash fields correctly while the feature gate remains off
4. Run `scripts/backfill_phash.py --dry-run` and review eligible/unsupported counts
5. Run a small initial backfill batch and validate grouping quality on that sample
6. Stop immediately if failure counts exceed the configured threshold or grouping quality is unacceptable
7. Run the remaining staged backfill batches
8. Enable the duplicate feature gate only after migration, smoke upload, and initial backfill validation all pass
9. Confirm duplicate-group UI appears as expected on both new and backfilled items

## Rollback Expectations

- If the migration applies but grouping logic is wrong, keep the duplicate feature gate off or disable it immediately while leaving the schema in place.
- If the migration itself is defective, restore the AWS DB backup rather than improvising a risky manual data repair.
- If backfill produces unacceptable false-group behavior, stop the backfill at once, leave existing exact-dedup behavior intact, and keep the duplicate feature surface disabled.
- If only a subset of items was backfilled when rollout stops, that is acceptable because the user-facing duplicate surface remains gated off until validation succeeds.

This workstream should be reversible without affecting core upload, search, billing, or source-registry behavior.

## Risks and Open Questions

- Does the bounded page-summary approach remain fast enough on real beta libraries, or should a persisted candidate-narrowing strategy become a Phase 5.5 follow-up?
- Should future phases surface operator-visible coverage metrics for pHash backfill completeness?

## Notes for Engineer

- Keep pHash as a technical asset signal, not semantic metadata.
- Preserve ADR-012 rigor on every new query.
- Do not introduce Gallery-side N+1 similarity fetching.
- Do not pull AI best-pick logic into this workstream.
- Keep the UI additive and low-risk; the value here is visibility into duplicates, not automatic curation.