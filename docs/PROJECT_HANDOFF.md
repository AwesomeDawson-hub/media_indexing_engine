# Project Handoff — Media Indexing Engine

_This document bootstraps a new AI session with full project context. Read this first when starting a new session on this project._

_Update this document at the end of every session and at every workstream transition._

## Quick Status

| Field | Value |
|---|---|
| **Current Phase** | Phase 4 — Beta Operations & Commercial Foundations (**in progress**) |
| **Current Workstream** | None — awaiting P4-004 activation |
| **Last Completed Work** | P4-003 — Source Registry & Source-Aware Media (2026-04-01): sources API, source_id on uploads/media, frontend selector+filter, 115/115 tests, AWS deploy |
| **Next Task** | Activate P4-004 — Admin Console & User Profile Management |
| **Next Step Requested** | Start P4-004 planning |

## Required Reading

Before making any changes, read these documents in order:

1. **This file** — you are here
2. **`docs/PROJECT_AI_CONTEXT.md`** — project identity, constraints, AI behavior rules
3. **Project `docs/CURRENT_STATE.md`** — live project status
4. **Project `docs/WORKSTREAMS.md`** — work tracking

If implementation is underway, also read:
5. **`docs/PROJECT_MAP.md`** — codebase structure
6. **`docs/PROJECT_PLAYBOOK.md`** — safety practices and common tasks

## System Summary

Media Indexing Engine is an AI-powered system that analyzes photos, enriches their metadata using vision AI models, and enables fast semantic search across large media libraries. Users upload images via a web interface; the system automatically processes, tags, and indexes them for natural language retrieval.

### Core Flow

```
Upload (web UI)
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
- Operational limitation remains: public beta is live over temporary HTTP on the EC2 hostname, but full HTTPS beta access is blocked until a real domain is attached.
- Phase 4 is in progress: P4-001, P4-002, and P4-003 are complete. Next workstream is P4-004 (Admin Console & User Profile Management).

## Document Ownership Note

This document owns **session bootstrap context and handoff state only**. It does not duplicate:
- Project identity or constraints → see `PROJECT_AI_CONTEXT.md`
- Codebase structure → see `PROJECT_MAP.md`
- Development practices → see `PROJECT_PLAYBOOK.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
- System status → see project `docs/CURRENT_STATE.md`
