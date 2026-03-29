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
