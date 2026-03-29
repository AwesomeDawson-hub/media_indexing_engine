# Phase Plan: Phase 3 — Polish & Production Readiness

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 3 — Polish & Production Readiness |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 2 complete (P2-001 through P2-005 delivered) |
| **Estimated Size** | Medium-Large (4 workstreams) |
| **Created** | 2026-03-28 |
| **Status** | Draft — awaiting operator review and workstream approval |

---

## Objective

Phase 3 brings the Media Indexing Engine from a functional MVP to a polished, production-deployable system. It has two tracks that run in sequence:

1. **Polish track** — resolve UI debt and inconsistencies accumulated across Phase 1 and 2: unify the Gallery, expose missing data (image dimensions), fix download filenames, and clean up naming.
2. **Production track** — add the infrastructure required for a real deployment: database migrations to replace the drop-and-recreate schema workflow, bulk operations that leverage the existing multi-select UI, and a Docker-based deployment stack with S3-compatible storage.

Phase 3 does not introduce new AI capabilities or new user-facing features beyond what is described here.

---

## Scope

### In Scope
- Gallery page (merged Library + Search) with filtering, sorting, and multi-select in a single surface
- Image dimensions (width × height) exposed in all API responses and the media detail page
- AI title used as download filename for all formats (not original camera filenames)
- Metadata comment prefix cleanup (remove "AI-generated description:" from embedded EXIF UserComment)
- "Upload" renamed to "Source" in all user-facing text
- Alembic database migration framework with initial migration from the current schema
- Bulk re-analysis and bulk delete endpoints, integrated with the Gallery multi-select UI
- Production deployment: S3-compatible file storage backend, Docker/docker-compose, PostgreSQL validation, health endpoint

### Out of Scope
- Cloud source integrations (Google Drive, Dropbox, SD card — deferred)
- Video analysis (deferred)
- Subscription/billing system
- Custom AI model training
- Admin dashboard beyond the health endpoint
- Multi-tenant or multi-organization features

---

## Constraints

All Phase 1 and 2 constraints apply. Additionally for Phase 3:

- Do not break backward compatibility on any existing API endpoints (URLs and response schemas must remain stable; new fields may be added)
- Every schema change from P3-002 onward must be handled by an Alembic migration (the drop-and-recreate pattern is retired after P3-002)
- Docker images must not embed credentials — all secrets via environment variables only
- P3-004 must support local dev with local filesystem + SQLite; Docker replaces that with S3 + PostgreSQL but does not remove the local path

---

## ID Scheme

Phase 3 workstreams use the **`P3-XXX`** prefix, consistent with Phase 2's `P2-XXX` convention.

> **Note on WS-006:** A detailed workstream plan (`docs/planning/WS-006_PLAN.md`) was drafted before the phase boundary was formally set. That plan is adopted verbatim as the implementation spec for P3-001. The file is kept at its original path as a historical artifact; `P3-001` is the official workstream ID in WORKSTREAMS.md and all governance documents.

---

## Workstreams

| ID | Name | Objective | Dependencies | Size |
|---|---|---|---|---|
| P3-001 | UI Polish & API Cleanup | Merge Library+Search into Gallery, fix download filenames, expose dimensions, Source rename | Phase 2 complete | M |
| P3-002 | Database Migrations | Alembic framework, initial migration, startup integration | Phase 2 complete | S |
| P3-003 | Bulk Operations | Bulk re-analyze and bulk delete API endpoints, integrated with Gallery multi-select | P3-001 complete | S-M |
| P3-004 | Production Deployment | S3 file storage, Docker + docker-compose, PostgreSQL validation, health endpoint | P3-002 complete | M-L |

---

## Workstream Sequencing

```
Phase 2 complete
      │
      ├──▶ P3-001 (UI Polish)         ──────────────▶ P3-003 (Bulk Operations)
      │                                                       │
      └──▶ P3-002 (Migrations)        ──────────────▶ P3-004 (Production)
                                                             │
                                                        Phase 3 complete
```

**P3-001 and P3-002** are independent for planning purposes, but per the launcher workflow only one workstream should be In Progress at a time unless the operator explicitly approves parallel execution. The recommended implementation order is P3-001 first (it produces the Gallery page that P3-003 extends) and then P3-002.

**P3-003** depends on P3-001 being complete because it adds bulk action buttons to the Gallery multi-select UI surface created in P3-001.

**P3-004** depends on P3-002 being complete because running Alembic migrations is a prerequisite for production deployment (you cannot ship a "drop and recreate on startup" system to prod).

---

## Workstream Definitions

### P3-001: UI Polish & API Cleanup

**Objective:** Five targeted improvements that clean up inconsistencies accumulated across Phase 1 and 2.

**Changes (see `docs/planning/WS-006_PLAN.md` for full implementation spec):**

1. **Fix metadata comment prefix** — Remove "AI-generated description:" prefix from `build_user_comment()` in `src/enrichment/field_mapping.py`. The description should stand alone.
2. **Use AI title for all download filenames** — `download_file()` and `download_batch()` in `src/api/routes/download.py` currently only use the AI title for BMP/GIF. All formats should use the AI-generated title (sanitized) as the download filename.
3. **Expose image dimensions** — `width` and `height` exist in the `media_items` DB table but are absent from API response schemas, frontend types, and the media detail page. Add to `MediaItemResponse`, `SearchMediaItem`, the search service `SearchResultItem` dataclass, frontend types, and the media detail page UI.
4. **Merge Library + Search into Gallery** — Replace `LibraryPage.tsx` and `SearchPage.tsx` with a unified `GalleryPage.tsx`. Browse mode (no query): calls `GET /api/v1/media` with filters. Search mode (query active): calls `GET /api/v1/search`. The `GET /api/v1/media` endpoint gains the same filter/sort params as search. URL reflects state via query params.
5. **Rename Upload → Source** — Change nav link text and page heading from "Upload" to "Source" in all user-facing text. The route `/upload` and API endpoints are unchanged.

**Exit criteria:** All existing tests pass. New tests cover dimensions in API and expanded media filter endpoint. `SearchPage.tsx` and `LibraryPage.tsx` deleted. `PROJECT_MAP.md` updated.

**Key architectural notes:**
- The `GET /api/v1/media` filter expansion requires joining `media_metadata`; the join should be a LEFT OUTER JOIN so media items without analysis results remain visible in browse mode.
- Gallery route is `/` (root). The `/search` route can 404 or redirect to `/?q=` — no old URL preservation required per MVP philosophy.
- The Gallery page's localStorage key for view preference must be distinct from the old per-page keys to avoid stale state.

---

### P3-002: Database Migrations

**Objective:** Replace the drop-and-recreate schema management pattern with Alembic migrations, so the schema can evolve without losing data.

**Context:** Currently, `src/database.py` creates all tables at startup (`metadata.create_all()`). Any schema change requires manually deleting the database file and restarting. This is acceptable for development but incompatible with production. P3-002 installs Alembic and creates the initial migration that represents the current schema.

**Implementation steps:**

1. Add `alembic` to `pyproject.toml` dependencies.
2. Run `alembic init alembic` to scaffold the migrations directory at project root.
3. Configure `alembic/env.py` to import `declarative_base` from `src/database.py` and read the database URL from `config/settings.yaml` (or `DATABASE_URL` env var for prod).
4. Generate the initial migration with `alembic revision --autogenerate -m "initial_schema"`. Review and clean the generated migration to remove autogenerate noise (index name formatting, etc.).
5. Update `src/database.py`: in production mode, run `alembic upgrade head` at startup instead of `metadata.create_all()`. In dev mode (or test mode), keep `create_all()` for speed.
6. Update `tests/conftest.py`: tests use in-memory SQLite with `create_all()` directly — this must remain unchanged (Alembic is for the real database, not tests).
7. Add `alembic/` to `.gitignore` exclusions that should be committed (the `versions/` folder must be tracked).
8. Update `README.md` with migration instructions: how to apply migrations on first run, how to create new migrations after schema changes.

**Constraints:**
- Tests continue to use `create_all()` on in-memory SQLite. Alembic is not invoked during tests.
- The migration must be idempotent (safe to run twice).
- The `DATABASE_URL` env var overrides the YAML config for Alembic in production.

**Exit criteria:** `alembic upgrade head` runs cleanly against a fresh SQLite DB and produces the expected schema. Existing 62 tests still pass. README updated with migration instructions.

---

### P3-003: Bulk Operations

**Objective:** Enable users to re-analyze multiple items and delete multiple items using the Gallery's existing multi-select UI.

**Context:** P2-004 added list view with checkboxes and a selection bar. P3-001 merges this into the Gallery. P3-003 extends the selection bar with two new actions: "Re-analyze Selected" and "Delete Selected." These require new backend endpoints.

**Backend changes:**

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `POST /api/v1/media/reanalyze-batch` | POST | `{"media_ids": ["uuid1", "uuid2"]}` | Enqueues background re-analysis jobs for each ID. Returns a count of queued items. |
| `DELETE /api/v1/media/batch` | DELETE | `{"media_ids": ["uuid1", "uuid2"]}` | Deletes media items, their metadata, their files from storage, and their vector embeddings. Returns a count of deleted items. |

**Constraints and rules:**
- Both endpoints are user-scoped — only the requesting user's media can be re-analyzed or deleted.
- Batch size cap: 50 items per request (consistent with `download-batch` cap).
- `DELETE /media/batch` must clean up all layers: DB rows (cascade deletes via FK), physical file (`LocalFileStore.delete()`), vector embeddings (`VectorStore.delete(ids=[...])`). If any layer fails, log the error but continue deleting the rest (best-effort cleanup).
- `LocalFileStore` needs a `delete()` method (not currently implemented). Add `delete(user_id, content_hash, original_filename)` that removes the file and the hash directory if empty.
- `ChromaDBVectorStore` needs a `delete_items(media_ids, user_id)` method. ChromaDB supports `collection.delete(where={"media_id": {"$in": [...]}})`.
- Re-analysis batch: each item is dispatched as a `BackgroundTask` (same pattern as single re-analyze). No polling mechanism needed in MVP — the Gallery's existing auto-poll for processing status covers it.

**Frontend changes:**
- `SelectionBar.tsx`: add "Re-analyze" button (calls `reanalyzeBatch()` API client method) and "Delete" button (calls `deleteBatch()` with a confirmation dialog).
- `frontend/src/api/client.ts`: add `reanalyzeBatch(mediaIds: string[])` and `deleteBatch(mediaIds: string[])`.
- On delete: clear the selection, remove deleted items from the local state, and show a brief toast/inline confirmation.
- Confirmation dialog on delete: "Delete X items? This cannot be undone." (browser `window.confirm()` is acceptable for MVP).

**Exit criteria:** 
- `POST /media/reanalyze-batch` queues re-analysis for valid owned items. Items transition to processing status. Gallery auto-poll picks them up.
- `DELETE /media/batch` removes items from DB, filesystem, and vector index. Deleted items no longer appear in the Gallery.
- At least 6 new integration tests: batch re-analyze (success, empty body, unauthorized IDs), batch delete (success, unauthorized IDs, cleans up files).
- Existing 62 tests still pass.

---

### P3-004: Production Deployment

**Objective:** Make the Media Indexing Engine deployable to a real server. Implement S3-compatible file storage, validate PostgreSQL end-to-end, add a Docker + docker-compose stack, and add a health check endpoint.

**Context:** The `FileStore` interface exists (ADR-004) but only `LocalFileStore` is implemented. ADR-006 designated S3-compatible storage as the production target. P3-002 provides the Alembic migrations required before any production database.

**Implementation steps:**

**Step 1: Health endpoint**
- `GET /api/v1/health` — returns `{"status": "ok", "version": "..."}`. No auth required. Checked by Docker health check. Minimal: this is a readiness probe, not a full system check.

**Step 2: S3FileStore**
- Implement `S3FileStore` in `src/storage/file_store.py` using the `boto3` library.
- Same interface as `LocalFileStore`: `store(user_id, content_hash, filename, data) → path`, `read(path) → bytes`, `delete(user_id, content_hash, filename)`.
- Storage path: `s3://{bucket}/{user_id}/{content_hash}/{filename}` — same content-addressed structure as local.
- Configuration: `storage.backend: local | s3`. When `s3`, requires `storage.s3_bucket`, `storage.s3_region`. AWS credentials from environment (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) — never in config files.
- `src/api/app.py` instantiates the correct `FileStore` implementation based on config.

**Step 3: PostgreSQL validation**
- `config/settings.yaml` has a `database.url` field. Validate that the async PostgreSQL driver (`asyncpg`) is in `pyproject.toml` as an optional dependency.
- Add `config/settings.production.yaml` (template, not committed with secrets) documenting all required env var overrides.
- Integration test: add a CI note that tests run against SQLite; PostgreSQL is validated manually against the Docker stack.

**Step 4: Docker + docker-compose**
- `Dockerfile` for the backend: Python 3.11 base image, install dependencies, copy source, expose port 8000, run `alembic upgrade head && uvicorn src.api.app:app`.
- `Dockerfile` for the frontend: multi-stage build (Node for `npm run build`, then nginx to serve the static `dist/`).
- `docker-compose.yml`: services — `backend`, `frontend`, `chromadb` (official ChromaDB Docker image), `postgres` (official `postgres:16` image). Environment variables for all secrets (no defaults for `AUTH_SECRET_KEY`, `ANTHROPIC_API_KEY`).
- `.env.example`: template with all required env vars and safe placeholder values.
- `docker-compose.yml` maps `./uploads/` volume for local file storage (dev fallback) and `./chromadb_data/` for ChromaDB persistence.

**Step 5: README update**
- Add "Production Deployment" section documenting: copy `.env.example` → `.env`, fill in secrets, `docker compose up -d`.
- Add "Database Migrations" section: `docker compose exec backend alembic upgrade head`.

**Constraints:**
- `LocalFileStore` remains the default (`storage.backend: local`). Docker stack uses `local` for dev, `s3` for prod. No forced migration.
- Do not commit any `.env` files. `.gitignore` already covers this; double-check.
- The frontend Dockerfile builds a static bundle — no Node.js runtime in production.

**Exit criteria:**
- `GET /api/v1/health` returns 200 with `{"status": "ok"}`.
- `docker compose up` starts all services without errors.
- A manual end-to-end smoke test (register → upload → analyze → search) passes against the Docker stack.
- `S3FileStore` is implemented and covered by unit tests with a mocked `boto3` client.
- `README.md` has a working production deployment guide.

---

## Phase 3 Exit Criteria

Phase 3 is complete when all four workstreams are closed and:

- [ ] Gallery page replaces Library and Search. Browsing and searching work from one surface.
- [ ] `width` and `height` appear in all API responses and the media detail page.
- [ ] AI-generated titles are used as download filenames for all formats.
- [ ] "Upload" → "Source" in all user-facing text.
- [ ] `alembic upgrade head` applies the full schema cleanly to a fresh database.
- [ ] Bulk re-analyze and bulk delete work from the Gallery selection bar.
- [ ] `docker compose up` starts a fully functional system.
- [ ] `GET /api/v1/health` returns 200.
- [ ] All backend tests (target: ≥75 after P3-001 and P3-003 additions) pass.
- [ ] `PROJECT_MAP.md` is updated to reflect any new modules.

---

## Architectural Decisions to Record at Phase 3 Start

The following decisions are established by this plan. ADR entries should be written to `DECISION_LOG.md` when each workstream begins (per the Architect role's responsibilities):

- **ADR-009 (P3-002):** Alembic for schema migrations — context: drop-and-recreate is not viable for prod; decision: Alembic with `upgrade head` at startup; consequence: tests remain on `create_all()`.
- **ADR-010 (P3-004):** S3FileStore as production storage backend — context: ADR-006 designated S3-compatible storage as prod target; decision: implement via boto3 with env-var credentials; consequence: local dev is unchanged, prod switches via config.
- **ADR-011 (P3-004):** Docker + docker-compose as delivery mechanism — context: multi-service system (backend, frontend, ChromaDB, PostgreSQL) needs a container orchestration approach; decision: docker-compose for simplicity; consequence: no Kubernetes support in V1.
