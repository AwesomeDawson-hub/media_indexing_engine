# Project Map — Media Indexing Engine

_This document describes the structure of the codebase for developers and AI assistants. It is the authoritative reference for what each module does and where to find it._

_Update this document whenever modules are added, removed, or their responsibilities change._

## Repository Structure

```
media_indexing_engine/
├── src/
│   ├── ingestion/       → File intake, validation, deduplication
│   ├── analysis/        → AI vision model integration, metadata extraction
│   ├── enrichment/      → Metadata embedding into image file headers
│   ├── search/          → Semantic search and query processing
│   ├── storage/         → Cloud storage and metadata persistence
│   ├── api/             → REST API layer
│   ├── auth/            → JWT and password utilities
│   └── utils/           → Shared utilities
├── alembic/             → Database migration scripts (Alembic) — P3-002
│   └── versions/        → Migration files (tracked in version control)
├── tests/               → Test suite
├── config/              → Configuration files
├── docs/                → Project-specific documentation
├── scripts/             → Automation and utility scripts
├── frontend/            → Web UI
│   ├── Dockerfile       → Multi-stage build: Node.js compile + nginx serve — P3-004
│   └── nginx.conf       → nginx SPA config + /api/ proxy to backend — P3-004
├── Dockerfile           → Backend container image (Python 3.11, uvicorn) — P3-004
├── docker-compose.yml   → Full stack orchestration (backend, frontend, chromadb, postgres) — P3-004
├── .env.example         → Environment variable template (no secrets) — P3-004
├── alembic.ini          → Alembic configuration (URL set dynamically in env.py) — P3-002
└── README.md
```

## Core Modules

### src/config.py

**Workstream:** WS-001
**Responsibilities:**
- Load settings from `config/settings.yaml`
- Provide typed configuration dataclasses (AppConfig, StorageConfig, DatabaseConfig, UploadConfig, ProcessingConfig, AnalysisConfig, SearchConfig, AuthConfig)

### src/database.py

**Workstream:** WS-001
**Responsibilities:**
- SQLAlchemy async engine and session factory
- Table creation/drop utilities (`create_tables()`, `drop_tables()`) for dev/test
- `run_migrations()` — runs `alembic upgrade head` in a thread executor for production startup (**P3-002**)
- DeclarativeBase for ORM models

### src/models.py

**Workstream:** WS-001
**Responsibilities:**
- ORM models: User, MediaItem, ProcessingJob, MediaMetadata
- Unique constraint `(user_id, content_hash)` on media_items
- FK relationships between all entities

### src/ingestion/

**Location:** `src/ingestion/`
**Workstream:** WS-001
**Files:**
- `validation.py` — File format (magic-byte MIME detection) and size validation
- `hashing.py` — SHA256 content hashing
- `dedup.py` — Per-user `(user_id, content_hash)` duplicate check
- `upload_service.py` — Orchestrator: validate → hash → dedup → store → DB records → enqueue job
- `job_manager.py` — Pending job queries (placeholder processor removed in WS-002)

### src/storage/

**Location:** `src/storage/`
**Workstream:** WS-001 (LocalFileStore), P3-004 (S3FileStore + factory)
**Files:**
- `file_store.py` — `FileStore` abstract interface; `LocalFileStore` (content-addressed paths, `delete()` via P3-003); `S3FileStore` (boto3, thread executor, same content-addressed key structure, optional `s3_endpoint_url` for MinIO compatibility — **P3-004**); `get_file_store(storage_config)` factory function selects implementation based on `storage.provider` config (`"local"` or `"s3"`) (**P3-004**)

### src/api/

**Location:** `src/api/`
**Workstream:** WS-001 (scaffold), WS-004 (hardening)
**Files:**
- `app.py` — FastAPI app creation, lifespan (DB init: `create_tables()` in dev, `run_migrations()` in prod — **P3-002**; dev user seed), router registration
- `schemas.py` — Pydantic response models (UploadResponse, BatchUploadResponse, MediaItemResponse, PaginatedResponse); `MediaItemResponse` and `SearchMediaItem` include `width`/`height` fields (**P3-001**); `BatchOperationRequest` (validated 1–50 `media_ids`), `BatchReanalyzeResponse`, `BatchDeleteResponse` (**P3-003**)
- `dependencies.py` — DB session dependency + JWT auth dependency (`get_current_user_id` with dev mode fallback)
- `error_handlers.py` — Standardized error response format (`detail` + `error_code`)
- `rate_limit.py` — In-memory sliding window rate limiter for auth endpoints
- `routes/upload.py` — `POST /api/v1/upload`, `POST /api/v1/upload/batch` (dispatches analysis via mock/real provider)
- `routes/media.py` — `GET /api/v1/media` (full filter+sort: `has_people`, `orientation`, `mood`, `mime_type`, `min/max_width/height`, `aspect_ratio`, `tags`, `sort_by`; metadata-based filters JOIN `MediaMetadata`; aspect ratio uses post-query Python filtering via `_matches_aspect_ratio()`), `GET /api/v1/media/{id}`, `GET /api/v1/media/{id}/file` (**P3-001**)
- `routes/analysis.py` — `GET /api/v1/media/{id}/analysis`, `POST /api/v1/media/{id}/reanalyze`; `POST /api/v1/media/reanalyze-batch` (50-item cap, user-scoped, skips in-progress items); `DELETE /api/v1/media/batch` (50-item cap, user-scoped, deletes DB rows + physical file + vector embeddings best-effort) (**P3-003**)
- `routes/search.py` — `GET /api/v1/search?q=...` (natural language search with pagination)
- `routes/auth.py` — `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `routes/download.py` — `GET /api/v1/media/{id}/download` (single enriched file), `POST /api/v1/media/download-batch` (ZIP archive), `POST /api/v1/media/{id}/convert-png` (BMP/GIF → PNG with metadata) — **P2-002**; all formats now use AI title as download filename via `_MIME_TO_EXT` dict + `_ext_for_mime()` helper (**P3-001**)
- `routes/health.py` — `GET /api/v1/health` (no auth; returns `{"status":"ok","version":"0.1.0"}`; used by Docker health checks) (**P3-004**)

### src/auth/

**Location:** `src/auth/`
**Workstream:** WS-004
**Files:**
- `passwords.py` — bcrypt password hashing and verification
- `tokens.py` — JWT token creation (`create_access_token`) and validation (`decode_access_token`)

### src/analysis/

**Location:** `src/analysis/`
**Workstream:** WS-002
**Files:**
- `provider.py` — `VisionProvider` protocol (abstract interface for AI vision providers)
- `anthropic_provider.py` — `AnthropicVisionProvider` using official Anthropic SDK (ADR-008)
- `mock_provider.py` — `MockVisionProvider` returning canned metadata (for testing)
- `image_prep.py` — Image resize (max 1568px longest side) + JPEG conversion + base64 encoding
- `schemas.py` — `MediaMetadataResult` Pydantic model (13 ADR-005 fields) + `parse_ai_response()` JSON parser
- `processor.py` — `analyze_media_item()` background task: load file → prepare → AI call → persist metadata → update statuses

### src/enrichment/

**Location:** `src/enrichment/`
**Workstream:** P2-001
**Responsibilities:**
- Embed AI-extracted metadata into image file binary headers at download time (non-destructive, operates on a copy)
- Dispatches to format-specific writers based on file format
**Files:**
- `embedder.py` — `MetadataEmbedder` dispatcher: routes by format to the correct writer
- `exif_writer.py` — EXIF (via `piexif`) + IPTC writer for JPEG, WebP, AVIF, TIFF
- `png_writer.py` — XMP metadata block via PNG `iTXt` chunk writer
- `avif_writer.py` — AVIF-specific EXIF box injection writer
- `webp_writer.py` — WebP EXIF embedding writer
- `field_mapping.py` — Maps `MediaMetadataResult` fields to EXIF/IPTC/XMP tag identifiers; `build_user_comment()` no longer adds an "AI-generated description:" prefix (**P3-001**)
- `xmp_builder.py` — Builds standards-compliant XMP XML payload

### alembic/ *(P3-002)*

**Location:** `alembic/` (project root)
**Workstream:** P3-002
**Responsibilities:**
- Database schema migration management (Alembic)
**Files:**
- `alembic.ini` — Alembic configuration; `sqlalchemy.url` is intentionally unset (set dynamically in `env.py`)
- `alembic/env.py` — Async-capable migration environment: `get_db_url()` reads `DATABASE_URL` env var or `config/settings.yaml`; `run_async_migrations()` uses `create_async_engine` + `connection.run_sync()`
- `alembic/versions/cce0c99946e6_initial_schema.py` — Initial migration: `CREATE TABLE` for users, media_items, media_metadata, processing_jobs with all FK constraints, unique constraints, and indexes

### src/search/
**Workstream:** WS-003
**Files:**
- `embedding_text.py` — Construct embedding text from metadata fields (Pydantic result or ORM model)
- `embedder.py` — `Embedder` class wrapping `SentenceTransformer` (`all-MiniLM-L6-v2`, 384-dim)
- `models.py` — `SearchHit` dataclass
- `vector_store.py` — `VectorStore` protocol (abstract interface for vector databases); `delete_items(media_ids)` added — **P3-003**
- `chromadb_store.py` — `ChromaDBVectorStore` implementation with persistent storage, cosine similarity, user_id filtering; `delete_items(media_ids)` implemented via `collection.delete(ids=[...])` — **P3-003**
- `indexing_service.py` — `IndexingService`: text construction → embedding → vector store upsert; `remove_items(media_item_ids)` bulk removal — **P3-003**
- `search_service.py` — `SearchService`: query embedding → vector search → DB join → ranked results

### frontend/

**Location:** `frontend/`
**Workstream:** WS-005 (MVP), P2-003 (download buttons), P2-004 (list view + multi-select), P2-005 (Search nav tab)
**Stack:** React 18 + TypeScript + Vite
**Key directories:**
- `src/api/client.ts` — Fetch-based API client wrapping all backend endpoints, JWT header injection, 401 auto-logout; includes `downloadFile()`, `downloadBatch()`, `convertToPng()` (P2-002/P2-003), `listMediaFiltered()` with full filter+sort params (**P3-001**); `reanalyzeBatch()`, `deleteBatch()` (**P3-003**)
- `src/api/useAuthImage.ts` — Hook for authenticated image loading via blob URLs
- `src/context/AuthContext.tsx` — Auth state management (login/register/logout, localStorage token, profile loading)
- `src/types/api.ts` — TypeScript interfaces matching all backend Pydantic schemas; `MediaItemResponse` and `SearchResultItem.media_item` include `width?`/`height?` (**P3-001**)
- `src/pages/` — LoginPage, RegisterPage, GalleryPage (unified browse+search, replaces LibraryPage+SearchPage — **P3-001**; passes `onDeleteSuccess` callback to SelectionBar — **P3-003**), UploadPage (heading renamed to "Source" — **P3-001**), MediaDetailPage (dimensions display + "Back to Gallery" — **P3-001**)
- `src/components/` — Layout (nav: Gallery + Source — **P3-001**), SearchBar (routes to `/?q=` — **P3-001**), UserMenu, MediaCard, AuthImage, StatusBadge, Pagination, DropZone, FileQueue, MetadataDisplay, ProtectedRoute, PublicRoute, ViewToggle (P2-004), MediaListRow (P2-004), SelectionBar (P2-004; Re-analyze + Delete buttons with confirm dialog — **P3-003**)
- `vite.config.ts` — Dev server proxy (`/api` → `http://localhost:8000`)

## Data Model

| Entity | Table | Purpose |
|---|---|---|
| User | `users` | User identity + auth (email, display_name, password_hash). JWT-based auth via WS-004. |
| MediaItem | `media_items` | File identity and storage metadata. Unique on `(user_id, content_hash)`. |
| ProcessingJob | `processing_jobs` | Pipeline state tracking. Status: pending → running → completed/failed. |
| MediaMetadata | `media_metadata` | AI-extracted structured metadata (13 fields per ADR-005). UNIQUE on `media_item_id`. Stores `ai_provider` and `ai_model` for provenance. |

## Architecture Direction

Layered pipeline architecture with clean module boundaries. Each layer (ingestion, analysis, search) is independently testable. The API layer is the sole interface between frontend and backend. AI providers (`VisionProvider`), vector databases (`VectorStore`), and storage backends (`FileStore`) are swappable behind interfaces. The vector store is a derived store (ADR-006) — rebuildable from the database via `scripts/rebuild_vector_store.py`.

## Document Ownership Note

This document owns **codebase structure and module responsibilities only**. It does not duplicate:
- System overview or data flow → see `PROJECT_PLAYBOOK.md`
- AI behavior rules → see `PROJECT_AI_CONTEXT.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
