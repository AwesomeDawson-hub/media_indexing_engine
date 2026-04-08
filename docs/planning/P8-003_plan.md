# Workstream Plan: P8-003 — Historical Connector Preview-Only Migration

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P8-003 |
| **Phase** | Phase 8 — Reference-Mode Storage Pivot |
| **Project** | Media Indexing Engine |
| **Dependencies** | `ARCH-002-reference-mode-storage.md` approved; P8-001 implemented; P8-002 approved and implemented so `_attempt_preview_pivot()` is the canonical replay-safe preview-only transition path |
| **Estimated Size** | Medium |
| **Created** | 2026-04-08 |
| **Status** | Draft — awaiting operator review |

## Objective

Convert historical connector-synced items that still retain full originals into the same `preview_only` end state used by new Phase 8 reference-mode ingestion, without introducing any new eligibility classes or duplicating the deletion logic already centralized in `_attempt_preview_pivot()`.

This workstream is an operational migration slice, not a product-surface slice. Its job is to reduce historical full-original retention for already-imported connector items while preserving the same safety rules already locked in P8-001 and P8-002:

- never delete the original unless a retained thumbnail exists first
- never pivot an item unless its connector source identity is already durable
- keep deletion failure non-fatal and leave the item in a consistent `full` state

## Scope

### In Scope

- Add a one-time operational migration script under `scripts/` for historical connector-backed items already stored as `full`
- Reuse `_attempt_preview_pivot()` directly as the only deletion / `preview_only` transition path
- Backfill a missing thumbnail for an otherwise eligible historical connector item before attempting the pivot
- Process items in bounded batches safe for a live system
- Make the migration idempotent and safe to re-run after interruption or partial completion
- Provide operator-visible progress and final outcome counts through structured logs/stdout

### Out of Scope

- New API endpoints for cleanup orchestration
- Startup-hook cleanup behavior
- New Alembic migrations or schema changes
- New eligibility classes beyond those already enforced by `_attempt_preview_pivot()`
- Migration of manual `__uploads__` items or browser-local working-folder items
- Re-analysis of historical items solely to trigger preview-only transition
- User-facing progress dashboards or DB-backed migration audit tables

## Locked Decisions

## 1. The Migration Lives in a Standalone Script

### Decision

P8-003 will use a standalone Python script under `scripts/`, intended to be run manually via `docker compose exec`, for example:

`docker compose exec backend python -m scripts.migrate_historical_preview_only ...`

### Reasoning

- this is a long-running operational backfill, not a user-facing request/response workflow
- the project already has a precedent for this shape in `scripts/backfill_phash.py`
- a script can support dry-run, staged batches, stop-after limits, and safe reruns without adding API/auth surface area
- a startup hook is unacceptable because it would run on every restart and makes rollback/control worse
- an admin API endpoint would create avoidable HTTP timeout, retry, and operator-control complexity for a one-time migration task

### Consequence

The workstream stays operationally explicit: deploy code, run the script in controlled batches, inspect logs, and re-run if needed.

## 2. Thumbnail Backfill Is In Scope for Eligible Historical Connector Items

### Decision

If a historical connector-backed item is otherwise eligible for preview-only migration but has `thumbnail_path = null`, the script will backfill a thumbnail by reading the retained original, generating JPEG thumbnail bytes through the existing thumbnail helper contract, saving the thumbnail through `FileStore.save_thumbnail()`, persisting `thumbnail_path`, and only then calling `_attempt_preview_pivot()`.

### Reasoning

- most historical items predate P8-001 and therefore have no `thumbnail_path`
- without thumbnail backfill, the migration would skip the majority of the targeted historical set and fail to achieve the Phase 8 storage-cost goal
- generating the thumbnail inside the migration still respects the locked safety rule: no original is deleted unless thumbnail retention is confirmed first
- this does not duplicate preview-only deletion logic because the script only prepares the missing prerequisite and then delegates the actual pivot to `_attempt_preview_pivot()`

### Consequence

P8-003 is a real conversion path for historical connector items, not a mostly-no-op scan that waits for unrelated future re-analysis.

## 3. The Migration Targets Historical Connector Items Only

### Decision

P8-003 migrates only historical connector-backed items that are currently `storage_mode = 'full'` and still retain their original in app storage.

It does not target:

- manual `__uploads__` items
- browser-local working-folder items
- any item not already covered by the connector eligibility rules enforced in `_attempt_preview_pivot()`

### Reasoning

- the main historical storage burden comes from connector-synced items imported before the preview-only pivot existed
- P8-002's browser-local working-folder flow is a separate lifecycle and does not need a historical cleanup migration in the same slice
- the prompt requires that the migration respect the same eligibility rules as P8-002 and introduce no new classes

### Consequence

The selection query narrows the candidate set operationally, and `_attempt_preview_pivot()` still acts as the final authority on eligibility.

## 4. Batches Are Small, Ordered, and Operator-Tunable

### Decision

The script will process candidates in deterministic ordered batches with conservative defaults:

- default `batch_size = 50`
- ordered by `MediaItem.created_at`, then `MediaItem.id`
- optional `--stop-after` limit for staged rollout
- optional short inter-batch sleep such as `--sleep-seconds 0.25` for live-system throttling

### Reasoning

- this repository already uses `50` as the default batch size for backfill work, and it is a safe starting point for file reads, thumbnail generation, and delete operations on a live EC2 deployment
- deterministic ordering keeps partial progress understandable and reruns predictable
- operator-tunable limits are more practical than hard-coded rate limiting because local filesystem and S3-backed environments can behave differently

### Consequence

The migration is safe to stage gradually in production rather than requiring one monolithic run.

## 5. Idempotency Is a Hard Requirement

### Decision

The migration must be safe to rerun without double-deleting, double-pivoting, or corrupting thumbnail state.

Locked idempotency rules:

- items already in `preview_only` are skipped
- items with `storage_path = null` are skipped
- items with an existing `thumbnail_path` do not regenerate a thumbnail
- items whose thumbnail backfill fails remain `full` and can be retried later
- `_attempt_preview_pivot()` remains the only code path that deletes originals and commits `preview_only`

### Reasoning

- live operational migrations are frequently interrupted by deploy windows, container restarts, or staged validation pauses
- idempotent rerun behavior is simpler and safer than trying to persist an extra migration cursor in the database

### Consequence

Restartability comes from deterministic selection plus safe skip rules, not from one-time mutable script state.

## 6. Operator Visibility Uses Logs and Dry-Run, Not New Database State

### Decision

P8-003 will use structured stdout/log output plus a dry-run mode for visibility. It will not add a new DB audit table, progress table, or admin endpoint.

The script will log at minimum:

- eligible count estimate in dry-run mode
- processed count
- migrated count
- thumbnail-backfilled count
- skipped count by major reason
- failed count

### Reasoning

- the migration is one-time operational work, so lightweight logging is sufficient
- adding persistent migration state would widen the slice without improving the correctness of the underlying preview-only transition logic
- Docker Compose and EC2 operations already support capturing and reviewing script output

### Consequence

Operators get actionable progress visibility without adding new product infrastructure.

## 7. No Schema Migration Is Needed

### Decision

P8-003 uses existing Phase 8 fields and models only. No Alembic migration is part of this workstream.

### Reasoning

- `MediaItem.storage_mode`, `MediaItem.thumbnail_path`, `MediaItem.storage_path`, and connector identity via `SourceObject` already exist
- the migration behavior is operational, not structural

### Consequence

Deployment stays bounded to application-code rollout plus explicit post-deploy script execution.

## Implementation Steps

## Backend

### Step 1: Add the Historical Preview-Only Migration Script

**Goal:** create the one-time operational entry point for historical connector item conversion.

**Required changes:**

- add a script under `scripts/`, for example `scripts/migrate_historical_preview_only.py`
- initialize the existing async DB session and file-store stack using the same project config shape as other scripts
- support at minimum:
  - `--dry-run`
  - `--batch-size`
  - `--stop-after`
  - `--user-id`
  - `--source-id`
  - `--sleep-seconds`

**Acceptance notes:**

- the script can be run manually via `docker compose exec backend ...`
- no API endpoint or startup hook is required for migration control

### Step 2: Define the Candidate Query and Skip Rules

**Goal:** ensure the migration only examines historical connector-backed items that might legally pivot.

**Required changes:**

- select `MediaItem` rows ordered by `created_at`, `id`
- narrow the candidate set to items that are currently:
  - `storage_mode = 'full'`
  - `storage_path IS NOT NULL`
  - `source_id IS NOT NULL`
  - associated with a connector-backed `Source`
- allow optional `user_id` / `source_id` filters for staged rollout
- rely on `_attempt_preview_pivot()` as the final eligibility check for `SourceObject` existence and any remaining guard conditions

**Acceptance notes:**

- manual uploads are not processed by this migration
- already-pivoted items are skipped without side effects

### Step 3: Backfill Missing Thumbnails Before Attempting the Pivot

**Goal:** satisfy the retained-preview prerequisite for historical items that predate P8-001 thumbnail generation.

**Required changes:**

- when `thumbnail_path` is missing for a candidate item:
  - read `storage_path` bytes through the existing `FileStore`
  - generate thumbnail bytes using the same thumbnail helper contract used by ingestion
  - save the thumbnail via `FileStore.save_thumbnail(user_id, content_hash, thumb_bytes)`
  - persist `thumbnail_path`
- if thumbnail generation or save fails:
  - log the failure
  - leave the item `full`
  - continue to the next item

**Acceptance notes:**

- no item can proceed to `_attempt_preview_pivot()` without a confirmed retained thumbnail
- thumbnail generation does not require re-analysis

### Step 4: Reuse `_attempt_preview_pivot()` Directly

**Goal:** ensure historical migration uses exactly the same deletion and `preview_only` transition logic as live Phase 8 flows.

**Required changes:**

- after any needed thumbnail backfill, refresh the `MediaItem` state and call `_attempt_preview_pivot(db, media_item, file_store)` directly
- do not duplicate deletion, `storage_mode` mutation, or guard logic in the migration script
- treat the helper's no-op skip behavior as a valid migration outcome when eligibility is not met

**Acceptance notes:**

- there is still only one canonical preview-only deletion path in the codebase
- deletion failure for an individual item is non-fatal and the script continues

### Step 5: Commit in Batches and Throttle Between Batches

**Goal:** keep the migration safe on a live system.

**Required changes:**

- process records in configurable batches rather than loading the entire table into one in-memory mutation pass
- commit durable changes as each item advances, while also emitting per-batch summary logs
- optionally sleep between batches when `--sleep-seconds` is set
- avoid table locks or any update pattern that blocks normal reads/writes broadly

**Acceptance notes:**

- the script can run while normal uploads, analysis, and reads continue
- an interrupted run can resume safely on a later invocation

### Step 6: Add Dry-Run and Summary Reporting

**Goal:** give operators enough visibility to stage and validate the migration safely.

**Required changes:**

- dry-run mode reports how many rows are candidate historical connector items before any writes occur
- log counters throughout the run for:
  - scanned
  - migrated
  - thumbnail_backfilled
  - skipped_already_preview_only
  - skipped_ineligible
  - skipped_missing_original
  - failed_thumbnail_backfill
  - failed_other
- return a non-zero exit code only for script-level failure or when failure counts exceed the chosen tolerance for the run

**Acceptance notes:**

- operators can test with `--dry-run`, then a small `--stop-after` sample, then the remaining staged batches

## Test Plan

### 1. Migration Script Unit / Integration Tests

- dry-run reports eligible candidates without mutating any rows
- already-preview-only items are skipped idempotently
- items with `storage_path = null` are skipped safely
- manual upload items are skipped safely
- connector-backed items with persisted `SourceObject` and existing `thumbnail_path` call `_attempt_preview_pivot()` and end in `preview_only`

### 2. Thumbnail Backfill Tests

- eligible historical connector item with no `thumbnail_path` generates and stores thumbnail, then pivots successfully
- thumbnail generation failure leaves item `full` and does not call the delete path
- thumbnail save failure leaves item `full` and does not corrupt thumbnail/original state

### 3. Idempotency Tests

- rerunning the script after a successful migration does not re-delete or reprocess already-pivoted items
- rerunning after a partial/interrupted batch resumes safely and migrates remaining eligible items
- rerunning after a thumbnail-backfill failure retries only the still-full item

### 4. Live-Path Parity Tests

- the migration uses `_attempt_preview_pivot()` rather than a separate delete implementation
- connector eligibility remains governed by the same `SourceObject` guard as P8-002
- deletion failure remains non-fatal and leaves the item `full`

## Rollout Notes

- Deploy the application code first.
- Do not run any new schema migration for P8-003 because none is required.
- Start with `--dry-run` in the target environment to estimate eligible historical connector items.
- Run a small sample batch first, for example `--batch-size 25 --stop-after 100`, and verify:
  - migrated items now have `storage_mode = 'preview_only'`
  - `storage_path = null`
  - `thumbnail_path` exists
  - connector-linked source identity still exists through `SourceObject`
- If the sample succeeds, continue staged batches with the conservative default batch size or a tuned batch size based on observed storage/DB load.
- If migration stops mid-run, rerun the script; idempotency is the recovery path.

## What Is NOT Being Decided Here

- Whether historical browser-local working-folder items should ever need a similar migration later
- Any user-facing progress reporting for migration coverage
- Any change to thumbnail format, dimensions, or storage key convention from P8-001
- Any source-proxy original-fetch UX
- Any automatic scheduled cleanup of future straggler items

## Next Gate

Operator reviews and approves this plan before Engineer begins P8-003 implementation.
