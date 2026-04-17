# Implementation Status

This is a **historical record** for the Media Indexing Engine project, not a live status document. For current state, see `CURRENT_STATE.md`. For active work, see `WORKSTREAMS.md`.

## Purpose

This document captures **snapshot summaries** of completed workstreams. Each entry records what was done, what was produced, and any lessons learned. It provides a permanent audit trail of the project's evolution.

## How This Document Is Updated

- A new entry is added **only** at workstream closeout
- Entries are **never modified** after creation — they are historical snapshots
- Each entry is written at the time of completion and reflects the state at that moment

## Format

Each completed workstream gets one entry in the log below, following this structure:

```
### WS-XXX: [Workstream Name]
- **Phase:** [Roadmap phase]
- **Completed:** [Date]
- **Objective:** [What the workstream set out to do]
- **Outcome:** [What was actually delivered]
- **Key decisions:** [Important choices made during implementation]
- **Artifacts produced:** [Files, configs, features created or modified]
- **Lessons learned:** [What went well, what didn't, what to do differently]
```

---

## Completed Workstream Log

### P12-010: Bounded Connector Analysis Concurrency Foundation
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** 2026-04-16
- **Objective:** Replace the serialised per-item connector analysis loop with a bounded parallel execution model. Multiple admitted connector analysis tasks may overlap up to a configured bound (default 2, range 1..3) without introducing unbounded memory growth, weakening quota admission, or violating Phase 9 storage contracts.
- **Outcome:** Full implementation delivered and Auditor-approved. Admission semaphore gates slot acquisition before download (D6). Quota reserved before task spawn (D5). Tasks return structured `ConnectorAnalysisTaskResult` outcomes (D7). `SyncRun` finalization waits for all admitted tasks to settle (D8). Quota stop halts new admission but drains already admitted work (D9, D10). Mutation/write-back remains inside the bounded task boundary (D11). Dedicated config setting with clamping enforces rollout safety (D12). Auditor blocking finding resolved: `analyze_connector_item` return type changed from `None` to `bool` so processor-handled failures (caught internally, no re-raise) propagate to `SyncRun.failed_count` rather than silently counting as success. 20/20 focused tests pass; 74/74 total across all directly affected suites.
- **Files Changed:**
  - `src/config.py` — added `ConnectorConfig` dataclass with `connector_sync_analysis_concurrency: int = 2`; `__post_init__` clamps to range 1..3; wired into `Settings`
  - `config/settings.yaml` — added `connector:` section with `connector_sync_analysis_concurrency: 2`
  - `src/connectors/sync_service.py` — added `ConnectorAnalysisTaskResult` dataclass (fields: `job_id`, `outcome`, `error`); added `_run_admitted_analysis_task()` coroutine (slot release in `finally`, outcome from `analyze_connector_item` return value, exception catch for unexpected propagation); refactored `_run_sync` with full bounded-admission loop: `asyncio.Semaphore(concurrency)`, slot-before-download discipline, quota-before-spawn, admitted task list, drain via `asyncio.gather`, aggregated failure accounting, structured run finalization
  - `src/analysis/processor.py` — `analyze_connector_item` return type changed from `-> None` to `-> bool`; `return True` added at success path (after `job.status = "completed"` / quota consume, including idempotency path); `return False` added at all handled-failure branches (job-not-found, MediaItem-not-found, exception handler after quota release); docstring updated to explain boolean contract and no-re-raise design
  - `tests/test_p12_010_connector_analysis_concurrency.py` — 20 focused tests across 6 classes: `TestConnectorConfigClamping` (×6 clamping cases), `TestAdmittedAnalysisTask` (×7: worker cap, gather completeness, exception-raised failure, exception batch accounting, per-item isolation, no-storage-path regression, concurrency-1 serialization), `TestQuotaStopAndDrain` (×2: admission stop, drain after stop), `TestByteBacklogPrevention` (×1: slot-before-download D6), `TestRolloutTarget` (×1: concurrency=2 end-to-end), `TestProcessorHandledFailurePropagation` (×3: return-False → failed outcome, batch failed_count, mixed success/failure accounting)
  - `tests/test_connectors.py` — two existing tests patched with `_get_vision_provider → None` to isolate from admission-outcome counting; both still pass
- **Auditor blocking finding (resolved):** Pre-fix, `_run_admitted_analysis_task` treated any normal return from `analyze_connector_item` as `outcome="success"`. Because `analyze_connector_item` catches all exceptions internally, writes `job.status="failed"` to DB, and returns (now `False`, previously `None`), production failures were never counted in `SyncRun.failed_count`. Fix: explicit `bool` return contract + branch on return value in task wrapper.
- **Key decisions:** D1–D12 all implemented as locked in `P12-010_plan.md`. `asyncio.Semaphore` used as the admission mechanism (not a thread pool or external worker). `_run_admitted_analysis_task` is the single admission path. Slot acquired before download to enforce D6 byte-backlog bound.
- **Validation status:** 20/20 P12-010 focused tests pass. 74/74 total (P12-010 ×20 + test_connectors ×32 + test_connector_ingest ×8 + test_p12_009_capture_metadata ×14) pass.

### P12-009: Source Capture Metadata Preservation Hardening
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** 2026-04-15
- **Objective:** Per ARCH-004, harden source-truth capture metadata preservation: store first-class DB fields for source-authored capture datetime and GPS; extract them at ingest time; enforce that AI write-back paths cannot overwrite source fields; remove AI `location_hint` from IPTC city and XMP Iptc4xmpCore:Location; make PNG XMP embedding non-destructive.
- **Outcome:** All four slices implemented and 14/14 focused tests pass (12 original + 2 added at closeout). ARCH-004 contracts D3, D4, D5, D6 are fully enforced.
- **Files Changed:**
  - `alembic/versions/e3f4a5b6c7d8_p12_009_source_capture_metadata.py` — new migration; adds 6 nullable columns to `media_items` (`source_capture_datetime_utc`, `source_capture_datetime_raw`, `source_capture_time_offset_minutes`, `source_gps_latitude`, `source_gps_longitude`, `source_gps_altitude_meters`) plus index on `source_capture_datetime_utc`
  - `src/models.py` — added 6 matching `Mapped[... | None]` fields to `MediaItem`
  - `src/ingestion/metadata_extractor.py` — new module; `CaptureMetadata` dataclass + `extract_source_capture_metadata(file_bytes, mime_type)` function; piexif-based EXIF extraction for JPEG/TIFF; DMS-to-decimal GPS conversion; OffsetTimeOriginal → UTC normalisation; fully non-fatal
  - `src/ingestion/upload_service.py` — calls `extract_source_capture_metadata` before `MediaItem` construction; populates 6 source-truth fields
  - `src/ingestion/connector_ingest.py` — same extraction call and field population
  - `src/enrichment/field_mapping.py` — removed `if metadata.location_hint: data["city"] = metadata.location_hint` (ARCH-004 D4 violation)
  - `src/enrichment/xmp_builder.py` — removed `location` variable, `Iptc4xmpCore:Location` element, and `xmlns:Iptc4xmpCore` namespace declaration (ARCH-004 D4 violation)
  - `src/enrichment/png_writer.py` — rewrote `embed_png` with non-destructive XMP merge via ElementTree; added `_try_merge_xmp` helper; fail-closed behaviour preserves original XMP when merge fails (ARCH-004 D6 violation fix)
  - `scripts/backfill_p12_009_capture_metadata.py` — new idempotent backfill script for existing full-storage items; CLI flags `--dry-run`, `--batch-size`, `--stop-after`, `--user-id`; **closeout fix (2026-04-16):** pending query now also requires `source_gps_latitude IS NULL` (was `source_capture_datetime_raw IS NULL` alone), making rerun semantics correct for GPS-only historical rows
  - `tests/test_p12_009_capture_metadata.py` — 14 focused tests (9 P12-009 contract tests + 3 edge-case extras + 2 backfill idempotency tests added at closeout)
- **Validation status:** 14/14 P12-009 focused tests pass.

### P12-001: Google OAuth Production-Readiness and Beta-Access Hardening
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** 2026-04-14
- **Objective:** Lock a canonical five-identifier error/state vocabulary across Google SSO and Google Drive OAuth surfaces to make provider-blocked, operator-misconfiguration, and user-consent-denied states unambiguous to the frontend and to any future operator onboarding checklist consumers.
- **Outcome:** All five locked identifiers are now emitted consistently from the backend and handled with guided messages in the frontend. No architecture changes, no new providers, no scope expansion beyond P12-001's four slices.
- **Files Changed:**
  - `src/api/routes/google_auth.py` — `/google/start` and `/google/exchange` 503 responses now use `detail={"error_code": "google_oauth_unavailable", "message": "..."}` dict form (previously bare string `"Google SSO is not enabled"`); callback `sso_disabled` redirect renamed to `google_oauth_app_not_ready`; callback `oauth_error` redirect renamed to `google_oauth_access_denied`
  - `src/api/routes/google_drive_connector.py` — all `connector_disabled` and `connector_unavailable` error codes in start/upgrade-scope/quick-connect 503 responses replaced with `google_oauth_unavailable`; callback `connector_disabled` redirect renamed to `google_oauth_unavailable`; callback `access_denied` renamed to `google_oauth_access_denied`; module docstring error codes list updated
  - `frontend/src/pages/GoogleAuthCallbackPage.tsx` — `ERROR_MESSAGES` dict extended with `google_oauth_app_not_ready`, `google_oauth_access_denied`, `google_oauth_unavailable`; legacy `sso_disabled` and `oauth_error` entries retained for backwards compatibility
  - `frontend/src/pages/SourcesPage.tsx` — `DRIVE_CONNECTOR_ERROR_MESSAGES` const added with all five locked identifiers plus legacy fallback entries; callback banner now uses message lookup instead of raw `code.replace(/_/g, ' ')`
  - `frontend/src/pages/AddMediaPage.tsx` — same `DRIVE_CONNECTOR_ERROR_MESSAGES` map added; callback error display now renders the mapped message directly (full sentence) with code-replace fallback for unknown codes
  - `tests/test_google_drive_connector.py` — `test_drive_callback_access_denied_redirect` assertion updated from `error_code=access_denied` to `error_code=google_oauth_access_denied`
  - `tests/test_p12_001_google_oauth_readiness.py` — new file; 7 focused tests covering all five locked identifiers across SSO and Drive connector paths
- **Error vocabulary mapping (canonical):**

  | Old code | Location | New code |
  |---|---|---|
  | `sso_disabled` (redirect) | SSO callback `is_ready=False` | `google_oauth_app_not_ready` |
  | `oauth_error` (redirect) | SSO callback provider error | `google_oauth_access_denied` |
  | `"Google SSO is not enabled"` (503 string) | SSO start, exchange | `error_code: google_oauth_unavailable` (dict form) |
  | `connector_disabled` (503 JSON) | Drive start/upgrade/quick-connect | `google_oauth_unavailable` |
  | `connector_unavailable` (503 JSON) | Drive start/upgrade/quick-connect | `google_oauth_unavailable` |
  | `connector_disabled` (redirect) | Drive callback `is_ready=False` | `google_oauth_unavailable` |
  | `access_denied` (redirect) | Drive callback provider error | `google_oauth_access_denied` |
  | (frontend-derived) | `connector_status='disconnected'` | `google_drive_reconnect_required` label in banner |
  | (frontend-derived) | `has_write_scope=false` | `google_drive_scope_upgrade_required` label in banner |

- **Response format note:** The app's `register_error_handlers` custom exception handler flattens dict `detail` HTTPExceptions: `error_code` is promoted to a top-level response key, `message` becomes the `detail` string. Tests assert `body["error_code"] == "..."` accordingly.
- **Pre-existing unrelated failure:** `tests/test_google_drive_connector.py::test_drive_list_objects_sends_correct_query` fails with `assert None == '42'`. This failure predates P12-001 and was not caused by any changes in this workstream.
- **Validation status:** P12-001 focused suite 7/7 pass. Updated `test_drive_callback_access_denied_redirect` passes. `test_drive_list_objects_sends_correct_query` failure remains out of scope.

### P11-002: Async Connector-Aware Bulk Export
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** Initial implementation landed 2026-04-12; narrow closeout remediation also landed 2026-04-12; final Auditor re-pass approved closeout 2026-04-13
- **Files Changed:**
  - `src/config.py` — added `ExportConfig` dataclass (`max_batch_size`, `max_active_jobs_per_user`, `artifact_ttl_hours`, `drive_concurrency`); wired into `Settings` and `load_settings`
  - `src/models.py` — added `ExportJob` ORM model (`export_jobs` table; status lifecycle, per-item JSON columns, artifact path/TTL, artifact_downloaded flag)
  - `src/api/schemas.py` — added `ExportBatchRequest`, `ExportItemOutcome`, `ExportBatchResponse`, `ExportItemResult`, `ExportJobStatusResponse`
  - `src/api/routes/export.py` — new file; 3 routes + background executor `_run_export_job`; bounded Drive semaphore; post-remediation contract alignment for no-eligible-items payload, incremental artifact writing, and expired-status promotion
  - `src/api/app.py` — registered `export.router`; app lifespan now wires startup cleanup for expired export artifacts
  - `tests/conftest.py` — added `export_mod.async_session` patching in both `client` and `client_user2` fixtures
  - `tests/test_p11_002_export_batch.py` — new file, 19 focused tests
- **Contract changes (new routes):**
  - `POST /api/v1/media/export-batch` — HTTP 202 with per-item submission outcomes; accepted/blocked/rejected classification; no job created on all-rejected/blocked
  - `GET /api/v1/media/export-jobs/{job_id}` — job status, item results, artifact_ready flag
  - `GET /api/v1/media/export-jobs/{job_id}/download` — single-use ZIP download; 410 after first download or TTL expiry
- **Historical closeout note:** P11-002 was briefly reopened on 2026-04-12 after Auditor review found four material drifts against ADR-036. That reopened state is now historical.
- **Post-remediation reconciliation:**
  - `export_no_eligible_items` now returns the full locked 409 detail payload (`request_count`, `accepted_count: 0`, `blocked_count`, `rejected_count`, `outcomes[]`)
  - ZIP assembly now writes incrementally to the temporary export artifact instead of buffering the full archive in memory
  - TTL-expired artifact cleanup now exists on startup via app lifespan wiring
  - completed and `completed_with_failures` jobs are now TTL-checked and can promote to `expired` on status polling
- **Final Auditor outcome:** No blocking findings. P11-002 approved for closeout. ADR-036 remains the authoritative contract.
- **Validation status:** P11-002 focused suite 19/19 pass. Directly affected suites 71 pass. The full backend suite is not fully green because of a separate unrelated failure in `tests/test_google_drive_connector.py`; that failure is not treated as a P11-002 regression.
- **Architect verdict:** P11-002 is formally completed and closed. The delivered contract remains the async export-job boundary with explicit per-item reporting, bounded Drive-aware execution, temporary user-scoped export artifacts, and local-folder plus non-Drive provider bulk export blocked by default.

### P11-001: Capability-Aware Batch Reanalysis
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** 2026-04-12
- **Files Changed:**
  - `src/api/schemas.py` — added `BatchReanalyzeItemOutcome`, `BatchReanalyzeResponseV2`; added `from typing import Literal`
  - `src/api/routes/analysis.py` — replaced `reanalyze_batch` with P11-001 capability-aware implementation; added `_run_drive_batch_item` background task helper with bounded Drive concurrency (`_DRIVE_BATCH_SEMAPHORE`); top-level imports for `asyncio`, `async_session`, `fetch_drive_reference_bytes`, `original_is_accessible`, new schemas
  - `tests/test_p11_001_batch_reanalysis.py` — new file, 9 focused tests covering all P11-001 cases
  - `tests/test_bulk_operations.py` — 3 tests updated from old `{queued, message}` shape to P11-001 response shape
  - `tests/test_storage_guards.py` — 1 test updated from silent-skip assertion to explicit-blocking assertion
- **Contract changes:**
  - `POST /api/v1/media/reanalyze-batch` response shape changed from `{queued, message}` to `BatchReanalyzeResponseV2` with `request_count`, `accepted_count`, `blocked_count`, `rejected_count`, `queued_count`, `outcomes[]`
  - Drive-backed `storage_mode='reference'` items are now eligible for batch reanalysis (async queue; no request-time Drive fetch)
  - All items return explicit per-item outcomes (no silent skips)
  - All-or-nothing quota contract enforced (quota failure → HTTP 429 with full per-item reclassification)
- **Test results:** Full regression 459/459 pass, 1 skipped at closeout; focused P11-001 validation 53/53 pass across P11-001 + bulk-operations + storage-guards + P10-001 suites.

### P10-001: On-Demand Drive Fetch for Reference Items
- **Phase:** Post-Phase 9 incremental workstreams
- **Completed:** 2026-04-12
- **Objective:** Introduce a controlled, transient Drive-only refetch path for `storage_mode='reference'` items so single-item re-analysis and single-item download/export can reuse the source-owned original without reintroducing app-retained originals.
- **Outcome:** Drive refetch path delivered and aligned to locked contract. `POST /api/v1/media/{id}/reanalyze` and `GET /api/v1/media/{id}/download` both serve Drive-backed reference items by transiently fetching bytes in-memory and never persisting the original. Non-Drive reference items continue to return 409 `original_at_source` at the route layer. All 18 P10-001 tests pass; 52/52 pass across all directly-affected suites (P10-001, storage_guards, analysis, download). Full regression: 459 passed, 1 skipped (no delta — P10-001 code was already present; this workstream aligned the error contract and confirmed implementation).
  - **`src/connectors/drive_reference_fetch.py`:** Shared Drive fetch service. Missing OAR / non-Drive OAR / missing `provider_object_id` reclassified from 422 to 502 `drive_fetch_failed` per locked contract (internal precondition failures, not client validation). All `detail` dicts changed from `"error"` key to `"error_code"` key to match error handler contract and produce consistent `error_code` in API responses.
  - **`src/api/routes/analysis.py`:** `POST /media/{id}/reanalyze` — Drive OAR check dispatches to `fetch_drive_reference_bytes`; non-Drive reference items fall through to `assert_original_accessible()` (409). Inline ad-hoc Drive branch removed, replaced by shared service.
  - **`src/api/routes/download.py`:** `GET /media/{id}/download` — Drive OAR check: requires metadata, fetches bytes transiently, embeds, serves. Non-Drive reference items fall through to `assert_original_accessible()` (409).
  - **`tests/test_p10_001_drive_reference_fetch.py`:** 18 tests. Assertions updated: tests 2-4 corrected from 422 to 502 + `error_code` check; all `detail["error"]` assertions updated to `detail["error_code"]`; route propagation test mocks updated to use `error_code` key so error handler promotes correctly.
- **Key decisions:** Internal precondition failures (missing OAR, wrong provider, missing connector) are 502 not 422 — callers are expected to resolve Drive-backed items only at the route layer before entering the shared service. `error_code` is the canonical key in all detail dicts to align with `error_handlers.py`.
- **Scope preserved:** No batch expansion, no convert-png expansion, no persistent original retention.

### P9-005: Local Working-Folder Intake and Eliminate App-Retained Browser Originals
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-10
- **Objective:** Replace the retained-original browser upload path with working-folder-first transient intake so new drag-drop items are stored as `local_folder` reference-mode records.
- **Outcome:** ARCH-002 browser/local intake gap closed. New local-folder intake path creates reference-mode items without calling `file_store.save()` for originals. Historical `app_upload` rows preserved as-is. Full suite: 459 passed, 1 skipped (+15 from 444). **Fix pass (2026-04-10):** two Auditor blockers resolved — (a) `UploadPage.tsx` `uploadOne()` now writes dropped files into the selected working folder via File System Access API before backend call; (b) quota-exceeded cleanup in `upload.py` extended to cover `OriginAssetRef`, `PreviewAsset`, and thumbnail file via `_cleanup_unqueued_local_folder_upload()` helper.
  - **New module `src/ingestion/local_folder_ingest.py`:** `process_local_folder_intake()` pipeline mirrors `process_connector_import()` — validate → hash → dedup → MIME → dimensions → thumbnail-only → `MediaItem(storage_mode='reference')` + `OriginAssetRef(provider_type='local_folder', local_file_fingerprint=content_hash)` + `PreviewAsset`. No `file_store.save()` for original.
  - **New endpoint `POST /api/v1/upload/local-folder`** in `src/api/routes/upload.py`: accepts file, optional `source_id` and `local_file_path` hint; calls `process_local_folder_intake()`; auto-creates a `Source(source_type='local_folder', name='__local_folder__')` via `_resolve_local_folder_source_id()`.
  - **Frontend gate `frontend/src/pages/UploadPage.tsx`:** File System Access API availability check; working-folder selection gate (`showDirectoryPicker()`); explicit unsupported-browser fallback messaging; drag-drop disabled until folder selected; calls `api.uploadLocalFolderFile()` for all local intake.
  - **New API client function `uploadLocalFolderFile()`** in `frontend/src/api/client.ts`: calls `POST /api/v1/upload/local-folder` with file + optional source_id + local_file_path hint.
  - **New type `LocalFolderUploadRequest`** added to `frontend/src/types/api.ts`.
  - **14 new tests** in `tests/test_p9_005_local_folder_intake.py` covering: no `file_store.save()`, reference mode, provider_type='local_folder', local_file_fingerprint, PreviewAsset, no app_upload ref, duplicate detection, endpoint schema, auto-source creation, reanalysis controlled outcome, historical compatibility (3 tests).

### P9-004: Source Capability and Durable Write-Back Operations — Auditor Remediation
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-10
- **Objective:** Remediate four Auditor findings against the P9-004 implementation to bring it into full compliance with `docs/planning/P9-004_plan.md`.
- **Outcome:** All four findings addressed. Retry endpoint now gates on Drive-backed status unconditionally. Per-attempt history is verified for all blocked exit paths and the missing test is added. Local-browser mutation scope is explicitly protected by a new contract test. Full suite: 444 passed, 1 skipped (delta +11 from 433).
  - **Finding 1 — Retry bootstrap scope (code fix):** `POST /media/{id}/retry-writeback` in `src/api/routes/media.py` now checks `is_drive_backed` as the first gate, before loading any `WriteBackOperation` row. Non-Drive items are rejected with 422 unconditionally, even when a backfill-created operation row exists.
  - **Finding 2 — Blocked-path audit history (test fix):** All three flagged exit paths in `drive_mutation_service.py` (credential decrypt failure, missing refresh token, missing Drive file ID) already call `_record_mutation_attempt`. Added `test_drive_rename_decrypt_failure_records_history` to explicitly cover the decrypt-failure path.
  - **Finding 3 — Local-browser mutation scope (contract test):** `POST /media/{id}/mutation-result` does not create `WriteBackOperation` rows. Added `test_local_mutation_result_does_not_create_writeback_operation` to document and enforce this P7-004 boundary.
  - **Finding 4 — Test coverage (tests added):** Added 3 new tests to `tests/test_p9_004_capabilities_writeback.py`: `test_drive_rename_decrypt_failure_records_history`, `test_local_mutation_result_does_not_create_writeback_operation`, `test_retry_endpoint_rejects_non_drive_item_with_existing_operation`.
- **Test count delta:** 433 → 444 (3 explicitly added + pre-existing tests now passing after code fix). Focused validation: 88 passed. Full regression: 444 passed, 1 skipped.

### P9-004: Source Capability and Durable Write-Back Operations
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-09
- **Objective:** Finish the operational side of the ARCH-002 migration by introducing connector-level capability snapshots and durable write-back intent records while preserving the existing `MediaItem` mutation-state contract for current API/frontend consumers.
- **Outcome:** Additive durable capability/write-back layer implemented end-to-end. `SourceCapabilitySnapshot` now records one current connector-level capability row per `SourceConnector`. `WriteBackOperation` now records canonical write-back state targeted at `OriginAssetRef` with denormalized `media_item_id` for compatibility. `MediaItem` mutation fields remain same-transaction mirrors, so existing API responses and `tests/test_mutation_completion.py` assertions continue to pass unchanged. Full suite: 433 passed, 1 skipped.
  - **New model `SourceCapabilitySnapshot`** in `src/models.py`: one current row per connector with `can_read`, `can_write`, `can_refetch`, `scope_text`, `scope_tier`, `verification_state`, verification timestamps, and operator-safe error fields.
  - **New model `WriteBackOperation`** in `src/models.py`: one current row per `(media_item_id, operation_type)` with canonical `origin_asset_ref_id`, denormalized `media_item_id`, retry attempt count, requested rename/metadata payload, applied timestamp, and error state.
  - **New migration `d2e3f4a5b6c7`**: creates `source_capability_snapshots` and `writeback_operations` plus all locked indexes/uniqueness constraints; no destructive schema changes.
  - **New `src/analysis/source_capability_service.py`**: derives Drive capability from connector scope + credential health, upserts the current snapshot, and exposes a refresh path for OAuth callback and write-back gating.
  - **New `src/analysis/writeback_operation_service.py`**: owns durable write-back upsert/bootstrap, mirror mapping, metadata payload hashing, and additive `OriginAssetRef` bootstrap for legacy rows that predate P9-003.
  - **Modified `src/analysis/drive_mutation_service.py`**: durable `WriteBackOperation(operation_type='rename')` is now the canonical state record; Drive rename outcomes map to `applied` / `failed` / `blocked` on the operation and mirror to `MediaItem` in the same transaction. `SourceMutationHistory` remains per-attempt audit history unchanged.
  - **Modified `src/api/routes/media.py`**: `POST /media/{id}/mutation-result` now writes durable rename/metadata-write operations when an origin ref exists; `POST /media/{id}/retry-writeback` bootstraps a missing rename operation from existing `MediaItem` mirrors when needed and permits retry for operation states `pending` and `failed`.
  - **Modified `src/api/routes/google_drive_connector.py`**: Drive connect/upgrade callback now refreshes the current `SourceCapabilitySnapshot` when scopes are stored.
  - **Modified `src/api/routes/connectors.py` + `src/api/schemas.py`**: `ConnectorResponse.has_write_scope` now prefers `SourceCapabilitySnapshot.can_write` when a snapshot exists and falls back to `granted_scopes` only when no snapshot is present.
  - **New `scripts/backfill_p9_004_capabilities_writeback.py`**: async, rerunnable two-phase backfill with `--dry-run`, `--batch-size`, `--stop-after`, `--user-id`, `--source-id`, `--sleep-seconds`; exits non-zero on failures.
  - **New `tests/test_p9_004_capabilities_writeback.py`**: covers capability snapshot derivation, connector response preference, durable write-back row creation, transient/blocking state mapping, retry bootstrap compatibility, and backfill idempotency.
- **Key decisions:**
  - `OriginAssetRef` remains the canonical write-back target. For legacy/historical rows that still lack an origin ref, the implementation bootstraps one additively from existing source/connectors/object mirrors instead of failing or rewriting older tests.
  - `WriteBackOperation.state='failed'` intentionally mirrors to `MediaItem.mutation_state='pending_writeback'` so the public contract stays stable while the backend state model becomes more precise.
  - Capability snapshots remain connector-level preconditions only. File-level 403/404 results block a specific operation but do not automatically rewrite the connector snapshot unless the error indicates connector-level auth breakage.
- **Test count delta:** 423 → 433 (10 new P9-004 tests). Focused validation: 77 passed. Full regression: 433 passed, 1 skipped.

### P9-003: Additive Origin/Preview Domain Split
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-09
- **Objective:** Add `OriginAssetRef` and `PreviewAsset` as first-class models behind the `MediaItem` aggregate so that provider identity, asset locators, and derived previews are tracked in their own tables rather than smeared across `MediaItem` columns and `SourceObject`.
- **Outcome:** Both tables introduced additively. `SourceObject` unchanged. `MediaItem.storage_path`/`thumbnail_path`/`source_file_fingerprint` kept as compatibility mirrors. Forward-write path covers all three ingestion code paths; backfill script handles pre-existing rows. 12 new tests, all green.
  - **New model `OriginAssetRef`** in `src/models.py`: 1:1 with `MediaItem`; `provider_type` in (`google_drive`, `s3_compatible`, `local_folder`, `app_upload`); `source_object_id` nullable FK (set by sync_service after SourceObject committed); `app_storage_path` mirrors `MediaItem.storage_path` for app-retained items; `local_file_fingerprint` mirrors for local-folder items; `provider_object_id`/`locator_snapshot`/`revision_marker` for connector-backed items.
  - **New model `PreviewAsset`** in `src/models.py`: many:1 with `MediaItem`; UNIQUE on `(media_item_id, variant_type)`; `variant_type='thumbnail'` for P9-003 scope; `storage_path` mirrors `MediaItem.thumbnail_path`.
  - **New migration `b0a1c2d3e4f5`**: No-op merge of prior two heads (`a0b1c2d3e4f5` + `a1b2c3d4e5f7`).
  - **New migration `c1b2d3e4f5a6`**: Creates `origin_asset_refs` and `preview_assets` tables with all indexes. Single Alembic head confirmed.
  - **Modified `src/ingestion/connector_ingest.py`**: `process_connector_import` gains `provider_type`/`provider_object_id`/`revision_marker` kwargs; creates `OriginAssetRef` + `PreviewAsset` in the same transaction as `MediaItem`.
  - **Modified `src/ingestion/upload_service.py`**: `process_upload` creates `OriginAssetRef(provider_type='app_upload', app_storage_path=storage_path)` + `PreviewAsset` in the same transaction as `MediaItem`.
  - **Modified `src/connectors/sync_service.py`**: `_run_sync` passes `provider_type=connector_row.connector_type`, `provider_object_id=remote_obj.key`, `revision_marker=remote_obj.version` to `process_connector_import`; after `_upsert_source_object("imported")` + commit, executes `sa_update(OriginAssetRef).where(...).values(source_object_id=imported_so.id)`. `_upsert_source_object` return type changed from `None` to `SourceObject`.
  - **New `scripts/backfill_p9_003_origin_preview.py`**: Async two-phase backfill (Phase 1: `OriginAssetRef` for all MediaItems without one; Phase 2: `PreviewAsset` thumbnail for all MediaItems with `thumbnail_path` but no PreviewAsset). Infers `provider_type` from `Source.source_type` + `SourceConnector.connector_type`. Conservative batch + dry-run + `--stop-after` controls.
  - **New `tests/test_origin_preview_models.py`**: 12 tests covering upload path (origin ref created, app_storage_path mirrors, preview asset created), connector import path (origin ref created, app_storage_path null, provider fields stored, preview asset created, source_object_id initially null), sync path (source_object_id populated after sync), ORM relationships (origin_asset_ref, preview_assets), and duplicate upload (no second OriginAssetRef).
- **Key decisions:**
  - `OriginAssetRef.source_object_id` starts NULL at import time (SourceObject does not exist yet); sync_service fills it after `_upsert_source_object` + commit via `sa_update`. This avoids changing the ingestion contract and keeps the two-phase nature explicit.
  - `upload_service` always uses `provider_type='app_upload'` regardless of source_type. The backfill correctly sets `provider_type='local_folder'` for historical local-folder items; forward correction can be made in a follow-on workstream.
  - `_upsert_source_object` now returns `SourceObject` (previously `None`) so the caller can use `imported_so.id` without an extra query.
  - `provider_type` default in `process_connector_import` is `"s3_compatible"` to match existing `connector_type` values in the codebase (plan said `s3`, code uses `s3_compatible`).
- **Test count delta:** 411 → 423 (12 new P9-003 tests).

### P9-002: Source-Aware Original Access Hardening
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-09
- **Objective:** Harden every API surface that assumes `storage_path` == original readable from app storage. Apply controlled 409 `original_at_source` responses as the default interim behavior per ADR-031.
- **Outcome:** All identified surfaces hardened. Shared guard module introduced. `delete_batch` crash on `None` storage_path fixed. 17 new tests, all green.
  - **New file:** `src/api/storage_guards.py` — `original_is_accessible(item) -> bool` and `assert_original_accessible(item) -> None` helpers; raises `HTTPException(409)` with `error_code='original_at_source'` for any item that is not `storage_mode='full'` with a non-null `storage_path`.
  - **Modified:** `src/api/routes/analysis.py` — `reanalyze` guarded with `assert_original_accessible` (before the "already in progress" check); `reanalyze_batch` silently skips non-full items; `delete_batch` split unconditional `file_store.delete(item.storage_path)` into two separately-guarded blocks (`if item.storage_path` / `if item.thumbnail_path`).
  - **Modified:** `src/api/routes/download.py` — `download_file` and `convert_to_png` guarded with `assert_original_accessible`; `download_batch` skips non-full items with `skipped` increment.
  - **Modified:** `src/analysis/processor.py` — `analyze_media_item` gains a fail-fast guard immediately after the "already completed" check; non-full items fail the job with a clear error message, release quota reservation, and return before any processing begins.
  - **Modified:** `src/curation/scoring_service.py` — `score_group` skips non-full items at the start of the item loop, incrementing `failed_count` rather than crashing on a missing `file_store.read()`.
  - **New file:** `tests/test_storage_guards.py` — 17 tests covering: helper unit tests (reference, preview_only, full modes); reanalyze 409 + batch skip; download 409 + batch skip; convert-png 409; delete_batch none-crash + thumbnail-cleanup; processor fail-fast for reference and preview_only; score_group skip.
- **Key decisions:**
  - ADR-031 interim rule: 409 `original_at_source` is the correct default for all storage-assuming surfaces. No on-demand source fetch in this slice.
  - One shared guard module (`storage_guards.py`) instead of duplicating the check at every call site — keeps the condition definition in one place for the eventual ADR-031 final implementation.
  - `delete_batch` uses best-effort deletion (no 409) since deletion should always succeed for the DB row regardless of file state; the file deletion is simply skipped when `storage_path` or `thumbnail_path` is None.
- **Test count delta:** 394 → 411 (17 new P9-002 tests).

### P9-001: Zero-Transient Connector Ingestion
- **Phase:** Phase 9 — ARCH-002 Gap Remediation
- **Completed:** 2026-04-09
- **Objective:** Close the ARCH-002 gap where connector-synced originals were written to app storage transiently (even briefly) before being deleted by `_attempt_preview_pivot`. Connector-ingested files should never touch app storage for the original.
- **Outcome:** Full zero-transient path implemented. Connector items are now created with `storage_mode='reference'` and `storage_path=None`. Only derived thumbnails are persisted. Analysis proceeds synchronously from the in-memory download bytes. No DDL migration required (`storage_mode` was already `String(20)`).
  - **New file:** `src/ingestion/connector_ingest.py` — `process_connector_import()` implements the full preparation pipeline (validate → hash → dedup → MIME → dimensions → thumbnail-only → reference-mode DB records → pHash) without calling `file_store.save()`.
  - **Modified:** `src/analysis/processor.py` — new `analyze_connector_item()` function; single-attempt synchronous analysis from caller bytes; no `file_store.read()`; no `_attempt_preview_pivot` call; quota consume/release paths preserved.
  - **Modified:** `src/connectors/sync_service.py` — `_run_sync` now calls `process_connector_import` → `analyze_connector_item` instead of `upload_service.process_upload` → conditional `analyze_media_item`. `upload_service` parameter kept in `trigger_sync` signature for backward compatibility.
  - **Modified:** `tests/test_preview_pivot.py` — test 10 (`test_sync_connector_pivot_regression`) updated to assert `storage_mode='reference'` (was `preview_only`/`full`).
  - **New file:** `tests/test_connector_ingest.py` — 8 tests covering happy-path reference mode creation, duplicate detection, validation failure, thumbnail failure graceful recovery, analysis success, analysis error graceful recovery, full `trigger_sync` reference-mode assertion with `file_store.save()` call interception, and re-sync duplicate detection.
- **Key decisions:**
  - ADR-031: synchronous analysis within the sync flow is allowed for the P9-001 first slice. No retry loop for connector items — failed items stay `reference/error` and long-term retry uses source re-fetch from the connector.
  - `storage_mode='reference'` is the new type for connector items where no original was ever stored. Distinct from `preview_only` (was stored, then deleted) and `full` (browser uploads, permanently kept).
  - `_attempt_preview_pivot` guard `if media_item.storage_mode != "full": return` already handles `reference` mode correctly — no code change needed.
  - `/file` endpoint guard `not item.storage_path` already handles `reference` items since `storage_path=None` — no logic change, docstring-only update.
- **Test count delta:** 386 → 394 (8 new P9-001 tests, +1 test updated).
- **Lessons learned:** The "backward-compatible parameter kept in signature" pattern (keeping `upload_service` in `trigger_sync`) avoids breaking all existing tests while transitioning the internal implementation — useful whenever a function's callers are numerous but a parameter is being deprecated.

### P8-003: Historical Connector Preview-Only Migration
- **Phase:** Phase 8 — Reference-Mode Storage Pivot
- **Completed:** 2026-04-08
- **Objective:** Convert historical connector-synced MediaItems that still hold full-resolution originals into the `preview_only` storage mode produced by live Phase 8 ingestion.
- **Outcome:** Standalone migration script delivered. Backfills missing thumbnails, then delegates every transition to the canonical `_attempt_preview_pivot()` function. No new schema changes.
  - **Script:** `scripts/migrate_historical_preview_only.py` — accepts `--dry-run`, `--batch-size`, `--stop-after`, `--user-id`, `--source-id`, `--sleep-seconds`. Candidate query joins `MediaItem → Source → SourceConnector` and filters `storage_mode='full'` + `storage_path IS NOT NULL`. Thumbnail backfill reads original from `file_store`, calls `_generate_thumbnail()`, persists via `file_store.save_thumbnail()`, commits, then calls `_attempt_preview_pivot()` as the sole pivot path. Exits with code 1 on any failure so re-runs are signalled.
  - **Tests:** `tests/test_historical_migration.py` — 12 tests covering dry-run, idempotency, null-storage-path exclusion, `__uploads__` skip, with-thumbnail pivot, no-thumbnail backfill+pivot, thumbnail-generation failure, thumbnail-save failure, second-run idempotency, live-path parity, `--stop-after` limit, user-id filter.
- **Key decisions:** Standalone script (not startup hook, not API endpoint) per the P8-003 plan; `_attempt_preview_pivot()` is the only deletion/transition path (no parallel code path); thumbnail backfill is in scope so no two-pass operator workflow is needed; candidate query is conservative (must have `SourceConnector` row); no DB audit table — structured logs + `sys.exit(1)` on failures.
- **Artifacts produced:** `scripts/migrate_historical_preview_only.py` (new), `tests/test_historical_migration.py` (new), `docs/WORKSTREAMS.md` (P8-003 moved to Completed), `docs/CURRENT_STATE.md` (test count 386, workstream cleared).
- **Lessons learned:** Module-global counters in test helpers (`_item_counter`, `_so_counter`) are necessary when multiple items share a source — `SourceObject.external_object_key` has a unique constraint on `(source_id, key)`. Using a sentinel value (`save_file: bool`) is cleaner than `Optional[str]` overrides when you need to express "force null rather than not provided".

### P8-002: Browser-Upload Preview-Only Pivot
- **Phase:** Phase 8 — Reference-Mode Storage Pivot
- **Completed:** 2026-04-08
- **Objective:** Extend preview-only pivoting to all eligible intake paths. Centralize pivot logic in `_attempt_preview_pivot()` driven entirely by persisted DB state; make `__uploads__` permanently ineligible; add `source_type='local_folder'` as an eligibility class; refactor sync-service to commit `SourceObject` before analysis.
- **Outcome:** `_attempt_preview_pivot(db, media_item, file_store)` is now the single pivot entry point. Sync-service Slice B refactored: `_upsert_source_object("imported")` committed before `analyze_media_item`. 11 tests in `tests/test_preview_pivot.py`. Total: 374/374 pass.
- **Artifacts produced:** `src/analysis/processor.py` (`_attempt_preview_pivot` extracted), `src/connectors/sync_service.py` (upsert-before-analyze), `tests/test_preview_pivot.py` (11 new tests).

### P8-001: Reference-Mode Storage Pivot (Slice A+B)
- **Phase:** Phase 8 — Reference-Mode Storage Pivot
- **Completed:** 2026-04-08
- **Objective:** Deliver thumbnail infrastructure and stop retaining full-resolution originals for newly connector-synced items after confirmed thumbnail storage.
- **Outcome:** `MediaItem.thumbnail_path` + `MediaItem.storage_mode` added; `save_thumbnail()` on both `LocalFileStore` and `S3FileStore`; `GET /thumbnail` with graceful fallback; `GET /file` returns `original_not_retained` 404 for `preview_only` items; connector Slice B: synchronous analysis + deletion. Frontend consumes `/thumbnail`. Alembic migration `a1b2c3d4e5f7`. 11 tests in `tests/test_storage_pivot.py`. Total: 363/363 pass. Committed `c11e8c8`, deployed to EC2.
- **Artifacts produced:** `src/models.py`, `src/storage/file_store.py`, `src/api/routes/media.py`, `src/connectors/sync_service.py`, `alembic/versions/a1b2c3d4e5f7_*.py`, `tests/test_storage_pivot.py`, frontend `client.ts` + display components.

### P7-006: Auto-sync Scheduler
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-07
- **Objective:** Let users configure a source connector to sync automatically on a schedule, removing the need to click "Sync now" manually.
- **Outcome:** Full auto-sync feature delivered across data model, migration, backend API, scheduler, and frontend.
  - **Data model:** Added `auto_sync_enabled: bool = False` and `auto_sync_interval_minutes: int = 60` to `SourceConnector` in `src/models.py`. Alembic migration `a0b1c2d3e4f5` (revises `f8a9b0c1d2e3`).
  - **Schema:** `AutoSyncUpdateRequest(enabled: bool, interval_minutes: int ge=15 le=1440)` added to `src/api/schemas.py`. `ConnectorResponse` extended with `auto_sync_enabled` and `auto_sync_interval_minutes`.
  - **Backend endpoint:** `PATCH /api/v1/sources/{source_id}/connector/auto-sync` in `src/api/routes/connectors.py`. Guards: 404 if source not owned or no connector exists. Sets fields, commits, returns `ConnectorResponse.from_connector()`.
  - **Sync service:** `trigger_sync()` in `src/connectors/sync_service.py` now accepts `trigger_type: str = "manual"` and passes it to `SyncRun`, enabling the scheduler to set `trigger_type="auto"`.
  - **Scheduler:** `_auto_sync_task()` opens its own `async_session` and calls `trigger_sync(..., trigger_type="auto")`. `_auto_sync_loop()` wakes every 60 s, queries connectors with `auto_sync_enabled=True` joined to non-archived sources, skips sources with an in-progress `SyncRun`, fires a background task per due source. Loop started via `asyncio.create_task()` in `lifespan()` just before `yield`; task is cancelled and awaited on shutdown.
  - **Frontend API:** `updateConnectorAutoSync(sourceId, enabled, intervalMinutes)` added to `frontend/src/api/client.ts`. `ConnectorResponse` type extended with `auto_sync_enabled?` and `auto_sync_interval_minutes?` in `frontend/src/types/api.ts`.
  - **Frontend UI:** Auto-sync row added to the Drive connector summary view in `SourcesPage.tsx` — checkbox toggle (On/Off) plus interval `<select>` that is only visible when auto-sync is enabled. Both controls call `updateConnectorAutoSync` and update local state via `setConnector(updated)`.
  - **Tests:** 6 new tests appended to `tests/test_connectors.py` (total 24): enable, disable, invalid interval (422), max interval (1440), no connector (404), wrong user (404).
- **Key decisions:**
  - Minimum interval 15 minutes to avoid hammering the Google Drive API; maximum 1440 minutes (24 h) to cover daily-sync use cases.
  - The scheduler loop fires background tasks per source rather than running sync inline, matching the pattern set by `_retry_writeback_task` (isolated sessions, no task blocking the loop tick).
  - `_auto_sync_loop` handles `asyncio.CancelledError` with a `break` so shutdown is clean.
  - `_file_store` and `_upload_service` are constructed inside `_auto_sync_task` using the same factory functions used at startup — avoids coupling to module-level state from `connectors.py`.
- **Lessons learned:** Module-level service instances from route modules should not be imported in background tasks; construct fresh from config instead.

### P7-005: Pending Write-back Retry Job
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-07
- **Objective:** Close the open loop from P7-004: items stuck in `mutation_state = 'pending_writeback'` (transient Drive 5xx / network errors) were never retried automatically, and the UI offered no manual retry path.
- **Outcome:** On-demand retry endpoint, startup sweep, and frontend retry button delivered.
  - **Backend endpoint:** `POST /api/v1/media/{id}/retry-writeback` in `src/api/routes/media.py`. Guards: 404 if item not found or belongs to another user; 422 if `mutation_state != 'pending_writeback'` (blocked items must not be silently retried). Calls `attempt_drive_rename_after_analysis(db, item)`, commits, returns `MutationStateResponse`.
  - **Startup sweep:** `_retry_writeback_task(media_item_id)` module-level coroutine in `src/api/app.py` opens its own `async_session`, loads the item fresh, calls the mutation service, commits. Added to `lifespan()` after the analysis-job resume block: queries all `pending_writeback` items and fires a background task per item.
  - **Frontend API:** `retryWriteback(mediaId)` added to `frontend/src/api/client.ts`.
  - **Frontend UI:** `retrying` / `retryError` state vars added to `MediaDetailPage.tsx`. "Retry now" button in the `pending_writeback` mutation-state banner; shows "Retrying…" while in flight, displays error message on failure, updates `media.mutation_state` from the response on success.
  - **Tests:** 6 new tests appended to `tests/test_mutation_completion.py` (total 33 tests in that file): `fully_applied` on mocked Drive 200, 422 on NULL state, 422 on `blocked_writeback` state, 404 on unknown item, 404 on wrong user, response stays `pending_writeback` on mocked Drive 5xx failure.
- **Key decisions:**
  - `blocked_writeback` items are explicitly rejected with 422 — they require user action (re-auth, folder access), not silent retry.
  - The startup sweep fires background tasks independently of the analysis job sweep — `_retry_writeback_task` opens its own session to avoid session lifetime issues.
  - The retry endpoint returns `MutationStateResponse` regardless of outcome — the caller can read the resulting state and decide what to show.
- **Lessons learned:** Startup background tasks that touch the DB must open their own async session; passing the lifespan session into a `create_task` coroutine causes `DetachedInstanceError` after the lifespan block exits.

### P7-001: Collections
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-06
- **Objective:** Allow users to organise media items into named collections (albums). Collections are user-owned, named groups of media items with an optional description. Items can belong to multiple collections.
- **Outcome:** Full collections feature delivered across data model, backend API, and frontend.
  - **Data model:** `collections` table (id, user_id FK, name VARCHAR(200), description VARCHAR(1000), created_at, UNIQUE(user_id, name)) and `collection_items` join table (id, collection_id FK, media_item_id FK, added_at, UNIQUE(collection_id, media_item_id)). Alembic migration `c0d1e2f3a4b5`. `Collection` and `CollectionItem` ORM models added to `src/models.py`.
  - **Backend API:** 7 endpoints in `src/api/routes/collections.py` registered at `/api/v1/collections`. `POST /api/v1/collections` (create, 201, enforces 100-collection-per-user limit, 409 on duplicate name). `GET /api/v1/collections` (list, user-scoped, includes item_count and cover_url per collection). `GET /api/v1/collections/{id}` (detail with full items list). `PATCH /api/v1/collections/{id}` (rename/update description). `DELETE /api/v1/collections/{id}` (204, cascades collection_items without deleting media items). `POST /api/v1/collections/{id}/items` (batch add, max 500 items, skips cross-user and duplicate items). `DELETE /api/v1/collections/{id}/items` (batch remove). All endpoints enforce ownership — other users' collections return 404.
  - **Schemas:** `CollectionCreateRequest`, `CollectionUpdateRequest`, `CollectionResponse` (with item_count, cover_url), `CollectionListResponse`, `CollectionDetailResponse` (with items list), `CollectionItemsRequest`, `CollectionItemsModifiedResponse` added to `src/api/schemas.py`.
  - **Frontend:** `CollectionsPage.tsx` at `/collections` — grid of collection cards (cover thumbnail, name, item count). `CollectionDetailPage.tsx` at `/collections/:id` — full item grid with back button, edit/delete controls. "Add to Collection" button and collection picker in `MediaDetailPage.tsx`. `listCollections`, `getCollection`, `createCollection`, `updateCollection`, `deleteCollection`, `addItemsToCollection`, `removeItemsFromCollection` in `client.ts`. TypeScript interfaces in `api.ts`. Nav link to Collections in `Layout.tsx`.
  - **Bug fix:** `_media_item_to_response` helper in `collections.py` used `item.display_name` (not an ORM attribute); corrected to `item.original_filename`.
  - **Tests:** 36 new tests in `tests/test_collections.py` covering all 7 endpoints, user isolation (IDOR protection), limits, idempotency, cascade behavior, and cover URL.
- **Key decisions:**
  - Collections are purely organisational — no re-analysis or re-index on add/remove.
  - Cover image auto-selects the earliest-added item's thumbnail; no manual override in this phase.
  - Deleting a collection never deletes the underlying media items.
  - Cross-user media items submitted to `add_items` are silently skipped (no 404 enumeration leak).
- **Lessons learned:** `MediaItem` ORM model does not have a `display_name` attribute — it is derived from `MediaMetadata.title` in `media.py`. Collection item responses must use `item.original_filename` as the display name fallback.

### P7-004: Source Mutation Completion States
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-06
- **Objective:** Formalize and implement the completion-state contract for Google Drive, browser local working-folder, and folder-scan intake flows. "Analysis alone ≠ completion when source mutation is required." Provide durable filename+mutation history so the system knows what each source asset was named before rename and metadata write-back.
- **Outcome:** Full P7-004 contract delivered across data model, backend services, API, and frontend.
  - **Data model:** `MediaItem` gains 9 new mutation-tracking fields (`mutation_state`, `first_seen_source_filename`, `prior_source_filename`, `source_filename_applied_at`, `last_writeback_at`, `last_mutation_attempted_at`, `last_mutation_error_code`, `last_mutation_error_message`, `source_file_fingerprint`). `SourceConnector` gains `granted_scopes` (Text, nullable). New `source_mutation_history` table for full audit trail. Alembic migration `f8a9b0c1d2e3` (revises `e2f3a4b5c6d7`).
  - **Drive scope upgrade:** `google_drive_oauth.py` rewritten — `DRIVE_SCOPE_READWRITE` is now the default for new authorizations, `scope_has_write()` helper added, `sign_state()`/`verify_state()` updated to embed and return a 3-tuple `(user_id, source_id, mode)` with backward compat for legacy 3-part states. New `POST /api/v1/sources/{id}/connector/google-drive/upgrade-scope/start` endpoint.
  - **Drive mutation service:** `src/analysis/drive_mutation_service.py` implements `attempt_drive_rename_after_analysis()` — slugifies AI title, checks write scope, decrypts credentials, refreshes access token, finds Drive file ID via `SourceObject`, calls Drive PATCH API. State transitions: `fully_applied` (HTTP 200), `blocked_writeback` (no scope / 401 / 403 / 404 / credential error), `pending_writeback` (HTTP 5xx / network error). History row written on every attempt.
  - **Processor integration:** `processor.py` calls `attempt_drive_rename_after_analysis()` after analysis success (guarded by `try/except` so mutation errors never kill analysis).
  - **Local flow endpoint:** `POST /api/v1/media/{id}/mutation-result` — browser reports rename or metadata write-back result; backend sets `fully_applied` or `blocked_writeback` and writes `SourceMutationHistory`.
  - **Schemas:** `MediaItemResponse`, `AnalysisResponse` gain `mutation_state` / `last_mutation_error_code`. `ConnectorResponse` gains `has_write_scope` computed via `from_connector()` classmethod. New `LocalMutationResultRequest` and `MutationStateResponse` schemas.
  - **Frontend:** Mutation-state banner in `MediaDetailPage.tsx` (green/yellow/red per state). Scope-upgrade warning + "Upgrade Drive permissions" button in `SourcesPage.tsx`. `upgradeGoogleDriveScope()` and `reportLocalMutationResult()` added to `client.ts`. TypeScript types updated in `api.ts`. CSS classes added to `index.css`.
  - **Tests:** 27 new tests in `tests/test_mutation_completion.py` covering all completion states, history persistence, backward-compat verify_state, unit tests for slugify/target_filename. 3 existing Drive connector tests updated for the scope change (`drive.readonly` → `drive`).
- **Key decisions:**
  - `DRIVE_SCOPE` default changed to writable; existing connectors with `granted_scopes = NULL` or only `drive.readonly` are classified as `blocked_writeback` (no silent fallback).
  - `verify_state()` now returns a 3-tuple — added `mode` for upgrade flow; backward compat handles legacy 3-part states.
  - `ConnectorResponse.from_connector()` classmethod pattern used instead of Pydantic model_validator to avoid ORM session complexity.
  - Mutation service errors never propagate to the analysis pipeline — wrapped in try/except in `processor.py`.
- **Lessons learned:** SQLAlchemy test records for `SourceConnector` require all NOT NULL fields including `remote_container_id`; tests fail with IntegrityError otherwise. When changing OAuth return values, all existing tests that unpack the old return format must be updated in the same session.

### P7-003: Navigation & UX Redesign (Add Media Hub)
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-05
- **Objective:** Eliminate Source management friction. Make `/add-media` the single ingestion entry point. Rename Sources → Connections. Enable Google Drive OAuth in one click without pre-creating a Source.
- **Outcome:** All 6 sub-workstreams delivered as designed. No DB migration required.
  - **WS-01 (Backend):** `_resolve_source_id()` in `upload.py` now auto-creates a per-user `__uploads__` system Source when no `source_id` is provided, instead of returning `None`. System sources use `__` prefix convention.
  - **WS-01 (Frontend):** Removed all source picker UI from `UploadPage.tsx` — 6 state vars, `useEffect`, `handleCreateSource`, `handleRestoreFromConflict`, the source section JSX, and the `selectedSourceId` argument to `uploadFile()`.
  - **WS-05:** "Sources" → "Connections" in `Layout.tsx` nav and `SourcesPage.tsx` `<h1>`. Path `/sources` unchanged.
  - **WS-03:** `POST /api/v1/connectors/google-drive/quick-connect` — creates a Source + initiates OAuth in one request. `ConnectorDriveQuickConnectRequest` schema added to `schemas.py`. `quickConnectGoogleDrive()` added to `client.ts`.
  - **WS-02:** `AddMediaPage.tsx` created at `/add-media`. Contains: file upload queue (full logic), inline Drive configure panel (folder picker after callback), Drive quick-connect button, S3 link to Connections. `/upload` → `<Navigate to="/add-media" />` redirect in `App.tsx`. CSS appended to `index.css`.
  - **WS-04:** Both `_error_redirect()` and the success path in `google_drive_callback()` now redirect to `{frontend_url}/add-media` instead of `/sources`.
  - **WS-06:** `SourcesPage.tsx`: system sources (`__` prefix) excluded from active/archived lists; "+ Add connection" link to `/add-media` added to header; empty-state links updated.
- **Key decisions:**
  - System sources use `__` prefix so they're identifiable without a schema column. Filtered at the query/display layer; no DB change needed.
  - Quick-connect creates the Source before returning the OAuth URL so `source_id` is available in the callback state. Source is committed inside the endpoint (not deferred to caller).
  - `/upload` route kept as a redirect rather than removed, to avoid 404s from bookmarks/external links.
- **Artifacts produced:** `frontend/src/pages/AddMediaPage.tsx` (new), `frontend/src/pages/UploadPage.tsx` (stripped), `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/pages/SourcesPage.tsx`, `frontend/src/api/client.ts`, `frontend/src/index.css`, `src/api/routes/upload.py`, `src/api/routes/google_drive_connector.py`, `src/api/schemas.py`, `docs/planning/ARCH-001-navigation-ux-redesign.md`, `docs/planning/ARCH-002-reference-mode-storage.md` (backlog). Commit: `985a220`.
- **Test fixes (same session):** Fixed 4 pre-existing test failures unrelated to P7-003: `MockVisionProvider.analyze_image()` missing `hint` keyword arg (added `hint: str | None = None` to `mock_provider.py`); 3 tests expecting 503 "feature disabled" were getting 200 because `config.py` calls `load_dotenv()` at import time and the `.env` file has credentials set — fixed by adding `monkeypatch` to each test to explicitly clear the setting. Commit: `8a69c8a`.
- **Lessons learned:** `load_dotenv()` at module import means all local tests run with production-like credentials from `.env`. Tests that assert "feature off" always need `monkeypatch` to override the setting explicitly.

### Beta Feedback Polish + Re-analyze Hint + Manual Metadata Edit
- **Phase:** Phase 6 — Identity & Access (post-P6-001 beta feedback)
- **Completed:** 2026-04-05
- **Objective:** Polish the UI based on beta tester feedback and add two user-requested features: guided re-analysis with an optional AI hint, and in-place manual metadata editing.
- **Outcome:** All items shipped and deployed to vyzindex.com. Key changes:
  - Upload status labels: `Uploading…` → `Processing…`, `Created` → `Completed`
  - Clear Completed button removed from UploadPage
  - Active nav highlight via React Router `NavLink` + `.nav-link.active` CSS
  - Billing page redesigned as 3-column horizontal plan cards with Active Plan banner + border
  - Auth divider centered with flexbox pseudo-element rules
  - MediaDetailPage polling fixed: auto-polls when media is processing/pending even if analysis is null
  - Re-analyze race condition fixed: `reanalyzing=true` state forces poll; no post-trigger getAnalysis fetch
  - **Re-analyze with AI hint:** Guidance textarea always shown in the Analysis panel. Hint sent to Claude as authoritative context that overrides conflicting visual impressions. Hint persists after re-analyze for refinement. `ReanalyzeRequest(hint: str | None, max_length=500)` schema; `analyze_image(hint=)` on `AnthropicVisionProvider` and `VisionProvider` protocol; `analyze_media_item(hint=)` in processor; `reanalyze(id, hint?)` in `client.ts`.
  - **Manual metadata editing:** `Edit` button toggles an inline form across all 13 editable fields (text, textarea, comma-separated lists, orientation dropdown). `PATCH /api/v1/media/{id}/analysis` endpoint; `MetadataUpdateRequest` Pydantic schema; `MetadataDisplay` component refactored with edit/view mode. On save: DB updated, vector index re-indexed best-effort, fresh `AnalysisResponse` returned to update UI state.
  - **`get_analysis` polling correctness:** Endpoint now checks for an active pending/running job before returning cached completed metadata, so re-analyze polling works correctly on first run.
  - **`getMedia` cache correctness:** Only caches terminal statuses (not `processing`/`pending`/`uploaded`), matching the same pattern as `getAnalysis`. Prevents stale "processing" badge after re-analyze completes.
- **Key decisions:** Hint prompt uses "ground truth — overrides conflicting visual impressions" framing rather than "additional guidance" so Claude defers to user-supplied context even when the image strongly suggests otherwise. Hint textarea is always shown (never gated behind a button) to make the feature discoverable and reduce clicks. Metadata PATCH uses `model_dump(exclude_unset=True)` so partial updates don't clobber fields not sent by the client. Vector re-indexing on metadata edit is best-effort (silent pass on failure) since stale embeddings are preferable to a failed save.
- **Artifacts modified:** `frontend/src/components/FileQueue.tsx`, `frontend/src/pages/UploadPage.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/pages/BillingPage.tsx`, `frontend/src/index.css`, `frontend/src/pages/MediaDetailPage.tsx`, `frontend/src/components/MetadataDisplay.tsx`, `frontend/src/api/client.ts`, `src/analysis/anthropic_provider.py`, `src/analysis/provider.py`, `src/analysis/processor.py`, `src/api/routes/analysis.py`, `src/api/schemas.py`

---

### P7-002: Google Drive Connector (Root-Only)
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Completed:** 2026-04-05
- **Objective:** Add the first OAuth-backed connector so users can authorise their Google Drive, connect `My Drive` as the root sync container, and pull supported image files through the existing ingestion pipeline — without widening scope to sub-folder selection, batch delete, or multi-account support.
- **Outcome:** Full end-to-end Google Drive connector implemented and tested. DB schema is now provider-neutral (`remote_container_id` / `remote_container_label` + four account-snapshot columns). An HMAC-signed, browser-bound OAuth state guards the callback. Encrypted Fernet token storage holds the refresh token alongside scopes and issuance timestamp. The sync pipeline now routes by connector type through a factory rather than hardcoding S3. A dedicated `DriveTokenManager` handles token refresh and in-memory access-token caching with rotation persistence. The UI gains a Drive connect / disconnect flow with an account-connected info panel and a callback result banner. 25 new tests pass; all 18 existing S3 regression tests pass.
- **Key decisions:** State signing uses the same HMAC-SHA256 pattern as Google SSO (`{user_id}|{source_id}|{nonce}.{ts}.{hmac_hex}`), with the nonce stored in a `gdrive_connector_state` HTTP-only cookie (max-age 600s) and consumed once on callback to prevent replay. `prompt=consent` and `access_type=offline` are always sent so a fresh refresh token is issued even if the user previously granted access — this ensures the refresh token is always present after authorisation. Drive query filter excludes shortcuts, all native Google Docs MIME types, and non-image files: `trashed=false and mimeType!='application/vnd.google-apps.shortcut' and not mimeType contains 'application/vnd.google-apps.' and mimeType contains 'image/'`. Reconnect logic: if the new authorised account's `provider_id` matches the existing connector, `source_objects` and `sync_runs` are preserved (same Drive, reuse state); if the `provider_id` differs, `source_objects` are deleted so the sync engine re-discovers objects under the new account from scratch. Logical disconnect (DELETE endpoint) clears `credentials_encrypted` to an empty dict but preserves the account snapshot columns so the UI can show "was connected to …" context. `RemoteObject` gained a `display_name` field so file names (not just Drive file IDs) flow through to the database. `build_connector()` factory dispatches on `connector_type` — S3 routes to the existing builder, `google_drive` routes to `GoogleDriveConnector` wrapping a `DriveTokenManager`. `sync_service.py` now calls `build_connector(connector_row, credentials)` instead of `build_s3_connector(...)`. ADRs 021–025 (pre-written by Architect) cover all five locked decisions.
- **Artifacts produced:**
  - `alembic/versions/d1e2f3a4b5c6_google_drive_connector.py` — renames `bucket_name` → `remote_container_id`; adds `remote_container_label`, `authorized_account_provider_id`, `authorized_account_email`, `authorized_account_display_name`; backfills `remote_container_label` from `remote_container_id` for existing S3 rows
  - `src/models.py` — `SourceConnector.bucket_name` → `remote_container_id`; four new nullable account columns
  - `src/api/schemas.py` — `ConnectorResponse` updated (provider-neutral field names + account snapshot fields); `ConnectorDriveStartResponse` added
  - `src/api/routes/connectors.py` — S3 upsert writes both `remote_container_id` and `remote_container_label`
  - `src/connectors/base.py` — `RemoteObject.display_name: str` added
  - `src/connectors/s3_connector.py` — `RemoteObject` construction sets `display_name = os.path.basename(key) or key`
  - `src/connectors/sync_service.py` — imports `build_connector` from factory; filename derivation uses `remote_obj.display_name` with fallback
  - `src/config.py` — `GoogleDriveConfig` dataclass + `Settings.google_drive` field + 5 env-var overrides
  - `src/auth/google_drive_oauth.py` (new) — `generate_nonce`, `sign_state`, `verify_state`, `build_auth_url`; `DRIVE_STATE_COOKIE`, `DRIVE_STATE_MAX_AGE`, `DRIVE_SCOPE` constants
  - `src/connectors/google_drive_tokens.py` (new) — `DriveTokenError`; `exchange_code`; `fetch_account_snapshot`; `DriveTokenManager` (in-memory access token cache + `_refresh_access_token` with rotation persistence)
  - `src/connectors/factory.py` (new) — `build_connector(connector_row, credentials) → ConnectorBase`
  - `src/connectors/google_drive_connector.py` (new) — `GoogleDriveConnector(ConnectorBase)` with `list_objects`, `download_object`, `validate`
  - `src/api/routes/google_drive_connector.py` (new) — `POST /sources/{id}/connector/google-drive/start`; `GET /connectors/google-drive/callback`; `DELETE /sources/{id}/connector/google-drive`
  - `src/api/app.py` — `google_drive_connector` router registered
  - `frontend/src/types/api.ts` — `ConnectorResponse` updated; `ConnectorDriveStartResponse` added
  - `frontend/src/api/client.ts` — `startGoogleDriveConnector`, `disconnectGoogleDriveConnector`
  - `frontend/src/pages/SourcesPage.tsx` — callback banner, Drive connect/disconnect flow, connected-account info panel, `remote_container_id` usage
  - `tests/test_google_drive_connector.py` (new) — 25 tests covering state crypto, OAuth URL, token exchange + rotation, factory dispatch, Drive query, start/callback/disconnect/reconnect routes
  - `tests/test_connectors.py` — updated for schema rename (`bucket_name` → `remote_container_id`) and `display_name` in `_make_remote_obj`
- **Lessons learned:** When patching async helper functions in route module tests, always patch the name at its **import location** in the route module (e.g. `src.api.routes.google_drive_connector.exchange_code`), not at the definition module — otherwise the route function resolves the original reference and the mock is never seen. In-process `authlib` dependency was already in `requirements.txt` but absent from the test environment; `pip install authlib` resolved 14 test errors immediately at the first pytest run. Using `prompt=consent` unconditionally on the Drive auth URL is the right default because Google only issues a refresh token on the first consent grant — without it, reconnects after a token expiry silently return no refresh token and silently break syncs.

---

### P6-001: Google SSO (Sign in with Google)
- **Phase:** Phase 6 — Identity & Access
- **Completed:** 2026-04-04
- **Objective:** Add Google-based sign-in and registration while preserving existing email+password auth, automatically linking same-email accounts, and keeping the existing JWT contract unchanged.
- **Outcome:** Full Google SSO flow implemented. Alembic migration `a3b4c5d6e7f8` (down_revision `f6a7b8c9d0e1`) adds `oauth_accounts` table (UNIQUE on `(provider, provider_user_id)` and `(user_id, provider)`) and `google_completion_records` table. `GoogleAuthConfig` dataclass added to `config.py` with `is_ready` property and 5 env overrides. `authlib>=1.3.0` and `httpx>=0.27.0` added to main dependencies. `src/auth/google_oauth.py` provides crypto utilities: HMAC-SHA256 signed state (format `{raw_state}.{ts}.{sig}`, max-age 600s), nonce generation, `build_auth_url`, `exchange_code_and_validate` (httpx code exchange + Authlib JWKS OIDC validation + nonce/email_verified checks). `src/api/routes/google_auth.py` provides: `GET /api/v1/auth/config` (feature-flag), `GET /api/v1/auth/google/start` (signed state + nonce cookies, redirect to Google), `GET /api/v1/auth/google/callback` (state validation, identity exchange, user resolution, completion record creation, redirect to frontend), `POST /api/v1/auth/google/exchange` (single-use completion record consumption, constant-time hash comparison, JWT issuance). Account resolution: provider-link-first → email fallback (with `_AccountDisabledError` + `_LinkConflictError` guards) → create new user with `password_hash=None`. Frontend: `GoogleAuthCallbackPage.tsx` reads `flow_id`/`error` query params, calls `loginWithGoogle`, navigates to `/` or shows mapped error; `LoginPage.tsx` and `RegisterPage.tsx` fetch `/api/v1/auth/config` on mount and show Google button when enabled; `AuthContext.tsx` gains `loginWithGoogle(flowId)` using `exchangeGoogleAuth` with `credentials: include`; `App.tsx` adds `/auth/google/callback` as standalone route (outside Public/Protected guards). 20 new tests in `tests/test_auth_google.py`; all pass.
- **Key decisions:** State signing uses HMAC-SHA256 over `{raw_state}:{ts}` with the existing `auth.secret_key`; raw state stored in HTTP-only cookie, signed state sent to Google, timestamp checked for replay (≤600s). OIDC nonce stored in HTTP-only cookie, checked against `nonce` claim after Authlib decode — two independent anti-CSRF layers. Completion handoff uses a short-lived DB record: public `flow_id` in redirect URL + secret `completion_id` in HTTP-only cookie scoped to `/api/v1/auth/google/exchange` only; `consumed_at` set on first use. Provider-link lookup takes priority over email fallback — no silent re-linking across different Google `sub` values. `ENABLE_GOOGLE_SSO` env var is a mandatory rollout gate (off by default). JWT contract (`sub` + `exp`) unchanged. Migration ID `a3b4c5d6e7f8` was chosen because the plan's proposed `a1b2c3d4e5f6` is taken by the `curation_scores` migration.
- **Artifacts produced:** `alembic/versions/a3b4c5d6e7f8_google_sso.py`, `src/auth/google_oauth.py`, `src/api/routes/google_auth.py`, `src/models.py` (OAuthAccount + GoogleCompletionRecord + User.oauth_accounts), `src/config.py` (GoogleAuthConfig + Settings + env overrides), `pyproject.toml` (authlib + httpx main deps), `src/api/app.py` (google_auth router), `src/api/schemas.py` (GoogleExchangeRequest), `frontend/src/types/api.ts` (AuthConfig + GoogleExchangeRequest), `frontend/src/api/client.ts` (getAuthConfig + exchangeGoogleAuth), `frontend/src/context/AuthContext.tsx` (loginWithGoogle), `frontend/src/pages/GoogleAuthCallbackPage.tsx`, `frontend/src/pages/LoginPage.tsx` (Google button), `frontend/src/pages/RegisterPage.tsx` (Google button), `frontend/src/App.tsx` (standalone callback route), `tests/test_auth_google.py` (20 tests)
- **Lessons learned:** Authlib's `jwt.decode()` accepts JWKS directly from a `requests.get` JSON response; no extra key conversion needed. Httpx `AsyncClient` must be created in the async function that uses it (not at module level) to avoid event loop issues. Cookie-scoped paths (`path=/api/v1/auth/google/callback`) reduce the attack surface dramatically but require the test client to send cookies explicitly.

---

### Bugfix: Concurrent upload race condition (2026-04-02)
- **Completed:** 2026-04-02
- **Objective:** Fix "Request failed" errors when two identical files are uploaded at the same time.
- **Outcome:** Added `except IntegrityError` handler in `UploadService.process_upload()`. When the unique constraint `uq_user_content_hash` is violated by a concurrent commit, the handler rolls back, deletes the orphaned stored file, re-queries for the winning item, and returns it as `is_duplicate=True`. Added `test_concurrent_duplicate_handled_gracefully` using a call-count side-effect patch to simulate the race window. 209/209 tests pass. Commit: `fc2147a`.
- **Artifacts produced:** `src/ingestion/upload_service.py` (IntegrityError import + handler), `tests/test_upload.py` (+1 test)

---

### P5-003: Connector Sync Foundation & First Connector
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Completed:** 2026-04-04
- **Objective:** Extend the Source Registry into a real connected-ingestion system with an encrypted credential store, sync-run state machine, idempotent per-object import tracking, and an S3-compatible connector that reuses the existing upload pipeline.
- **Outcome:** Full connector sync foundation implemented end-to-end. Alembic migration `f6a7b8c9d0e1` (down_revision `a1b2c3d4e5f6`) adds `connector_status VARCHAR(30)` and `last_synced_at TIMESTAMPTZ` to `sources`; creates `source_connectors` (UNIQUE on `source_id`), `sync_runs`, and `source_objects` (UNIQUE on `source_id, external_object_key`) tables. `ConnectorConfig` dataclass added to `src/config.py` with `credentials_key: str = ""` (from env `CONNECTOR_CREDENTIALS_KEY`) and `max_objects_per_sync: int = 1000`. `src/connectors/` package: `secrets.py` wraps Fernet (from `cryptography`, transitive dep via `python-jose[cryptography]`) — `encrypt_credentials()`, `decrypt_credentials()`, `require_encryption_key()` fail-closed guard, `MissingEncryptionKeyError`; `base.py` defines `RemoteObject` dataclass + `ConnectorBase` ABC + `ConnectorValidationError`; `s3_connector.py` implements `S3Connector` (all boto3 calls via `asyncio.run_in_executor`, image-extension filter, `max_keys` bound, prefix pagination) + `build_s3_connector()` factory; `sync_service.py` provides `trigger_sync()` public entry point + `_run_sync()` core orchestrator (decrypt credentials → build connector → list objects → load existing SourceObjects → iterate with idempotency check, download, process_upload, quota reservation, analysis task enqueue, per-object error isolation, run counter updates, terminal state). ORM models added to `src/models.py`: `SourceConnector` (credentials_encrypted, config_validated_at), `SyncRun` (trigger_type, status, all counters, error_summary), `SourceObject` (external_object_key, external_version, state, last_error, last_content_hash); `Source` extended with `connector_status`, `last_synced_at`, `connector` relationship. `src/api/routes/connectors.py` created: `POST /{id}/connector/s3` (upsert config, encrypt credentials, update Source.connector_status, 503 when key absent), `GET /{id}/connector` (no secrets in response), `POST /{id}/sync` (validate no overlap + connector exists → return 202 + background task), `GET /{id}/sync-runs` (paginated, newest-first). Connectors router registered in `src/api/app.py`. `src/api/schemas.py` extended with `ConnectorS3ConfigRequest`, `ConnectorResponse` (secrets excluded), `SyncRunResponse`, `SyncRunsResponse`, `TriggerSyncResponse`, `SourceResponse` extended with `connector_status`/`last_synced_at`. Frontend: `frontend/src/types/api.ts` extended with connector/sync interfaces; `frontend/src/api/client.ts` adds `configureS3Connector`, `getConnector`, `triggerSync`, `listSyncRuns`; `frontend/src/pages/SourcesPage.tsx` gains `ConnectorPanel` component (tabbed: Configure / Sync runs) with S3 form (credentials masked after save), "Sync now" button, sync runs table with status badges and counters; connector status badge shown inline on each source row. 18 new tests in `tests/test_connectors.py`; all 208 tests pass.
- **Key decisions:** Credentials encrypted with Fernet symmetric encryption (not stored in plaintext); key sourced from env only — fail closed if absent (503 from all connector endpoints). Secrets never returned in API responses — `ConnectorResponse` has no `credentials_encrypted`, `access_key_id`, or `secret_access_key` fields. Idempotency keyed on `(external_object_key, external_version)` — skip if both match a terminal state (`imported`/`duplicate`); conservative re-download when version field unavailable. Overlap prevention: check for `pending`/`running` SyncRun before accepting a new trigger. Quota reservation matches manual upload path exactly: `quota_service.reserve()` after `process_upload()` succeeds for non-duplicate files, before `analyze_media_item` task is enqueued. Per-object failures are isolated — `failed_count` incremented, run continues. Quota exhaustion stops the loop gracefully with `completed_with_errors` status. S3 connector uses `asyncio.run_in_executor` for all boto3 calls (boto3 is synchronous). `boto3` listed as prod optional dependency; lazy import with helpful error if missing. ADRs 014 (credential encryption) and 015 (idempotency strategy) were pre-written in DECISION_LOG by the Architect before implementation.
- **Artifacts produced:** `alembic/versions/f6a7b8c9d0e1_connector_sync_foundation.py`, `src/connectors/__init__.py`, `src/connectors/secrets.py`, `src/connectors/base.py`, `src/connectors/s3_connector.py`, `src/connectors/sync_service.py`, `src/api/routes/connectors.py`, `src/models.py` (SourceConnector + SyncRun + SourceObject + Source extensions), `src/config.py` (ConnectorConfig + CONNECTOR_CREDENTIALS_KEY), `src/api/app.py` (connectors router), `src/api/schemas.py` (connector + sync schemas + SourceResponse extension), `frontend/src/types/api.ts` (connector/sync types + SourceResponse extension), `frontend/src/api/client.ts` (4 new API functions), `frontend/src/pages/SourcesPage.tsx` (ConnectorPanel + status badge), `tests/test_connectors.py` (18 tests)

### P5-002: AI Best-Photo Selection
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Completed:** 2026-04-02
- **Objective:** Within near-duplicate groups detected by P5-001, rank each member by AI-assessed quality and mark the recommended best pick so users can curate burst shots faster.
- **Outcome:** Per-item AI quality scoring pipeline. Alembic migration `a1b2c3d4e5f6` adds `curation_scores` table with `quality_score` (FLOAT), `rationale` (TEXT), `scoring_model` (VARCHAR 100), `scored_at` (TIMESTAMPTZ), `user_id` FK, `media_item_id` FK (UNIQUE per item). `CurationScore` ORM model added to `src/models.py` with `curation_score` relationship on `MediaItem`. `CurationConfig.enable_ai_scoring` feature gate added to `src/config.py` (env var `ENABLE_AI_SCORING`, default OFF). `src/curation/scoring_service.py` provides `score_group()` (finds group members via pHash → calls AI for each → upserts scores), `load_scores_for_items()` (bulk DB load), `find_best_pick()` (pure-Python highest-score selector). AI prompt asks Claude for `quality_score` (0.0–1.0) + `rationale` (≤ 80 chars), scoped to sharpness, exposure, composition, motion blur, noise. `SimilarItemResponse` extended with `quality_score | None`, `rationale | None`, `is_best_pick: bool`. `SimilarItemsResponse` extended with `anchor_quality_score | None`, `anchor_rationale | None`, `anchor_is_best_pick: bool`. `ScoreGroupResponse` schema added. `GET /api/v1/media/{id}/similar` now attaches scores and computes best-pick at query time (reads from DB; does not re-trigger AI). `POST /api/v1/media/{id}/score-group` triggers scoring for the group (idempotent upsert). Frontend: `ScoreGroupResponse` type added; `scoreGroup(id)` added to client; `MediaDetailPage` similar strip shows anchor as first item, quality percentage badge on each item, 👑 crown on best pick, "Find best pick" button when scoring not yet done, `score-error` feedback. CSS: `.similar-header`, `.score-error`, `.similar-item--anchor`, `.similar-item--best-pick`, `.best-pick-crown`, `.similar-item-score` added. 16 new tests in `tests/test_scoring.py`. All 190/190 tests pass.
- **Key decisions:** Per-item scoring (not per-group) so scores survive group membership changes when new similar photos are uploaded. Best-pick computed at query time from live score rows — no stale `is_best_pick` flag in DB. Both `enable_duplicate_detection` AND `enable_ai_scoring` must be ON for scoring endpoints to activate — the two features compose cleanly. Scoring prompt is quality-focused only (not aesthetic) to keep AI responses consistent. Anchor item is shown as the first slot in the similar strip so users can compare all group members including their current photo. Failed individual item scores are non-fatal (logged at WARNING); remaining items continue normally.
- **Artifacts produced:** `alembic/versions/a1b2c3d4e5f6_curation_scores.py`, `src/models.py` (CurationScore + relationship), `src/config.py` (enable_ai_scoring + env override), `src/curation/scoring_service.py`, `src/api/schemas.py` (SimilarItemResponse extended + SimilarItemsResponse extended + ScoreGroupResponse), `src/api/routes/media.py` (GET /similar extended + POST /score-group), `frontend/src/types/api.ts` (ScoreGroupResponse + extended similar types), `frontend/src/api/client.ts` (scoreGroup()), `frontend/src/pages/MediaDetailPage.tsx` (scoring UI), `frontend/src/index.css` (score/crown CSS), `tests/test_scoring.py`, `docs/planning/P5-002_plan.md`

### P5-001: Near-Duplicate Detection Core
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Completed:** 2026-04-03
- **Objective:** Detect visually similar images per user, generate near-duplicate groups, and surface those groups in the Gallery without changing the existing exact-dedup upload rules.
- **Outcome:** Full end-to-end perceptual hashing pipeline. `imagehash>=4.3.1` added to `pyproject.toml`. Alembic migration `f1e2d3c4b5a6` adds `perceptual_hash` (VARCHAR 16), `phash_version` (VARCHAR 20), `phash_computed_at` (TIMESTAMPTZ) nullable columns + index to `media_items`. `src/curation/phash_service.py` provides `compute_phash()` (EXIF transpose → alpha flatten → greyscale → 64-bit pHash → 16 lowercase hex chars), `hamming_distance()`, `find_similar()`. `PHASH_VERSION = "phash64-v1"`, `PHASH_THRESHOLD = 10`. `CurationConfig.enable_duplicate_detection` feature gate added to `src/config.py` with `ENABLE_DUPLICATE_DETECTION` env var override (default OFF). pHash computed after DB commit in `upload_service.py` (non-fatal). `MediaItemResponse` extended with `has_similar: bool = False` / `similar_count: int = 0`. `SimilarItemResponse`/`SimilarItemsResponse` schemas added. `GET /api/v1/media/{id}/similar` endpoint returns user-scoped near-duplicates (feature-gated; 404 when OFF). Gallery batch similarity computation: one extra query per page response (no N+1). Frontend: `MediaItemResponse` TypeScript type updated; `getSimilarMedia(id)` added to client; `MediaCard` renders `.similar-badge` overlay when `hasSimilar=true`; `MediaDetailPage` shows similar photos strip when gate ON. Backfill script `scripts/backfill_phash.py` supports `--dry-run`, `--batch-size`, `--stop-after`, `--user-id`. 16 new tests in `tests/test_phash.py`. PROJECT_MAP updated.
- **Key decisions:** Hash stored on `media_items` (not `media_metadata`) — structural identity, not analysis. GIF excluded from pHash (first-frame-only would mislead similarity). Hamming threshold 10 bits → ~84% pixel similarity catches crops/exposure shifts without false positives between distinct subjects. Gallery similarity is batched per-page in Python (no SQL Hamming), which is safe for typical per-user libraries (<10k images). No persisted similarity graph in Phase 5 — computed on demand. Feature gate defaults OFF so existing users are unaffected until explicitly enabled.
- **Artifacts produced:** `alembic/versions/f1e2d3c4b5a6_perceptual_hash.py`, `src/curation/__init__.py`, `src/curation/phash_service.py`, `src/models.py` (3 pHash columns), `src/config.py` (CurationConfig + env override), `src/api/schemas.py` (has_similar/similar_count + SimilarItemResponse/SimilarItemsResponse), `src/api/routes/media.py` (batch similarity in _build_media_item_responses + GET /similar endpoint), `src/ingestion/upload_service.py` (pHash post-commit), `frontend/src/types/api.ts` (similarity types), `frontend/src/api/client.ts` (getSimilarMedia), `frontend/src/components/MediaCard.tsx` (similar badge), `frontend/src/pages/GalleryPage.tsx` (hasSimilar/similarCount props), `frontend/src/pages/MediaDetailPage.tsx` (similar strip), `frontend/src/index.css` (similar badge + strip styles), `scripts/backfill_phash.py`, `tests/test_phash.py`, `pyproject.toml` (imagehash dep)

### P4-006: OCR Search Enrichment
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Completed:** 2026-04-01
- **Objective:** Extract text from images using Tesseract OCR, store it alongside AI metadata, and incorporate it into semantic search.
- **Outcome:** Full end-to-end OCR pipeline. `pytesseract>=0.3.10` added to `pyproject.toml`; `tesseract-ocr` (v5.5) installed in Dockerfile. Alembic migration `d5e6f7a8b9c0` adds `ocr_text` nullable Text column to `media_metadata`. `src/ocr/ocr_service.py` runs Tesseract with `--psm 11 --oem 1` (sparse text — best for mixed-content images), upscales images where shortest dimension < 1000px, collapses newline fragments into single-line output, and applies word-ratio quality filter (discards if <20% of tokens are ≥3-char ≥80%-alpha words). OCR runs in the analysis processor after AI analysis; result stored in DB and passed to indexing. Both `build_embedding_text()` and `build_embedding_text_from_db()` append OCR text to semantic search vectors. `MetadataFields` schema returns `ocr_text`; analysis route populates it. Frontend `MetadataDisplay` shows "Extracted Text (OCR)" section (120px height cap, scrollable). 11 new tests in `tests/test_ocr.py`; **158/158 total tests pass**. Commits: `5dc4837`, `6c2002e`, `fa17515`, and threshold-fix commit. AWS deployed.
- **Key decisions:** `--psm 11` (sparse text) chosen as universal default over `--psm 3` (document layout) — performs better across natural photos, posters, screenshots, and signage. Upscaling to min 1000px before OCR recovers accuracy on small images. Newlines collapsed to single space — PSM 11 returns one word per line; storing as a flat string is better for search and display. Word-ratio filter at 0.20 threshold discards Tesseract noise from image texture/compression artifacts (ratio ~0.14) while passing real mixed-content results (ratio 0.25+). 120px display cap prevents UI page-stretch from verbose OCR output.
- **Artifacts produced:** `alembic/versions/d5e6f7a8b9c0_ocr_text.py`, `src/ocr/__init__.py`, `src/ocr/ocr_service.py`, `src/models.py` (ocr_text field), `src/analysis/processor.py` (OCR call + pass-through), `src/search/indexing_service.py` (ocr_text param), `src/search/embedding_text.py` (OCR text in both builders), `src/api/schemas.py` (ocr_text in MetadataFields), `src/api/routes/analysis.py` (ocr_text in response), `frontend/src/types/api.ts` (ocr_text field), `frontend/src/components/MetadataDisplay.tsx` (OCR display), `tests/test_ocr.py`, `pyproject.toml` (pytesseract dep), `Dockerfile` (tesseract-ocr apt package)

### P4-005: Billing Groundwork & Commercial Modeling
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Completed:** 2026-04-01
- **Objective:** Measure image-processing cost, codify plan tiers, and implement Stripe test-mode billing groundwork without enabling live paid launch.
- **Outcome:** Full implementation across all steps. `StripeConfig` dataclass added to `src/config.py` with env-var wiring (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_ADVANCED`, `STRIPE_PRICE_ID_PREMIUM`). `User` model extended with `stripe_customer_id`, `stripe_subscription_id`, `billing_status` (default: "none"). `StripeEvent` model added for webhook idempotency. Alembic migration `c3d4e5f6a7b8` creates billing columns and `stripe_events` table. `src/billing/billing_service.py` implements `create_checkout_session()`, `create_portal_session()`, `construct_stripe_event()`, `apply_subscription_event()` — all with dev-mode (empty key) fallbacks to placeholder URLs, idempotency via StripeEvent table, and plan tier mapping. Billing routes (`src/api/routes/billing.py`): `GET /status`, `POST /create-checkout-session`, `POST /create-portal-session`, `POST /webhook`. Admin PATCH extended to accept and validate `billing_status` overrides. `AdminUserSummary` + `AdminUpdateUserRequest` schemas extended with billing fields. Frontend: `BillingPage.tsx` (plan cards, upgrade/manage buttons, success/cancel URL param feedback), Billing nav link in `Layout.tsx`, billing API functions in `client.ts`, `BillingStatus` types in `api.ts`. 12 new tests in `tests/test_billing.py`; **147/147 total tests pass**. Commit: `406d5c6`. AWS deployed.
- **Key decisions:** Dev mode (empty `stripe.secret_key`) returns placeholder URLs instead of making real API calls — no code path differences for tests. Webhook signature verification skipped when `webhook_secret` is empty (dev only; always set in prod). Price-to-plan mapping is runtime-computed from settings, not hardcoded, so adding new tiers requires only env-var changes. `apply_subscription_event()` handles idempotency by recording events in `stripe_events` before returning — even for "user not found" cases, to avoid infinite retries. Dev-mode checkout skips price_id validation (price IDs not configured in dev).
- **Artifacts produced:** `src/config.py` (StripeConfig), `src/models.py` (User billing cols + StripeEvent), `alembic/versions/c3d4e5f6a7b8_billing.py`, `src/billing/__init__.py`, `src/billing/billing_service.py`, `src/api/routes/billing.py`, `src/api/app.py` (billing router), `src/api/schemas.py` (4 billing schemas + admin billing fields), `src/api/routes/admin.py` (billing_status PATCH), `frontend/src/pages/BillingPage.tsx`, `frontend/src/api/client.ts` (billing functions), `frontend/src/types/api.ts` (BillingStatus + billing fields on UserProfile/AdminUserSummary), `frontend/src/App.tsx` (/billing route), `frontend/src/components/Layout.tsx` (Billing nav), `tests/test_billing.py`, `docs/planning/P4-005_plan.md`
- **Lessons learned:** SQLite does not support `unique=True` inline in `ADD COLUMN` — must use a separate `CREATE UNIQUE INDEX` statement. This caused a double-run issue on dev DB (partial migration left columns added but not indexed); `alembic stamp` resolved it. PostgreSQL on AWS handles the migration cleanly. Dev-mode flag (empty secret_key) is the right pattern — no mock/stub needed in tests since the real code path returns predictable placeholder values.

### P4-004: Admin Console & User Profile Management
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Completed:** 2026-04-01
- **Objective:** Add admin-only user management, backend RBAC, audited admin actions, self-service profile updates, verified email change, and account recovery.
- **Outcome:** Full implementation across all 9 steps. Alembic migration `b2c3d4e5f6a7` adds `role`, `phone`, `company`, `icon_url`, `disabled_at` to users + new `admin_audit_log` and `pending_tokens` tables. `get_current_user()` and `require_admin()` dependencies added. Admin routes: `GET/PATCH /admin/users`, `GET /admin/users/{id}`, `GET /admin/audit-log` — all write audit entries on change. Auth routes extended: `PATCH /me`, expanded `GET /me` (returns role/phone/company/plan/limit), verified email-change (bcrypt-hashed PendingToken, 30-min expiry), password-reset (no enumeration, 2-hr expiry), disabled-user 403, email normalization. Frontend: `ProfilePage.tsx` + `AdminPage.tsx` (users table + edit modal, audit log tab). `/profile` + `/admin` routes in App.tsx; Layout shows conditional Admin nav link for admins. 20 new tests; **135/135 total tests pass**. Commit: `cb3326c`.
- **Key decisions:** PendingToken stores bcrypt hash (not plaintext) — plaintext only returned in `dev_mode` response for testability. Password-reset scans all non-expired tokens and bcrypt-verifies to avoid user enumeration at the request endpoint. `require_admin` also rejects `disabled_at is not None` so a disabled admin cannot use admin routes. Audit entries written within the same DB transaction as the change they record.
- **Artifacts produced:**
  - Created: `alembic/versions/b2c3d4e5f6a7_admin_profile.py`
  - Created: `src/api/routes/admin.py`
  - Created: `frontend/src/pages/ProfilePage.tsx`
  - Created: `frontend/src/pages/AdminPage.tsx`
  - Created: `tests/test_admin.py`, `tests/test_profile.py`
  - Modified: `src/models.py` (User extended, AdminAuditLog + PendingToken models)
  - Modified: `src/api/dependencies.py` (get_current_user, require_admin)
  - Modified: `src/api/schemas.py` (UserProfile extended, 8 new schemas)
  - Modified: `src/api/routes/auth.py` (PATCH /me, expanded GET /me, email-change, password-reset, disabled check, email normalization)
  - Modified: `src/api/app.py` (admin router registered)
  - Modified: `frontend/src/types/api.ts` (UserProfile extended, 5 new admin interfaces)
  - Modified: `frontend/src/api/client.ts` (10 new functions)
  - Modified: `frontend/src/App.tsx` (/profile + /admin routes)
  - Modified: `frontend/src/components/Layout.tsx` (Profile + conditional Admin nav links)
- **Validation performed:** 135/135 backend tests pass. AWS deployed and validated — `GET /api/v1/auth/me` returns extended profile; `GET /api/v1/admin/users` returns 403 for non-admin, 200 for admin. Dev user seeded as admin on AWS.
- **AWS deploy status:** Complete — migration `b2c3d4e5f6a7` ran on AWS postgres. Commit `cb3326c`.

### P4-002: Plans, Quotas & Analysis Confirmation
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Completed:** 2026-03-31
- **Objective:** Enforce per-user monthly analysis limits, add quota-aware confirmation modal on the Sources page, protect capture date/geo-location from overwrite on re-analysis, and provide a structured 429 response on quota exhaustion.
- **Outcome:** Full reservation-ledger quota system implemented end-to-end. `quota_events` table stores `reserved`/`consumed`/`released` events per user per month. `SELECT FOR UPDATE` on the `users` row serializes quota decisions under concurrent uploads. All upload and re-analysis paths enforce quota before enqueueing work. Frontend modal shows plan info, usage counts, overwrite/geo warning, and disables confirm when exhausted. Structured `HTTP 429` with `error_code`/`error`/`remaining`/`limit` body. All 5 local smoke scenarios passed. 91/91 tests pass. TypeScript clean. ADR-013 recorded.
- **Key decisions:** Ledger model chosen over mutable counter (audit trail, concurrency safety, future billing bridge). Batch upload uses per-item best-effort error; batch re-analysis uses all-or-nothing 429 — both intentional and tested. `SELECT FOR UPDATE` on users row preferred over a separate quota lock table (simpler, avoids deadlock complexity at current scale). `period_month` stored as PostgreSQL `Date` (first day of month), serialized as `"YYYY-MM"` in API — matches UTC server time.
- **Artifacts produced:**
  - Created: `alembic/versions/7a8b9c0d1e2f_quota_plans.py` (migration: plan_name/monthly_limit on users + quota_events table)
  - Created: `src/quota/__init__.py`, `src/quota/quota_service.py` (`QuotaService`, `QuotaExceededError`, `build_quota_exceeded_detail`)
  - Created: `src/api/routes/quota.py` (`GET /api/v1/quota/status`)
  - Created: `tests/test_quota.py` (5 tests: status endpoint, consumption, user-scoped, lifecycle, duplicate no-quota)
  - Modified: `src/models.py` (User: plan_name, monthly_limit; QuotaEvent model)
  - Modified: `src/api/schemas.py` (QuotaStatusResponse)
  - Modified: `src/api/app.py` (quota router registered)
  - Modified: `src/api/routes/upload.py` (reserve before enqueue; 429+cleanup on exceeded; per-item batch error)
  - Modified: `src/api/routes/analysis.py` (reanalyze: reserve before job; reanalyze-batch: all-or-nothing with rollback)
  - Modified: `src/analysis/processor.py` (reservation_id param; consume on success; release on permanent failure)
  - Modified: `src/api/error_handlers.py` (dict passthrough for arbitrary keys → error/remaining/limit reach response body)
  - Modified: `frontend/src/types/api.ts` (QuotaStatus interface, ApiError optional fields)
  - Modified: `frontend/src/api/client.ts` (ApiRequestError class, getQuotaStatus())
  - Modified: `frontend/src/pages/UploadPage.tsx` (quota modal: exceedsQuota/quotaDepleted compute, modal copy, geo note, 429 fast-fail)
  - Modified: `frontend/src/index.css` (modal overlay + utility text classes)
  - Modified: `docs/DECISION_LOG.md` (ADR-013)
- **Validation performed:** 91/91 backend tests pass. TypeScript build clean (`npx tsc --noEmit`). Full local smoke: upload → consumed; re-analysis → decremented; over-limit modal disabled; forced 429 returns structured payload; duplicate upload does not create additional quota event. Commit: `c147790`.
- **AWS deploy status:** Complete — migration `7a8b9c0d1e2f` ran on AWS postgres; quota endpoint live; upload→analysis→consumed and delete (with quota_events FK fix) validated on AWS beta 2026-03-31.

### P4-001: Gallery & Detail UX Continuity
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Completed:** 2026-03-31
- **Objective:** Keep filters always visible; add dimensions-based filtering; simplify status badge display; reorganize Media Detail metadata into sections; preserve Gallery URL state when navigating back from details.
- **Outcome:** All 6 changes delivered and validated. (1) Filter panel toggle button removed — filters always visible below the search bar. (2) Source button removed from Gallery page header (empty-state CTA preserved). (3) Size bucket select (Small <1000px / Medium 1000–2499px / Large 2500px+) added to FilterPanel; `sizeBucketToWidthParams()` helper maps to `min_width`/`max_width`; `client.ts` `listMediaFiltered` now passes those params; both `/api/v1/media` and `/api/v1/search` already supported them. (4) `StatusBadge` returns `null` for `completed` and any unknown status — only `uploaded`/`processing`/`error` show badges. (5) `MetadataDisplay` restructured into two sections: **Metadata** (Title, Description, Tags, Mood, People, People Count, Orientation) and **Additional Search Data** (Objects, Scenes, Context, Colors, Location Hint, Quality Notes). (6) `GalleryPage` imports `useLocation` and passes `state={{ from: location.pathname + location.search }}` to all detail links (MediaCard, MediaListRow, SearchListRow, search-grid Link); `MediaDetailPage` reads `location.state?.from` and falls back to `/` for the "← Back to Gallery" link. 82/82 backend tests pass. TypeScript build clean. Frontend deployed to Docker.
- **Key decisions:** Size bucket approach chosen over free-form pixel input for UX simplicity (bucket boundaries align with Small/HD/4K breakpoints). `navigate(-1)` approach rejected in favor of explicit location state to handle direct-URL navigation. `useLocation` imported at GalleryPage level — not in sub-components — to avoid prop-drilling the full location object.
- **Artifacts produced:**
  - Modified: `frontend/src/pages/GalleryPage.tsx` (filters always visible, Source btn removed, Size bucket filter, useLocation + fromPath passing)
  - Modified: `frontend/src/api/client.ts` (listMediaFiltered passes min_width/max_width)
  - Modified: `frontend/src/components/StatusBadge.tsx` (completed returns null)
  - Modified: `frontend/src/components/MetadataDisplay.tsx` (two-section layout)
  - Modified: `frontend/src/pages/MediaDetailPage.tsx` (useLocation, backHref from state)
  - Modified: `frontend/src/components/MediaCard.tsx` (fromPath prop + state on Link)
  - Modified: `frontend/src/components/MediaListRow.tsx` (fromPath prop + state on Link)
  - Modified: `docs/CURRENT_STATE.md`, `docs/WORKSTREAMS.md`, `docs/PROJECT_HANDOFF.md`, `docs/planning/PHASE_4_beta_operations_plan.md`, `docs/planning/P4-001_plan.md`
- **Validation performed:** 82/82 backend tests pass (`python -m pytest tests/ -q`). `npm run build` (tsc + vite) clean. Frontend Docker container rebuilt and running. Full local smoke (7 flows) and AWS beta smoke (7 flows) passed. AWS deploy: `git pull` on EC2 + `docker compose -f docker-compose.yml -f docker-compose.beta.yml up -d --build`.
- **Post-implementation fixes applied during smoke (all committed to master):**
  - `35ad90d` — poll terminal-status fix: `MediaDetailPage` poll used a denylist that missed `running` status; replaced with allowlist `['completed','failed','error']` so badge auto-clears correctly.
  - `90624a5` — Delete button added to Media Detail (right of Download, both format branches); Clear Search button added to filter panel (visible in search mode only); both use existing `deleteBatch()` API.
  - `c113393` — `.btn-danger` CSS added to `index.css` (red `#dc2626`, hover `#b91c1c`).
  - `311617a` — Sort order written to URL immediately via `handleSortChange` so back-navigation preserves sort.
  - `d91975c` — Filter state (all 6 filter values) written to URL immediately on change via a `useEffect`, matching the sort persistence pattern. Mount-skip ref prevents initial clobber.
- **Lessons learned:** Backend dimension params were already wired — backend-first planning pays off. `location.state` pattern is clean for gallery-state preservation without URL pollution. Sort and filter state must both write to URL on change — any state that is read from the URL on back-nav must be written to the URL on every user change, not only on form submit.

### P3-004: Production Deployment
- **Phase:** Phase 3 — Polish & Production Readiness
- **Completed:** 2026-03-28
- **Objective:** Make the Media Indexing Engine deployable to a real server. Implement S3-compatible file storage, validate PostgreSQL end-to-end, add a Docker + docker-compose stack, and add a health check endpoint.
- **Outcome:** All five deliverables shipped. `GET /api/v1/health` returns `{"status":"ok","version":"0.1.0"}` with no auth. `S3FileStore` implemented in `src/storage/file_store.py` using boto3 in a thread executor for async compatibility; `get_file_store()` factory selects backend by `storage.provider` config (or `STORAGE_PROVIDER` env var). `StorageConfig` extended with `s3_bucket`, `s3_region`, `s3_endpoint_url`. `config.py` env var override chain extended with `DATABASE_URL`, `STORAGE_PROVIDER`, `S3_BUCKET`, `S3_REGION`. `boto3` and `asyncpg` added to `project.optional-dependencies.prod` in `pyproject.toml`. `Dockerfile` (backend) and `frontend/Dockerfile` (multi-stage: Node.js build + nginx serve) created. `frontend/nginx.conf` proxies `/api/` to backend. `docker-compose.yml` defines all four services with healthchecks and persistent volumes. `.env.example` documents all required env vars. `README.md` updated with Production Deployment guide. 12 new unit tests for `S3FileStore` and `get_file_store()` factory. **82/82 tests pass** (70 existing + 12 new). Health endpoint confirmed via live smoke test. ADR-009 (Alembic), ADR-010 (S3FileStore), ADR-011 (Docker) recorded in DECISION_LOG.md.
- **Key decisions:** boto3 in thread executor over aioboto3 (avoids extra dependency, runs sync SDK async safely). `LocalFileStore` remains the default — no forced migration. Docker frontend is multi-stage (static files only in production). All secrets via environment variables only; `.env` in `.gitignore`. `S3_ENDPOINT_URL` field supports MinIO and other S3-compatible stores.
- **Artifacts produced:**
  - New: `src/api/routes/health.py` (`GET /api/v1/health`)
  - Modified: `src/storage/file_store.py` (added `S3FileStore`, `get_file_store()` factory)
  - Modified: `src/config.py` (added `StorageConfig.s3_*` fields; `DATABASE_URL`, `STORAGE_PROVIDER`, `S3_BUCKET`, `S3_REGION` env overrides)
  - Modified: `src/api/app.py` (registered `health.router`)
  - Modified: `src/api/routes/upload.py` (uses `get_file_store()` factory instead of hardcoded `LocalFileStore`)
  - Modified: `pyproject.toml` (`[project.optional-dependencies.prod]` with `asyncpg`, `boto3`)
  - New: `Dockerfile` (backend)
  - New: `frontend/Dockerfile` (multi-stage: Node.js + nginx)
  - New: `frontend/nginx.conf` (SPA + `/api/` proxy)
  - New: `docker-compose.yml` (backend, frontend, chromadb, postgres)
  - New: `.env.example`
  - Modified: `README.md` (Production Deployment section)
  - New: `tests/test_storage.py` (12 unit tests for S3FileStore and factory)
  - Modified: `docs/DECISION_LOG.md` (ADR-009, ADR-010, ADR-011)
  - Modified: `docs/PROJECT_MAP.md`, `docs/WORKSTREAMS.md`, `docs/CURRENT_STATE.md`, `docs/PROJECT_HANDOFF.md`
- **Validation performed:** 82/82 backend tests pass. `GET /api/v1/health` → `{"status":"ok","version":"0.1.0"}` confirmed via live uvicorn smoke test. `docker-compose.yml` validates as correct YAML. Dockerfile syntax reviewed manually. PostgreSQL end-to-end and full Docker stack smoke test require a live Docker environment — not run locally (Docker Desktop not available in current workspace).
- **Unresolved risks:** Docker stack requires live Docker environment for full validation. S3 integration tests use mocked boto3 only — real S3 bucket connectivity not validated. PostgreSQL + Alembic migration path was validated against SQLite in P3-002; asyncpg driver requires explicit installation (`pip install -e ".[prod]"`) and a running PostgreSQL instance to fully test.

### P3-003: Bulk Operations
- **Phase:** Phase 3 — Polish & Production Readiness
- **Completed:** 2026-03-28
- **Objective:** Add bulk re-analysis and bulk delete API endpoints. Add `LocalFileStore.delete()` and `ChromaDBVectorStore.delete_items()`. Integrate Re-analyze and Delete actions into the Gallery SelectionBar UI.
- **Outcome:** Two new endpoints added to `routes/analysis.py`. `LocalFileStore.delete()` already existed (abstract method declared, implementation was present). Added `delete_items()` to `VectorStore` protocol and `ChromaDBVectorStore` using `collection.delete(ids=[...])` for batch efficiency. Added `remove_items()` to `IndexingService` for bulk vector removal. `SelectionBar.tsx` updated with "Re-analyze" and "Delete" buttons (Delete uses `window.confirm()`); `GalleryPage.tsx` passes `onDeleteSuccess` callbacks to filter deleted items from local state. 8 integration tests added; 70/70 tests pass (62 existing + 8 new).
- **Key decisions:** Placed both batch endpoints in `routes/analysis.py` (already imports BackgroundTasks, vision provider, file store, indexing service). FK cascade: SQLAlchemy ORM relationships lack cascade=delete-orphan, so `delete_batch` uses bulk `sql_delete()` in child-first order (MediaMetadata → ProcessingJob → MediaItem) to avoid NOT NULL FK constraint violations. `DELETE /media/batch` uses raw HTTP DELETE with JSON body (not query params) — `request()` call needed in tests since `httpx.AsyncClient.delete()` doesn't forward JSON body. Vector embedding removal is best-effort (wrapped in try/except). Batch cap of 50 items consistent with download-batch (P2-002).
- **Artifacts produced:**
  - Modified: `src/search/vector_store.py` (added `delete_items()` to protocol)
  - Modified: `src/search/chromadb_store.py` (implemented `delete_items()` via `collection.delete(ids=[...])`)
  - Modified: `src/search/indexing_service.py` (added `remove_items()` bulk removal)
  - Modified: `src/api/schemas.py` (added `BatchOperationRequest`, `BatchReanalyzeResponse`, `BatchDeleteResponse`)
  - Modified: `src/api/routes/analysis.py` (added `POST /media/reanalyze-batch`, `DELETE /media/batch`)
  - Modified: `frontend/src/api/client.ts` (added `reanalyzeBatch()`, `deleteBatch()`, response interfaces)
  - Modified: `frontend/src/components/SelectionBar.tsx` (Re-analyze + Delete buttons, `onDeleteSuccess` prop)
  - Modified: `frontend/src/pages/GalleryPage.tsx` (pass `onDeleteSuccess` handlers to SelectionBar)
  - New: `tests/test_bulk_operations.py` (8 integration tests)
  - Modified: `docs/PROJECT_MAP.md`, `docs/WORKSTREAMS.md`, `docs/CURRENT_STATE.md`, `docs/PROJECT_HANDOFF.md`
- **Lessons learned:** When using `from module import name` in Python, module-level patching in tests only affects the importing module if done before import. For file store and indexing service in analysis.py, patching `analysis_mod._file_store` directly in the specific test is the cleanest approach. Use `client.request("DELETE", ...)` (not `client.delete(...)`) when an HTTP DELETE needs a JSON body — httpx's `delete()` shortcut doesn't expose the `json=` parameter cleanly. Content-hash dedup means the same image bytes uploaded twice in one test creates only one DB record; use distinct file formats (JPEG + PNG) to upload two truly distinct items.

### P3-002: Database Migrations
- **Phase:** Phase 3 — Polish & Production Readiness
- **Completed:** 2026-03-28
- **Objective:** Replace the drop-and-recreate schema pattern with Alembic migrations, so the schema can evolve without losing data. Integrate migration execution into production startup.
- **Outcome:** Alembic fully integrated. `alembic upgrade head` against a fresh SQLite DB produces the complete 4-table schema and exits cleanly. Production startup (`settings.app.debug: false`) now calls `run_migrations()` instead of `create_all()`. Dev/test startup is unchanged (`create_all()` on the real/in-memory DB). 62/62 existing tests pass — tests use in-memory SQLite via `Base.metadata.create_all` and are entirely unaffected by Alembic.
- **Key decisions:** Used `create_async_engine` + `connection.run_sync()` pattern in `alembic/env.py` for async SQLAlchemy compatibility (no sync driver needed). `run_migrations()` in `database.py` uses `loop.run_in_executor()` to avoid nested event loop error (Alembic's env.py calls `asyncio.run()` internally). Database URL priority: `DATABASE_URL` env var > `config/settings.yaml`. Dev vs prod mode determined by `settings.app.debug`. Initial migration generated from ORM models against a fresh DB, then existing DB restored.
- **Artifacts produced:**
  - `alembic.ini` — Alembic configuration (URL set dynamically in env.py, not hardcoded)
  - `alembic/env.py` — async-capable env with `get_db_url()`, `run_async_migrations()`, `do_run_migrations()`
  - `alembic/script.py.mako` — migration file template (scaffolded)
  - `alembic/versions/cce0c99946e6_initial_schema.py` — initial migration: CREATE TABLE for users, media_items, media_metadata, processing_jobs with all constraints and indexes
  - Modified: `pyproject.toml` (added `alembic>=1.13.0`), `src/database.py` (added `run_migrations()`), `src/api/app.py` (lifespan switches on `settings.app.debug`), `README.md` (Getting Started + migration instructions), `.gitignore` (added clarifying comment)
- **Lessons learned:** Autogenerate against an existing database produces an empty migration. Always generate against a fresh DB for the initial migration. For existing deployments that predate Alembic, `alembic stamp head` marks the current state without re-running DDL. `asyncio.run()` in Alembic env.py requires a thread executor when called from an already-running event loop.

### P3-001: UI Polish & API Cleanup
- **Phase:** Phase 3 — Polish & Production Readiness
- **Completed:** 2026-03-28
- **Objective:** Five targeted improvements: (1) remove the "AI-generated description:" prefix from embedded metadata comments; (2) use the AI-extracted title as the download filename for all supported formats (not just BMP/GIF); (3) expose image dimensions (`width × height`) in all API schemas, frontend types, and the media detail page; (4) merge the Library and Search pages into a unified Gallery page with inline filter+sort controls; (5) rename "Upload" → "Source" throughout the UI.
- **Outcome:** All 5 changes delivered. 62/62 backend integration tests pass (1 test assertion updated to match new AI-title download behaviour). `field_mapping.py` updated (Change 1). `download.py` extended with `_MIME_TO_EXT` dict and `_ext_for_mime()` helper; applied to both `download_file()` and `download_batch()` (Change 2). `schemas.py`, `search.py`, `types/api.ts`, `MediaDetailPage.tsx` updated with `width`/`height` (Change 3). `media.py` completely rewritten with full filter+sort params and aspect-ratio post-query filtering; new `GalleryPage.tsx` created; `App.tsx`, `Layout.tsx`, `SearchBar.tsx`, `client.ts` updated; `LibraryPage.tsx` and `SearchPage.tsx` deleted (Change 4). `Layout.tsx` nav and `UploadPage.tsx` heading renamed (Change 5).
- **Key decisions:** Used an explicit `_MIME_TO_EXT` dict rather than `mimetypes.guess_extension()` — stdlib MIME-to-extension mapping is platform-dependent on Windows and returns `.jpe`/`.jfif` instead of `.jpg`. Aspect ratio filtering implemented as a post-query Python pass (no stored column) consistent with the pattern already used in `search_service.py`. `GalleryPage` disambiguates browse vs. search via the presence of the `?q=` URL param — no separate route needed. `/search` route removed entirely.
- **Artifacts produced:**
  - Modified: `src/enrichment/field_mapping.py` — removed prefix from `build_user_comment()`
  - Modified: `src/api/routes/download.py` — `_MIME_TO_EXT`, `_ext_for_mime()`, AI-title download for all formats
  - Modified: `src/api/routes/media.py` — full filter+sort params, `MediaMetadata` JOIN, `_matches_aspect_ratio()` post-query helper
  - Modified: `src/api/routes/search.py` — pass `width`/`height` into `SearchMediaItem`
  - Modified: `src/api/schemas.py` — `width`/`height` fields on `MediaItemResponse` and `SearchMediaItem`
  - Created: `frontend/src/pages/GalleryPage.tsx` — unified browse+search page (~320 lines)
  - Deleted: `frontend/src/pages/LibraryPage.tsx`, `frontend/src/pages/SearchPage.tsx`
  - Modified: `frontend/src/api/client.ts` — `listMediaFiltered()` with full filter+sort params
  - Modified: `frontend/src/types/api.ts` — `width?`/`height?` on `MediaItemResponse` and `SearchResultItem.media_item`
  - Modified: `frontend/src/pages/MediaDetailPage.tsx` — dimensions display, "Back to Gallery"
  - Modified: `frontend/src/pages/UploadPage.tsx` — heading renamed to "Source"
  - Modified: `frontend/src/components/Layout.tsx` — nav: "Gallery" + "Source" (removed Search tab)
  - Modified: `frontend/src/components/SearchBar.tsx` — navigates to `/?q=` instead of `/search?q=`
  - Modified: `frontend/src/App.tsx` — `GalleryPage` replaces `LibraryPage`/`SearchPage`, `/search` route removed
  - Modified: `tests/test_download.py` — updated JPEG download assertion to match AI-title output
- **Lessons learned:** `_MIME_TO_EXT` dict is more reliable than `mimetypes` for extension mapping on Windows. When merging two pages into one unified route, the `?q=` URL param is a natural branch point that preserves deep-linking for both browse and search.

### P2-004: List View + Multi-Select + Batch Download
- **Phase:** Phase 2 — Enhancements
- **Completed:** 2026-03-28
- **Objective:** Add a grid/list view toggle to the Library and Search pages, with checkbox multi-select in list view and a batch ZIP download action.
- **Outcome:** Grid/list view toggle added to Library and Search pages. List view renders a compact `MediaListRow` with a checkbox per item. "Select all" checkbox in the header, floating `SelectionBar` with count and "Download Selected" button (triggers batch ZIP via `POST /media/download-batch`). View mode persisted in `localStorage` per page. 3 new frontend components: `ViewToggle`, `MediaListRow`, `SelectionBar`.
- **Key decisions:** No new ADRs. Per-page localStorage key for view preference (library vs. search are independent). SelectionBar floats above the footer so it doesn't collapse the grid. Batch download reuses the P2-002 zip endpoint.
- **Artifacts produced:**
  - `frontend/src/components/ViewToggle.tsx` — grid/list toggle button pair
  - `frontend/src/components/MediaListRow.tsx` — compact list row with checkbox, thumbnail, title, status, date
  - `frontend/src/components/SelectionBar.tsx` — floating selection action bar
  - Modified: `frontend/src/pages/LibraryPage.tsx` (view toggle, checkbox state, SelectionBar), `frontend/src/pages/SearchPage.tsx` (same), `frontend/src/api/client.ts` (`downloadBatch()`)
- **Lessons learned:** localStorage view preference prevents jarring mode resets on navigation. Floating selection bars must be above any bottom chrome (footer, scroll bars) — use `position: fixed` with a bottom offset.

### P2-003: Frontend Download Button
- **Phase:** Phase 2 — Enhancements
- **Completed:** 2026-03-28
- **Objective:** Add a "Download (with metadata)" button to the Media Detail page for embeddable formats; a convert-to-PNG option for BMP/GIF.
- **Outcome:** MediaDetailPage shows "Download (with metadata)" for JPEG, WebP, PNG, and TIFF items (calls `GET /media/{id}/download`). BMP and GIF items show two buttons: "Download" (raw file) and "Convert to PNG with metadata" (calls `POST /media/{id}/convert-png`). Download is triggered using a temporary blob URL + anchor click, preserving the enriched filename from the response `Content-Disposition` header. No new backend tests — covered by P2-002 tests.
- **Key decisions:** No new ADRs. Blob URL approach reused from authenticated image loading (`useAuthImage`). Format detection uses the `media_item.format` field from the API response.
- **Artifacts produced:**
  - Modified: `frontend/src/pages/MediaDetailPage.tsx` (download/convert buttons, blob download helper)
  - Modified: `frontend/src/api/client.ts` (`downloadFile()`, `convertToPng()`)
- **Lessons learned:** `Content-Disposition: attachment; filename="..."` from the server must be read via `response.headers.get('content-disposition')` before the blob is consumed. Blob URLs must be revoked after the anchor click to prevent memory leaks.

### P2-002: Download Endpoints
- **Phase:** Phase 2 — Enhancements
- **Completed:** 2026-03-28
- **Objective:** Expose backend endpoints for single file download (with metadata embedded), batch ZIP download, and BMP/GIF convert-to-PNG.
- **Outcome:** 3 new API endpoints in `src/api/routes/download.py`: `GET /api/v1/media/{id}/download` returns the enriched file (metadata embedded at request time) with `Content-Disposition: attachment`. `POST /api/v1/media/download-batch` accepts a list of media IDs and returns a ZIP archive of enriched files. `POST /api/v1/media/{id}/convert-png` converts BMP/GIF to PNG, embeds metadata, and streams the result. BMP/GIF single downloads use the AI title as the filename (sanitized). 8 new integration tests, 62 total pass.
- **Key decisions:** No new ADRs. Enrichment is performed at download time (not stored) — keeps the stored file as the original, produces enriched copies on demand. ZIP is assembled in memory (`io.BytesIO`) then streamed — acceptable for MVP batch sizes. Batch endpoint enforces a 50-item cap per request.
- **Artifacts produced:**
  - `src/api/routes/download.py` — all 3 download/convert endpoints
  - `tests/test_download.py` — 8 integration tests
  - Modified: `src/api/app.py` (download router registration), `src/api/schemas.py` (`BatchDownloadRequest`)
- **Lessons learned:** FastAPI `Response` with pre-built bytes is simpler than `StreamingResponse` for in-memory ZIP archives. Sanitizing AI-generated titles for filesystem use (strip punctuation, collapse spaces) is necessary before using them as filenames.

### P2-001: Metadata Embedder Module
- **Phase:** Phase 2 — Enhancements
- **Completed:** 2026-03-28
- **Objective:** Build a module that embeds AI-extracted metadata (title, description, tags, objects, scenes, etc.) into image file binary headers at download time, so metadata travels with the file.
- **Outcome:** 8-file `src/enrichment/` package. `MetadataEmbedder` dispatches to format-specific writers based on magic-byte MIME type. JPEG and TIFF: EXIF (via `piexif`) + IPTC keyword fields. WebP and AVIF: EXIF embedding. PNG: XMP metadata block via `iTXt` chunk. BMP and GIF: pass-through (no embedding) with a convert-to-PNG fallback path. `field_mapping.py` maps `MediaMetadataResult` fields to EXIF/IPTC/XMP tags. `xmp_builder.py` builds standards-compliant XMP XML. 16 new integration tests, 54 total pass.
- **Key decisions:** No new ADRs. Embedding is non-destructive (operates on a copy of the file bytes). `piexif` used for EXIF/IPTC (mature library, all target formats supported). PNG XMP preferred over EXIF for richness of tag support. AVIF EXIF support via `piexif` with raw box injection.
- **Artifacts produced:**
  - `src/enrichment/__init__.py`
  - `src/enrichment/embedder.py` — `MetadataEmbedder` dispatcher
  - `src/enrichment/exif_writer.py` — JPEG/WebP/AVIF/TIFF EXIF+IPTC writer
  - `src/enrichment/png_writer.py` — PNG XMP iTXt writer
  - `src/enrichment/avif_writer.py` — AVIF-specific EXIF writer
  - `src/enrichment/webp_writer.py` — WebP EXIF writer
  - `src/enrichment/field_mapping.py` — metadata field → EXIF/IPTC/XMP tag mapping
  - `src/enrichment/xmp_builder.py` — XMP XML builder
  - `tests/test_enrichment.py` — 16 integration tests
- **Lessons learned:** `piexif` requires bytes objects (not strings) for all tag values. PNG iTXt chunks must use UTF-8 and follow the keyword/text/compression flag structure exactly. AVIF EXIF injection requires wrapping the EXIF payload in an `Exif\x00\x00` box header. Testing with minimal valid image bytes (not real photos) is sufficient for format dispatch and field-mapping tests.

### P2-005: Search as Nav Tab
- **Phase:** Phase 2 — Enhancements
- **Completed:** 2026-03-28
- **Objective:** Add Search as a first-class navigation tab in the app header so users can reach the Search page directly.
- **Outcome:** Search added as the third link in the `Layout` component header navigation. No backend changes. No new tests — change is a single-line frontend addition.
- **Key decisions:** No new ADRs. Nav order: Library → Upload → Search (matches typical user journey).
- **Artifacts produced:**
  - Modified: `frontend/src/components/Layout.tsx` (added Search nav link)
- **Lessons learned:** Simple UI improvements are sometimes the highest-leverage items — zero risk, immediate discoverability gain.

### WS-000: Core Foundations
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-27
- **Objective:** Extract reusable patterns from prior project (`marketing_asset_pipeline`), define media identity model, metadata schema, storage model, database entities, and API scaffold for Media Indexing Engine.
- **Outcome:** All deliverables produced and approved. Prior Art Summary completed with 8 reused decisions, 6 modified decisions, and 6 rejected decisions. Identity model (SHA256 + user scope), metadata schema (13 fields), storage model (3-store architecture), 4 database entities, and API scaffold (4 routers, 10 endpoints) defined. 8 architectural decisions recorded in DECISION_LOG.md (ADR-001 through ADR-008).
- **Key decisions:** ADR-001 (SHA256 identity), ADR-002 (DB as sole system of record), ADR-003 (normalized entities), ADR-004 (content-addressed storage), ADR-005 (metadata schema), ADR-006 (3-store architecture), ADR-007 (defer review workflow), ADR-008 (Anthropic Claude as initial provider).
- **Artifacts produced:** Prior Art Summary, Media Identity Model, Metadata Schema definition, Storage Model definition, Entity design (users, media_items, media_metadata, processing_jobs), API Scaffold Recommendation, 8 ADR entries in DECISION_LOG.md.
- **Lessons learned:** Prior art extraction before design prevented reinventing solved problems (especially hash-based identity, AI output parsing chain, image preparation). The marketing pipeline's 3-layer storage and flat table were its biggest pain points — normalizing early avoids the same trap.

### WS-001: Ingestion Pipeline
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-27
- **Objective:** Build the complete file ingestion pipeline: file upload, validation, SHA256 hashing, per-user deduplication, content-addressed file storage, database persistence, background task pattern, and upload/media API endpoints.
- **Outcome:** Full ingestion pipeline operational. Single and batch file upload via REST API. Magic-byte MIME detection validates 6 image formats (JPEG, PNG, WebP, TIFF, BMP, GIF). SHA256 hashing with per-user `(user_id, content_hash)` deduplication. Content-addressed local file storage. Background task pattern with placeholder processor (ready for WS-002 AI analysis). 4 API endpoints: `POST /upload`, `POST /upload/batch`, `GET /media`, `GET /media/{id}`. 13 integration tests pass. Dev user auto-seeded on startup.
- **Key decisions:** No new ADRs — WS-001 implemented the designs from WS-000 (ADR-001 through ADR-008) without deviation. Key implementation choices: Python dataclasses for config (over Pydantic Settings), magic-byte detection for MIME type (over trusting file extensions), sequential processing within batch requests (over parallel, to bound memory), FastAPI BackgroundTasks for job dispatch (over external broker per plan).
- **Artifacts produced:**
  - `pyproject.toml` — project dependencies and build config
  - `config/settings.yaml` — dev configuration
  - `src/config.py` — typed settings loader
  - `src/database.py` — async SQLAlchemy engine, session factory, table management
  - `src/models.py` — User, MediaItem, ProcessingJob ORM models
  - `src/ingestion/validation.py` — format and size validation with magic-byte MIME detection
  - `src/ingestion/hashing.py` — SHA256 content hashing
  - `src/ingestion/dedup.py` — per-user duplicate check
  - `src/ingestion/upload_service.py` — upload orchestrator (validate → hash → dedup → store → DB → job)
  - `src/ingestion/job_manager.py` — processing job management and placeholder processor
  - `src/storage/file_store.py` — FileStore interface + LocalFileStore (content-addressed paths)
  - `src/api/app.py` — FastAPI app with lifespan (DB init, dev user seed)
  - `src/api/schemas.py` — Pydantic response models
  - `src/api/dependencies.py` — DB session and dev-user dependency injection
  - `src/api/routes/upload.py` — single and batch upload endpoints
  - `src/api/routes/media.py` — media list and detail endpoints
  - `tests/conftest.py` — test fixtures (in-memory DB, test clients, user isolation)
  - `tests/test_upload.py` — 7 upload integration tests
  - `tests/test_media.py` — 6 media endpoint integration tests
  - `__init__.py` files for all packages
- **Lessons learned:** httpx ASGITransport does not trigger FastAPI lifespan events — tests must manually init the DB. Background tasks using module-level session factories need explicit patching in tests to use the test DB. Returning the processing_job_id from the upload service (rather than relying on lazy-loaded ORM relationships) simplifies background task dispatch. The 10-step plan with per-step validation checkpoints worked well — each step built cleanly on the last with no rework needed.

### WS-002: AI Analysis Pipeline
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-27
- **Objective:** Build the AI analysis pipeline: pick up pending processing jobs, send images to Anthropic Claude's vision API, extract structured metadata conforming to the 13-field ADR-005 schema, persist results in the `media_metadata` table, and expose analysis status and re-analysis API endpoints. Abstract the AI provider behind an interface for future swaps.
- **Outcome:** Full AI analysis pipeline operational. Uploads are automatically analyzed via Anthropic Claude vision API. `media_metadata` table stores all 13 ADR-005 fields plus AI provider provenance. `VisionProvider` protocol abstracts the AI layer — `AnthropicVisionProvider` is the live implementation, `MockVisionProvider` for testing. Image preparation resizes to 1568px max and converts to JPEG/base64. Three-stage output parsing (extract JSON → parse → validate). Job retry logic (up to 3 attempts). Two new API endpoints: `GET /media/{id}/analysis`, `POST /media/{id}/reanalyze`. Re-analysis updates metadata in-place (upsert, no duplicates). 21 total integration tests pass (8 new analysis + 13 existing). Manual smoke test verified with real Anthropic API — metadata quality excellent on real photos.
- **Key decisions:** No new ADRs. Key implementation choices: SQLAlchemy relationship named `analysis_metadata` (not `metadata`, which is reserved by SQLAlchemy's DeclarativeBase). JSON arrays stored as TEXT columns (works across SQLite and PostgreSQL). `python-dotenv` added for `.env` file loading. Vision provider instantiated at module level in upload routes with graceful fallback if API key missing (uploads still work, analysis skipped). Image resize uses Pillow LANCZOS filter at quality 85 for JPEG output.
- **Artifacts produced:**
  - `src/analysis/provider.py` — `VisionProvider` protocol (abstract interface)
  - `src/analysis/anthropic_provider.py` — Anthropic SDK implementation with error handling
  - `src/analysis/mock_provider.py` — Deterministic mock for testing (canned metadata)
  - `src/analysis/image_prep.py` — Pillow resize + JPEG conversion + base64 encoding
  - `src/analysis/schemas.py` — `MediaMetadataResult` Pydantic model + `parse_ai_response()` JSON parser
  - `src/analysis/processor.py` — `analyze_media_item()` background task (full pipeline)
  - `src/api/routes/analysis.py` — GET analysis status, POST re-analyze endpoints
  - `tests/test_analysis.py` — 8 integration tests (mock provider)
  - Modified: `src/models.py` (added `MediaMetadata` ORM model), `src/config.py` (added `AnalysisConfig` + dotenv), `src/api/schemas.py` (added analysis response models), `src/api/app.py` (registered analysis router), `src/api/routes/upload.py` (replaced placeholder with real processor), `src/storage/file_store.py` (added `read()` method), `src/ingestion/job_manager.py` (removed placeholder processor), `pyproject.toml` (added anthropic, Pillow, python-dotenv), `config/settings.yaml` (added analysis section), `tests/conftest.py` (mock provider injection, real test images)
- **Lessons learned:** SQLAlchemy's `DeclarativeBase` reserves the attribute name `metadata` — use `analysis_metadata` for the relationship. Providing a mock vision provider at the test fixture level (injected into the upload route module) is cleaner than mocking at the HTTP level — it tests the real processor code path. The `.env` file approach for API keys is simple and works well for dev; `python-dotenv` loaded early in `config.py` ensures all modules see the env vars. The three-stage JSON parsing pipeline (strip fences → find braces → parse → validate) handles Claude's occasional response formatting variations reliably.

### WS-003: Search & Retrieval
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-28
- **Objective:** Build the search and retrieval pipeline: generate text embeddings from AI-extracted metadata, index them in ChromaDB, expose a natural language search endpoint with ranked results and relevance scores. Auto-index on analysis completion, re-index on re-analysis.
- **Outcome:** Full semantic search pipeline operational. Metadata text is constructed from 13 ADR-005 fields (excluding `quality_notes`), embedded via `all-MiniLM-L6-v2` (384-dim, local — no API), and indexed in ChromaDB with user_id filtering. `GET /api/v1/search?q=...` returns ranked results with relevance scores (0–1), paginated, user-scoped. Auto-indexing hooks into the analysis processor — uploads are automatically searchable after analysis. Re-analysis updates embeddings in place (upsert). Rebuild script proves ADR-006 "derived store" principle — full vector store can be regenerated from the database. 28 total integration tests pass (7 new search + 21 existing).
- **Key decisions:** No new ADRs. Key implementation choices: `all-MiniLM-L6-v2` runs locally via sentence-transformers (no external API, no cost). ChromaDB cosine similarity with distance-to-score conversion `1 - (distance / 2)`. Indexing is non-fatal — if ChromaDB fails, analysis still succeeds (warning logged). `VectorStore` protocol abstracts the vector DB for future swaps. `IndexingService` and `SearchService` share the same `Embedder` and `VectorStore` instances. Search route accesses shared instances from the upload module (single point of initialization). Test fixtures inject temp ChromaDB directories per test to avoid cross-test contamination.
- **Artifacts produced:**
  - `src/search/embedding_text.py` — Build embedding text from metadata (Pydantic or ORM)
  - `src/search/embedder.py` — `Embedder` wrapping SentenceTransformer (384-dim)
  - `src/search/models.py` — `SearchHit` dataclass
  - `src/search/vector_store.py` — `VectorStore` protocol (abstract interface)
  - `src/search/chromadb_store.py` — `ChromaDBVectorStore` with cosine similarity + user filtering
  - `src/search/indexing_service.py` — `IndexingService`: text → embed → upsert
  - `src/search/search_service.py` — `SearchService`: query → embed → search → DB join → ranked results
  - `src/api/routes/search.py` — `GET /api/v1/search?q=...` endpoint
  - `scripts/rebuild_vector_store.py` — Full vector store rebuild from DB
  - `tests/test_search.py` — 7 search integration tests
  - Modified: `src/config.py` (added `SearchConfig`), `src/analysis/processor.py` (auto-indexing hook), `src/api/routes/upload.py` (indexing service init), `src/api/routes/analysis.py` (pass indexing to re-analyze), `src/api/app.py` (search router), `src/api/schemas.py` (search response models), `pyproject.toml` (chromadb, sentence-transformers), `config/settings.yaml` (search section), `.gitignore` (chromadb_data/), `tests/conftest.py` (search fixtures)
- **Lessons learned:** `from __future__ import annotations` must be the very first import after the docstring — even before stdlib imports. Test fixtures need per-test temp ChromaDB directories (not shared) to avoid state leakage. Module-level service initialization with graceful fallback (try/except returning None) works well for optional services. ChromaDB's `upsert` is idempotent by ID — simplifies re-indexing. The sentence-transformers model download (~80MB) happens once and is cached.

### WS-004: Auth & API Hardening
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-28
- **Objective:** Replace the hardcoded dev user with real JWT-based authentication (email/password signup and login, bcrypt password hashing, token-protected routes), add dev/demo mode bypass for local testing, standardize API error responses, and add basic rate limiting on auth endpoints.
- **Outcome:** Full JWT auth system operational. Users register with email/password (bcrypt-hashed) and receive a JWT token. All routes accept `Authorization: Bearer <token>` header. Dev mode (`auth.dev_mode: true`) preserves the existing no-auth behavior with auto-seeded dev user. Standardized error responses (`detail` + `error_code`) across all endpoints. In-memory rate limiting on login (5/min) and register (3/min). 3 new auth API endpoints: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`. `AUTH_SECRET_KEY` env var overrides config for production. 38 total integration tests pass (10 new auth + 28 existing).
- **Key decisions:** No new ADRs. Key implementation choices: Used `bcrypt` directly instead of `passlib[bcrypt]` (passlib has compatibility issues with bcrypt>=4.2). `password_hash` column is nullable (preserves dev user and existing DB state). Auth dependency uses `Header(None)` for optional Authorization, with dev mode fallback. Rate limiter state is in-memory (resets on restart — acceptable for MVP). Error handlers registered as FastAPI exception handlers (global, automatic for all HTTPException raises). Dev user only seeded when `dev_mode: true`. Startup logs a WARNING when dev mode is active.
- **Artifacts produced:**
  - `src/auth/__init__.py` — auth package
  - `src/auth/passwords.py` — bcrypt hash/verify
  - `src/auth/tokens.py` — JWT create (`create_access_token`) and decode (`decode_access_token`)
  - `src/api/routes/auth.py` — register, login, me endpoints
  - `src/api/error_handlers.py` — standardized error response handler + validation error handler
  - `src/api/rate_limit.py` — `RateLimiter` sliding window counter + pre-configured login/register limiters
  - `tests/test_auth.py` — 10 auth integration tests
  - Modified: `src/models.py` (added `password_hash`), `src/config.py` (added `AuthConfig` + env var override), `src/api/dependencies.py` (JWT auth + dev mode fallback), `src/api/app.py` (auth router, error handlers, conditional dev seed, startup warning), `src/api/schemas.py` (auth request/response models), `pyproject.toml` (python-jose, bcrypt), `config/settings.yaml` (auth section), `config/settings.example.yaml` (auth section with dev_mode)
- **Lessons learned:** `passlib` has compatibility issues with `bcrypt>=4.2` — use bcrypt directly for modern Python. Rate limiter state must be reset between tests (or tests hit the limit from prior tests). The FastAPI dependency override pattern (`app.dependency_overrides[deps.get_current_user_id]`) works regardless of the real dependency's signature — tests that override it are completely isolated from auth changes. Conditional dev user seeding (only when `dev_mode: true`) prevents confusion in production environments.

### WS-005: Frontend MVP
- **Phase:** Phase 1 — MVP
- **Completed:** 2026-03-28
- **Objective:** Build the frontend MVP: a React + TypeScript SPA that consumes all backend API endpoints. Users can register/login, upload images (drag-and-drop + file picker), browse their library in a paginated grid, view image details with AI-extracted metadata, search using natural language, and trigger re-analysis.
- **Outcome:** Full frontend operational. React 18 + TypeScript + Vite SPA with 6 pages (Login, Register, Library, Upload, Media Detail, Search), 11 reusable components, typed API client for all 11 endpoints. Dark mode UI. Library auto-polls for status updates. Upload handles single and batch files sequentially with per-file status feedback. Media detail shows all 13 AI metadata fields with analysis polling. Search shows ranked results with relevance percentages. JWT auth integrated with localStorage persistence and auto-logout on 401. Backend additions: `GET /media/{id}/file` endpoint for image serving, CORS middleware, `cors_origins` config. File storage truncates long filenames to avoid Windows MAX_PATH limit. 38 backend tests still pass.
- **Key decisions:** No new ADRs. Key implementation choices: CSS-only dark mode (no CSS framework or Tailwind — all styles in single `index.css`). Vite dev proxy eliminates CORS issues during development. Images served via authenticated blob URLs (`useAuthImage` hook) since `<img src>` can't send JWT headers. Upload uses sequential single-file requests instead of batch endpoint for better per-file error handling. Library auto-polls every 5s when items are processing, stops when all complete. Long filenames truncated on disk to 70 chars (preserving extension) to avoid Windows 260-char path limit; original filename preserved in DB for display. No frontend unit tests in MVP — manual integration testing against running backend.
- **Artifacts produced:**
  - Backend: `GET /api/v1/media/{id}/file` endpoint, CORS middleware, `cors_origins` config, filename truncation in `FileStore`
  - `frontend/` — complete React+TS+Vite SPA (22+ source files):
    - `src/api/client.ts` — typed API client for all 11 endpoints
    - `src/api/useAuthImage.ts` — hook for authenticated image loading
    - `src/context/AuthContext.tsx` — JWT auth state management
    - `src/types/api.ts` — TypeScript interfaces matching all backend schemas
    - `src/pages/` — LoginPage, RegisterPage, LibraryPage, UploadPage, MediaDetailPage, SearchPage
    - `src/components/` — Layout, SearchBar, UserMenu, MediaCard, AuthImage, StatusBadge, Pagination, DropZone, FileQueue, MetadataDisplay, ProtectedRoute, PublicRoute
    - `src/index.css` — dark mode styles
    - `vite.config.ts` — dev proxy to backend
  - Modified: `src/api/routes/media.py` (file serving), `src/api/app.py` (CORS), `src/config.py` (cors_origins), `src/storage/file_store.py` (filename truncation), config files
- **Lessons learned:** `<img src>` cannot send Authorization headers — use fetch + blob URLs for authenticated image loading. Windows MAX_PATH (260 chars) is a real constraint with content-addressed paths + long filenames — truncate on disk, keep original in DB. Sequential single-file uploads provide better UX than batch when some files may fail. Auto-polling the library page when items are "uploaded" or "processing" gives real-time feel without WebSockets. Dark mode should be the default for developer-facing tools. Vite's dev proxy is the simplest way to avoid CORS during development.
