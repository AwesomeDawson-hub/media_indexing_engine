# Decision Log — Media Indexing Engine

## Document Role

This document records **architectural and irreversible decisions** for the Media Indexing Engine project. It provides a permanent audit trail of *why* significant choices were made, so future sessions and operators can understand the reasoning without re-litigating settled questions.

### What This Document Owns
- Architectural decisions (technology choices, structural patterns, integration approaches)
- Irreversible decisions (data model changes, API contracts, external commitments)
- Significant trade-off resolutions where the "why" is not obvious from the code

### What This Document Does NOT Own
- Implementation details — those belong in `IMPLEMENTATION_STATUS.md`
- Workstream summaries — those belong in `IMPLEMENTATION_STATUS.md`
- Current system state — that belongs in `CURRENT_STATE.md`
- Task tracking — that belongs in `WORKSTREAMS.md`
- Process rules — those belong in the launcher's `AI_WORKFLOW.md`

### Update Trigger
A new entry is added whenever an architectural or irreversible decision is made during any workstream. Entries are **never modified after creation** — they are historical records. If a decision is reversed, a new entry is created referencing the original.

---

## Entry Format

Each decision follows this structure:

```
### ADR-XXX: [Decision Title]
- **Date:** [Date]
- **Workstream:** [WS-XXX or "System-level"]
- **Status:** Accepted | Superseded by ADR-YYY
- **Context:** [What situation or problem prompted this decision]
- **Decision:** [What was decided]
- **Reasoning:** [Why this option was chosen over alternatives]
- **Alternatives considered:** [What else was evaluated]
- **Consequences:** [Known trade-offs, risks, or downstream effects]
```

---

## Decision Log

### ADR-001: SHA256 Content Hash as Media Identity
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Need a deterministic, reliable way to identify media files for deduplication and cross-system reference. Prior project (`marketing_asset_pipeline`) used SHA256 `file_hash` as the primary asset identity with proven results.
- **Decision:** Use SHA256 hex digest of raw file bytes as the content identity. Canonical identity is the tuple `(user_id, content_hash)`. A separate UUID v4 serves as the internal reference key for API URLs and foreign keys.
- **Reasoning:** SHA256 is deterministic, collision-resistant, and proven in the prior project. Scoping dedup per-user avoids cross-tenant conflicts while preventing same-user duplicates.
- **Alternatives considered:** MD5 (faster but weaker collision resistance), perceptual hashing (useful for near-duplicate detection but not exact dedup), UUID-only (no dedup capability).
- **Consequences:** Dedup check must occur before file storage to avoid storing duplicates. Re-upload after deletion creates a new UUID but same hash — file will be reprocessed (correct behavior).

### ADR-002: Database as Sole System of Record
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Prior project used three storage layers (SQLite + JSON sidecars + CSV index), which created sync complexity and dual-write problems. Its own documentation noted a move toward "SQLite-first."
- **Decision:** PostgreSQL (SQLite for dev) is the sole system of record. No JSON sidecar files, no CSV index files. The API serves metadata directly from the database.
- **Reasoning:** A web app with an API has no need for portable file-based metadata. Single source of truth eliminates sync bugs. The prior project's 3-layer approach was an artifact of its file-based workflow.
- **Alternatives considered:** Keep JSON sidecars for portability (rejected: adds sync complexity with no consumer in a web app), keep CSV for quick export (rejected: export can be an API endpoint).
- **Consequences:** No offline/file-based metadata access. If the database is lost, metadata must be regenerated. Mitigated by standard database backup practices.

### ADR-003: Normalized Entity Model
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Prior project used a flat 43-column `assets` table mixing file identity, AI metadata, review state, and storage paths. This made updates and queries complex.
- **Decision:** Normalize into four tables: `users`, `media_items` (file identity and storage), `media_metadata` (AI output), `processing_jobs` (pipeline state).
- **Reasoning:** Separation of concerns. Each table owns a distinct domain. Metadata can be updated without touching file identity. Processing state is independent of final metadata. Enables clean foreign key relationships.
- **Alternatives considered:** Flat table (rejected: proved unwieldy in prior project), document store (rejected: adds infrastructure complexity for relational data).
- **Consequences:** Joins required for full media view. Mitigated by creating a database view or query helper that combines the common case.

### ADR-004: Content-Addressed File Storage
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Prior project used AI-generated filename slugs with complex cross-run collision protection (`load_existing_slugs`, `ensure_unique_slug`). This added significant code complexity.
- **Decision:** Store files using content-addressed paths: `{user_id}/{content_hash}/{original_filename}`. Human-readable names exist only in metadata, not on disk.
- **Reasoning:** Eliminates the entire slug collision problem. Storage paths are deterministic from identity. Original filenames are preserved in the database for display.
- **Alternatives considered:** UUID-based paths (simpler but lose dedup alignment), slug-based (rejected: proven complex in prior project).
- **Consequences:** File paths are not human-readable on disk. Acceptable for a web app where files are accessed through the API, never by browsing storage directly.

### ADR-005: Metadata Schema for General Media Indexing
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Prior project's schema was marketing-specific (14 fields including `marketing_caption`, `seo_keywords`, `suggested_use`). Media Indexing Engine serves photographers and general search users.
- **Decision:** New schema with 13 fields: `title`, `description`, `tags`, `objects`, `scenes`, `context`, `mood`, `people`, `people_count`, `orientation`, `colors`, `location_hint`, `quality_notes`. Dropped all marketing-specific fields. Added `objects`, `scenes`, `context`, `mood`, `people_count`, `quality_notes`.
- **Reasoning:** `objects` + `scenes` + `context` enable the semantic search queries that photographers and marketing teams need ("dogs on a beach", "team meeting in office"). `mood` supports tone-based searches. `people_count` distinguishes group photos from portraits.
- **Alternatives considered:** Minimal schema (title + tags only — rejected: insufficient for semantic search quality), keep marketing fields (rejected: wrong domain).
- **Consequences:** Schema is the contract between WS-002 (analysis) and WS-003 (search). Changes require coordinated updates across both workstreams.

### ADR-006: Three-Store Architecture (Files, Database, Vector DB)
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Need to store raw files, structured metadata, and vector embeddings. Prior project used filesystem + SQLite + numpy files. A multi-user web app needs concurrent access and proper indexing.
- **Decision:** Three stores: S3-compatible file storage (local filesystem for dev), PostgreSQL for metadata (SQLite for dev), ChromaDB for vectors (Qdrant for prod). Vector store is derived and can be rebuilt from the database.
- **Reasoning:** Each store is optimized for its data type. Vector DB supports concurrent access, filtering, and incremental updates (unlike numpy files). S3-compatible storage is industry standard and scales horizontally.
- **Alternatives considered:** All-in-one PostgreSQL with pgvector (viable but less flexible for vector search tuning), Pinecone (SaaS dependency, harder to develop locally).
- **Consequences:** Three services to manage in deployment. Mitigated: local dev uses SQLite + filesystem + ChromaDB (all embedded, no external services).

### ADR-007: Defer Review Workflow to Phase 2
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Prior project had a three-mode review workflow (auto/hybrid/review) with per-asset flags, approval flows, and finalization steps. This added significant complexity.
- **Decision:** V1 auto-processes everything. No review gates, no approval workflow, no finalization step. All analyzed media goes directly to searchable state.
- **Reasoning:** MVP should prove the end-to-end pipeline works before adding workflow complexity. The prior project's review system was its most complex subsystem.
- **Alternatives considered:** Implement review from the start (rejected: blocks MVP delivery for a feature that isn't in V1 success criteria).
- **Consequences:** No human-in-the-loop quality gate in V1. Mitigated: AI metadata quality issues surface through search results and can be addressed in Phase 2.

### ADR-008: Anthropic Claude as Initial AI Provider
- **Date:** 2026-03-27
- **Workstream:** WS-000
- **Status:** Accepted
- **Context:** Phase 1 plan lists OpenAI, Anthropic, and Google as potential vision API providers. Need to pick one to start.
- **Decision:** Start with Anthropic Claude as the sole AI provider. Use the official Anthropic SDK (not raw HTTP). Abstract the vision analysis behind an interface to enable future provider swaps.
- **Reasoning:** Prior project used Claude successfully. Team has existing API access and familiarity. SDK handles auth, retries, and model selection. Interface abstraction keeps the door open without building multi-provider support prematurely.
- **Alternatives considered:** OpenAI GPT-4o (viable, no strong reason to prefer), Google Gemini (less proven for structured metadata extraction), multi-provider from day one (rejected: premature complexity).
- **Consequences:** Locked to Anthropic pricing and availability for V1. Mitigated by the interface abstraction — switching providers is a single module change.

### ADR-009: Alembic for Database Schema Migrations
- **Date:** 2026-03-28
- **Workstream:** P3-002
- **Status:** Accepted
- **Context:** The project used `metadata.create_all()` at startup, which recreates tables from scratch. Any schema change requires dropping the database manually. This is acceptable for development but cannot be used in production where data must be preserved.
- **Decision:** Adopt Alembic as the migration framework. Generate an initial migration from the current schema and run `alembic upgrade head` at production startup. Development and test environments retain `create_all()` for speed.
- **Reasoning:** Alembic is the standard migration tool for SQLAlchemy projects. It supports async engines (via `run_sync`), has first-class autogenerate, and integrates naturally with the existing stack. The split between prod (Alembic) and dev/test (`create_all()`) avoids test slowdowns while enabling production schema evolution.
- **Alternatives considered:** Flyway, Liquibase (Java-centric tools, not idiomatic for Python). Manual SQL migration scripts (no tooling support, prone to drift). Rolling `create_all()` into prod (rejected: data loss risk).
- **Consequences:** All future schema changes require `alembic revision --autogenerate` + review + `alembic upgrade head`. Tests remain independent of Alembic.

### ADR-010: S3-Compatible Object Storage as Production File Storage Backend
- **Date:** 2026-03-28
- **Workstream:** P3-004
- **Status:** Accepted
- **Context:** ADR-006 (Three-Store Architecture) designated `FileStore` as an abstract interface precisely to allow swapping local disk for object storage in production. ADR-004 defined content-addressed paths (`{user_id}/{content_hash}/{filename}`) — this path scheme maps directly to an S3 key.
- **Decision:** Implement `S3FileStore` using the `boto3` library. AWS credentials are sourced exclusively from environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`). The active backend is selected by `storage.provider` config field (overridable via `STORAGE_PROVIDER` env var). `LocalFileStore` remains the default for local development.
- **Reasoning:** boto3 is the de facto AWS SDK for Python. Using `run_in_executor` wraps the synchronous boto3 calls for async compatibility without requiring aioboto3. The `S3_ENDPOINT_URL` field allows targeting S3-compatible stores (MinIO, Backblaze B2, etc.) for cost flexibility.
- **Alternatives considered:** aioboto3 (async wrapper; adds dependency and complexity beyond what's needed), direct HTTP to S3 (requires signing implementation), hard-coding S3 (removes local dev path).
- **Consequences:** Requires `boto3` installed in production (optional dependency in `pyproject.toml`). Local file storage is unchanged and tested. S3 operations are covered by unit tests with a mocked client; real S3 validation requires a live bucket.

### ADR-011: Docker + docker-compose as Deployment Mechanism
- **Date:** 2026-03-28
- **Workstream:** P3-004
- **Status:** Accepted
- **Context:** The system has four components — FastAPI backend, React frontend, ChromaDB vector store, and PostgreSQL — that must be started, networked, and configured together for production deployment. Without a container orchestration approach, deployment requires manual setup of each service.
- **Decision:** Use Docker containers for each service and docker-compose for orchestration. Backend: Python 3.11-slim image, runs `alembic upgrade head && uvicorn`. Frontend: multi-stage build (Node.js compile, nginx serve). ChromaDB and PostgreSQL: official images.
- **Reasoning:** docker-compose is the minimal viable orchestration tool for a four-service deployment. It provides service dependency ordering, volume management, and environment variable injection without the operational complexity of Kubernetes. The frontend's multi-stage build keeps the production image small (only nginx + static files). All secrets are injected via environment variables; no credentials are baked into images.
- **Alternatives considered:** Kubernetes (overengineered for V1 scale requirements), bare-metal manual setup (error-prone, not reproducible), single Docker image with all services (violates separation of concerns, makes updates difficult).
- **Consequences:** Requires Docker 24+ and Docker Compose v2 on the deployment host. Manual end-to-end smoke test against the Docker stack is required to fully validate PostgreSQL + S3 integration (not automated in CI). Kubernetes migration is possible later without architectural changes.

### ADR-013: Monthly Quota Uses Reservation Ledger Semantics
- **Date:** 2026-03-31
- **Workstream:** P4-002
- **Status:** Accepted
- **Context:** The system needs enforceable monthly analysis limits that remain correct under concurrent requests and can later support billing reconciliation. A mutable counter on `users` is simple but does not preserve an audit trail, makes refund/release handling brittle, and is difficult to reconcile when failures occur.
- **Decision:** Use a `quota_events` ledger as the authoritative monthly-usage record. Reserve quota before analysis is enqueued (`event_type=reserved`), convert the reservation to `consumed` on success, and `released` on permanent failure. Compute remaining quota as `monthly_limit - consumed - reserved` for the current UTC month. Row-level locking (`SELECT FOR UPDATE` on the `users` row) serializes quota decisions per user without introducing a mutable counter.
- **Reasoning:** The ledger preserves history, supports concurrency-safe reservation semantics, and provides a clean bridge into future billing and admin reconciliation. Reservation-before-enqueue prevents double-spend under concurrent uploads. The `reserved` state ensures in-flight work is counted against the limit even before analysis completes.
- **Alternatives considered:** Mutable `used_this_month` integer on `users` (rejected: weak auditability, no in-flight visibility, race-prone); app-memory counters (rejected: invalid in distributed deployments); eventual reconciliation from processing jobs (rejected: too indirect and failure-prone).
- **Consequences:** All analysis-triggering paths must reserve quota before enqueueing work. Background job success/failure paths must finalize reservation state (`consume` or `release`). Future billing and admin tooling should read from the `quota_events` ledger. Batch upload uses per-item best-effort error semantics; batch re-analysis uses all-or-nothing 429 semantics — both are intentional and tested. The `period_month` field is stored as a PostgreSQL `Date` (first day of month) and serialized as `"YYYY-MM"` in the API response.

### ADR-012: User Isolation Must Be Enforced at the Database Layer for All Read Paths
- **Date:** 2026-03-29
- **Workstream:** Post-Phase-3 bug fix (commit fd5013e)
- **Status:** Accepted
- **Context:** During a post-Phase-3 security audit, it was discovered that `search_service.py` enforced user isolation only via ChromaDB's `where={"user_id": user_id}` filter. The subsequent DB queries to fetch full `MediaItem` records used `WHERE id IN (hit_ids)` with no `user_id` constraint. While ChromaDB correctly filtered hits to the authenticated user's embeddings, this created a theoretical defense-in-depth gap: any bug or bypass in the ChromaDB filter layer could expose other users' media items.
- **Decision:** All read-path queries (list, search, file access) that return `MediaItem` records MUST include `MediaItem.user_id == user_id` in the database WHERE clause. The DB layer is the authoritative enforcement point for user isolation — external filters (ChromaDB, URL parameters) are supplementary, not primary.
- **Reasoning:** Defense-in-depth is a core security principle. If ChromaDB's user filter were bypassed (by a ChromaDB bug, misconfiguration, or future refactor), the DB would silently return another user's records. Adding `user_id` at the DB level costs nothing (indexed column) and eliminates the entire vulnerability class.
- **Alternatives considered:** Relying solely on ChromaDB filtering (rejected — single point of failure for a security-sensitive constraint), application-layer post-filtering (rejected — still exposes data in the DB result before filtering).
- **Consequences:** Every new list or search endpoint added in future workstreams MUST include user_id scoping in its DB query. This is now an explicit inviolable rule (see `PROJECT_AI_CONTEXT.md` "What AI Must NOT Do"). Failure to include it is a security defect, not a code style issue.

### ADR-014: Connector Configuration Uses Split Tables and Encrypted Per-Source Credentials
- **Date:** 2026-04-02
- **Workstream:** P5-003
- **Status:** Accepted
- **Context:** Phase 5 introduces the first connected-ingestion source. The existing `sources` table was designed as a lightweight source registry for manual uploads and currently owns user-facing source identity only (`name`, `source_type`, archive state). Connector-based ingestion adds provider configuration, operational state, and per-source credentials that should not be mixed into the generic source contract.
- **Decision:** Keep `sources` as the stable user-facing registry and add a one-to-one `source_connectors` table for connector-specific configuration. Sensitive connector credentials are stored encrypted at rest in `source_connectors.credentials_encrypted` using an application-managed encryption key from environment configuration. Non-secret operational fields such as bucket, prefix, region, and endpoint URL may remain in plain columns.
- **Reasoning:** Split tables keep manual sources simple, prevent `sources` from turning into a sparse connector blob, and isolate security-sensitive fields from normal source list/read paths. Application-managed encryption avoids plaintext database storage without requiring a new external secrets vendor.
- **Alternatives considered:** Store connector config directly on `sources` (rejected: weak separation of concerns, spreads secret-bearing fields across a generic table), environment-only connector credentials (rejected: cannot support per-user or per-source credentials), plaintext DB storage (rejected: unacceptable security posture).
- **Consequences:** Connector APIs must fail closed when the encryption key is absent. Secret material must never appear in API responses or logs. Future connector families can add provider-specific config while preserving the stable `sources` contract.

### ADR-015: Manual-Triggered Sync Foundation Reuses Existing Ingestion Pipeline
- **Date:** 2026-04-02
- **Workstream:** P5-003
- **Status:** Accepted
- **Context:** Connector sync introduces automated import behavior, run history, and remote-object memory. Without an explicit boundary, implementation could drift into a second ingestion pipeline that bypasses the exact-dedup, quota, storage, and analysis rules already proven in earlier workstreams.
- **Decision:** Phase 5 connector sync is manual-trigger only and must reuse the existing upload/ingestion pipeline for all imported files. Add dedicated `sync_runs` and `source_objects` tables for connector execution state and idempotent remote-object tracking, but do not overload `processing_jobs` and do not introduce a recurring scheduler in Phase 5.
- **Reasoning:** Reusing the existing ingest path preserves one authoritative import contract and ensures connector imports inherit exact deduplication, quota enforcement, storage, and downstream analysis automatically. Manual trigger proves the connector foundation without forcing a scheduler, worker orchestration layer, or broad operational redesign into the final Phase 5 workstream.
- **Alternatives considered:** Parallel connector-specific ingest path (rejected: duplicate logic and drift risk), overload `processing_jobs` for sync runs (rejected: media-item job model does not fit source-level execution), scheduled sync in Phase 5 (rejected: too much orchestration complexity for the current sprint).
- **Consequences:** Connector code is responsible only for config validation, remote listing/download, and sync-state bookkeeping before handing files to the existing ingestion service. Scheduled sync, remote delete propagation, and broader orchestration remain deferred to a later phase or follow-up ADR.
