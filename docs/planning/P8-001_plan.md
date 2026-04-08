# Workstream Plan: P8-001 — Reference-Mode Storage Pivot (Slice A+B)

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P8-001 |
| **Phase** | Phase 8 — Reference-Mode Storage Pivot |
| **Project** | Media Indexing Engine |
| **Dependencies** | P7-002 complete; P7-004 complete; P7-005 complete; P7-006 complete; `ARCH-002-reference-mode-storage.md` is the approved architectural blueprint |
| **Estimated Size** | Large |
| **Created** | 2026-04-07 |
| **Status** | Draft — awaiting operator review |

## Objective

Deliver the first implementation slice of the reference-mode storage pivot by adding retained preview infrastructure and then using that infrastructure to stop retaining full-resolution originals for newly connector-synced items.

This workstream intentionally covers only Slice A and Slice B:

1. Slice A: preview / thumbnail generation and serving infrastructure
2. Slice B: connector-synced items transition from retained full originals to preview-only retention after analysis completes successfully

The purpose of this slice is to establish the minimum retained-asset layer required by `ARCH-002-reference-mode-storage.md` without yet changing browser-upload retention behavior.

## Scope

### In Scope

- Add retained thumbnail / preview infrastructure to the existing `MediaItem` storage model
- Generate and persist a JPEG thumbnail during `UploadService.process_upload()`
- Add a dedicated thumbnail-serving endpoint with backward-compatible fallback behavior for older items
- Switch gallery and item-detail image display to use thumbnail delivery rather than full original bytes
- Add explicit `storage_mode` state on `MediaItem` so full-retention versus preview-only retention is machine-readable
- Change connector sync behavior so newly connector-synced items delete their retained full-resolution original only after analysis succeeds and thumbnail storage is confirmed
- Make `GET /media/{id}/file` return a controlled 404 response when the original is intentionally not retained
- Preserve backward compatibility for pre-existing items with full originals and no generated thumbnails

### Out of Scope

- Browser-upload original deletion or browser-upload preview-only mode
- Source-proxy or connector-mediated "download original from source" behavior
- Video preview infrastructure
- Local agent or device bridge work
- Historical backfill of thumbnails for all existing items
- Historical cleanup migration that deletes already-retained connector originals from older imports

## Locked Decisions

## 1. Thumbnail Format and Dimensions

### Decision

Slice A will generate a single retained JPEG thumbnail with:

- max `800px` on the longest edge
- JPEG quality `85`
- aspect ratio preserved

For P8-001, this retained asset is the product's **preview-class derivative** for both gallery rendering and item-detail display. It is not just a tiny grid icon.

### Reasoning

- `800px` is large enough to support current gallery cards and item-detail display without forcing the frontend to keep loading full originals
- JPEG at quality `85` is operationally simple, broadly supported, and sufficient for photo-preview use
- one retained preview variant is enough for this slice; multiple derivative tiers can be deferred until usage data justifies them
- this keeps P8-001 aligned with `ARCH-002-reference-mode-storage.md`, which requires a retained preview layer for fast UX rather than a database of tiny thumbnails only

### Alternative considered

Generate a larger preview such as `1280px` immediately. Rejected for Slice A+B because the primary goal here is enabling the architecture transition with the smallest useful retained derivative, not solving every later preview-quality tradeoff at once.

### Clarifying policy boundary

If later operator review decides that `800px` is insufficient for detail-view quality in production usage, that should be handled as a later retained-preview sizing revision. It does not change the P8-001 decision that the retained derivative in this slice is the canonical preview-class asset.

## 2. Thumbnail Storage Key Convention

### Decision

The retained thumbnail key format is:

`thumbnails/{user_id}/{content_hash}/thumb.jpg`

### Reasoning

- aligns with the project's existing content-addressed storage shape
- avoids leaking the original filename into the preview path
- stays deterministic across LocalFileStore and S3FileStore
- keeps the preview asset clearly separated from the original-retention path

### Consequence

Original and thumbnail assets are no longer implicitly interchangeable storage objects even when both exist.

## 3. Canonical Signal for Original Retention State

### Decision

`MediaItem.storage_mode` is the canonical field for whether the application retains the original.

Locked values for this slice:

- `full`
- `preview_only`

`storage_path = null` is an enforced storage consequence for `preview_only`, not the primary semantic signal.

### Reasoning

- `storage_mode` is explicit, queryable, and safe for future states without overloading null semantics
- `storage_path = null` alone is too ambiguous because it could also mean data drift, failed persistence, or an unhandled bug
- the architecture needs a machine-readable retention contract, not just absence of a path

### Enforcement rule

- `storage_mode = full` implies `storage_path` should contain a retained original path
- `storage_mode = preview_only` implies `storage_path` must be null after successful deletion
- read paths must still handle unexpected drift defensively rather than assuming the invariant always holds

## 4. Existing-Item Migration Strategy

### Decision

No thumbnail backfill is required for launch.

Migration defaults:

- existing items receive `storage_mode = full`
- existing items receive `thumbnail_path = null`

### Runtime rule

If `thumbnail_path` is null, the new thumbnail endpoint may fall back to the retained original for backward compatibility.

### Consequence

Older items keep working immediately after migration without a storage backfill job.

## 5. Slice B Deletion Timing

### Decision

For newly connector-synced items in Slice B, deletion of the retained full original is synchronous within the sync/orchestration flow after:

1. original ingest succeeded
2. thumbnail generation and storage succeeded
3. AI analysis completed successfully

### Reasoning

- avoids introducing a second cleanup subsystem before the first preview-only retention path is even proven
- ensures the DB record and storage state converge immediately for newly imported connector items
- prevents the project from accumulating a hidden backlog of originals awaiting later deletion

### Consequence

Slice B stays architecturally honest: a connector item either remains `full` because processing failed before the pivot point, or it becomes `preview_only` immediately after successful post-analysis retention handoff.

## 6. Thumbnail Failure Policy

### Decision

Thumbnail generation is not fatal to browser-upload ingestion in this slice, but it is fatal to the Slice B transition to `preview_only`.

### Operational rule

- browser-upload item: keep `storage_mode = full`, keep original, leave `thumbnail_path = null`, and continue to function through fallback behavior
- connector-synced item: do not delete the retained original unless thumbnail generation and storage succeeded first

### Reasoning

- preserves current browser-upload reliability while the preview system rolls out
- protects Slice B from deleting the only retained asset before the preview layer exists

### Consequence

Connector items may temporarily remain `full` when preview generation fails, and that is acceptable for this slice because correctness is more important than aggressive deletion.

## 7. Connector Original Pointer Source of Truth

### Decision

When a connector-synced item moves to `preview_only`, the canonical pointer back to the source original remains the existing `SourceObject` record and its remote key / provider identifier.

### Reasoning

- this workstream should reuse the connector identity model already delivered in Phase 7 rather than inventing a parallel source-pointer system
- Slice D can later build user-facing source-original fetch behavior on top of that existing source-object record

## 8. `/file` Behavior for Preview-Only Items

### Decision

`GET /api/v1/media/{id}/file` must stop throwing an unhandled storage exception when no retained original exists.

For intentionally preview-only items, return HTTP `404` with:

```json
{
  "error_code": "original_not_retained",
  "message": "Original is at the source. Use the source connector to access it."
}
```

### Reasoning

- this is the first concrete user-visible contract change required by the reference-mode pivot
- the API must distinguish intentional non-retention from server failure

## 9. Thumbnail Endpoint Backward Compatibility

### Decision

`GET /api/v1/media/{id}/thumbnail` serves the retained thumbnail when `thumbnail_path` exists and falls back to the original only when:

- `thumbnail_path` is null
- `storage_mode = full`
- `storage_path` still exists

It must not silently fall back to `/file` behavior for `preview_only` items with no retained original.

### Reasoning

- supports launch without a historical thumbnail backfill
- keeps the architecture honest for preview-only items

## 10. Browser Uploads Are Explicitly Unchanged in Slice B

### Decision

Browser-upload items remain `storage_mode = full` in this workstream.

### Reasoning

- avoids mixing connector reference-mode changes with browser intake policy changes
- preserves a smaller review and rollback surface for the first storage-pivot implementation slice

## Implementation Steps

## Backend

### Step 1: Schema Evolution

**Goal:** add the minimum fields required to represent preview retention and explicit original-retention mode.

**Required changes:**

- add `thumbnail_path: Mapped[str | None]` to `MediaItem`
- add `storage_mode: Mapped[str]` to `MediaItem` with default `full`
- create Alembic migration for both fields

**Migration defaults:**

- existing rows: `storage_mode = 'full'`
- existing rows: `thumbnail_path = null`

**Acceptance notes:**

- no historical item should become inaccessible because of the migration
- no backfill job is required for launch

### Step 2: UploadService Thumbnail Generation

**Goal:** generate and persist a retained preview during ingestion.

**Required changes:**

- extend `UploadService.process_upload()` to generate a JPEG thumbnail from the uploaded image bytes
- preserve aspect ratio with longest edge capped at `800px`
- save the thumbnail to the deterministic thumbnail key
- persist `thumbnail_path` on the created `MediaItem`
- leave `storage_mode = full` for ordinary browser-upload items

**Behavior rules:**

- thumbnail generation failure is non-fatal for browser-upload items
- when thumbnail generation fails, log it, keep original retention, and leave `thumbnail_path = null`

### Step 3: Thumbnail Serving Route

**Goal:** create a stable application route for preview delivery.

**Required changes:**

- add `GET /api/v1/media/{id}/thumbnail`
- serve `thumbnail_path` when present
- for existing `full` items with `thumbnail_path = null`, fall back to the retained original bytes
- return a controlled 404 when neither thumbnail nor a retained original is available

**Backward compatibility requirement:**

- older items without thumbnails must still render in the UI at launch

### Step 4: `/file` Route Retention-Aware Behavior

**Goal:** stop treating missing retained originals as an unhandled storage failure.

**Required changes:**

- update `GET /api/v1/media/{id}/file` to check `storage_mode` and `storage_path`
- for `preview_only` items, return the locked `original_not_retained` 404 response
- for `full` items where the file is unexpectedly missing, return a controlled not-found/server-safe response rather than an unhandled exception

**Reasoning for implementation scope:**

Even though Slice D will later define connector-mediated original retrieval, Slice A+B must first make the existing route retention-aware and non-fragile.

### Step 5: Connector Sync Transition to Preview-Only Retention

**Goal:** stop retaining the full-resolution original for newly connector-synced items once preview retention and analysis are safely complete.

**Required changes:**

- update `sync_service._run_sync()` orchestration so connector-synced items are eligible for retention downgrade after successful processing
- require the following before deletion:
  - `thumbnail_path` exists and thumbnail bytes were stored successfully
  - analysis completed successfully
  - `SourceObject` identity record exists for source-original recovery later
- delete the retained full original from `_file_store`
- set `MediaItem.storage_path = null`
- set `MediaItem.storage_mode = 'preview_only'`

**Failure handling:**

- if thumbnail generation/storage failed, do not delete the original
- if analysis failed, do not delete the original
- if storage deletion fails, do not mark the item `preview_only`

### Step 6: Storage-Mode Guardrails and Logging

**Goal:** make the new retention transition observable and debuggable.

**Required changes:**

- add structured logging around thumbnail generation success/failure
- add structured logging around connector original deletion success/failure
- add explicit guardrails so `preview_only` is never written before deletion succeeds

**Reasoning:**

This is the first slice that intentionally nulls `storage_path`; silent drift would be expensive to debug later.

## Frontend

### Step 7: Gallery Preview Source Switch

**Goal:** stop using `/file` as the default display path for list/grid imagery.

**Required changes:**

- gallery cards switch from `/api/v1/media/{id}/file` to `/api/v1/media/{id}/thumbnail`
- existing auth-image loading utilities continue to work against the new endpoint

**Expected effect:**

- existing items continue to render via fallback
- newly connector-synced preview-only items render without relying on retained originals

### Step 8: Item-Detail Display Switch

**Goal:** make detail-page display rely on retained preview delivery rather than the original-file route.

**Required changes:**

- item-detail visual display switches to `/thumbnail`
- explicit original-download actions, if present, continue using `/file`

**Reasoning:**

The UI must visually succeed for preview-only items before the original-retention deletion path is introduced.

### Step 9: Explicit Original-Access Messaging

**Goal:** make preview-only behavior understandable rather than looking like a broken image fetch.

**Required changes:**

- ensure original-download actions surface the `original_not_retained` response cleanly
- show user-facing messaging that the original remains at the source connector when appropriate

## Migration Notes

- Existing rows migrate to `storage_mode = 'full'` and `thumbnail_path = null`.
- No thumbnail backfill runs in this slice.
- Existing browser-upload items continue to behave exactly as retained-full items.
- Existing connector-synced items also remain `full` until they are newly ingested or otherwise explicitly processed by the new Slice B logic; this slice does not retro-delete historical retained originals.
- `thumbnail_path = null` is valid at launch and is expected for older data.
- `storage_path = null` is valid only for items intentionally transitioned to `preview_only` in the new flow.

## Rollout and Rollback Guidance

## Rollout Sequence

### 1. Deploy schema and read-path support first

The first deployment step must safely introduce:

- `thumbnail_path`
- `storage_mode`
- `/thumbnail` read path
- retention-aware `/file` behavior

This step must be backward-compatible with existing rows that still have:

- `storage_mode = full`
- `thumbnail_path = null`
- retained originals only

### 2. Verify backward-compatible thumbnail serving

Before enabling connector preview-only deletion behavior, validate in the deployed environment that:

- older items without thumbnails still render through `/thumbnail` fallback
- browser-upload items still render and download normally
- `/file` continues serving retained originals for `full` items
- `preview_only` error handling is correct where exercised in tests or controlled validation data

### 3. Enable connector preview-only transition only after preview delivery is proven

The synchronous deletion path for newly connector-synced items should only be considered active once the operator has validated that thumbnail creation and thumbnail serving are functioning correctly in the real deployment environment.

### 4. Validate first connector imports explicitly

The first production-like connector syncs after deployment must be manually checked for:

- thumbnail written successfully
- gallery renders from `/thumbnail`
- item detail renders from `/thumbnail`
- `storage_mode = preview_only` only after analysis success and successful original deletion
- `/file` returns the locked `original_not_retained` response for transitioned items

## Post-Deploy Validation Checklist

- Run migration successfully and confirm existing records default to `storage_mode = full`
- Upload a browser-local item and confirm:
  - original retained
  - thumbnail generated when possible
  - gallery/detail render correctly
- Sync at least one new connector item and confirm:
  - thumbnail exists
  - item renders in gallery/detail
  - original is deleted only after successful analysis + thumbnail persistence
  - `storage_mode` flips to `preview_only`
  - `/file` returns the locked 404 payload for the transitioned item
- Confirm that a connector item with simulated thumbnail-generation failure or analysis failure remains `full`

## Rollback Guidance

### Immediate rollback trigger examples

- thumbnail route fails for existing items and causes broad image-display regression
- connector-synced items transition to `preview_only` but thumbnails are missing or unreadable
- synchronous deletion runs before stable preview delivery is confirmed
- unexpected drift causes `storage_mode = preview_only` while original deletion did not actually complete

### Rollback posture for this slice

- stop new connector preview-only transitions first
- preserve already-retained originals where they still exist
- treat `storage_mode` as the control point for halting further retention downgrades
- do not broaden deletion behavior while investigating thumbnail-serving or state-transition defects

### Operational recovery rule

If thumbnail delivery is failing after deploy, the safe recovery path is:

1. halt or disable the Slice B transition path for new connector imports
2. continue operating items as `full` where originals are still retained
3. fix preview generation or thumbnail serving first
4. only then resume connector `preview_only` transitions

### Important limitation

This workstream does not define automatic restoration of originals after successful deletion. Once a connector item has already transitioned to `preview_only`, rollback means stopping further transitions and fixing the preview path, not reconstructing deleted retained originals from app storage.

That limitation is acceptable in P8-001 because the source original remains the canonical original outside the app, but it makes rollout sequencing and first-import validation mandatory.

## Test Plan Outline

### 1. Migration Tests

- migration adds `thumbnail_path` and `storage_mode` without breaking existing rows
- migrated existing items default to `storage_mode = full`
- migrated existing items default to `thumbnail_path = null`

### 2. UploadService Tests

- browser upload stores original and thumbnail successfully
- generated thumbnail respects JPEG / max-800px / quality expectations as far as practical in tests
- browser upload with thumbnail-generation failure still succeeds with `thumbnail_path = null` and `storage_mode = full`

### 3. Thumbnail Route Tests

- `/thumbnail` serves retained thumbnail when present
- `/thumbnail` falls back to original for older `full` items with `thumbnail_path = null`
- `/thumbnail` returns controlled not-found when no thumbnail and no retained original exist

### 4. `/file` Route Tests

- `/file` still serves retained originals for `full` items
- `/file` returns locked `original_not_retained` 404 payload for `preview_only` items
- `/file` no longer throws an unhandled exception when the DB row exists but storage is missing

### 5. Connector Slice B Tests

- connector-synced item becomes `preview_only` only after thumbnail and analysis succeed
- original bytes are deleted after successful transition
- `storage_path` is null after successful transition
- `storage_mode` remains `full` if thumbnail generation fails
- `storage_mode` remains `full` if analysis fails
- transition does not occur unless a `SourceObject` pointer exists

### 6. Frontend Tests

- gallery uses `/thumbnail` for image display
- item-detail uses `/thumbnail` for image display
- explicit original-download path continues to use `/file`
- preview-only original access surfaces a user-facing message rather than a broken image state

### 7. Regression Coverage

- older items without thumbnails still render in gallery and detail
- browser-upload behavior remains unchanged
- connector sync still completes for supported images after the retention change

## What Is NOT Being Decided Here

- Whether browser-upload items should later become `preview_only` as part of Slice C
- Whether the application should fetch and stream the source original on demand through `/file` or a new route in Slice D
- Whether multiple preview tiers, WebP previews, or CDN-delivered variants should replace the single retained JPEG thumbnail later
- Whether historical connector originals already stored in AWS/local storage should be backfilled and deleted retroactively
- Whether local-agent and device-bridge workflows need a different preview policy
- Any video preview or poster-frame strategy

## Next Gate

Operator reviews and approves this Slice A+B plan before any Engineer implementation begins for Phase 8 reference-mode storage work.