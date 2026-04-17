# Project Handoff — Media Indexing Engine

_This document bootstraps a new AI session with full project context. Read this first when starting a new session on this project._

_Update this document at the end of every session and at every workstream transition._

## Quick Status

| Field | Value |
|---|---|
| **Current Phase** | Post-Phase 9 incremental workstreams |
| **Current Workstream** | None — P12-010 formally closed 2026-04-16 |
| **Last Completed Work** | P12-010 — formally closed 2026-04-16. Bounded connector analysis concurrency foundation delivered: `ConnectorAnalysisTaskResult`, `_run_admitted_analysis_task`, bounded admission loop in `_run_sync`, `analyze_connector_item` bool return. 20/20 focused tests pass; 74/74 total. |
| **Next Task** | Operator selection of next workstream (P12-002 is next in Planned, or operator may direct otherwise) |
| **Next Step Requested** | Operator approval to activate P12-002 (Remembered-Photo Evaluation Baseline) or another planned workstream |

## Required Reading

Before making any changes, read these documents in order:

1. **This file** — you are here
2. **`docs/PROJECT_AI_CONTEXT.md`** — project identity, constraints, AI behavior rules
3. **Project `docs/CURRENT_STATE.md`** — live project status
4. **Project `docs/WORKSTREAMS.md`** — work tracking

If implementation is underway, also read:
5. **`docs/PROJECT_MAP.md`** — codebase structure
6. **`docs/PROJECT_PLAYBOOK.md`** — safety practices and common tasks
7. **`docs/planning/ARCH-002-reference-mode-storage.md`** — approved architectural basis for the storage pivot
8. **`docs/planning/PHASE_9_arch002_gap_remediation_plan.md`** — current approved Phase 9 remediation plan and decision baseline
9. **`docs/planning/P9-004_plan.md`** — locked implementation scope for source capability snapshots and durable write-back operations
10. **`docs/planning/P12-010_plan.md`** — closed historical contract for bounded connector analysis concurrency foundation
11. **`docs/planning/ARCH-005-connector-sync-bounded-concurrency.md`** — governing architecture note for bounded connector sync concurrency (enforced, closed)
12. **`docs/planning/P12-009_plan.md`** — closed historical contract for source capture metadata preservation hardening
13. **`docs/planning/ARCH-004-source-capture-metadata-preservation.md`** — governing architecture note for source-truth capture metadata (enforced, closed)
14. **`docs/planning/P12-002_plan.md`** — separately planned remembered-photo evaluation baseline workstream; not yet active
15. **`docs/planning/ARCH-003-remembered-photo-retrieval-roadmap.md`** — staged search-quality roadmap and P12-002 parent architecture context
16. **`docs/planning/P12-001_plan.md`** — closed historical contract for Google OAuth production-readiness and beta-access hardening
17. **`docs/planning/P11-002_plan.md`** — closed historical contract for async connector-aware bulk export

## System Summary

Media Indexing Engine is an AI-powered system that analyzes photos, enriches their metadata using vision AI models, and enables fast semantic search across large media libraries. Users connect supported sources through a web interface; the system processes, tags, and indexes that media for natural language retrieval. Historical local working-folder intake may still exist in code and past workstream records, but it is hidden/deprecated and is not part of the supported beta experience.

### Core Flow

```
Connected Source Intake (web UI)
    │
    ▼
Ingestion (validate, deduplicate, store)
    │
    ▼
AI Analysis (vision model → structured metadata)
    │
    ▼
Search Index (vector embeddings)
    │
    ▼
Natural Language Search (web UI)
```

## Key Technologies

| Component | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI / SQLAlchemy (async) |
| Frontend | Modern JS/TS (React or similar) |
| AI Vision | Anthropic Claude (claude-sonnet-4-20250514) via `VisionProvider` interface |
| Vector DB | ChromaDB (dev) via `VectorStore` interface / sentence-transformers `all-MiniLM-L6-v2` |
| Database | PostgreSQL (SQLite for local dev) |
| Auth | JWT (HS256) via `python-jose` + bcrypt passwords, dev mode bypass |

## Important System Behaviors

- Hash-based deduplication prevents reprocessing identical files (per-user scope via `(user_id, content_hash)`)
- Magic-byte MIME detection validates image format from file content, not extensions
- Content-addressed file storage at `{user_id}/{content_hash}/{original_filename}`
- Background processing jobs trigger automatic AI analysis on upload via Anthropic Claude
- Image resized to max 1568px and converted to JPEG before API submission (cost optimization)
- Structured metadata (13 fields) extracted, validated, and persisted in `media_metadata` table
- Re-analysis overwrites existing metadata (upsert pattern, no duplicates)
- Image validation prevents invalid files from reaching the AI API
- After analysis, metadata is auto-embedded (sentence-transformer) and indexed in ChromaDB for semantic search
- `GET /api/v1/search?q=...` returns ranked results with relevance scores, user-scoped
- Vector store is derived from DB — rebuildable via `scripts/rebuild_vector_store.py` (ADR-006)
- JWT auth on all routes (register/login for tokens, Bearer header for protected endpoints)
- Dev mode (`auth.dev_mode: true`) bypasses auth using auto-seeded dev user
- Standardized error responses with `detail` + `error_code` across all endpoints
- Rate limiting on auth endpoints (5/min login, 3/min register)
- Supported beta intake is source-connected intake (currently Google Drive), not local working-folder onboarding
- Local working-folder intake remains historical implementation context only; it is hidden/deprecated and any legacy local-folder reference items remain blocked for server-side bulk export

## Development Guidelines

When suggesting code changes:

**Prefer:**
- Small, incremental changes that build on working code
- Independent testability of each component
- Using proven libraries over custom implementations

**Avoid:**
- Skipping deduplication or validation steps
- Coupling frontend directly to internal modules (use the API)
- Hardcoding credentials or configuration

## Recent Session Activity

- **P12-010 implementation and closeout (2026-04-16):**
  - `ConnectorConfig.connector_sync_analysis_concurrency` added to `src/config.py` (default 2, clamped to range 1..3) and `config/settings.yaml`.
  - `ConnectorAnalysisTaskResult` dataclass and `_run_admitted_analysis_task()` task wrapper added to `src/connectors/sync_service.py`.
  - `_run_sync` refactored: bounded `asyncio.Semaphore` admission, slot-before-download discipline, quota-before-spawn, admitted task list, drain via `asyncio.gather`, aggregated failure accounting, structured run finalization.
  - `analyze_connector_item` in `src/analysis/processor.py` return type changed from `None` to `bool` to propagate processor-handled failures to `SyncRun.failed_count` (Auditor blocking finding resolved).
  - 20 focused tests in `tests/test_p12_010_connector_analysis_concurrency.py`; 74/74 pass across all directly affected suites.
  - Governance consequence: P12-010 is now formally completed and closed. Active workstream slot is clear. Next step is operator selection of next workstream.

- **P12-009 planning lock (2026-04-15):**
  - `docs/planning/P12-009_plan.md` defines the current metadata-preservation hardening slice.
  - Governing architecture note: `docs/planning/ARCH-004-source-capture-metadata-preservation.md` locks the source-truth contract for capture date/time and GPS, DB-backed date-taken behavior, authoritative source-field protection, AI non-overwrite rules, and PNG XMP non-destructive preservation.
  - Locked scope: no retrieval changes, no ranking changes, no richer AI metadata schema expansion, no remembered-photo benchmark implementation, and no multimodal work.
  - Governance consequence: P12-009 is now the current approval gate. P12-002 remains separately planned. The next workflow step is a short Auditor confirmation pass before operator approval and Engineer handoff.

- **P12-002 planning lock (2026-04-13):**
  - `docs/planning/P12-002_plan.md` defines the next remembered-photo retrieval workstream as a strictly measurement-first slice.
  - Locked contract: P12-002 freezes the benchmark owner, the three relevance labels (`primary_match`, `acceptable_match`, `non_match`), the three core metrics (`top1_primary_hit_rate`, `top5_primary_hit_rate`, `top5_primary_or_acceptable_hit_rate`), and the reporting shape before any retrieval or metadata work changes the system.
  - Tightened benchmark coverage rule: the first frozen benchmark set must contain at least 30 total queries, at least 5 queries in each mandatory class, and broad semantic regression queries may not exceed 20% of the benchmark.
  - Planning consequence only: P12-002 remains separately planned and is not implicitly merged into P12-009.

- **P12-001 closeout reconciliation (2026-04-14):**
  - `docs/planning/P12-001_plan.md` was converted from approval-gate wording into a closed historical contract after implementation verification.
  - `docs/CURRENT_STATE.md`, `docs/PROJECT_HANDOFF.md`, `docs/WORKSTREAMS.md`, and `docs/IMPLEMENTATION_STATUS.md` were reconciled so they all agree that P12-001 is completed and closed.
  - Locked closeout note: the unrelated failure `tests/test_google_drive_connector.py::test_drive_list_objects_sends_correct_query` remains out of scope and is not treated as a P12-001 regression.
  - Governance consequence: the active workstream slot is clear and the next workstream is operator-selected.

- **P12-001 planning lock (2026-04-13):**
  - `docs/planning/P12-001_plan.md` created to define the next post-P11 cleanup/hardening workstream: Google OAuth production-readiness and beta-access hardening.
  - Locked decision: the next slice is about external beta readiness for Google SSO and Google Drive OAuth, not provider expansion, not export redesign, and not reactivating deprecated local working-folder intake.
  - Locked contract: blocked Google platform states must become explicit user-facing and operator-facing product states, with clearer reconnect/scope-upgrade guidance and a single current readiness checklist.
  - Historical planning consequence only: P12-001 became the approval gate at that time. That planning state is now superseded by the 2026-04-14 closeout reconciliation above.

- **Live intake-model reconciliation (2026-04-13):**
  - Live governance/docs were reconciled to the current product truth that supported connected sources are the active beta intake path.
  - Historical P9-005 and related architecture records remain intact as implementation history, but local working-folder intake is no longer described as a supported current beta flow.
  - Governance consequence: no workstream was reopened; this was a live-state wording correction only.

- **P11-002 final closeout approval (2026-04-13):**
  - Final Auditor re-pass returned no blocking findings and approved P11-002 for closeout.
  - Governance consequence: P11-002 is now formally completed and closed. ADR-036 remains the authoritative contract, and the unrelated failure in `tests/test_google_drive_connector.py` remains explicitly out of scope for P11-002.
  - Workflow consequence: the active workstream slot is cleared and the next planning decision is now open.

- **P11-002 post-remediation governance reconciliation (2026-04-12):**
  - The previously reopened P11-002 closeout package was reconciled to the current post-remediation state without reopening architecture or scope.
  - The four previously identified contract drifts are now resolved in code: `export_no_eligible_items` returns the full locked 409 payload; ZIP assembly writes incrementally to a temporary artifact; expired export-artifact cleanup is wired from app lifespan; and completed/completed_with_failures jobs can promote to `expired` during status polling.
  - Validation now observed: P11-002 focused suite 19/19 pass and directly affected suites 71 pass. A separate backend-suite failure in `tests/test_google_drive_connector.py` remains outside P11-002 scope and is not treated as a workstream regression.
  - Governance consequence: P11-002 was no longer in Engineer remediation and moved into a final Auditor closeout re-pass state.

- **P11-002 implementation-closeout reconciliation (2026-04-12):**
  - The implementation landed in `src/config.py`, `src/models.py`, `src/api/schemas.py`, `src/api/routes/export.py`, `src/api/app.py`, `tests/conftest.py`, and `tests/test_p11_002_export_batch.py`.
  - Auditor closeout review found four material drifts against the locked ADR-036/P11-002 contract: the `export_no_eligible_items` response omits the full locked detail payload; ZIP assembly is still in-memory instead of incremental; TTL-expired artifacts have no startup or sweeper cleanup path; and status polling does not fully promote completed jobs to `expired`.
  - Governance consequence: P11-002 was reopened for a narrow remediation slice. That reopened state is now historical after the post-remediation reconciliation above.

- **P11-002 planning lock (2026-04-12):**
  - `docs/planning/P11-002_plan.md` created to define the next post-P11 workstream: async connector-aware bulk export.
  - Locked decision: the final mixed-selection bulk export contract must not extend the legacy synchronous `POST /api/v1/media/download-batch` ZIP route. P11-002 instead introduces a dedicated async export-job boundary with explicit submission-time accepted/blocked/rejected reporting and explicit runtime export results.
  - Locked contract: full items and Drive-backed reference items may participate only through bounded async export execution; local-folder and other non-Drive reference providers remain blocked; temporary export artifacts are user-scoped, short-lived, and must not become permanent retained originals.
  - Governance consequence: P11-002 is now the current approval gate. The next workflow step is Auditor review of the planning and governance package.

- **P11-001 post-implementation closeout reconciliation (2026-04-12):**
  - `docs/CURRENT_STATE.md`, `docs/PROJECT_HANDOFF.md`, `docs/planning/P11-001_plan.md`, and `docs/DECISION_LOG.md` were reconciled so the project now reads as one post-P11 closeout state rather than a mix of implementation-complete and approval-gate language.
  - Locked contract clarification: the shipped API intentionally collapses both missing IDs and unauthorized IDs into rejected `media_item_not_found`. The separate `not_owned` reason from the planning draft was removed from the authoritative governance contract without reopening implementation scope.
  - Governance consequence: P11-001 is completed and closed. That interim closeout-only state was later superseded the same day when P11-002 became the current approval gate.

- **P11-001 implementation closeout (2026-04-12):**
  - `POST /api/v1/media/reanalyze-batch` now uses explicit per-item `accepted`/`blocked`/`rejected` reporting instead of silent skips.
  - Drive-backed reference items are admitted only through async queueing; no request-time Drive download occurs.
  - Local-folder and other non-Drive reference providers remain blocked, and all-or-nothing quota enforcement returns HTTP 429 with explicit per-item outcomes when exhausted.

- **P11-001 planning lock (2026-04-12):**
  - `docs/planning/P11-001_plan.md` created to define the next post-P10 workstream: capability-aware batch reanalysis.
  - Locked decision: batch reanalysis and bulk export are separate workstreams. `P11-001` covers `POST /api/v1/media/reanalyze-batch` only; `P11-002 — Async Connector-Aware Bulk Export` is explicitly deferred as a later planning slice.
  - Locked contract: the current batch reanalysis route is legacy full-storage silent-skip behavior, not the final UX. Future mixed selections are allowed only with explicit per-item accepted/blocked/rejected reporting. Full items remain eligible; Drive-backed reference items may participate only through a capability-aware queueing model; local-folder and other non-Drive reference providers remain blocked.
  - _(Historical planning state only: this approval-gate wording was superseded once P11-001 was implemented and moved into closeout.)_

- **P10-001 Architect reconciliation (2026-04-12):**
  - Auditor re-pass found plan-versus-code drift: the shared Drive fetch service, both route integrations, and dedicated P10-001 tests already exist in the repo, so P10-001 is no longer a pre-Engineer approval gate.
  - `docs/planning/P10-001_plan.md` was reconciled to the live implementation baseline and now serves as the authoritative post-implementation contract rather than a pre-implementation proposal.
  - Locked contract: non-Drive reference items stay on `409 original_at_source`; Drive fetch failures use standardized `detail` + `error_code` payloads; shared-service misuse or inconsistent supposedly-Drive state is `502 drive_fetch_failed`, not `422`.
  - Governance consequence: P10-001 moved into implementation reconciliation/closeout status.

- **P10-001 closeout governance reconciliation (2026-04-12):**
  - Closeout audit result is now the governing workflow state: P10-001 is completed and closed out.
  - Stale next-step text that still left Auditor closeout as a pending workflow step was removed from the live governance docs.
  - Optional follow-up only: stale P10-001 test names may be cleaned up later if the operator wants cosmetic naming consistency, but they do not block closeout.

- **2026-04-11 (ad-hoc fixes — no workstream):**
  - `PATCH /api/v1/sources/{id}` rename endpoint added to `src/api/routes/sources.py`. Allows any connection to be renamed independently of its connector configuration.
  - `google_drive_configure` in `src/api/routes/google_drive_connector.py` now captures the return value of `_require_owned_source` and sets `source.name = body.target_folder_label or "Google Drive"` before committing. Previously only `target_folder_label` on the connector row was updated; `source.name` stayed as the creation-time default.
  - `SourcesPage.tsx` — inline rename UI: pencil icon appears on hover, opens text input pre-filled with current name, commits on Enter/Save or dismisses on Escape. Calls `api.renameSource()` in `frontend/src/api/client.ts`.
  - Source type display label in `SourcesPage.tsx` changed from raw `google_drive` / `s3` to human-readable `"Google Drive"` / `"Amazon S3"` via a `SOURCE_TYPE_LABELS` lookup map.
  - **Operator-performed operational actions (not repo changes):** two existing Google Drive connections renamed to their Drive folder labels via DB UPDATE; 52 dev sample images deleted from `/input/` on EC2 (24 MB freed).

- **P9-005 fix pass (2026-04-10):**
  - Resolved two Auditor blockers identified against the P9-005 implementation.
  - `frontend/src/pages/UploadPage.tsx` `uploadOne()` now writes the dropped file into the selected working folder via File System Access API (`getFileHandle() → createWritable() → write() → close()`) before sending bytes transiently to the backend. The local device is now the source of truth as the plan required.
  - `src/api/routes/upload.py` quota-exceeded cleanup for `POST /upload/local-folder` extended to delete `OriginAssetRef` and `PreviewAsset` (FK-safe order) and to delete the persisted thumbnail file via `_file_store.delete()`. New `_cleanup_unqueued_local_folder_upload(db, media_item_id, thumbnail_path)` helper.
  - Test #15 `test_upload_local_folder_quota_exceeded_cleans_up_all_artifacts` added; all assertions on zero DB rows and zero thumbnail files pass.
  - Full regression: 459 passed, 1 skipped. Phase 9 is fully closed.

- **P9-005 completion (2026-04-10):**
  - Closed the final ARCH-002 browser/local intake gap. All connector-synced and locally-selected originals are now reference-mode; no new full-retained originals can be created via normal user flows.
  - New `src/ingestion/local_folder_ingest.py` — `process_local_folder_intake()` mirrors `process_connector_import()`: validate → hash → dedup → MIME → dimensions → thumbnail-only → `MediaItem(storage_mode='reference', storage_path=None)` + `OriginAssetRef(provider_type='local_folder')` + `PreviewAsset`; no `file_store.save()` for original.
  - New `POST /api/v1/upload/local-folder` endpoint in `src/api/routes/upload.py` with `_resolve_local_folder_source_id()` auto-create helper.
  - `frontend/src/pages/UploadPage.tsx` rewritten with File System Access API gate, working-folder selection (`showDirectoryPicker()`), unsupported-browser messaging, calls `uploadLocalFolderFile()`.
  - 14 new tests in `tests/test_p9_005_local_folder_intake.py`. Suite at 458 passed, 1 skipped before fix pass.

- **P9-004 Auditor remediation (2026-04-10):**
  - **Finding 1 (Retry bootstrap scope):** In `src/api/routes/media.py`, moved the `is_drive_backed` guard to the top of `retry_writeback` so ALL non-Drive items return 422 unconditionally — including items that already have a backfill-created `WriteBackOperation` row. Previously the guard only blocked the bootstrap path; a non-Drive item with an existing operation could silently enter a no-op retry flow.
  - **Finding 2 (Blocked-path audit history):** Verified the three flagged exit paths in `drive_mutation_service.py` (credential decrypt failure, missing refresh token, missing Drive file ID) each call `_record_mutation_attempt`. The code was already correct; added the missing test `test_drive_rename_decrypt_failure_records_history` to explicitly cover the decrypt-failure path.
  - **Finding 3 (Local-browser mutation scope):** Confirmed `POST /media/{id}/mutation-result` does not create `WriteBackOperation` rows. Added `test_local_mutation_result_does_not_create_writeback_operation` to document and protect this contract.
  - **Finding 4 (Test coverage):** Added 3 focused tests to `tests/test_p9_004_capabilities_writeback.py`: credential decrypt failure writes history, mutation-result stays in P7-004 scope, non-Drive item with existing operation is rejected from retry.
  - Validation: focused suite 88 passed; full suite 444 passed, 1 skipped.
  - P9-004 is now ready for Auditor re-review.

- **P9-004 completion (2026-04-09):**
  - Added `SourceCapabilitySnapshot` and `WriteBackOperation` as additive ORM tables and Alembic migration `d2e3f4a5b6c7_p9_004_capability_writeback.py`.
  - Added `src/analysis/source_capability_service.py` for connector-level Google Drive capability snapshots and `src/analysis/writeback_operation_service.py` for durable write-back intent + mirror helpers.
  - Refactored `src/analysis/drive_mutation_service.py` so write-back state is canonical on `WriteBackOperation` while `MediaItem` mutation fields remain same-transaction compatibility mirrors.
  - Added additive `OriginAssetRef` bootstrap for legacy/historical item state so pre-P9-003 style rows and existing mutation tests continue to work without rewrites.
  - Updated `src/api/routes/google_drive_connector.py` to refresh capability snapshots on OAuth connect/upgrade and `src/api/routes/connectors.py` to prefer snapshot-derived `has_write_scope`.
  - Updated `src/api/routes/media.py` so local mutation reporting and retry compatibility bootstrap create durable write-back rows without changing `MutationStateResponse`.
  - Added `scripts/backfill_p9_004_capabilities_writeback.py` and `tests/test_p9_004_capabilities_writeback.py`.
  - Validation: focused suite 77 passed; full suite 433 passed, 1 skipped.

- **P9-004 planning lock (2026-04-09):**
  - `docs/planning/P9-004_plan.md` created to lock the implementation-ready scope for source capability snapshots and durable write-back operations.
  - Locked boundary: `SourceCapabilitySnapshot` is a single current-state row per `SourceConnector`, not a history table and not a `Source`-level summary.
  - Locked targeting: `WriteBackOperation` targets `OriginAssetRef` canonically and keeps `media_item_id` as a denormalized convenience FK for compatibility.
  - Locked compatibility rule: `WriteBackOperation` becomes the canonical backend state while `MediaItem.mutation_state` and related fields remain same-transaction mirrors for existing routes/tests.
  - _(Historical: P9-004 was subsequently implemented and audited — see completion and Auditor remediation entries above.)_

- **P9-003 scope resolution (2026-04-09):**
  - `docs/planning/P9-003_plan.md` created to lock the implementation-ready scope for the additive origin/preview domain split.
  - Locked boundary: `OriginAssetRef` is a new `MediaItem`-owned 1:1 origin locator and does not replace `SourceObject`, which remains connector sync memory.
  - Locked applicability: `OriginAssetRef` applies to connector-backed items, local-folder items, and manual app-retained uploads.
  - Locked migration treatment: `storage_path`, `thumbnail_path`, and `source_file_fingerprint` are true migrations with compatibility mirrors; mutation/write-back fields stay on `MediaItem` for this slice.
  - Locked sequencing: P9-003 remains a prerequisite for P9-004 because `WriteBackOperation` should target `OriginAssetRef`, not the existing mixed locator fields.

- **P9-003 completion (2026-04-09):**
  - `OriginAssetRef` and `PreviewAsset` are now implemented in the live ORM and ingestion paths.
  - Backfill script `scripts/backfill_p9_003_origin_preview.py` and `tests/test_origin_preview_models.py` landed with the slice.
  - `docs/IMPLEMENTATION_STATUS.md` records the completed implementation baseline and the test-suite increase to 423 passing tests.

- **P9-002 completion (2026-04-09):**
  - Shared storage guards now block source-inaccessible original reads consistently across download, convert, re-analysis, and scoring flows.
  - The codebase now fails fast with controlled `original_at_source` behavior instead of assuming `storage_path` implies app-readable originals.

- **P9-001 completion (2026-04-09):**
  - Connector ingestion no longer writes full originals to app storage even transiently.
  - Connector analysis now runs from caller-provided bytes and persists connector-backed `MediaItem` rows directly in `storage_mode='reference'` semantics.

- **Phase 9 activation and operator approval (2026-04-08):**
  - `docs/planning/PHASE_9_arch002_gap_remediation_plan.md` is now approved rather than draft.
  - Operator locked five implementation decisions: close the transient-write gap now; use source re-fetch as the long-term retry rule; allow synchronous sync-flow analysis only as a short-term rollout tactic if needed; use controlled source-aware errors first for storage-assuming features unless cheap/reliable on-demand source fetch already exists; use additive domain evolution instead of a big-bang `MediaItem` rewrite; include operational audit/cleanup of already-retained connector originals.
  - `P9-001 — Zero-Transient Connector Ingestion` is now the next approved workstream.

- **P8-003 planning/governance activation (2026-04-08):**
  - `docs/planning/P8-003_plan.md` became the Phase 8 approval gate at that time.
  - The plan defines the historical connector preview-only migration as a one-time operational script, not an API endpoint or startup hook.
  - Missing thumbnails are explicitly backfilled in-scope for otherwise eligible historical connector items before `_attempt_preview_pivot()` is invoked.
  - The plan locks conservative batch controls, rerun-safe idempotency, and log-based operator visibility.
  - Script execution examples now use the real Docker Compose backend service name: `backend`.
  - That approval-gate state is now historical because Phase 9 is active and `P9-001` is the next approved workstream.

- **P8-002 completion (2026-04-08):**
  - `analyze_media_item()` now owns the replay-safe preview-only transition path via `_attempt_preview_pivot()`.
  - Eligibility is derived from persisted source state, not a transient enqueue-time flag.
  - Connector items require a durable `SourceObject`; `source_type='local_folder'` items require a persisted `source_file_fingerprint`; manual `__uploads__` items remain ineligible.
  - Sync-service deletion logic was removed after connector identity ordering was made safe for processor-owned pivot evaluation.

- **P8-001 planning activation (2026-04-08):**
  - Phase 8 planning became active for the reference-mode storage pivot with Slice A+B as the first implementation gate.
  - That approval gate is now historical because P8-001 and P8-002 completed, P8-003 later superseded it within Phase 8, and Phase 9 has now promoted `P9-001` as the current approved next workstream.

- **P7-004 revision after Auditor findings (2026-04-05):**
  - `docs/planning/P7-004_plan.md` and `docs/planning/ARCH-002-reference-mode-storage.md` were revised to resolve the critical contradiction between the mandatory source-mutation contract and the completed P7-002 `drive.readonly` Google Drive foundation.
  - Locked decision: P7-004 includes the Google Drive writable-scope upgrade and re-consent path plus the rewrite-and-reupload metadata mutation workflow. Existing read-only Drive connectors remain valid for sync/analysis but are `blocked_writeback` until reauthorized.
  - Locked rule: browser drag-drop and local-folder flows must not silently fall back to permanent AWS original retention.
  - Locked rule: cloud metadata fallback counts only when it writes canonical metadata to a provider-approved source-side representation; app-only metadata persistence does not satisfy `fully_applied`.
  - `docs/DECISION_LOG.md` updated with the storage-pivot ADR and related P7-004 decisions so Engineer inherits a complete architecture record.

- **P7-002 plan revision before approval (2026-04-05):**
  - `docs/planning/P7-002_plan.md` updated to explicitly require a non-secret authorized Google account snapshot and define same-account vs different-account reconnect handling.
  - Callback-state wording narrowed to the exact guarantees in this workstream: signed browser-bound state plus provider single-use auth-code enforcement, without claiming a separate DB-backed one-time state store.
  - Backend callback redirect behavior is now locked to a fixed success/failure query contract so the Sources page can show deterministic banners.
  - At that time, `CURRENT_STATE.md` was reconciled for the P7-002 approval gate; that is now historical and has been superseded by P7-004.

- **P7-002 planning (2026-04-05):**
  - `docs/planning/P7-002_plan.md` created to formalize the first Google Drive connector on top of the existing connector foundation.
  - Locked decisions include: authenticated SPA OAuth start returning `authorization_url`, signed browser-bound callback state, Drive refresh tokens in encrypted connector-secret storage, dedicated token manager for exchange/refresh/rotation persistence, provider-neutral connector container semantics (`remote_container_id`, `remote_container_label`), root-only `My Drive`, `drive.readonly`, exclusion of trashed files/shortcuts/Google-native docs, file ID + Drive `version` idempotency, connector factory/registry adoption, and `RemoteObject.display_name` for non-path-based connectors.
  - `docs/DECISION_LOG.md` updated with `ADR-021` through `ADR-025`.
  - At that time, `docs/WORKSTREAMS.md` was updated so `P7-002` became the planned approval gate; that state is now historical and has been superseded by P7-004.

- **P6-001 plan revision after audit (2026-04-03):**
  - `docs/planning/P6-001_plan.md` updated to lock the backend-to-frontend completion handoff as a short-lived DB-backed one-time record plus HTTP-only completion cookie and non-secret `flow_id` correlation.
  - OIDC nonce validation is now mandatory in addition to signed state-cookie comparison; state and nonce cookies are single-use and short-lived.
  - Account-linking precedence is now explicit: existing provider link first, verified-email fallback only when no provider link exists, disabled accounts fail, later provider-email drift cannot re-key ownership, and Phase 6 enforces one Google identity per local user via `UNIQUE (user_id, provider)`.
  - Google rollout gating is now mandatory via `ENABLE_GOOGLE_SSO`, so schema/code can ship dark before exposing the Google button and routes.
  - At that time, `CURRENT_STATE.md` and `WORKSTREAMS.md` were reconciled for the P6-001 approval gate; that state is historical and no longer current.

- **Bugfix: Concurrent upload race condition (2026-04-02):**
  - `UploadService.process_upload()`: added `except IntegrityError` handler after the DB write. When two identical files race past the dedup check and the second INSERT hits `uq_user_content_hash`, the handler rolls back, deletes the stored file, and re-queries for the winner — returning `is_duplicate=True` instead of propagating a 500.
  - `tests/test_upload.py`: added `test_concurrent_duplicate_handled_gracefully` (call-count side-effect patch simulates the race window). 209/209 tests pass. Commit: `fc2147a`. **AWS deploy needed.**

- **P5-003 implementation (2026-04-03):**
  - Full connector sync foundation implemented: encrypted credential storage, S3-compatible connector, sync-run state machine, idempotent per-object import tracking.
  - Alembic migration `f6a7b8c9d0e1`: adds `connector_status`/`last_synced_at` to `sources`; creates `source_connectors`, `sync_runs`, `source_objects` tables.
  - `ConnectorConfig` added to `config.py` — `credentials_key` from env `CONNECTOR_CREDENTIALS_KEY` (fail-closed when absent), `max_objects_per_sync=1000`.
  - `src/connectors/` package: `secrets.py` (Fernet encryption), `base.py` (RemoteObject + ConnectorBase ABC), `s3_connector.py` (boto3 via `run_in_executor`), `sync_service.py` (full sync orchestrator with overlap prevention, idempotency, quota reservation, per-object error isolation).
  - `src/models.py` extended: `SourceConnector`, `SyncRun`, `SourceObject` ORM models added; `Source` extended with `connector_status`, `last_synced_at`, `connector` relationship.
  - `src/api/routes/connectors.py` created: `POST /{id}/connector/s3`, `GET /{id}/connector`, `POST /{id}/sync`, `GET /{id}/sync-runs`; registered in `app.py`.
  - Schemas: `ConnectorS3ConfigRequest`, `ConnectorResponse` (no secrets), `SyncRunResponse`, `SyncRunsResponse`, `TriggerSyncResponse`; `SourceResponse` extended.
  - Frontend: `SourcesPage.tsx` gains `ConnectorPanel` (S3 config form, sync trigger, sync run history table), connector status badge per row; `api.ts` + `client.ts` updated.
  - 18 new tests in `tests/test_connectors.py`; connector workstream completed cleanly and later project-level regression coverage brought the suite to 209/209.
  - **AWS deploy not yet done** — `CONNECTOR_CREDENTIALS_KEY` env var must be set before deploying; migration `f6a7b8c9d0e1` will run on startup.

- **P5-001 + P5-002 implementation (2026-04-03):**
  - P5-001: pHash 64-bit (imagehash library) added to upload pipeline and stored on `media_items`. `GET /api/v1/media/{id}/similar` endpoint. Gallery similar badge. Backfill script. 16 tests.
  - P5-002: AI quality scoring for near-duplicate groups. `curation_scores` table. `POST /api/v1/media/{id}/score-group`. `GET /similar` extended with scores + best-pick flags. Frontend best-pick crown + quality badge. 16 tests.
  - 190/190 total tests passed after P5-002.

- **P4-003 implementation + AWS deploy (2026-04-01):**
  - Full Source Registry implemented across 8 steps.
  - Step 1: `Source` model + Alembic migration `a1b2c3d4e5f6` (sources table, source_id FK on media_items). `batch_alter_table` required for SQLite FK compat.
  - Steps 2+3: `SourceResponse`/`SourceCreateRequest` schemas, `source_id` on `MediaItemResponse`, `src/api/routes/sources.py` with 4 endpoints (create, list, archive, restore), registered in `app.py`.
  - Steps 4+5: `source_id` query filter on `GET /api/v1/media`; `source_id: str | None = Form(None)` on both upload endpoints with `_resolve_source_id()` helper (404 not found, 403 cross-user IDOR); propagated through `upload_service.py`.
  - Steps 6+7: Frontend — `SourceResponse` type, `listSources()`/`createSource()` in `client.ts`; UploadPage: source selector + inline create-source form, auto-selects new source; GalleryPage: Source dropdown in FilterPanel, wired to URL params, buildFilters, apply/reset.
  - Step 8: `tests/test_sources.py` — 24 tests (create/list/archive/restore/IDOR/filter). 115/115 total pass. TypeScript clean.
  - AWS deploy: `git push`, EC2 pull + `docker compose up -d --build`, migration `a1b2c3d4e5f6` ran on startup. Smoke: source create, list, source-tagged upload, gallery filter validated.
  - Commits: `13e9c69`, `003e67d`, `a96d81a`, `4a3e5b7`, `30bb319`, docs closeout.

- **P4-002 AWS deploy + closeout (2026-03-31):****
  - `pg_dump` backup taken on EC2: `media_indexing_pre_p4002_20260401_040910.sql.gz`.
  - `git push origin master` pushed 6 commits (`d91975c..5ca5ee6`); git stash + pull on EC2, merge conflicts resolved (server config files: `--ours`; test files: `--theirs`).
  - `docker compose -f docker-compose.yml -f docker-compose.beta.yml up -d --build` rebuilt all 5 containers; migration `7a8b9c0d1e2f` ran on startup.
  - AWS smoke: quota status endpoint returned `{plan_name:basic, monthly_limit:500, consumed:0, remaining:500}`; upload→analysis→consumed=1; delete (with quota_events FK fix) returned `{deleted:1}`. All checks passed.
  - Delete FK bug fixed in same session: `quota_events.media_item_id` FK caused batch delete to fail for post-P4-002 files; fix: clear quota_events before media_items in `delete_batch()`. Commit: `5ca5ee6`.
  - P4-002 fully closed. Commits: `c147790`, `6a1d20d`, `5ca5ee6`.

- **P4-002 implementation + smoke session (2026-03-31):**
  - Quota enforcement system implemented end-to-end: `quota_events` ledger, `QuotaService` (reserve/consume/release with `SELECT FOR UPDATE`), `GET /api/v1/quota/status`, upload + reanalyze routes enforce quota, processor consumes on success / releases on failure.
  - Frontend: confirmation modal shows plan, period, selected count, used/limit, available, overwrite warning, geo note; confirm button disabled when quota exhausted; `ApiRequestError` fast-fail on 429.
  - 5 new quota tests created (`tests/test_quota.py`); 91/91 total backend tests pass. TypeScript clean.
  - Local smoke complete: upload → consumed (499 remaining); re-analysis → decremented; over-limit → modal disabled + button non-clickable; forced HTTP 429 → `{error_code, error, remaining, limit}` payload; duplicate upload → quota unchanged.
  - ADR-013 recorded in `docs/DECISION_LOG.md` (reservation ledger semantics).
  - Commit: `c147790` — "P4-002: quota enforcement, structured 429, frontend modal, tests (91/91)".
  - AWS deploy completed in subsequent session (see entry above).

- **AWS public beta deployment session (2026-03-29):**
  - Operator chose AWS instead of a generic VPS recommendation.
  - Single-instance EC2 deployment path used successfully: Ubuntu 24.04, Docker Engine, Docker Compose, Elastic IP.
  - Project copied to EC2, `.env` created, and full stack started with `docker compose -f docker-compose.yml -f docker-compose.beta.yml up -d --build`.
  - Backend, frontend, PostgreSQL, ChromaDB, and Caddy all started successfully; backend health check passed.
  - Temporary blocker discovered: automatic HTTPS cannot be issued for the AWS-provided hostname `ec2-13-216-223-46.compute-1.amazonaws.com` because ACME rejects that identifier.
  - Temporary workaround applied: `deploy/Caddyfile` changed to HTTP-only for the EC2 hostname so the beta can be accessed without a custom domain.
  - Public health endpoint verified over HTTP: `curl -i --max-time 10 http://ec2-13-216-223-46.compute-1.amazonaws.com/api/v1/health` returned `200 OK` with `{"status":"ok","version":"0.1.0"}`.
  - AWS security group and Ubuntu firewall both verified to allow ports 22, 80, and 443.
  - Browser behavior note: site initially failed in the normal browser due to cached HTTPS/HSTS state; confirmed working in Incognito mode using the full `http://` URL.
  - Follow-up required: rotate exposed `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, and `AUTH_SECRET_KEY`, then attach a real domain and switch Caddy back to automatic HTTPS.
- **Phase 4 planning session (2026-03-31):**
  - Operator provided pre-beta feature and control feedback covering Gallery UX, Sources flow, monthly quotas, source tracking, admin controls, billing, OCR, profile management, and future expansion ideas.
  - New phase plan created at `docs/planning/PHASE_4_beta_operations_plan.md`.
  - Six planned workstreams defined: `P4-001` Gallery & Detail UX Continuity, `P4-002` Plans/Quotas & Analysis Confirmation, `P4-003` Source Registry & Source-Aware Media, `P4-004` Admin Console & User Profile Management, `P4-005` Billing Groundwork & Commercial Modeling, `P4-006` OCR Search Enrichment.
  - Naming/domain selection explicitly kept out of Phase 4 planning per operator instruction.
  - High-risk items deferred from Phase 4 exit criteria: full video analysis, facial recognition, and broad connector rollout across every cloud source.
  - Phase rule established: each workstream must be validated locally first, then smoke-tested in the AWS beta environment before closeout.

- **Post-Phase-3 bug fixes (2026-03-29, commit fd5013e on master):**
  - **nginx upload limit:** `client_max_body_size` raised to 50M in `frontend/nginx.conf` (files >1MB were returning HTTP 413)
  - **Search security fix:** `src/search/search_service.py` — `MediaItem.user_id == user_id` added to DB WHERE clauses (defense-in-depth; ChromaDB already filtered by user_id)
  - **Search sort fix:** `frontend/src/pages/GalleryPage.tsx` — `handleSubmit` now calls `doSearch()` directly, tracks `lastSubmittedQuery` ref, resets sort to relevance when switching browse→search. Confirmed: first search after login returns relevance-ranked results.
  - 82/82 tests still pass. All changes deployed to Docker stack and verified live.

- Project initialized at `Projects/media_indexing_engine/`
- Directory scaffolded with src/, tests/, config/, docs/, scripts/, frontend/
- Phase 1 plan created, revised (WS-000 added, WS-004 narrowed), and approved
- WS-000 completed: prior art extracted from `marketing_asset_pipeline`, all foundational design decisions made
- 8 ADRs recorded in DECISION_LOG.md (ADR-001 through ADR-008)
- WS-001 completed: full ingestion pipeline (15 source files, 4 endpoints, 13 tests)
- WS-002 completed: full AI analysis pipeline
  - 8 new source files: provider interface, Anthropic implementation, mock provider, image prep, metadata schemas, processor, analysis API routes, analysis tests
  - 10 modified files: models (MediaMetadata), config (AnalysisConfig + dotenv), schemas, app, upload routes, file_store, job_manager, pyproject.toml, settings, conftest
  - 2 new API endpoints: `GET /media/{id}/analysis`, `POST /media/{id}/reanalyze`
  - 21 total integration tests (8 analysis + 13 existing) — all passing
  - Smoke test verified with real Anthropic API on Polynesian Cultural Center photos — metadata quality excellent
  - `.env` file with `ANTHROPIC_API_KEY` required for real analysis; graceful fallback without it
- WS-003 completed: full semantic search pipeline
  - 8 new source files: embedding_text, embedder, models, vector_store, chromadb_store, indexing_service, search_service, search API route
  - 1 new script: `scripts/rebuild_vector_store.py`
  - 1 new API endpoint: `GET /api/v1/search?q=...` with pagination and relevance scores
  - Auto-indexing: analysis completion triggers embedding generation + ChromaDB upsert
  - User-scoped search: users only see their own media in results
  - 28 total integration tests (7 search + 8 analysis + 13 upload/media) — all passing
  - Search runs entirely locally (sentence-transformers + ChromaDB — no external API)
- WS-004 completed: auth & API hardening
  - 7 new source files: passwords, tokens, auth routes, error_handlers, rate_limit + auth __init__, test_auth
  - 3 new API endpoints: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
  - JWT auth replaces hardcoded dev user — dev mode preserves backwards compatibility
  - Standardized error responses (`detail` + `error_code`) across all endpoints
  - Rate limiting: 5/min login, 3/min register (in-memory sliding window)
  - 38 total integration tests (10 auth + 28 existing) — all passing
- WS-005 completed: frontend MVP
  - React 18 + TypeScript + Vite SPA with dark mode UI
  - 6 pages: Login, Register, Library (paginated grid + auto-polling), Upload (drag-drop), Media Detail (13 metadata fields + re-analyze), Search (ranked results with scores)
  - Typed API client for all 11 backend endpoints, authenticated image loading via blob URLs
  - Backend: `GET /media/{id}/file` endpoint, CORS middleware, filename truncation for Windows MAX_PATH
  - Manual integration test verified: full register → upload → analyze → search flow works end-to-end
- Post-Phase 1 informal improvements applied (no formal workstream): search filters (people, orientation, aspect ratio, file type, mood, sort order), AVIF support, image dimensions stored on upload, upload UX improvements, dark mode, long filename truncation, authenticated image loading
- **Phase 2 workstreams completed (P2-001 through P2-005):**
  - P2-005: Search added as third nav link in header Layout — no backend changes
  - P2-001: `src/enrichment/` module (8 files) — EXIF/IPTC/XMP embedding for JPEG, WebP, AVIF, PNG, TIFF; BMP/GIF pass-through; 16 new tests, 54 total
  - P2-002: `src/api/routes/download.py` — `GET /media/{id}/download`, `POST /media/download-batch`, `POST /media/{id}/convert-png`; 8 new tests, 62 total
  - P2-003: Frontend download buttons on MediaDetailPage — "Download (with metadata)" for embeddable formats, convert-to-PNG for BMP/GIF
  - P2-004: Grid/list view toggle on Library + Search pages, checkbox multi-select, "Download Selected" batch ZIP; 3 new components (ViewToggle, MediaListRow, SelectionBar)
- **P3-001 (UI Polish & API Cleanup) completed:**
  - Change 1: `field_mapping.py` — removed "AI-generated description:" prefix from `build_user_comment()`
  - Change 2: `download.py` — `_MIME_TO_EXT` dict + `_ext_for_mime()` helper; AI title now used as download filename for ALL formats (not just BMP/GIF)
  - Change 3: `schemas.py`, `search.py`, `types/api.ts`, `MediaDetailPage.tsx` — `width`/`height` exposed throughout stack; dimensions displayed on media detail page
  - Change 4: `media.py` completely rewritten with full filter+sort params (metadata JOIN, aspect ratio post-query); new `GalleryPage.tsx` (~320 lines) replaces `LibraryPage.tsx` + `SearchPage.tsx`; `client.ts` `listMediaFiltered()`; `/search` route removed; `App.tsx`, `Layout.tsx`, `SearchBar.tsx` updated
  - Change 5: `Layout.tsx` nav + `UploadPage.tsx` heading renamed from "Upload" to "Source"
  - 62/62 tests pass; 1 test assertion updated (`test_single_download_jpeg`)
- **P3-002 (Database Migrations) completed:**
  - `alembic` 1.14 added to `pyproject.toml` and installed
  - `alembic init alembic` scaffolded at project root; `alembic.ini` URL placeholder removed (URL set dynamically in env.py)
  - `alembic/env.py` rewritten: async engine (`create_async_engine` + `connection.run_sync()`), `get_db_url()` reads `DATABASE_URL` env var or `config/settings.yaml`, offline mode supported
  - Initial migration `cce0c99946e6_initial_schema.py` generated from fresh-DB autogenerate — creates all 4 tables with FK constraints, unique constraints, and indexes
  - `src/database.py`: added `run_migrations()` using thread executor to avoid nested asyncio event loop
  - `src/api/app.py`: lifespan calls `run_migrations()` when `settings.app.debug: false`; `create_tables()` otherwise (dev + test path unchanged)
  - `README.md`: full Getting Started section with fresh-install and existing-DB migration instructions
  - `alembic upgrade head` validates clean on fresh SQLite; 62/62 tests pass
- **P3-003 (Bulk Operations) completed:**
  - `POST /api/v1/media/reanalyze-batch`: accepts `{media_ids: [...]}`, 1–50 cap, user-scoped, skips items with in-progress jobs, enqueues background analysis jobs, returns `{queued, message}`
  - `DELETE /api/v1/media/batch`: accepts `{media_ids: [...]}`, 1–50 cap, user-scoped, deletes MediaMetadata + ProcessingJob + MediaItem in child-first order (FK constraint safe), physical file removal (best-effort), vector embedding removal (best-effort); returns `{deleted, message}`
  - `delete_items(media_ids)` added to `VectorStore` protocol and `ChromaDBVectorStore` (uses `collection.delete(ids=[...])`)
  - `remove_items(media_item_ids)` added to `IndexingService`
  - `BatchOperationRequest` (validated 1–50 `media_ids`), `BatchReanalyzeResponse`, `BatchDeleteResponse` added to `schemas.py`
  - `SelectionBar.tsx`: Re-analyze + Delete buttons (Delete uses `window.confirm()`); `onDeleteSuccess?: (ids: string[]) => void` prop added
  - `GalleryPage.tsx`: passes `onDeleteSuccess` callbacks to both SelectionBar instances to remove deleted items from local browse/search state
  - `client.ts`: `reanalyzeBatch()` and `deleteBatch()` added
  - 8 new integration tests in `tests/test_bulk_operations.py`; 70/70 tests pass

## Open Questions / Blockers

- No application blockers.
- Operational limitation remains: AWS SES production access is still pending for live password reset email sending, but this does not block Phase 5 planning.
- Workflow state: P11-002 is completed and closed. There is no active implementation workstream; the next operator step is the next planning decision.
- Validation note: P11-002 focused suite is 19/19 pass and directly affected suites are 71 pass. The current unrelated failure in `tests/test_google_drive_connector.py` is not treated as a P11-002 blocker.

## Document Ownership Note

This document owns **session bootstrap context and handoff state only**. It does not duplicate:
- Project identity or constraints → see `PROJECT_AI_CONTEXT.md`
- Codebase structure → see `PROJECT_MAP.md`
- Development practices → see `PROJECT_PLAYBOOK.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
- System status → see project `docs/CURRENT_STATE.md`
