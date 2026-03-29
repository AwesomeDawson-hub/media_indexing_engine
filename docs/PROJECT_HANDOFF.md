# Project Handoff — Media Indexing Engine

_This document bootstraps a new AI session with full project context. Read this first when starting a new session on this project._

_Update this document at the end of every session and at every workstream transition._

## Quick Status

| Field | Value |
|---|---|
| **Current Phase** | Phase 3 — Polish & Production Readiness (P3-001 complete) |
| **Current Workstream** | None — P3-002 through P3-004 planned, awaiting operator go-ahead |
| **Last Completed Work** | P3-001 — UI Polish & API Cleanup (Gallery page, dimensions, AI-title downloads, Source rename, metadata prefix fix) |
| **Next Task** | Operator approves P3-002 start (Database Migrations — Alembic) |
| **Next Step Requested** | Engineer implements P3-002: install Alembic, generate initial migration, integrate into startup |

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

## Open Questions / Blockers

- None. **P3-001 is complete.** Remaining Phase 3 workstreams (P3-002 through P3-004) are planned and awaiting operator approval.

## Document Ownership Note

This document owns **session bootstrap context and handoff state only**. It does not duplicate:
- Project identity or constraints → see `PROJECT_AI_CONTEXT.md`
- Codebase structure → see `PROJECT_MAP.md`
- Development practices → see `PROJECT_PLAYBOOK.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
- System status → see project `docs/CURRENT_STATE.md`
