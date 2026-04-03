# Project Map — Media Indexing Engine

_This document describes the structure of the codebase for developers and AI assistants. It is the authoritative reference for what each module does and where to find it._

_Update this document whenever modules are added, removed, or their responsibilities change._

## Repository Structure

```
media_indexing_engine/
├── src/
│   ├── ingestion/       → File intake, validation, deduplication
│   ├── analysis/        → AI vision model integration, metadata extraction
│   ├── curation/        → Near-duplicate detection (perceptual hashing) — P5-001
│   ├── connectors/      → Connected-ingestion: credential encryption, S3 connector, sync orchestration — P5-003
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
├── scripts/             → Automation and utility scripts (rebuild_vector_store.py; backfill_phash.py — P5-001)
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
- Provide typed configuration dataclasses (AppConfig, StorageConfig, DatabaseConfig, UploadConfig, ProcessingConfig, AnalysisConfig, SearchConfig, AuthConfig, CurationConfig — **P5-001**, ConnectorConfig — **P5-003**)
- `CurationConfig.enable_duplicate_detection` feature gate (env var `ENABLE_DUPLICATE_DETECTION`, default `false`)
- `ConnectorConfig.credentials_key` — Fernet encryption key for connector credentials (env var `CONNECTOR_CREDENTIALS_KEY`, default empty — fail-closed when absent) — **P5-003**
- `ConnectorConfig.max_objects_per_sync` — max objects enumerated per sync run (default `1000`) — **P5-003**

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
- ORM models: User, MediaItem, ProcessingJob, MediaMetadata, QuotaEvent (**P4-002**), CurationScore (**P5-002**), Source, SourceConnector, SyncRun, SourceObject (**P5-003**)
- Unique constraint `(user_id, content_hash)` on media_items
- User: `plan_name` (default `'basic'`), `monthly_limit` (default 500) columns added (**P4-002**)
- MediaItem: `perceptual_hash` (VARCHAR 16), `phash_version` (VARCHAR 20), `phash_computed_at` (TIMESTAMPTZ) — nullable columns + index — **P5-001**
- Source: extended with `connector_status` (VARCHAR 30), `last_synced_at` (TIMESTAMPTZ), `connector` relationship — **P5-003**
- FK relationships between all entities

### src/ingestion/

**Location:** `src/ingestion/`
**Workstream:** WS-001
**Files:**
- `validation.py` — File format (magic-byte MIME detection) and size validation
- `hashing.py` — SHA256 content hashing
- `dedup.py` — Per-user `(user_id, content_hash)` duplicate check
- `upload_service.py` — Orchestrator: validate → hash → dedup → store → DB records → enqueue job; computes pHash after commit (non-fatal, non-blocking) — **P5-001**
- `job_manager.py` — Pending job queries (placeholder processor removed in WS-002)

### src/storage/

**Location:** `src/storage/`
**Workstream:** WS-001 (LocalFileStore), P3-004 (S3FileStore + factory)
**Files:**
- `file_store.py` — `FileStore` abstract interface; `LocalFileStore` (content-addressed paths, `delete()` via P3-003); `S3FileStore` (boto3, thread executor, same content-addressed key structure, optional `s3_endpoint_url` for MinIO compatibility — **P3-004**); `get_file_store(storage_config)` factory function selects implementation based on `storage.provider` config (`"local"` or `"s3"`) (**P3-004**)

### src/connectors/

**Location:** `src/connectors/`
**Workstream:** P5-003
**Responsibilities:**
- Encrypted credential storage for external source connectors (Fernet symmetric encryption, fail-closed when key absent)
- Abstract connector interface and remote object model
- S3-compatible connector implementation (boto3 via `asyncio.run_in_executor`)
- Sync orchestration: list remote objects → idempotent import via existing upload pipeline → quota reservation → per-object error isolation → run state management
**Files:**
- `__init__.py` — Package marker
- `secrets.py` — `encrypt_credentials(payload) -> str`, `decrypt_credentials(ciphertext) -> dict` (Fernet, from `cryptography` package); `require_encryption_key()` — raises `MissingEncryptionKeyError` when `CONNECTOR_CREDENTIALS_KEY` not set; `_get_fernet()` internal helper
- `base.py` — `RemoteObject` dataclass (`key`, `version`, `last_modified_at`, `size`); `ConnectorBase` ABC (`connector_type` property, `list_objects()`, `download_object()`, `validate()`); `ConnectorValidationError` exception
- `s3_connector.py` — `S3Connector(ConnectorBase)`: wraps boto3, all I/O via `run_in_executor` (non-blocking); filters to image extensions only; paginates `list_objects_v2` with `max_keys` bound; `_sync_list_objects()`, `_sync_download_object()`, `_sync_validate()` (boto3 `head_bucket`). `build_s3_connector(*, bucket_name, credentials, region, endpoint_url, prefix)` factory.
- `sync_service.py` — `trigger_sync(source_id, user_id, db, file_store, upload_service)` public entry point: validates encryption key + source ownership + no overlap → creates SyncRun → calls `_run_sync()`. `_run_sync()` orchestrator: decrypt credentials → build connector → list objects → load existing SourceObjects → iterate (idempotency skip if key+version match; download; `process_upload()`; quota reserve + `analyze_media_item` task for new imports; per-object error tracking; quota-exhaustion graceful stop). `_upsert_source_object()` INSERT-or-UPDATE helper. `SyncRunResult` dataclass.

### src/curation/

**Location:** `src/curation/`
**Workstream:** P5-001, P5-002
**Responsibilities:**
- Compute 64-bit DCT perceptual hashes (pHash) for images
- Calculate Hamming distance between hashes to identify near-duplicates
- Provide `find_similar()` helper for batch similarity queries
- AI-based quality scoring for near-duplicate groups (best-photo selection)
**Files:**
- `phash_service.py` — `compute_phash(file_bytes, mime_type) -> str | None`: full normalisation pipeline (EXIF transpose → alpha composite → greyscale → pHash via `imagehash` library). `hamming_distance(h1, h2) -> int`. `find_similar(candidates, anchor_hash, threshold) -> list[tuple[id, dist]]`. Constants: `PHASH_VERSION = "phash64-v1"`, `PHASH_THRESHOLD = 10`, `SUPPORTED_MIME_TYPES`.
- `scoring_service.py` — `score_group(anchor_id, user_id, db, file_store) -> GroupScoreResult`: finds group members via pHash, calls Anthropic vision AI for each image, upserts `CurationScore` rows, returns scored/failed counts + `best_pick_id`. `load_scores_for_items(db, item_ids) -> dict[str, CurationScore]`: bulk loader. `find_best_pick(scores: dict[str, float]) -> str | None`: pure-Python highest-score selector. `_call_ai_score()`: calls AI with `SCORING_SYSTEM_PROMPT` (quality: sharpness, exposure, composition, blur, noise); returns `ScoreResult(quality_score, rationale, scoring_model)`. `_upsert_score()`: INSERT or UPDATE on `curation_scores`. `SCORING_SYSTEM_PROMPT`. `ScoreResult`, `GroupScoreResult` dataclasses. — **P5-002**

### src/api/

**Location:** `src/api/`
**Workstream:** WS-001 (scaffold), WS-004 (hardening)
**Files:**
- `app.py` — FastAPI app creation, lifespan (DB init: `create_tables()` in dev, `run_migrations()` in prod — **P3-002**; dev user seed), router registration
- `schemas.py` — Pydantic response models (UploadResponse, BatchUploadResponse, MediaItemResponse, PaginatedResponse); `MediaItemResponse` and `SearchMediaItem` include `width`/`height` fields (**P3-001**); `MediaItemResponse` adds `has_similar: bool = False` / `similar_count: int = 0` — **P5-001**; `SimilarItemResponse` (+ `quality_score`, `rationale`, `is_best_pick` — **P5-002**), `SimilarItemsResponse` (+ `anchor_quality_score`, `anchor_rationale`, `anchor_is_best_pick` — **P5-002**), `ScoreGroupResponse` — **P5-002**; for the drill-down endpoint; `BatchOperationRequest` (validated 1–50 `media_ids`), `BatchReanalyzeResponse`, `BatchDeleteResponse` (**P3-003**); `QuotaStatusResponse` (**P4-002**)
- `dependencies.py` — DB session dependency + JWT auth dependency (`get_current_user_id` with dev mode fallback)
- `error_handlers.py` — Standardized error response format (`detail` + `error_code`)
- `rate_limit.py` — In-memory sliding window rate limiter for auth endpoints
- `routes/upload.py` — `POST /api/v1/upload`, `POST /api/v1/upload/batch`; reserves quota before enqueue; returns `HTTP 429 QUOTA_EXCEEDED` with structured payload on exhaustion; batch returns per-item error (**P4-002**)
- `routes/media.py` — `GET /api/v1/media` (full filter+sort: `has_people`, `orientation`, `mood`, `mime_type`, `min/max_width/height`, `aspect_ratio`, `tags`, `sort_by`; metadata-based filters JOIN `MediaMetadata`; aspect ratio uses post-query Python filtering via `_matches_aspect_ratio()`), `GET /api/v1/media/{id}`, `GET /api/v1/media/{id}/file` (**P3-001**); `GET /api/v1/media/{id}/similar` returns near-duplicate neighbours with quality scores + best-pick flags when `enable_ai_scoring` ON — **P5-001**, **P5-002**; `POST /api/v1/media/{id}/score-group` triggers AI scoring for entire near-duplicate group — **P5-002**; `_build_media_item_responses()` enriches `has_similar`/`similar_count` when curation gate ON — **P5-001**
- `routes/analysis.py` — `GET /api/v1/media/{id}/analysis`, `POST /api/v1/media/{id}/reanalyze` (quota-enforced — **P4-002**); `POST /api/v1/media/reanalyze-batch` (50-item cap, all-or-nothing quota — **P4-002**, **P3-003**); `DELETE /api/v1/media/batch` (50-item cap, user-scoped, deletes DB rows + physical file + vector embeddings best-effort) (**P3-003**)
- `routes/search.py` — `GET /api/v1/search?q=...` (natural language search with pagination)
- `routes/auth.py` — `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `routes/download.py` — `GET /api/v1/media/{id}/download` (single enriched file), `POST /api/v1/media/download-batch` (ZIP archive), `POST /api/v1/media/{id}/convert-png` (BMP/GIF → PNG with metadata) — **P2-002**; all formats now use AI title as download filename via `_MIME_TO_EXT` dict + `_ext_for_mime()` helper (**P3-001**)
- `routes/health.py` — `GET /api/v1/health` (no auth; returns `{"status":"ok","version":"0.1.0"}`; used by Docker health checks) (**P3-004**)
- `routes/quota.py` — `GET /api/v1/quota/status` (user-scoped; returns plan_name, monthly_limit, consumed, reserved, remaining, period_month) (**P4-002**)

### src/quota/

**Location:** `src/quota/`
**Workstream:** P4-002
**Files:**
- `quota_service.py` — `QuotaService`: `get_status()`, `reserve()`, `consume()`, `release()`; `QuotaExceededError`; `build_quota_exceeded_detail()`; concurrency via `SELECT FOR UPDATE` on `users` row; ledger-based remaining = `monthly_limit - consumed - reserved` for current UTC month

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
- `processor.py` — `analyze_media_item()` background task: load file → prepare → AI call → persist metadata → update statuses; `reservation_id` param: consume on success, release on permanent failure (**P4-002**)

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
- `alembic/versions/f1e2d3c4b5a6_perceptual_hash.py` — Adds `perceptual_hash`, `phash_version`, `phash_computed_at` nullable columns + index to `media_items` — **P5-001**
- `alembic/versions/a1b2c3d4e5f6_curation_scores.py` — Creates `curation_scores` table (FK to `media_items` + `users`; UNIQUE index on `media_item_id`; `quality_score`, `rationale`, `scoring_model`, `scored_at`, `created_at` columns) — **P5-002**
- `alembic/versions/f6a7b8c9d0e1_connector_sync_foundation.py` — Adds `connector_status`/`last_synced_at` to `sources`; creates `source_connectors` (UNIQUE on `source_id`), `sync_runs`, `source_objects` (UNIQUE on `source_id, external_object_key`) tables — **P5-003**

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
- `src/api/schemas.py` (connector + sync schemas + SourceResponse extension):
  - `SourceResponse` extended with `connector_status: str | None`, `last_synced_at: datetime | None` — **P5-003**
  - `ConnectorS3ConfigRequest` — write-only S3 config (accepts `access_key_id`, `secret_access_key`) — **P5-003**
  - `ConnectorResponse` — read-only config (no secret fields) — **P5-003**
  - `SyncRunResponse`, `SyncRunsResponse`, `TriggerSyncResponse` — **P5-003**
- `src/api/client.ts` — adds `configureS3Connector(sourceId, config)`, `getConnector(sourceId)`, `triggerSync(sourceId)`, `listSyncRuns(sourceId, page?, perPage?)` — **P5-003**; `getSimilarMedia(id)` — **P5-001**; `scoreGroup(id)` — **P5-002**
- `src/api/useAuthImage.ts` — Hook for authenticated image loading via blob URLs
- `src/context/AuthContext.tsx` — Auth state management (login/register/logout, localStorage token, profile loading)
- `src/types/api.ts` — TypeScript interfaces matching all backend Pydantic schemas; `MediaItemResponse` and `SearchResultItem.media_item` include `width?`/`height?` (**P3-001**); `MediaItemResponse` adds `has_similar?`/`similar_count?`; `SimilarItemResponse` (+ `quality_score?`, `rationale?`, `is_best_pick?` — **P5-002**), `SimilarItemsResponse` (+ `anchor_quality_score?`, `anchor_rationale?`, `anchor_is_best_pick?` — **P5-002**), `ScoreGroupResponse` — **P5-002**; `SourceResponse` extended with `connector_status?`/`last_synced_at?`; `ConnectorS3ConfigRequest`, `ConnectorResponse`, `SyncRunResponse`, `SyncRunsResponse`, `TriggerSyncResponse` added — **P5-003**
- `src/pages/SourcesPage.tsx` — source list with connector status badge, connector setup/management via `ConnectorPanel` component (tabbed: Configure / Sync runs), S3 credentials form (masked after save), "Sync now" button, sync run history table — **P5-003**
- `src/pages/` — LoginPage, RegisterPage, GalleryPage (unified browse+search, replaces LibraryPage+SearchPage — **P3-001**; passes `onDeleteSuccess` callback to SelectionBar — **P3-003**), UploadPage (heading renamed to "Source" — **P3-001**), MediaDetailPage (dimensions display + "Back to Gallery" — **P3-001**)
- `src/components/` — Layout (nav: Gallery + Source — **P3-001**), SearchBar (routes to `/?q=` — **P3-001**), UserMenu, MediaCard (optional `hasSimilar`/`similarCount` props render a `.similar-badge` overlay — **P5-001**), AuthImage, StatusBadge, Pagination, DropZone, FileQueue, MetadataDisplay, ProtectedRoute, PublicRoute, ViewToggle (P2-004), MediaListRow (P2-004), SelectionBar (P2-004; Re-analyze + Delete buttons with confirm dialog — **P3-003**)
- `vite.config.ts` — Dev server proxy (`/api` → `http://localhost:8000`)

## Data Model

| Entity | Table | Purpose |
|---|---|---|
| User | `users` | User identity + auth (email, display_name, password_hash). JWT-based auth via WS-004. |
| MediaItem | `media_items` | File identity and storage metadata. Unique on `(user_id, content_hash)`. `perceptual_hash`/`phash_version`/`phash_computed_at` added for near-duplicate detection — **P5-001**. |
| ProcessingJob | `processing_jobs` | Pipeline state tracking. Status: pending → running → completed/failed. |
| MediaMetadata | `media_metadata` | AI-extracted structured metadata (13 fields per ADR-005). UNIQUE on `media_item_id`. Stores `ai_provider` and `ai_model` for provenance. |
| CurationScore | `curation_scores` | Per-item AI quality scores for near-duplicate group best-photo selection. UNIQUE on `media_item_id`. Stores `quality_score` (0.0–1.0), `rationale`, `scoring_model`, `scored_at`. — **P5-002** |
| Source | `sources` | Named source for organising media. Soft-delete via `archived_at`. Extended with `connector_status`, `last_synced_at` — **P5-003**. |
| SourceConnector | `source_connectors` | Connector configuration for a Source. UNIQUE on `source_id`. Stores `connector_type`, `bucket_name`, `prefix`, `region`, `endpoint_url`, `credentials_encrypted` (Fernet ciphertext). — **P5-003** |
| SyncRun | `sync_runs` | Record of one sync execution. Tracks `status` (running/completed/completed_with_errors/failed), all object counters, `error_summary`. — **P5-003** |
| SourceObject | `source_objects` | Per-object tracking for idempotent sync. UNIQUE on `(source_id, external_object_key)`. Stores `external_version`, `state` (imported/duplicate/skipped/failed), `last_content_hash`. — **P5-003** |

## Architecture Direction

Layered pipeline architecture with clean module boundaries. Each layer (ingestion, analysis, search) is independently testable. The API layer is the sole interface between frontend and backend. AI providers (`VisionProvider`), vector databases (`VectorStore`), and storage backends (`FileStore`) are swappable behind interfaces. The vector store is a derived store (ADR-006) — rebuildable from the database via `scripts/rebuild_vector_store.py`.

## Document Ownership Note

This document owns **codebase structure and module responsibilities only**. It does not duplicate:
- System overview or data flow → see `PROJECT_PLAYBOOK.md`
- AI behavior rules → see `PROJECT_AI_CONTEXT.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
