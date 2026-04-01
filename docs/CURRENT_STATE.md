# Current State

This is the live status file for the Media Indexing Engine project. It reflects what is happening **right now**. Read this at the start of every session. Update this at the end of every session and at every workstream transition.

## System Status

| Field | Value |
|---|---|
| **Current Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Active Project** | Media Indexing Engine (`Projects/media_indexing_engine/`) |
| **Active Workstream** | P4-003 — Source Registry & Source-Aware Media (In Progress) |
| **Last Updated** | 2026-04-01 |
| **Updated By** | AI — Engineer (P4-002 closeout) |

## System Health

| Check | Status |
|---|---|
| Docs aligned | Yes |
| Drift detected | No |
| All docs in sync | Yes — verified at Phase 3 planning reconciliation |
| Registry complete | Yes |
| No orphan documents | Yes |
| No duplicate ownership | Yes |
| Test status | 91/91 pass (79 backend integration + 12 S3FileStore unit tests) |
| Active workstream | P4-003 — Source Registry & Source-Aware Media (In Progress) |
| Last governance audit | 2026-03-31 — Pre-Phase-4 Auditor review (0 blocking findings) |

## Recent Activity

- **2026-03-27:** Project "Media Indexing Engine" initialized at `Projects/media_indexing_engine/`. Directory scaffolded, README created. Phase 1 plan created with 6 workstreams (WS-000 through WS-005).
- **2026-03-27:** WS-000 (Core Foundations) completed. Prior art extracted from `marketing_asset_pipeline`. Identity model, metadata schema, storage model, and entity design defined. 8 ADRs recorded (ADR-001 through ADR-008). Next: WS-001 (Ingestion Pipeline).
- **2026-03-27:** Drift resolution — two audit findings fixed. (1) Launcher orphan files: `docs/README.md` and `docs/ai_prompts/consultant_role.md` added to DOCUMENT_REGISTRY.md. (2) PROJECT_HANDOFF.md: corrected references from "Launcher CURRENT_STATE.md/WORKSTREAMS.md" to project-level docs; fixed "Current Task" label to "Next Task".
- **2026-03-27:** WS-001 (Ingestion Pipeline) moved to In Progress. Plan approved. Beginning Step 1.
- **2026-03-27:** WS-001 implementation complete (Steps 1-10). All 13 integration tests pass. Modules: config, database, models, ingestion (validation, hashing, dedup, upload_service, job_manager), storage (file_store), API (app, schemas, dependencies, upload/media routes). PROJECT_MAP updated.
- **2026-03-27:** WS-001 closeout complete. Summary written to IMPLEMENTATION_STATUS.md. Workstream moved to Completed in WORKSTREAMS.md. PROJECT_HANDOFF.md updated. All docs verified consistent.
- **2026-03-27:** WS-002 (AI Analysis Pipeline) moved to In Progress. Plan approved. Beginning Step 1.
- **2026-03-27:** WS-002 implementation complete (Steps 1-10). 8 new analysis tests + 13 existing = 21/21 pass. Modules: analysis (provider, anthropic_provider, mock_provider, image_prep, schemas, processor), API routes (analysis). MediaMetadata model added. Smoke test passed with real Anthropic API.
- **2026-03-27:** WS-002 closeout complete. Summary written to IMPLEMENTATION_STATUS.md. Workstream moved to Completed. All docs verified consistent.
- **2026-03-28:** WS-003 (Search & Retrieval) moved to In Progress. Plan approved. Beginning Step 1.
- **2026-03-28:** WS-003 implementation complete (Steps 1-11). 7 new search tests + 21 existing = 28/28 pass. Modules: search (embedding_text, embedder, models, vector_store, chromadb_store, indexing_service, search_service), API routes (search). Auto-indexing hooked into analysis processor. Rebuild script created. PROJECT_MAP updated.
- **2026-03-28:** WS-003 closeout complete. Summary written to IMPLEMENTATION_STATUS.md. Workstream moved to Completed. All docs verified consistent.
- **2026-03-28:** WS-004 (Auth & API Hardening) moved to In Progress. Plan approved. Beginning Step 1.
- **2026-03-28:** WS-004 implementation complete (Steps 1-11). 10 new auth tests + 28 existing = 38/38 pass. Modules: auth (passwords, tokens), API (auth routes, error_handlers, rate_limit, dependencies updated). JWT auth with dev mode fallback, bcrypt passwords, standardized errors, rate limiting. PROJECT_MAP updated.
- **2026-03-28:** WS-004 closeout complete. Summary written to IMPLEMENTATION_STATUS.md. Workstream moved to Completed. All docs verified consistent.
- **2026-03-28:** WS-005 (Frontend MVP) moved to In Progress. Plan approved. This is the final Phase 1 workstream.
- **2026-03-28:** WS-005 implementation and manual integration test complete. Full React+TS+Vite SPA with dark mode. Auth, upload, library, media detail, search — all working end-to-end.
- **2026-03-28:** WS-005 closeout complete. **Phase 1 — MVP is complete.** All 6 workstreams (WS-000 through WS-005) finished. The full pipeline is operational: register → login → upload → AI analysis → semantic search, with a web UI.
- **2026-03-28:** Post-Phase 1 improvements applied (no formal workstream):
  - Search filters: people toggle, orientation, aspect ratio (7 standard ratios + Other), file type, mood dropdown, sort order (relevance/newest/oldest/largest/smallest)
  - AVIF file support: backend magic-byte detection, config, frontend validation with extension fallback
  - Image dimensions (`width`, `height`) stored on upload for dimension/aspect ratio filtering
  - Upload UX: buttons moved to page header, file queue scrollable
  - Dark mode UI
  - Long filename truncation for Windows MAX_PATH
  - Authenticated image loading via blob URLs
- **2026-03-28:** P2-005 (Search as Nav Tab) implemented. Search added as third nav link in header Layout.
- **2026-03-28:** P2-001 (Metadata Embedder Module) implemented. 8 new files in `src/enrichment/`. Supports JPEG (EXIF+IPTC), WebP (EXIF), AVIF (EXIF), PNG (XMP via iTXt), TIFF (EXIF+IPTC). BMP/GIF pass-through + convert-to-PNG. 16 new tests, 54 total pass.
- **2026-03-28:** P2-002 (Download Endpoints) implemented. 3 new endpoints: `GET /media/{id}/download` (enriched file), `POST /media/download-batch` (ZIP), `POST /media/{id}/convert-png`. BMP/GIF downloads use AI title as filename. 8 new tests, 62 total pass.
- **2026-03-28:** P2-003 (Frontend Download Button) implemented. "Download (with metadata)" on detail page for embeddable formats. BMP/GIF: "Download" + "Convert to PNG with metadata" button. API client: `downloadFile()`, `downloadBatch()`, `convertToPng()`.
- **2026-03-28:** P2-004 (List View + Multi-Select + Batch Download) implemented. Grid/list view toggle on Library and Search pages. List view with checkboxes, "Select all", selection bar with "Download Selected" (ZIP). View preference persisted in localStorage. 3 new components: ViewToggle, MediaListRow, SelectionBar.
- **2026-03-28:** Phase 3 plan produced by Architect. 4 workstreams defined: P3-001 (UI Polish & API Cleanup), P3-002 (Database Migrations), P3-003 (Bulk Operations), P3-004 (Production Deployment). Phase plan at `docs/planning/PHASE_3_polish_production_plan.md`. WORKSTREAMS.md Planned section populated. P3-001 implementation spec at `docs/planning/WS-006_PLAN.md`.
- **2026-03-28:** P3-001 (UI Polish & API Cleanup) implemented and closed out. All 5 changes delivered: metadata comment prefix removed; AI title used as download filename for all formats (explicit `_MIME_TO_EXT` dict); `width`/`height` exposed in API schemas, search route, frontend types, and media detail page; Library + Search merged into unified Gallery page (`GalleryPage.tsx`; `LibraryPage.tsx` and `SearchPage.tsx` deleted; `/search` route removed); UI text "Upload" renamed to "Source" throughout. 62/62 tests pass.

- **2026-03-28:** P3-002 (Database Migrations) implemented and closed out. Alembic 1.14 installed. `alembic/env.py` configured with async SQLAlchemy support (`create_async_engine` + `connection.run_sync()`). Initial migration `cce0c99946e6_initial_schema.py` generated against a fresh DB — creates all 4 tables (users, media_items, media_metadata, processing_jobs) with constraints and indexes. `src/database.py` extended with `run_migrations()` (thread executor to avoid nested event loop). `src/api/app.py` lifespan now calls `run_migrations()` when `settings.app.debug: false`, `create_tables()` otherwise. `alembic upgrade head` validates clean against fresh SQLite. 62/62 tests pass unchanged.

- **2026-03-28:** P3-003 (Bulk Operations) implemented and closed out. `POST /api/v1/media/reanalyze-batch` and `DELETE /api/v1/media/batch` added to `routes/analysis.py` (user-scoped, 50-item cap). `delete_items()` added to `VectorStore` protocol and `ChromaDBVectorStore`; `remove_items()` added to `IndexingService`. `BatchOperationRequest` and response schemas added to `schemas.py`. `SelectionBar.tsx` updated with Re-analyze + Delete buttons (confirm dialog). `GalleryPage.tsx` passes `onDeleteSuccess` callbacks to filter deleted items from local state. `reanalyzeBatch()` and `deleteBatch()` added to `client.ts`. 8 new integration tests; 70/70 tests pass.

- **2026-03-28:** P3-004 (Production Deployment) implemented and closed out. `GET /api/v1/health` returns `{"status":"ok","version":"0.1.0"}` with no auth. `S3FileStore` added to `src/storage/file_store.py` (boto3, thread executor, content-addressed keys). `get_file_store()` factory selects backend by `storage.provider` config or `STORAGE_PROVIDER` env var. `StorageConfig` extended with `s3_bucket`, `s3_region`, `s3_endpoint_url`. Config env override chain extended with `DATABASE_URL`, `STORAGE_PROVIDER`, `S3_BUCKET`, `S3_REGION`. `Dockerfile` (backend), `frontend/Dockerfile` (multi-stage nginx), `docker-compose.yml` (backend + frontend + chromadb + postgres), `.env.example`, and `frontend/nginx.conf` created. README updated with production deployment guide. 12 new S3FileStore unit tests; **82/82 tests pass (Phase 3 total)**. ADR-009, ADR-010, ADR-011 recorded in DECISION_LOG.md. **Phase 3 is complete.**

- **2026-03-29:** Post-Phase-3 bug fixes applied (commit fd5013e, master branch). Three production bugs resolved:
  - **nginx upload limit:** `client_max_body_size` raised from 1M (default) to 50M in `frontend/nginx.conf`. Files >1MB were returning HTTP 413; now uploads up to 50MB work correctly.
  - **Search security fix (defense-in-depth):** `src/search/search_service.py` — added `MediaItem.user_id == user_id` to both DB WHERE clauses in `search_media()`. ChromaDB already filtered by user_id; DB now enforces it independently. 82/82 tests still pass.
  - **Search sort after login:** `frontend/src/pages/GalleryPage.tsx` — `handleSubmit` now calls `doSearch()` directly (no longer relies solely on URL `useEffect`), tracks `lastSubmittedQuery` ref to prevent double-fire, and resets `sort_by` to relevance when switching from browse to search mode. Confirmed working: first search after login now correctly sends relevance-ranked results.
- **2026-03-29:** AWS public beta deployment validated on EC2. Stack deployed to Ubuntu 24.04 EC2 with Docker + Compose using `docker-compose.yml` + `docker-compose.beta.yml`. All services healthy. Because Let's Encrypt cannot issue certificates for the AWS-provided hostname `ec2-13-216-223-46.compute-1.amazonaws.com`, temporary HTTP-only access was configured in `deploy/Caddyfile` for the EC2 hostname. Verified working endpoint: `http://ec2-13-216-223-46.compute-1.amazonaws.com/api/v1/health` → `{"status":"ok","version":"0.1.0"}`. AWS security group and Ubuntu firewall both confirmed open on ports 22/80/443. Normal browser had cached HTTPS/HSTS refusal; site worked in Incognito mode with explicit `http://` URL.
- **2026-03-31:** Phase 4 planning completed from operator beta-readiness feedback. New phase plan created at `docs/planning/PHASE_4_beta_operations_plan.md` with 6 planned workstreams: Gallery UX continuity, plans/quotas, source registry, admin/profile management, billing/commercialization, and OCR search enrichment. Naming/domain selection intentionally excluded from this phase plan per operator direction.
- **2026-03-31:** P4-001 (Gallery & Detail UX Continuity) moved to In Progress. Plan approved. Pre-Phase-4 Auditor review passed with 0 blocking findings.
- **2026-03-31:** P4-001 (Gallery & Detail UX Continuity) completed. All 6 changes delivered: filters always visible; Source button removed from Gallery header; size bucket dimension filter (Small/Medium/Large) wired to backend `min_width`/`max_width`; StatusBadge hides `completed` status; MetadataDisplay split into Metadata + Additional Search Data sections; Back-to-Gallery restores full gallery URL state via React Router location state. 82/82 tests pass. Commit: `e8dedcf`.
- **2026-03-31:** P4-001 post-implementation fixes applied during local + AWS smoke: poll terminal-status allowlist fix (`35ad90d`); Delete button on Media Detail (`90624a5`); Clear Search button in filter panel (`90624a5`); `btn-danger` red CSS (`c113393`); sort order written to URL immediately on change (`311617a`); filter state written to URL immediately on change (`d91975c`). All local and AWS smoke flows pass: filter+page back-nav, search back-nav, sort persistence, delete, Gallery nav link, processing badge auto-clear, Clear Search. P4-001 fully closed.
- **2026-03-31:** P4-002 (Plans, Quotas & Analysis Confirmation) implemented and fully closed. Alembic migration `7a8b9c0d1e2f` (plan_name/monthly_limit on users + quota_events ledger). `QuotaService` with reserve/consume/release + `SELECT FOR UPDATE`. `GET /api/v1/quota/status` endpoint. Upload and re-analysis routes enforce quota; processor consumes/releases. Frontend modal shows plan, period, selected count, used/limit, available, overwrite note, geo note; confirm disabled when exhausted. Structured HTTP 429 with error_code/error/remaining/limit. 5 new quota tests; 91/91 total pass. ADR-013 recorded. Bug fix: batch delete now clears quota_events before media_items (FK constraint). Local + AWS smoke passed. Commits: `c147790`, `6a1d20d`, `5ca5ee6`.

## Blockers

- No application blockers.
- Operational limitation: current beta access is temporary HTTP-only on the EC2 hostname. A real domain is required before restoring HTTPS.

## Known Bugs (Unresolved)

- **Gallery empty after bulk delete of all items on current page:** When the user clicks "Select All" then deletes, only the current page items are deleted (correct). However, the gallery immediately shows the empty-state "no images" message instead of fetching the next page of results. The gallery needs to re-query with the current filters/pagination after a successful batch delete so remaining images on other pages are loaded. Requires a frontend fix in the delete-batch response handler.

## Notes for Next Session

- **P4-002 is fully closed.** Local + AWS smoke both passed. Migration live on AWS postgres. Delete bug (FK constraint on quota_events) fixed and deployed.
- **Next workstream: P4-003** — Source Registry & Source-Aware Media.
- **Most recent commits (newest first):** `5ca5ee6` delete FK fix; `6a1d20d` P4-002 docs closeout; `c147790` P4-002 quota enforcement + tests; `d91975c` filter state to URL; `311617a` sort to URL; `e8dedcf` P4-001.
- **ADR-013** recorded in `docs/DECISION_LOG.md` (reservation ledger semantics).
- **AWS beta is live:** `http://ec2-13-216-223-46.compute-1.amazonaws.com` (HTTP only, temporary — ACME refuses AWS hostname). Stack: `docker-compose.yml` + `docker-compose.beta.yml`. SSH key: `C:\Code\AWS\media-indexing-key.pem`, user `ubuntu`.
- **Before inviting broader beta users:** rotate the exposed `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, and `AUTH_SECRET_KEY`.
- **System is production-deployable:** `docker compose up -d` starts all services. Copy `.env.example` → `.env`, fill secrets.
- **Health endpoint:** `GET /api/v1/health` → `{"status":"ok","version":"0.1.0"}` — no auth required.
- **Schema changes** require `alembic revision --autogenerate` + review + `alembic upgrade head`. Back up the AWS DB before any migration deploy.
- **Codebase:** Python backend (FastAPI, 91 tests) + React/TS frontend (Vite + nginx) + Docker stack (postgres, chromadb, backend, frontend, caddy).
