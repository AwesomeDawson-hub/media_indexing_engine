# Workstreams

This document tracks all work items for the Media Indexing Engine through their lifecycle. It is the **single source of truth** for what work is planned, in progress, and completed.

## How Workstreams Move Between Sections

### Planned → In Progress
- Operator approves the workstream to start
- A plan exists (created from phase plan or equivalent)
- `CURRENT_STATE.md` is updated to reflect the active workstream

### In Progress → Completed
- All implementation work is done
- Validation confirms the work meets its objectives
- Closeout checklist has been followed
- A summary is written to `IMPLEMENTATION_STATUS.md`
- `CURRENT_STATE.md` is updated to clear the active workstream

### Cancellation
- Operator may cancel a workstream at any stage
- Cancelled workstreams move to Completed with status "Cancelled" and a reason
- All document updates still apply (state must remain consistent)

---

## Planned

_Phase 4 — Beta Operations & Commercial Foundations. Full phase plan at `docs/planning/PHASE_4_beta_operations_plan.md`. Workstreams use `P4-XXX` prefix._





### P4-003: Source Registry & Source-Aware Media
- **Objective:** Persist named sources, associate media with sources, add archive/restore behavior for deleted sources, and establish the connector abstraction for future online sources.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Planned

### P4-004: Admin Console & User Profile Management
- **Objective:** Add admin-only user management, backend RBAC, audited admin actions, self-service profile updates, verified email change, and account recovery.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Planned

### P4-005: Billing Groundwork & Commercial Modeling
- **Objective:** Measure image-processing cost, codify plan tiers, and implement Stripe test-mode billing groundwork without enabling live paid launch.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Planned

### P4-006: OCR Search Enrichment
- **Objective:** Extract text from images, store it as additional search data, and make it searchable.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Planned

---

## In Progress

_No workstreams currently in progress._

---

---

## Post-Phase 3 Bug Fixes (Applied 2026-03-29, commit fd5013e)

_These production bug fixes were applied directly without a formal workstream, after Phase 3 closeout:_
- **nginx upload limit:** `frontend/nginx.conf` — `client_max_body_size` raised from 1M (default) to 50M. Files >1MB were returning HTTP 413.
- **Search security fix (defense-in-depth):** `src/search/search_service.py` — `MediaItem.user_id == user_id` added to DB WHERE clauses in `search_media()`. ChromaDB already filtered by `user_id`; DB now enforces it independently at the read path.
- **Search sort after login:** `frontend/src/pages/GalleryPage.tsx` — `handleSubmit` now calls `doSearch()` directly (not relying solely on URL `useEffect`), tracks `lastSubmittedQuery` ref to prevent double-fire, resets `sort_by` to relevance when switching browse→search. First search after login now correctly returns relevance-ranked results.

---

## Post-Phase 1 Improvements (Applied 2026-03-28)

_These changes were applied directly without a formal workstream, after Phase 1 closeout:_
- Search filters: people, orientation, aspect ratio (7 standard + Other), file type, mood, sort order
- AVIF file support (backend + frontend)
- Image dimensions stored on upload (`width`, `height` columns)
- Upload UX improvements (header buttons, scrollable queue)
- Dark mode UI
- Long filename truncation, authenticated image loading

---

## Completed

### P4-002: Plans, Quotas & Analysis Confirmation
- **Objective:** Enforce monthly image-processing limits, add quota-aware confirmation on the Sources page, and protect capture date/geo-location from overwrite.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed (local smoke passed; AWS deploy pending)
- **Plan:** `docs/planning/P4-002_plan.md`
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Outcome:** Quota enforcement fully implemented and smoke-tested locally. Alembic migration `7a8b9c0d1e2f` adds `plan_name`/`monthly_limit` to `users` and creates `quota_events` ledger. `QuotaService` implements reserve/consume/release with `SELECT FOR UPDATE` concurrency. `GET /api/v1/quota/status` endpoint live. Upload and re-analysis routes enforce quota (single: 429+cleanup; batch: per-item error). Processor consumes on success, releases on failure. Frontend modal shows plan, period, selected count, used/limit, available, overwrite note, geo note; confirm button disabled when exhausted. `ApiRequestError` fast-fail on 429. 5 new quota tests; 91/91 total tests pass. TypeScript clean. ADR-013 recorded. Commit: `c147790`.

### P4-001: Gallery & Detail UX Continuity
- **Objective:** Keep filters visible, add dimensions filtering, simplify status display, reorganize Media Detail, and preserve Gallery state when returning from details. Source-backed filtering is explicitly deferred to P4-003.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-03-31
- **Completed:** 2026-03-31
- **Plan:** `docs/planning/P4-001_plan.md`
- **Outcome:** All 6 changes delivered plus 5 smoke-discovered fixes. Filters always visible (toggle removed). Source button removed from Gallery header. Size bucket filter (Small/Medium/Large) wired to backend `min_width`/`max_width`. StatusBadge hides `completed` status. MetadataDisplay split into Metadata + Additional Search Data sections. Back-to-Gallery Link restores full gallery URL state. Smoke fixes: poll terminal-status allowlist; Delete button on Media Detail; Clear Search button in filter panel; btn-danger CSS; sort + filter state both written to URL immediately on every change. All 7 local and 7 AWS smoke flows pass. Final commits: `e8dedcf` (original 6) through `d91975c` (filter persistence).

### P3-004: Production Deployment
- **Objective:** Implement S3-compatible `S3FileStore`, add a health endpoint (`GET /api/v1/health`), validate PostgreSQL end-to-end, and produce a Docker + docker-compose stack for the full system (backend, frontend, ChromaDB, PostgreSQL).
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** `GET /api/v1/health` returns `{"status":"ok","version":"0.1.0"}` with no auth. `S3FileStore` implemented via boto3 in thread executor; `get_file_store()` factory selects backend by `storage.provider` config/env. `StorageConfig` extended with S3 fields; env override chain extended with `DATABASE_URL`, `STORAGE_PROVIDER`, `S3_BUCKET`, `S3_REGION`. `Dockerfile` (backend) and `frontend/Dockerfile` (multi-stage nginx) created. `docker-compose.yml` defines all four services. `.env.example` documents all required env vars. README updated with production deployment guide. 12 unit tests for S3FileStore; **82/82 tests pass**. ADR-009, ADR-010, ADR-011 recorded.

### P3-003: Bulk Operations
- **Objective:** Add bulk re-analysis and bulk delete API endpoints. Implement `LocalFileStore.delete()` and `ChromaDBVectorStore.delete_items()`. Integrate Re-analyze and Delete actions into the Gallery SelectionBar UI.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** `POST /api/v1/media/reanalyze-batch` and `DELETE /api/v1/media/batch` added. `delete_items()` added to `VectorStore` protocol and `ChromaDBVectorStore`. `remove_items()` added to `IndexingService`. `BatchOperationRequest` (1–50 media_ids) and response schemas added. SelectionBar updated with Re-analyze + Delete buttons. GalleryPage passes `onDeleteSuccess` callbacks. 8 new integration tests; 70/70 tests pass.

### P3-002: Database Migrations
- **Objective:** Install Alembic migration framework, generate the initial migration from the current schema, and integrate migration execution into startup so the drop-and-recreate pattern is retired.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Alembic installed and configured with async SQLAlchemy support. `alembic upgrade head` creates the full 4-table schema on a fresh database. Production startup calls `run_migrations()`; dev/test keeps `create_all()`. 62/62 tests pass unaffected. README updated with migration instructions.

### P3-001: UI Polish & API Cleanup
- **Objective:** Five targeted improvements: fix metadata comment prefix; use AI title as download filename for all formats; expose image dimensions throughout stack; merge Library + Search into unified Gallery page; rename "Upload" → "Source" throughout UI.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** All 5 changes delivered. `field_mapping.py` prefix removed. `download.py` extended with `_MIME_TO_EXT` dict — AI title used as filename for all formats. `schemas.py`, `types/api.ts`, and `MediaDetailPage.tsx` updated with `width`/`height`. `media.py` rewritten with full filter+sort params and aspect-ratio post-query filtering. New `GalleryPage.tsx` replaces `LibraryPage.tsx` and `SearchPage.tsx`. Nav updated to "Gallery / Source". 62/62 tests pass.

### P2-004: List View + Multi-Select + Batch Download
- **Objective:** Grid/list view toggle on Library and Search pages, checkbox multi-select, batch ZIP download
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Grid/list view toggle on Library and Search pages. List view with per-row checkboxes, "Select all", floating selection bar with "Download Selected" (batch ZIP). View preference persisted in localStorage. 3 new components: ViewToggle, MediaListRow, SelectionBar. API client: `downloadBatch()`.

### P2-003: Frontend Download Button
- **Objective:** Download with metadata button on media detail page; BMP/GIF convert-to-PNG option
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** "Download (with metadata)" button on MediaDetailPage for embeddable formats (JPEG, WebP, PNG, TIFF). BMP/GIF: "Download" button + "Convert to PNG with metadata" button. API client additions: `downloadFile()`, `downloadBatch()`, `convertToPng()`.

### P2-002: Download Endpoints
- **Objective:** Backend download endpoints: single file with metadata embedded, batch ZIP, convert-to-PNG
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** 3 new API endpoints in `src/api/routes/download.py`: `GET /media/{id}/download` (single enriched file), `POST /media/download-batch` (ZIP archive), `POST /media/{id}/convert-png` (BMP/GIF to PNG with metadata). BMP/GIF downloads use AI title as filename. 8 new tests, 62 total pass.

### P2-001: Metadata Embedder Module
- **Objective:** Embed AI-extracted metadata (title, description, tags, etc.) into image file headers at download time
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** 8 new files in `src/enrichment/`: `MetadataEmbedder` dispatcher, EXIF writer (JPEG/WebP/AVIF/TIFF), IPTC writer, PNG XMP writer, AVIF writer, WebP writer, field mapping, XMP builder. Supports JPEG (EXIF+IPTC), WebP (EXIF), AVIF (EXIF), PNG (XMP via iTXt), TIFF (EXIF+IPTC). BMP/GIF pass-through with convert-to-PNG fallback. 16 new tests, 54 total pass.

### P2-005: Search as Nav Tab
- **Objective:** Make Search accessible as a primary nav link rather than only via the search bar
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Search added as third nav link in the header Layout component. Users can navigate directly to the Search page without a pre-existing query.

### WS-005: Frontend MVP
- **Objective:** Upload UI, library browser, search interface
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** React+TS+Vite SPA with dark mode. Auth pages, drag-drop upload, paginated library with auto-polling, media detail with 13 metadata fields, natural language search with scores. 22+ frontend files, file serving endpoint, CORS. 38 backend tests pass. Manual integration test verified.

### WS-004: Auth & API Hardening
- **Objective:** Authentication middleware, API security, error handling, rate limiting, dev/demo mode
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** JWT auth (register/login/me), bcrypt passwords, dev mode fallback, standardized error responses, rate limiting. 3 new auth endpoints. 38 total tests pass (10 new).

### WS-003: Search & Retrieval
- **Objective:** Embedding generation, vector indexing, natural language query, search API endpoint
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Full semantic search pipeline operational. Local sentence-transformer embeddings, ChromaDB vector store, auto-indexing on analysis, user-scoped search with relevance scores. 1 new API endpoint, rebuild script. 28 total tests pass (7 new).

### WS-002: AI Analysis Pipeline
- **Objective:** Vision model integration, metadata extraction, structured output to DB, analysis API endpoints
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** Full AI analysis pipeline operational. Anthropic Claude vision integration with VisionProvider abstraction. MediaMetadata table with 13 ADR-005 fields. Image resize/prep, 3-stage JSON parsing, retry logic. 2 new API endpoints. 21 total tests pass (8 new). Smoke test verified with real API.

### WS-001: Ingestion Pipeline
- **Objective:** File upload, validation, hashing, deduplication, file storage, background task pattern, upload API endpoints
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** Full ingestion pipeline operational. 15 source files, 4 API endpoints, 13 passing integration tests. Implements ADR-001 (SHA256 identity), ADR-003 (normalized entities), ADR-004 (content-addressed storage). Background task pattern ready for WS-002.

### WS-000: Core Foundations
- **Objective:** Prior art extraction from marketing_asset_pipeline, media identity model, metadata schema, storage model, DB schema, project setup, API scaffold
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** All design deliverables produced and approved. 8 ADRs recorded. Ready for WS-001.

<!-- Entry format:
### WS-XXX: [Workstream Name]
- **Objective:** [What this workstream accomplished]
- **Phase:** [Which roadmap phase this belonged to]
- **Started:** [Date]
- **Completed:** [Date]
- **Status:** Completed | Cancelled
- **Outcome:** [Brief summary — detail lives in IMPLEMENTATION_STATUS.md]
-->
