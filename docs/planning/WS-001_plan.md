# Workstream Plan: WS-001 — Ingestion Pipeline

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-001 |
| **Phase** | Phase 1 — MVP |
| **Project** | Media Indexing Engine |
| **Dependencies** | WS-000 (Core Foundations) — Completed |
| **Estimated Size** | Medium |
| **Created** | 2026-03-27 |
| **Status** | Draft — awaiting operator review |

## Objective

Build the complete file ingestion pipeline: users can upload one or more image files, which are validated, hashed, deduplicated per-user, stored using content-addressed paths, and registered in the database with a background job queued for downstream processing.

## Scope

### In Scope

- Database schema: `users`, `media_items`, and `processing_jobs` tables (per ADR-003)
- File validation: format whitelist, file size limits, basic integrity checks
- SHA256 content hashing (per ADR-001)
- Per-user deduplication: `(user_id, content_hash)` uniqueness (per ADR-001)
- Content-addressed file storage: `{user_id}/{content_hash}/{original_filename}` (per ADR-004)
- Local filesystem storage backend for dev (per ADR-006)
- Single file upload endpoint
- Batch upload endpoint (multiple files in one request)
- Background task pattern using FastAPI BackgroundTasks (lightweight, no external broker for MVP)
- Processing job creation (status tracking for downstream WS-002)
- Upload response model with per-file status (success, duplicate, validation error)

### Out of Scope

- AI analysis of uploaded files (WS-002)
- Vector embeddings or search indexing (WS-003)
- Authentication middleware (WS-004 — WS-001 uses a hardcoded dev user)
- Frontend UI (WS-005)
- S3/cloud storage implementation (dev uses local filesystem; cloud adapter deferred)
- Resumable/chunked uploads (Phase 2 optimization)
- Video file support (deferred per project constraints)

## Constraints

- **Stack:** Python 3.11+, FastAPI, SQLAlchemy (async), SQLite for dev (per ADR-002, ADR-006)
- **Storage:** Local filesystem for dev; content-addressed paths per ADR-004
- **Identity:** SHA256 hex digest + UUID v4 per media item (per ADR-001)
- **Dedup scope:** Per-user, not global (per ADR-001)
- **File size limit:** 50 MB per file (reasonable for high-res photos; configurable)
- **Supported formats:** JPEG, PNG, WebP, TIFF, BMP, GIF (common image formats)
- **Batch limit:** 20 files per request (prevents memory pressure; configurable)
- **No external task queue:** Use FastAPI BackgroundTasks for MVP. Celery/ARQ deferred to scaling phase.

## Governing Decisions

| ADR | Decision | Impact on WS-001 |
|---|---|---|
| ADR-001 | SHA256 content hash as media identity | Hash before storage; dedup check on `(user_id, content_hash)` |
| ADR-002 | Database as sole system of record | All metadata lives in PostgreSQL/SQLite — no sidecar files |
| ADR-003 | Normalized entity model | Implement `users`, `media_items`, `processing_jobs` tables |
| ADR-004 | Content-addressed file storage | Store at `{user_id}/{content_hash}/{original_filename}` |
| ADR-006 | Three-store architecture | Use local filesystem for file storage in dev |
| ADR-007 | Defer review workflow | No approval gates — upload goes straight to processing |

## Database Schema

### `users` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default uuid4 | Internal reference key |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL | Login identity |
| `display_name` | VARCHAR(100) | NOT NULL | Display purposes |
| `created_at` | TIMESTAMP | NOT NULL, default now | |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | |

_Note: Auth fields (password_hash, etc.) are deferred to WS-004. WS-001 seeds a dev user._

### `media_items` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default uuid4 | Internal reference key (API URLs, FKs) |
| `user_id` | UUID | FK → users.id, NOT NULL | Owner |
| `content_hash` | VARCHAR(64) | NOT NULL | SHA256 hex digest |
| `original_filename` | VARCHAR(255) | NOT NULL | Preserved for display |
| `file_size` | BIGINT | NOT NULL | Bytes |
| `mime_type` | VARCHAR(50) | NOT NULL | Detected MIME type |
| `storage_path` | VARCHAR(500) | NOT NULL | Relative path in storage |
| `status` | VARCHAR(20) | NOT NULL, default 'uploaded' | uploaded → processing → completed → error |
| `created_at` | TIMESTAMP | NOT NULL, default now | |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | |

**Unique constraint:** `(user_id, content_hash)` — enforces per-user deduplication at the DB level.

**Index:** `(user_id, content_hash)` — fast dedup lookups.

### `processing_jobs` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default uuid4 | |
| `media_item_id` | UUID | FK → media_items.id, NOT NULL | One job per media item |
| `job_type` | VARCHAR(50) | NOT NULL | 'analysis' for WS-002 |
| `status` | VARCHAR(20) | NOT NULL, default 'pending' | pending → running → completed → failed |
| `error_message` | TEXT | NULLABLE | Error details if failed |
| `attempts` | INTEGER | NOT NULL, default 0 | Retry tracking |
| `created_at` | TIMESTAMP | NOT NULL, default now | |
| `started_at` | TIMESTAMP | NULLABLE | When processing began |
| `completed_at` | TIMESTAMP | NULLABLE | When processing finished |

**Index:** `(status)` — fast queue polling for pending jobs.

## File Storage Layout

Per ADR-004, files are stored at content-addressed paths:

```
uploads/                          ← configurable root (settings.yaml → storage.local_path)
└── {user_id}/
    └── {content_hash}/
        └── {original_filename}   ← original name preserved on disk
```

Example:
```
uploads/a1b2c3d4-.../e5f6a7b8.../sunset_beach.jpg
```

## API Endpoints

### `POST /api/v1/upload`

Upload a single file.

**Request:** `multipart/form-data` with one file field.

**Response (201):**
```json
{
  "id": "uuid",
  "content_hash": "sha256hex",
  "original_filename": "photo.jpg",
  "file_size": 2048576,
  "mime_type": "image/jpeg",
  "status": "uploaded",
  "is_duplicate": false,
  "created_at": "2026-03-27T12:00:00Z"
}
```

**Response (200, duplicate):**
```json
{
  "id": "existing-uuid",
  "content_hash": "sha256hex",
  "original_filename": "photo.jpg",
  "status": "uploaded",
  "is_duplicate": true,
  "message": "File already exists in your library"
}
```

**Error responses:**
- `400` — Invalid file format or exceeds size limit
- `422` — Missing file field

### `POST /api/v1/upload/batch`

Upload multiple files in one request.

**Request:** `multipart/form-data` with multiple file fields.

**Response (200):**
```json
{
  "total": 5,
  "successful": 3,
  "duplicates": 1,
  "failed": 1,
  "results": [
    { "filename": "a.jpg", "status": "created", "id": "uuid", "content_hash": "..." },
    { "filename": "b.jpg", "status": "duplicate", "id": "existing-uuid" },
    { "filename": "c.pdf", "status": "error", "error": "Unsupported file format" }
  ]
}
```

### `GET /api/v1/media`

List media items for the current user (paginated).

**Query params:** `page` (default 1), `per_page` (default 20), `status` (optional filter).

**Response (200):**
```json
{
  "items": [ { "id": "...", "original_filename": "...", "status": "...", ... } ],
  "total": 42,
  "page": 1,
  "per_page": 20
}
```

### `GET /api/v1/media/{id}`

Get a single media item by ID.

**Response:** Full media_item record (same shape as upload response, plus `storage_path` omitted from public API).

## Upload Flow (Single File)

```
Client sends file
    │
    ▼
1. Validate format (MIME type check against whitelist)
2. Validate size (reject if > 50 MB)
    │
    ▼
3. Read file bytes, compute SHA256 hash
    │
    ▼
4. Query DB: SELECT WHERE user_id = ? AND content_hash = ?
    │
    ├── EXISTS → Return 200 with existing record, is_duplicate: true
    │
    └── NOT EXISTS ─▼
                    5. Write file to content-addressed path
                    6. INSERT media_item (status: 'uploaded')
                    7. INSERT processing_job (status: 'pending', type: 'analysis')
                    8. Enqueue background task (placeholder — actual analysis is WS-002)
                    9. Return 201 with new record
```

## Batch Upload Flow

```
Client sends N files (max 20)
    │
    ▼
For each file (sequentially to control memory):
    1. Validate format and size
    2. If invalid → record error in results, skip to next
    3. Compute SHA256 hash
    4. Check dedup
    5. If duplicate → record duplicate in results, skip to next
    6. Store file, create DB records, enqueue job
    7. Record success in results
    │
    ▼
Return aggregated results
```

_Note: Files are processed sequentially within a batch request to keep memory bounded. Parallelism happens at the request level (multiple users uploading concurrently)._

## Background Task Pattern

WS-001 establishes the background task pattern that WS-002 will use for AI analysis:

1. **Processing job created** in DB with status `pending` during upload.
2. **Background task dispatched** via `FastAPI BackgroundTasks` after upload response is sent.
3. **Placeholder processor** in WS-001 — simply logs that a job exists. WS-002 replaces this with actual AI analysis.
4. **Job status transitions:** `pending` → `running` → `completed` | `failed`.
5. **Retry tracking:** `attempts` column incremented on each run. Max attempts configurable (default 3).

This pattern gives WS-002 a clean contract: pick up `pending` jobs, do analysis, update status.

## Implementation Steps

Each step has a validation checkpoint. Do not proceed to the next step until the current step's validation passes.

### Step 1: Project Dependencies and Configuration

**What:** Set up pyproject.toml (or requirements.txt), install FastAPI, SQLAlchemy, Uvicorn, python-multipart, aiofiles. Create settings loader from settings.yaml.

**Files:**
- `pyproject.toml` (project root)
- `src/config.py` — settings loader (reads settings.yaml, provides typed config)

**Validation:**
- [ ] `uvicorn` starts without errors
- [ ] Config loads from `settings.yaml` (copy from `settings.example.yaml`)
- [ ] Import paths work: `from src.config import settings`

### Step 2: Database Models and Migration

**What:** Define SQLAlchemy async models for `users`, `media_items`, `processing_jobs`. Create database engine, session factory, and table creation utility. Seed a dev user.

**Files:**
- `src/database.py` — engine, session factory, base model, table creation
- `src/models.py` — User, MediaItem, ProcessingJob ORM models
- `scripts/seed_dev_user.py` — creates a dev user for testing (or auto-seed on startup in dev mode)

**Validation:**
- [ ] Tables created in SQLite on startup
- [ ] Dev user exists in `users` table
- [ ] `(user_id, content_hash)` unique constraint enforced on `media_items`
- [ ] Foreign keys work: `media_items.user_id` → `users.id`, `processing_jobs.media_item_id` → `media_items.id`

### Step 3: File Validation Module

**What:** Create a validation module that checks MIME type against the whitelist and file size against the configured limit.

**Files:**
- `src/ingestion/validation.py` — `validate_file(file) → ValidationResult`

**Supported MIME types:**
- `image/jpeg`, `image/png`, `image/webp`, `image/tiff`, `image/bmp`, `image/gif`

**Validation:**
- [ ] Valid JPEG accepted
- [ ] Invalid format (e.g., PDF) rejected with clear error message
- [ ] Oversized file rejected with clear error message
- [ ] MIME type detected from file content (not just extension)

### Step 4: Hashing and Deduplication

**What:** Create the hashing module (SHA256 of raw bytes) and dedup check (query DB for existing `(user_id, content_hash)`).

**Files:**
- `src/ingestion/hashing.py` — `compute_sha256(file_bytes) → str`
- `src/ingestion/dedup.py` — `check_duplicate(db, user_id, content_hash) → Optional[MediaItem]`

**Validation:**
- [ ] Same file produces same hash across runs
- [ ] Different files produce different hashes
- [ ] Dedup check returns existing record when `(user_id, content_hash)` match exists
- [ ] Dedup check returns None when no match
- [ ] Same file uploaded by different users is NOT flagged as duplicate (per-user scope)

### Step 5: File Storage Service

**What:** Create the storage service that writes files to content-addressed paths on the local filesystem. Abstract behind an interface so WS-006 or later can swap in S3.

**Files:**
- `src/storage/file_store.py` — `FileStore` interface + `LocalFileStore` implementation
  - `save(user_id, content_hash, original_filename, file_bytes) → storage_path`
  - `exists(storage_path) → bool`
  - `delete(storage_path) → None`

**Storage path:** `{configured_root}/{user_id}/{content_hash}/{original_filename}`

**Validation:**
- [ ] File saved to correct content-addressed path
- [ ] File content on disk matches original bytes
- [ ] Parent directories created automatically
- [ ] `exists()` returns True for saved file, False for missing
- [ ] Path uses forward slashes (normalized)

### Step 6: Upload Service (Core Business Logic)

**What:** Create the upload service that orchestrates the full flow: validate → hash → dedup check → store → create DB records → enqueue job. This is the core logic that both the single and batch endpoints call.

**Files:**
- `src/ingestion/upload_service.py` — `UploadService`
  - `process_upload(db, user_id, file) → UploadResult`
  - `process_batch(db, user_id, files) → BatchUploadResult`

**Validation:**
- [ ] New file: validated, hashed, stored, media_item created, processing_job created
- [ ] Duplicate file: detected, existing record returned, no file written, no job created
- [ ] Invalid file: rejected with error, no side effects
- [ ] Batch: mix of new, duplicate, and invalid files handled correctly in one call
- [ ] Database transaction: if storage fails after DB insert, records are rolled back

### Step 7: FastAPI Application and Upload Endpoints

**What:** Create the FastAPI app, wire up the database lifecycle, and implement the upload endpoints. Use a hardcoded dev user ID for now (auth comes in WS-004).

**Files:**
- `src/api/app.py` — FastAPI app creation, lifespan (DB init), middleware
- `src/api/routes/upload.py` — `POST /api/v1/upload`, `POST /api/v1/upload/batch`
- `src/api/routes/media.py` — `GET /api/v1/media`, `GET /api/v1/media/{id}`
- `src/api/schemas.py` — Pydantic response models (UploadResponse, BatchUploadResponse, MediaItemResponse, PaginatedResponse)
- `src/api/dependencies.py` — DB session dependency, dev user dependency

**Validation:**
- [ ] `POST /api/v1/upload` with valid JPEG → 201, file stored, DB records created
- [ ] `POST /api/v1/upload` with same file again → 200, `is_duplicate: true`
- [ ] `POST /api/v1/upload` with PDF → 400, clear error
- [ ] `POST /api/v1/upload/batch` with mixed files → 200, per-file results
- [ ] `GET /api/v1/media` → paginated list of uploaded items
- [ ] `GET /api/v1/media/{id}` → single item detail
- [ ] `GET /api/v1/media/{bad-id}` → 404

### Step 8: Background Task Integration

**What:** Wire up FastAPI BackgroundTasks to dispatch a placeholder task after successful upload. Create the processing job manager that WS-002 will extend.

**Files:**
- `src/ingestion/job_manager.py` — `enqueue_processing(db, media_item_id)` creates job record, `placeholder_processor(job_id)` logs and updates status

**Validation:**
- [ ] After upload, a `processing_job` record exists with status `pending`
- [ ] Background task runs (visible in logs)
- [ ] Job status transitions: `pending` → `running` → `completed` (placeholder just marks complete)
- [ ] Multiple uploads create independent jobs

### Step 9: Integration Testing

**What:** End-to-end tests that exercise the full upload flow through the API.

**Files:**
- `tests/test_upload.py` — single upload, batch upload, dedup, validation errors
- `tests/test_media.py` — list, detail, pagination, 404
- `tests/conftest.py` — test client, test DB, fixtures

**Test cases:**
- [ ] Upload valid image → 201, file on disk, DB records exist
- [ ] Upload duplicate → 200, `is_duplicate: true`, no new file
- [ ] Upload invalid format → 400
- [ ] Upload oversized file → 400
- [ ] Batch upload with mixed results → correct per-file statuses
- [ ] List media → paginated, correct count
- [ ] Get media by ID → correct record
- [ ] Get missing ID → 404
- [ ] Dedup is per-user (same file, different users → both stored)
- [ ] Processing job created for each new upload

### Step 10: PROJECT_MAP Update

**What:** Update `docs/PROJECT_MAP.md` with the implemented module responsibilities and data model.

**Validation:**
- [ ] `src/ingestion/` module documented with file list and responsibilities
- [ ] `src/storage/` module documented
- [ ] `src/api/` module documented (routes added in this workstream)
- [ ] Data Model table populated with `users`, `media_items`, `processing_jobs`

## Module Dependency Graph

```
src/config.py           ← settings loader (no dependencies)
src/database.py         ← engine, sessions (depends on config)
src/models.py           ← ORM models (depends on database)
src/ingestion/
  validation.py         ← format + size checks (depends on config)
  hashing.py            ← SHA256 (no dependencies)
  dedup.py              ← DB lookup (depends on models)
  upload_service.py     ← orchestrator (depends on validation, hashing, dedup, file_store, models)
  job_manager.py        ← job creation + placeholder (depends on models)
src/storage/
  file_store.py         ← file I/O (depends on config)
src/api/
  app.py                ← FastAPI app (depends on database, config)
  schemas.py            ← Pydantic models (no dependencies)
  dependencies.py       ← DI providers (depends on database, models)
  routes/
    upload.py           ← upload endpoints (depends on upload_service, schemas, dependencies)
    media.py            ← media endpoints (depends on models, schemas, dependencies)
```

## Exit Criteria

All of the following must be true to close WS-001:

- [ ] Database tables `users`, `media_items`, `processing_jobs` created and functional
- [ ] Single file upload works end-to-end (validate → hash → dedup → store → DB → job)
- [ ] Batch upload works with per-file status reporting
- [ ] Duplicate detection works per-user via `(user_id, content_hash)`
- [ ] Files stored at content-addressed paths per ADR-004
- [ ] Background processing job created for each new upload
- [ ] `GET /api/v1/media` returns paginated list
- [ ] `GET /api/v1/media/{id}` returns single item
- [ ] All integration tests pass
- [ ] No files created inside the launcher repo
- [ ] `PROJECT_MAP.md` updated with new modules
- [ ] Closeout checklist completed

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Large batch uploads consume too much memory | Medium | Process files sequentially within a batch; enforce 20-file limit |
| SHA256 hashing is slow for large files | Low | 50 MB files hash in <1s on modern hardware; chunked read if needed |
| SQLite async limitations | Low | Use aiosqlite; move to PostgreSQL for prod (already planned) |
| File storage race condition on concurrent uploads | Low | Content-addressed paths are deterministic — same path = same content |

## Notes

- WS-001 uses a **hardcoded dev user** for all API calls. WS-004 replaces this with real auth.
- The `media_metadata` table (ADR-003's fourth table) is NOT created in WS-001. It belongs to WS-002 (AI Analysis) which defines its columns based on the metadata schema (ADR-005).
- The background task placeholder does not perform AI analysis — it just proves the pattern works. WS-002 fills in the real processor.
- The storage interface (`FileStore`) is intentionally abstract so a future S3 implementation can be dropped in without changing upstream code.
