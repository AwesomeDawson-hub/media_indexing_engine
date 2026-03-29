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
├── tests/               → Test suite
├── config/              → Configuration files
├── docs/                → Project-specific documentation
├── scripts/             → Automation and utility scripts
├── frontend/            → Web UI
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
- Table creation/drop utilities
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
**Workstream:** WS-001
**Files:**
- `file_store.py` — `FileStore` abstract interface + `LocalFileStore` implementation (content-addressed paths: `{user_id}/{content_hash}/{filename}`; `read()` added in WS-002)

### src/api/

**Location:** `src/api/`
**Workstream:** WS-001 (scaffold), WS-004 (hardening)
**Files:**
- `app.py` — FastAPI app creation, lifespan (DB init + dev user seed), router registration
- `schemas.py` — Pydantic response models (UploadResponse, BatchUploadResponse, MediaItemResponse, PaginatedResponse); `MediaItemResponse` and `SearchMediaItem` include `width`/`height` fields (**P3-001**)
- `dependencies.py` — DB session dependency + JWT auth dependency (`get_current_user_id` with dev mode fallback)
- `error_handlers.py` — Standardized error response format (`detail` + `error_code`)
- `rate_limit.py` — In-memory sliding window rate limiter for auth endpoints
- `routes/upload.py` — `POST /api/v1/upload`, `POST /api/v1/upload/batch` (dispatches analysis via mock/real provider)
- `routes/media.py` — `GET /api/v1/media` (full filter+sort: `has_people`, `orientation`, `mood`, `mime_type`, `min/max_width/height`, `aspect_ratio`, `tags`, `sort_by`; metadata-based filters JOIN `MediaMetadata`; aspect ratio uses post-query Python filtering via `_matches_aspect_ratio()`), `GET /api/v1/media/{id}`, `GET /api/v1/media/{id}/file` (**P3-001**)
- `routes/analysis.py` — `GET /api/v1/media/{id}/analysis`, `POST /api/v1/media/{id}/reanalyze`
- `routes/search.py` — `GET /api/v1/search?q=...` (natural language search with pagination)
- `routes/auth.py` — `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `routes/download.py` — `GET /api/v1/media/{id}/download` (single enriched file), `POST /api/v1/media/download-batch` (ZIP archive), `POST /api/v1/media/{id}/convert-png` (BMP/GIF → PNG with metadata) — **P2-002**; all formats now use AI title as download filename via `_MIME_TO_EXT` dict + `_ext_for_mime()` helper (**P3-001**)

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

### src/search/

**Location:** `src/search/`
**Workstream:** WS-003
**Files:**
- `embedding_text.py` — Construct embedding text from metadata fields (Pydantic result or ORM model)
- `embedder.py` — `Embedder` class wrapping `SentenceTransformer` (`all-MiniLM-L6-v2`, 384-dim)
- `models.py` — `SearchHit` dataclass
- `vector_store.py` — `VectorStore` protocol (abstract interface for vector databases)
- `chromadb_store.py` — `ChromaDBVectorStore` implementation with persistent storage, cosine similarity, user_id filtering
- `indexing_service.py` — `IndexingService`: text construction → embedding → vector store upsert
- `search_service.py` — `SearchService`: query embedding → vector search → DB join → ranked results

### frontend/

**Location:** `frontend/`
**Workstream:** WS-005 (MVP), P2-003 (download buttons), P2-004 (list view + multi-select), P2-005 (Search nav tab)
**Stack:** React 18 + TypeScript + Vite
**Key directories:**
- `src/api/client.ts` — Fetch-based API client wrapping all backend endpoints, JWT header injection, 401 auto-logout; includes `downloadFile()`, `downloadBatch()`, `convertToPng()` (P2-002/P2-003), `listMediaFiltered()` with full filter+sort params (**P3-001**)
- `src/api/useAuthImage.ts` — Hook for authenticated image loading via blob URLs
- `src/context/AuthContext.tsx` — Auth state management (login/register/logout, localStorage token, profile loading)
- `src/types/api.ts` — TypeScript interfaces matching all backend Pydantic schemas; `MediaItemResponse` and `SearchResultItem.media_item` include `width?`/`height?` (**P3-001**)
- `src/pages/` — LoginPage, RegisterPage, GalleryPage (unified browse+search, replaces LibraryPage+SearchPage — **P3-001**), UploadPage (heading renamed to "Source" — **P3-001**), MediaDetailPage (dimensions display + "Back to Gallery" — **P3-001**)
- `src/components/` — Layout (nav: Gallery + Source — **P3-001**), SearchBar (routes to `/?q=` — **P3-001**), UserMenu, MediaCard, AuthImage, StatusBadge, Pagination, DropZone, FileQueue, MetadataDisplay, ProtectedRoute, PublicRoute, ViewToggle (P2-004), MediaListRow (P2-004), SelectionBar (P2-004)
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
