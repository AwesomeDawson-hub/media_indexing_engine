# Workstream Plan: P8-002 — Browser-Upload Preview-Only Pivot

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P8-002 |
| **Phase** | Phase 8 — Reference-Mode Storage Pivot |
| **Project** | Media Indexing Engine |
| **Dependencies** | P7-004 complete; `ARCH-002-reference-mode-storage.md` approved; P8-001 approved and implemented as the Slice A+B foundation; existing thumbnail and `storage_mode` infrastructure available |
| **Estimated Size** | Medium-Large |
| **Created** | 2026-04-08 |
| **Status** | Draft — awaiting operator review |

## Objective

Extend the reference-mode storage pivot to browser-local intake only where the application has a durable source-of-truth contract for the original. In practice, this means P8-002 applies to a dedicated no-install local working-folder flow and to the processor-owned retention-downgrade path shared with connector items.

This workstream intentionally reuses the Slice A+B preview infrastructure that already exists from P8-001. Its purpose is to make browser-local items follow the same retained-preview / non-retained-original end state already established for connector-synced items, but only when the original remains durably identifiable outside app storage.

Ordinary browser uploads that land in the current manual `__uploads__` source do not satisfy that contract and therefore remain out of scope for preview-only deletion in this slice.

## Scope

### In Scope

- Define the minimum browser-local source-of-truth contract required before any browser-local item may transition to `preview_only`
- Limit browser-local preview-only behavior to a dedicated no-install local working-folder flow
- Ensure the original is deleted only after successful analysis commit and only when `thumbnail_path` exists
- Move preview-only eligibility from transient caller intent to persisted source-backed rules that survive startup replay
- Centralize preview-only pivot guardrails in the analysis processor rather than duplicating them across flows
- Refactor the existing sync-service Slice B path to use the same processor-owned eligibility rules while preserving the P8-001 connector safety contract
- Keep deletion non-fatal and state-safe when storage deletion fails

### Out of Scope

- New database fields or Alembic migration work
- New background workers, queues, schedulers, or deferred cleanup jobs
- Full browser-intake UX redesign beyond the minimum gating and unsupported-environment behavior needed for safe local working-folder onboarding
- Source-proxy or source-original fetch behavior
- Converting ordinary manual browser uploads in the existing `__uploads__` source to `preview_only`
- Retrospective cleanup of historical browser-upload items already retained as `full`
- Any change to thumbnail generation policy, thumbnail size, or thumbnail route behavior from P8-001

## Locked Decisions

## 1. Browser Preview-Only Applies Only to a Local Working-Folder Flow

### Decision

P8-002 does not apply preview-only retention to ordinary browser uploads that land in the current manual `__uploads__` source. It applies only to browser-local items ingested through a dedicated no-install local working-folder flow.

### Reasoning

- `ARCH-002-reference-mode-storage.md` explicitly rejects leaving plain browser uploads in a source-less `preview_only` state
- an ordinary manual browser upload has no durable external original pointer once the app-retained original is deleted
- the architecture allows a no-install local workflow only when the item is anchored to a user-selected local working folder and later source access can be re-confirmed

### Consequence

Legacy manual browser uploads remain `storage_mode = full` in this slice. P8-002 must not wire the existing `__uploads__` route into preview-only deletion.

## 2. Local Working-Folder Source-of-Truth Contract Is Required Before Deletion

### Decision

A browser-local item may transition to `preview_only` only when all of the following are true:

- it belongs to a dedicated `Source` representing a local working-folder flow, not the generic manual `__uploads__` source
- the selected working folder is the source of truth for the original after intake
- `MediaItem.source_id` points to that local working-folder source
- a durable local-origin rematch signal is persisted before deletion, using existing item-level source fields such as `source_file_fingerprint` and the remembered source filename fields from the P7-004 mutation contract

### Reasoning

- the local working folder is the only browser-local model in `ARCH-002-reference-mode-storage.md` that supports non-hosted originals without a desktop agent
- the app must be able to explain where the original now lives and how future rename/metadata operations will re-find it
- deletion is unsafe if the item has no persisted source anchor beyond the app-stored copy itself

### Consequence

If the local working-folder source contract is not present, the browser-local item stays `full` and P8-002 must treat that as the correct outcome, not as a fallback bug.

## 3. Original Access and Unsupported-Browser Behavior Follow ARCH-002

### Decision

For browser-local preview-only items, original access is a remembered local-source operation, not an app-hosted-file operation.

Locked behavior:

- when local working-folder access is still available, original-facing actions use the remembered local working folder and rematch signals
- when access is no longer available, the product requires folder re-confirmation before source-side operations proceed
- if the browser environment lacks the file-system capabilities needed for the local working-folder flow, that flow is unsupported in that environment and must not opt the item into preview-only deletion

### Reasoning

- this matches `ARCH-002-reference-mode-storage.md` Section 5.8 and Section 6.2
- unsupported environments cannot honestly claim a durable browser-local source-of-truth path

### Consequence

Unsupported browsers must direct the user to a supported browser or a connected cloud source for reference-mode behavior. They must not silently create source-less preview-only items.

## 4. Pivot Eligibility Is Derived From Persisted State, Not a Transient Flag

### Decision

The preview-only pivot logic will live in `analyze_media_item()` in `processor.py`, but eligibility must be computed from persisted database state loaded during processing, not from a transient caller parameter such as `pivot_to_preview_on_success=True`.

### Reasoning

- browser uploads use FastAPI `BackgroundTask`, and startup replay in `src/api/app.py` resumes pending jobs using only persisted job/media-item state
- a function argument passed at enqueue time would be lost if the process restarts before analysis completes
- the processor is still the correct execution boundary, but eligibility must survive replay and retry

### Consequence

Post-analysis retention downgrade becomes a processor-owned concern whose intent is re-derivable from persisted source state on every execution, including resumed jobs.

## 5. Persisted Eligibility Rules Differ by Source Type

### Decision

The processor may attempt preview-only transition only when the persisted source contract proves the original still exists outside app storage.

Locked eligibility rules for this slice:

- connector item: a persisted `SourceObject` identity exists for the item's source, `thumbnail_path` exists, `storage_mode = full`, and the item has completed analysis successfully
- browser-local item: the item belongs to a dedicated local working-folder source, the local rematch fields are already persisted, `thumbnail_path` exists, `storage_mode = full`, and the item has completed analysis successfully
- ordinary manual browser upload in `__uploads__`: never eligible in P8-002

### Reasoning

- restart-safe behavior requires a persisted contract that the processor can recompute on demand
- P8-001 already established `SourceObject` as the canonical original pointer for connector items
- `ARCH-002-reference-mode-storage.md` requires a dedicated local source anchor for browser-local reference mode

### Consequence

The processor decides from persisted source state whether the item is eligible. Caller-side code may still choose when to enqueue analysis, but it does not carry one-time-only pivot intent.

## 6. The Pivot Runs Only After Success Commit

### Decision

The preview-only pivot happens only after:

1. file bytes were already read successfully for analysis
2. analysis completed successfully
3. metadata and status updates were committed successfully

### Reasoning

- `file_store.read(media_item.storage_path)` happens earlier in the same function and must continue to succeed for the AI call
- deleting the original before the success commit would create a race against the current analysis implementation and risk losing the only readable source bytes for that run

### Consequence

The pivot is a post-success transition, not part of the pre-analysis or mid-analysis path.

## 7. Thumbnail Presence Is a Hard Prerequisite

### Decision

The processor must never attempt the pivot unless `media_item.thumbnail_path` is present after the success refresh/commit state is available.

### Reasoning

- P8-002 must never delete the only retained asset
- P8-001 already established that preview retention is the architectural prerequisite for original deletion

### Consequence

If `thumbnail_path` is absent, the item remains `full` and the job still succeeds.

## 8. Deletion Failure Is Non-Fatal and Must Not Leave Drift

### Decision

If `file_store.delete(media_item.storage_path)` fails during the pivot attempt:

- log a warning
- leave `storage_mode = 'full'`
- leave `storage_path` unchanged
- do not fail the job

### Reasoning

- analysis success and metadata persistence should remain durable even if storage cleanup fails
- the application must not claim `preview_only` when the retained original still exists or when deletion outcome is unknown

### Consequence

The pivot is best-effort cleanup layered on top of a successful analysis result, but it is state-safe best-effort cleanup.

## 9. Connector Safety Contract From P8-001 Must Be Preserved

### Decision

P8-002 will refactor the existing sync-service Slice B post-analysis deletion block to use the same processor-owned eligibility path, but it must preserve the P8-001 connector rule that no connector item becomes `preview_only` until source-original identity is durably persisted.

### Reasoning

- `P8-001_plan.md` explicitly locked `SourceObject` as the canonical source pointer for connector items
- current `sync_service.py` performs deletion only after sync already knows which remote object produced the item
- moving deletion into the processor must not accidentally weaken the identity precondition that already protects connector items

### Consequence

The sync refactor must reorder or pre-persist connector identity so `SourceObject` exists before any processor-owned deletion path runs. If that precondition is not satisfied, the item remains `full`.

## 10. No New Async Infrastructure or Hidden Migration

### Decision

The pivot remains synchronous inside the existing `analyze_media_item()` flow after the success commit. No new queue, worker, or scheduler is introduced.

### Reasoning

- the current architecture already has a workable execution boundary
- introducing a second asynchronous cleanup subsystem would expand scope and complicate rollback for a slice whose core need is simply to move deletion to the correct place in the existing flow

### Consequence

Engineer work stays bounded to processor, upload route call sites, and sync-service cleanup/refactor.

## Implementation Steps

## Backend

### Step 1: Introduce the Durable Browser-Local Scope Boundary

**Goal:** make the slice safe by preventing ordinary manual uploads from ever being treated as browser-local reference-mode items.

**Required changes:**

- define a dedicated local working-folder source classification for browser-local reference-mode intake using existing source metadata rather than the generic `__uploads__` manual source
- require browser-local preview-only candidates to carry a real `source_id` for that local working-folder source
- explicitly preserve current manual `__uploads__` items as out-of-scope full-retention items in this slice

**Acceptance notes:**

- an Engineer cannot accidentally wire the existing manual upload source into preview-only deletion
- the plan is explicit that ordinary browser uploads remain unchanged until the local working-folder path is used

### Step 2: Replace the Transient Pivot Flag With Persisted Eligibility Rules

**Goal:** make preview-only eligibility replay-safe across startup resume and retries.

**Required changes:**

- do not use a caller-supplied one-time boolean to indicate preview-only intent
- have the processor load current `MediaItem` and `Source` state and determine eligibility from persisted fields
- make the eligibility logic valid both for direct background-task execution and for the pending-job replay path in `src/api/app.py`
- document the persisted source predicates separately for connector items and local working-folder items

**Acceptance notes:**

- restarting the process before analysis completes does not change whether the item is eligible for the pivot
- replayed jobs do not need caller memory to make the same preview-only decision

### Step 3: Implement the Processor-Owned Post-Success Pivot Helper

**Goal:** centralize the actual retention-downgrade logic after success commit.

**Required changes:**

- after the success commit path in `analyze_media_item()`, refresh or otherwise operate on current `MediaItem` state
- verify before deletion:
  - `media_item.status == 'completed'`
  - `media_item.thumbnail_path` is set
  - `media_item.storage_path` still exists
  - `media_item.storage_mode == 'full'`
  - the persisted source contract proves eligibility under Decision 5
- attempt deletion of the retained original from `file_store`
- only after successful deletion:
  - set `media_item.storage_path = None`
  - set `media_item.storage_mode = 'preview_only'`
  - commit the state change

**Acceptance notes:**

- the original is still readable during analysis because the pivot runs only after the success commit
- preview-only state is never written before deletion succeeds

### Step 4: Non-Fatal Failure Handling and Logging

**Goal:** make post-analysis cleanup safe and debuggable.

**Required changes:**

- wrap deletion in `try/except`
- on deletion failure, log a warning with media-item context
- do not raise through the job
- do not null `storage_path`
- do not flip `storage_mode`

**Acceptance notes:**

- a failed delete leaves the item in a consistent `full` state
- the job still completes successfully from the user’s perspective

### Step 5: Define Browser-Local Original Access and Unsupported-Environment Behavior

**Goal:** keep browser-local preview-only behavior aligned with `ARCH-002-reference-mode-storage.md`.

**Required changes:**

- require the local working-folder flow to persist the rematch data needed for later original access before any deletion path can run
- state explicitly that original-facing actions for browser-local preview-only items use remembered local-source identity plus later folder re-confirmation when needed
- state explicitly that unsupported browsers must not enroll items into this flow

**Acceptance notes:**

- the plan no longer leaves browser-local preview-only items with no defined way to find the original again
- unsupported environments are blocked from preview-only browser-local intake rather than failing later after deletion

### Step 6: Preserve Connector Safety During the Sync-Service Refactor

**Goal:** remove duplicate post-analysis deletion logic from `sync_service.py`.

**Required changes:**

- ensure the remote-object identity that becomes `SourceObject` is durably persisted before the processor-owned deletion path can evaluate connector eligibility
- only allow the processor to pivot connector items when that `SourceObject` record already exists
- remove the duplicate post-analysis `file_store.delete()` / `storage_path = None` / `storage_mode = 'preview_only'` block from `sync_service.py` only after the identity-ordering rule is satisfied
- keep sync-service logging focused on orchestration, not retention-downgrade implementation

**Acceptance notes:**

- sync-service still achieves the same business outcome
- the processor becomes the single source of truth for preview-only transition logic
- connector items never enter `preview_only` unless their source-original identity already exists in durable storage
- if connector identity persistence is missing or fails, the item remains `full`

### Step 7: Guardrails Around Unexpected State

**Goal:** handle edge cases without turning state drift into crashes.

**Required changes:**

- if `thumbnail_path` is missing, log and leave item `full`
- if `storage_path` is already null, log and exit safely
- if `storage_mode` is already `preview_only`, do nothing
- if the item belongs to the manual `__uploads__` source, do nothing
- if a connector item has no persisted `SourceObject`, do nothing
- if a browser-local item has no persisted local working-folder source contract, do nothing

**Acceptance notes:**

- repeated or unexpected calls remain idempotent and non-destructive

## Test Plan

### 1. Processor Unit / Integration Tests

- successful analysis for an eligible connector item deletes original and flips item to `preview_only`
- successful analysis for an eligible local working-folder item deletes original and flips item to `preview_only`
- successful analysis for a manual `__uploads__` item leaves the item `full`
- successful analysis with missing `thumbnail_path` leaves item `full`
- successful analysis with missing persisted source contract leaves item `full`
- deletion failure logs warning and leaves item `full` with original path intact
- startup-resumed pending jobs make the same pivot decision as first-run jobs from persisted data alone

### 2. Upload Route Tests

- ordinary manual browser upload still routes to the manual source and remains ineligible for preview-only deletion
- local working-folder intake routes to the dedicated local source and persists the minimum source-rematch contract before any eligible pivot path can occur
- duplicate uploads do not create an unsafe preview-only candidate without source contract

### 3. Sync-Service Regression Tests

- connector sync still transitions eligible items to `preview_only`
- sync-service no longer owns duplicate deletion logic outside the processor
- connector items do not transition to `preview_only` unless `SourceObject` exists before the processor-owned deletion path runs
- thumbnail-missing or delete-failure cases leave synced items `full` without crashing the run

### 4. Existing Behavior Regression Checks

- analysis still reads the original before any deletion attempt
- analysis failure still leaves item in non-completed state and does not attempt pivot
- ordinary manual browser uploads remain full-retention items in this slice
- quota and indexing side effects remain unchanged

### 5. Browser-Local Policy Checks

- browser-local preview-only behavior is available only in environments with the required local file-system capabilities
- unsupported environments block the local working-folder preview-only flow and direct the user to a supported browser or cloud source
- original-facing actions for local working-folder items have a defined re-confirmation path after access expires

## Rollout Notes

- No migration is required for P8-002.
- The safest rollout order is: establish durable browser-local source classification, make processor eligibility replay-safe from persisted state, then refactor sync-service to reuse the centralized path.
- Post-deploy validation should check three cases: manual browser upload stays full, eligible local working-folder intake pivots safely, and eligible connector sync still pivots safely.
- If any regression appears in persisted-eligibility checks or connector identity ordering, revert the centralization change before broad rollback.

## What Is NOT Being Decided Here

- Any change to the retained preview asset size or format from P8-001
- Any new database schema changes
- Any new background cleanup subsystem for deferred deletion
- Full deprecation of the legacy manual browser upload path
- Any source-proxy original-fetch behavior
- Any retrospective cleanup of older browser-upload originals already retained as `full`

## Next Gate

Operator reviews and approves this plan before Engineer begins P8-002 implementation.