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

### ADR-016: Authlib Is the OAuth2 / OpenID Client Library for Google SSO
- **Date:** 2026-04-02
- **Workstream:** P6-001
- **Status:** Accepted
- **Context:** The project needs Google sign-in without disrupting the existing FastAPI + JWT auth stack. The implementation must handle OAuth2/OpenID redirects, token exchange, and claim parsing safely while remaining small and maintainable.
- **Decision:** Use Authlib as the OAuth2 / OpenID Connect client library for Google SSO.
- **Reasoning:** Authlib fits Python web applications cleanly, avoids reimplementing security-sensitive OAuth flows over raw `httpx`, and is less Google-specific than adopting Google’s broader client libraries for a single-provider login feature.
- **Alternatives considered:** Manual `httpx` implementation (rejected: too much security-sensitive protocol code to hand-roll), Google’s own auth library (rejected: tighter provider coupling than needed for this app architecture).
- **Consequences:** Google SSO will depend on Authlib for discovery, authorization redirect, token exchange, and ID token handling. Future providers can reuse the same library choice rather than introducing multiple OAuth stacks.

### ADR-017: Google OAuth Callback Is Backend-Managed and Returns Existing JWT via Frontend Completion Exchange
- **Date:** 2026-04-02
- **Workstream:** P6-001
- **Status:** Accepted
- **Context:** Google SSO must keep `GOOGLE_CLIENT_SECRET` server-side, preserve the current JWT issuance model, and avoid exposing final bearer tokens in URL parameters. The frontend is a React SPA that already expects a standard `AuthResponse` payload from backend auth endpoints.
- **Decision:** The Google OAuth callback will be handled on the backend. The backend performs the code exchange, validates the Google identity, finds or creates the local user, and then redirects to a frontend completion route. The frontend completion route calls a backend exchange endpoint that returns the same `AuthResponse` shape used by existing login/register flows.
- **Reasoning:** Backend-managed callback handling keeps client secrets off the frontend, centralizes account linking near the database, and preserves the current bearer-token model without placing final JWTs into query strings.
- **Alternatives considered:** Frontend-handled OAuth callback and token exchange (rejected: exposes too much OAuth protocol logic to the frontend and complicates secret handling), backend callback redirecting with JWT in query param (rejected: poor token hygiene and leakage risk).
- **Consequences:** The auth flow gains a frontend callback page and a backend exchange endpoint, but downstream auth consumers remain unchanged because the final token is still produced by the existing JWT helper.

### ADR-018: OAuth Anti-CSRF Uses Signed State Cookie Comparison Rather Than Server Session Storage
- **Date:** 2026-04-02
- **Workstream:** P6-001
- **Status:** Accepted
- **Context:** Google OAuth requires CSRF protection via the `state` parameter. The current application does not already use server-side sessions and should avoid adding a session subsystem solely for one OAuth provider.
- **Decision:** Implement anti-CSRF by generating a short-lived signed state value, storing it in an HTTP-only SameSite=Lax cookie, sending the same value as the OAuth `state` parameter, and verifying signature, expiry, and exact match on callback.
- **Reasoning:** This is the smallest secure solution compatible with the existing JWT-oriented architecture. It avoids introducing session storage or a dedicated database state table while still providing robust CSRF protection.
- **Alternatives considered:** Server-side session storage for OAuth state (rejected: new subsystem for a small workstream), raw unsigned state nonce (rejected: too easy to tamper with).
- **Consequences:** The backend callback must clear the state cookie after verification and treat missing, invalid, or expired state as a hard auth failure. Reverse-proxy and cookie settings must be validated in production.

### ADR-019: Google SSO Auto-Links Accounts by Verified Email Match
- **Date:** 2026-04-02
- **Workstream:** P6-001
- **Status:** Accepted
- **Context:** The operator requires that existing email+password accounts continue to work and that a Google login with the same email not create a duplicate local account. The system already normalizes emails to lowercase and treats them as unique local identifiers.
- **Decision:** If Google returns a verified email that matches an existing local user, the Google identity is linked automatically to that existing user. If no matching user exists, a new user is created with `password_hash = null`. If the email is unverified, login fails.
- **Reasoning:** Automatic linking on verified email match is the simplest user-friendly rule that satisfies the operator requirement without adding explicit account-link management UI in the initial SSO workstream.
- **Alternatives considered:** Require manual account linking (rejected: worse UX and fails the operator’s automatic-link requirement), always create a new account (rejected: duplicate-account risk).
- **Consequences:** Email verification from Google becomes a security-critical claim. The implementation must be conservative and never auto-link on unverified email.

### ADR-020: External Provider Identities Live in `oauth_accounts`, Not on `users`
- **Date:** 2026-04-02
- **Workstream:** P6-001
- **Status:** Accepted
- **Context:** Google SSO requires storing Google’s stable subject ID. Hardcoding provider-specific columns like `google_sub` onto `users` would couple the core user model to a single provider and scale poorly when future identity providers are added.
- **Decision:** Add a separate `oauth_accounts` table keyed to `user_id` that stores provider name, provider user ID, provider email snapshot, verification flag, and login timestamps.
- **Reasoning:** A normalized identity-link table keeps `users` provider-neutral, supports future providers cleanly, and avoids schema sprawl on the primary account table.
- **Alternatives considered:** Add `google_sub` directly to `users` (rejected: provider-specific coupling and poor extensibility).
- **Consequences:** Google-created accounts remain ordinary `users` rows, while provider identities are linked through `oauth_accounts`. Future SSO providers can reuse the same table and API/service patterns.

### ADR-021: Delegated Connector OAuth Tokens Live in Encrypted Connector Storage, Not `oauth_accounts`
- **Date:** 2026-04-05
- **Workstream:** P7-002
- **Status:** Accepted
- **Context:** The first Google Drive connector needs a persistent refresh token. The project already has two related but distinct storage patterns: `oauth_accounts` for login identity linkage from Google SSO, and `source_connectors.credentials_encrypted` for per-source connector secrets. Storing Drive tokens in the wrong place would blur the boundary between app authentication and delegated external access.
- **Decision:** Store Google Drive refresh tokens only in encrypted per-source connector-secret storage (`source_connectors.credentials_encrypted`). Do not store delegated connector tokens in `oauth_accounts`.
- **Reasoning:** Drive connector tokens are source-scoped operational secrets, not user-login identity records. Keeping them in encrypted connector storage preserves the separation already established by ADR-014 and ADR-020 and avoids coupling login identity management to connector authorization state.
- **Alternatives considered:** Store Drive tokens in `oauth_accounts` (rejected: mixes login identity and connector authorization concerns), add a separate provider-token table now (rejected: unnecessary extra subsystem for the first OAuth-backed connector).
- **Consequences:** The Drive connector must own its own secret lifecycle. Future OAuth-backed connectors may reuse the same encrypted connector-secret pattern until there is enough evidence to justify a dedicated provider-token subsystem.

### ADR-022: Connector OAuth Initiation Uses Authenticated SPA Start and Signed Browser-Bound Callback State
- **Date:** 2026-04-05
- **Workstream:** P7-002
- **Status:** Accepted
- **Context:** The application is bearer-token based. A plain browser link to a protected connector OAuth start endpoint would create a fragile initiation boundary because top-level navigation is not the app’s normal authenticated API path. The callback also needs request binding and replay protection even though it is not an OpenID login flow.
- **Decision:** Connector OAuth initiation starts from an authenticated SPA API request that returns an authorization URL. The callback uses short-lived signed browser-bound state carrying `user_id`, `source_id`, issued-at timestamp, and one-time random context. No OIDC nonce is required because this is a delegated connector authorization flow, not a login identity flow.
- **Reasoning:** This preserves the existing bearer-token auth model, lets the backend validate source ownership before authorization begins, and provides strong callback request binding without introducing a session subsystem.
- **Alternatives considered:** Plain browser navigation to a protected backend start route (rejected: weak fit for bearer auth), server-side session storage for connector state (rejected: unnecessary new subsystem for this workstream).
- **Consequences:** The frontend must initiate the flow through the API client and then redirect the browser explicitly. The backend callback must treat missing, invalid, expired, or replayed state as a hard failure.

### ADR-023: `source_connectors` Uses Provider-Neutral Remote Container Semantics
- **Date:** 2026-04-05
- **Workstream:** P7-002
- **Status:** Accepted
- **Context:** The existing connector foundation stores S3-specific `bucket_name` in `source_connectors`. The first non-S3 connector, Google Drive, does not have buckets, and reusing `bucket_name` as a Drive folder/container identifier would immediately create misleading schema debt.
- **Decision:** Evolve `source_connectors` to use provider-neutral remote container semantics by renaming `bucket_name` to `remote_container_id` and adding nullable `remote_container_label`.
- **Reasoning:** This is the smallest schema change that removes S3-only naming while preserving the existing connector table structure and keeping future connectors reversible.
- **Alternatives considered:** Continue overloading `bucket_name` (rejected: misleading semantics and long-term debt), redesign the entire connector table now (rejected: unnecessary scope expansion for the first OAuth-backed connector).
- **Consequences:** Existing S3-compatible connector code and schemas must be migrated and regression-tested. Future connectors gain a clearer storage contract without forcing a full provider-specific config table split.

### ADR-024: First Google Drive Connector Slice Is Root-Only and Uses `drive.readonly`
- **Date:** 2026-04-05
- **Workstream:** P7-002
- **Status:** Accepted
- **Context:** Google Drive introduces provider-specific choices around folder picking, scope breadth, native document handling, and file eligibility. Without an explicit limit, the first Drive connector could quickly sprawl beyond the existing connector foundation’s intended expansion path.
- **Decision:** The first Google Drive connector slice is limited to `My Drive` root only and requests `drive.readonly` only. It excludes trashed files, shortcuts, and Google-native Docs/Sheets/Slides.
- **Reasoning:** Root-only plus `drive.readonly` is the smallest useful scope that proves delegated Drive ingestion without adding folder-selection UX, export logic for native document types, or broader permission requests.
- **Alternatives considered:** Folder-picker support in the first slice (rejected: extra provider-specific UI and API complexity), broader Drive scopes (rejected: unnecessary permission creep), Google-native docs support (rejected: not compatible with the current file-ingestion pipeline).
- **Consequences:** The first Drive connector delivers a narrower but cleaner capability. Folder targeting and additional Drive object types remain explicit future follow-up work rather than implicit scope creep.

### ADR-025: Connector Construction Uses a Registry/Factory and Dedicated Token Manager Without Introducing `OAuthConnectorBase`
- **Date:** 2026-04-05
- **Workstream:** P7-002
- **Status:** Accepted
- **Context:** The existing `sync_service` builds the S3 connector inline. Adding Google Drive would introduce provider branching and refresh-token behavior, but one OAuth-backed connector is not enough evidence to justify a new inheritance hierarchy such as `OAuthConnectorBase`.
- **Decision:** Keep `ConnectorBase` as the base abstraction. Add a connector registry/factory for provider construction and a dedicated Drive token manager for OAuth token lifecycle. Do not introduce `OAuthConnectorBase` in this workstream.
- **Reasoning:** The real architectural need now is separation of connector construction and token lifecycle concerns from sync orchestration, not a new class hierarchy. A small factory and token-manager boundary solve that with less complexity and remain reversible.
- **Alternatives considered:** Branch provider construction inside `sync_service` (rejected: orchestration drift), introduce `OAuthConnectorBase` immediately (rejected: speculative abstraction based on one OAuth-backed connector).
- **Consequences:** `sync_service` stays focused on orchestration. Future OAuth-backed connectors can either reuse the same pattern or, if several accumulate enough shared behavior, motivate a later ADR that introduces a broader OAuth connector abstraction.

### ADR-026: Source Mutation Completion Is Separate from Analysis Completion
- **Date:** 2026-04-05
- **Workstream:** P7-004
- **Status:** Accepted
- **Context:** The storage pivot changes the product contract: generated metadata and computed filenames are meant to be applied back to the source asset, not merely stored inside the app. If analysis success alone were treated as terminal completion, the system would misrepresent items whose source images were never actually updated.
- **Decision:** Source-mutation-aware items must track a completion state separate from analysis state. The canonical completion outcomes are `fully_applied`, `pending_writeback`, and `blocked_writeback`. Analysis success alone is insufficient to mark an item complete when source mutation is required.
- **Reasoning:** This keeps the product honest about whether the source image actually matches the app's computed end state and prevents silent drift between app metadata and source asset state.
- **Alternatives considered:** Treat analysis completion as the only terminal state and log write-back failures as warnings (rejected: hides material product failure); use a single generic warning state (rejected: loses the important distinction between retryable pending work and blocked flows requiring intervention).
- **Consequences:** Data model, orchestration, and UX all need explicit mutation-state support. Connections and item detail must surface these states clearly.

### ADR-027: Source Mutation History Must Preserve Original and Prior Filenames
- **Date:** 2026-04-05
- **Workstream:** P7-004
- **Status:** Accepted
- **Context:** The new product direction requires images to be renamed and enriched at the source. Once that happens, the application still needs to explain what the image used to be before the system changed it and to support auditability across cloud and local flows.
- **Decision:** The system must preserve durable source-mutation history including first-seen original filename, prior filename before each rename, current filename after successful rename, and the last successfully written metadata payload or equivalent revision marker.
- **Reasoning:** Without mutation history, the system cannot answer a core user and operator question: what did this image used to be before the app changed it? History also supports troubleshooting, rollback reasoning, and trustworthy status display.
- **Alternatives considered:** Store only the current filename (rejected: loses provenance), store only the first original filename (rejected: insufficient once multiple renames occur), infer history from external provider logs (rejected: incomplete and provider-dependent).
- **Consequences:** The data model needs mutation-history fields or tables. UI must expose enough history to explain current versus prior state without overwhelming the user.

### ADR-028: Storage Pivot Keeps Originals at Source and Prohibits Silent Permanent AWS Original Fallback
- **Date:** 2026-04-05
- **Workstream:** P7-004
- **Status:** Accepted
- **Context:** The storage pivot is meant to stop the product from acting like a long-term original-image host. Without an explicit ADR, implementation could drift back toward app-owned permanent originals whenever browser-local flows or cloud-source mutation become operationally awkward.
- **Decision:** Originals remain at their source system. AWS retains metadata, search/index state, and preview assets only. Browser drag-drop and local-folder flows must not silently fall back to permanent AWS original retention, and cloud write-back failures must not be "solved" by mutating a permanent AWS-hosted original instead of the source asset.
- **Reasoning:** This is the central architectural boundary of the storage pivot. Without locking it explicitly, later implementation pressure would almost certainly reintroduce the very storage model this redesign is meant to replace.
- **Alternatives considered:** Continue storing permanent originals in AWS for convenience (rejected: contradicts the new product direction), allow silent permanent-copy fallback only for local/browser flows (rejected: creates a hidden second product model and misleading user expectations).
- **Consequences:** Source-mutation failures must surface as `pending_writeback` or `blocked_writeback`. Preview retention remains allowed, but permanent original retention does not.

### ADR-029: P7-004 Expands Google Drive from `drive.readonly` to a Writable Mutation-Capable Grant
- **Date:** 2026-04-05
- **Workstream:** P7-004
- **Status:** Accepted
- **Context:** P7-002 deliberately shipped a narrow Google Drive connector foundation using root-only `My Drive` and `drive.readonly`. P7-004 requires source rename and embedded metadata mutation, which cannot be satisfied under the completed read-only grant.
- **Decision:** P7-004 includes a Google Drive writable-scope upgrade and re-consent path for mutation-capable sources, plus the rewrite-and-reupload path needed for embedded metadata mutation. Existing connectors that remain on the P7-002 read-only grant may continue to sync and analyze, but they must be treated as `blocked_writeback` when source mutation is required.
- **Reasoning:** This preserves the value of the completed P7-002 foundation while making the new source-mutation contract implementable without pretending read-only connectors can satisfy it.
- **Alternatives considered:** Exclude Google Drive from `fully_applied` in P7-004 (rejected: leaves a central intake flow outside the workstream’s own contract), rewrite P7-002 as if it had always been writable (rejected: historically false and needlessly disruptive).
- **Consequences:** Engineer must implement reauthorization handling, writable-scope persistence, and explicit blocked-state UX for legacy read-only connectors.

### ADR-030: Cloud Metadata Fallback Counts Only When It Writes Back to the Source System
- **Date:** 2026-04-05
- **Workstream:** P7-004
- **Status:** Accepted
- **Context:** Some cloud providers do not support cheap native embedded metadata mutation, and some mutation paths may be lossy or intentionally deferred. Without a locked fallback rule, `fully_applied`, `pending_writeback`, and `blocked_writeback` would be inconsistently interpreted across providers.
- **Decision:** For cloud sources, `fully_applied` requires source rename plus either successful embedded metadata write-back or successful operator-approved provider-specific fallback written to the source system itself. App-only metadata persistence and permanent AWS original retention never satisfy fallback. `pending_writeback` is reserved for safe queued mutation or approved fallback writes that need no user action; `blocked_writeback` is required when writable permission is missing, no approved fallback exists, or the mutation path is unsafe or terminally failed.
- **Reasoning:** This keeps the completion states honest while still giving the operator a structured way to support provider differences without redefining the storage pivot.
- **Alternatives considered:** Treat app-side metadata as good enough for `fully_applied` (rejected: source and app would diverge), require embedded rewrite for every provider with no fallback concept at all (rejected: too rigid for future provider diversity).
- **Consequences:** Each provider needs an explicit write-back mode decision, and the UI/data model must record whether completion happened through embedded mutation or provider-approved source fallback.

### ADR-031: Phase 9 Remediation Closes the Connector Ingestion Boundary Before Domain Cleanup
- **Date:** 2026-04-08
- **Workstream:** Phase 9 / P9-001 through P9-004
- **Status:** Accepted
- **Context:** After Phase 8 completion, the live code still routed connector ingestion through `upload_service.process_upload()`, which transiently persisted full originals before later deleting them. Several consumer paths still assumed app-retained originals, and the ARCH-002 additive domain split had not yet been built. The operator needed to decide whether to close the ingestion-boundary violation immediately, what retry contract to use once transient originals disappear, how storage-assuming features should behave meanwhile, whether to do a big-bang model rewrite, and whether already-retained originals require cleanup.
- **Decision:** Phase 9 begins by closing the transient connector-original write gap now. The long-term retry contract is source re-fetch rather than app-retained original replay, though synchronous sync-flow analysis is allowed as a short-term rollout tactic if needed for the first zero-transient slice. Storage-assuming features should return controlled source-aware errors first unless on-demand source fetch is already cheap and reliable enough for that surface. Domain evolution remains additive: fix the ingestion boundary first, then add structured origin and preview models behind the existing `MediaItem` aggregate. Operational audit/cleanup of already-retained connector originals is required.
- **Reasoning:** The transient-write gap is the direct ARCH-002 violation and should be removed before further model cleanup inherits the wrong boundary. Source re-fetch preserves the approved source-of-truth architecture without rebuilding a hidden storage dependency. Controlled source-aware errors keep the product honest while individual surfaces are hardened. Additive evolution reduces migration and rollout risk in a live beta system with existing data.
- **Alternatives considered:** Defer the ingestion fix until after a full domain-model rewrite (rejected: prolongs the architectural violation), preserve transient or hidden retained originals to support retries (rejected: reintroduces the very dependency Phase 9 is supposed to remove), implement broad on-demand source fetch everywhere before hardening error paths (rejected: too much coupling and rollout risk for the first slice), replace `MediaItem` wholesale up front (rejected: unnecessary destabilization).
- **Consequences:** `P9-001 — Zero-Transient Connector Ingestion` becomes the immediate next workstream. `P9-002` must harden storage-assuming features explicitly. Later domain and write-back cleanup must build on the corrected ingestion boundary rather than replace it.
