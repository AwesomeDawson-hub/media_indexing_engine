# Phase Plan: Phase 1 — MVP

## Objective

Deliver a functional MVP of the Media Indexing Engine: users can upload images, have them automatically analyzed by AI, and search their library using natural language queries. The system must be web-accessible, authenticated, and handle deduplication.

## Scope

### In Scope
- Local file upload and drag-and-drop ingestion
- File validation (supported image formats) and hash-based deduplication
- Cloud storage for uploaded media
- AI vision model integration for metadata extraction (objects, scenes, context)
- Structured metadata persistence (database)
- Vector embedding generation and storage for semantic search
- Natural language search query processing and ranked results
- REST API connecting all services
- Basic authentication (login/signup)
- Simple web UI: upload, browse library, search
- Batch upload support (multiple files at once)

### Out of Scope
- Video analysis (deferred)
- Cloud source integrations (Google Drive, Dropbox — deferred)
- Custom model training
- Subscription/billing system
- Advanced admin dashboard
- Mobile-native apps
- Extreme scale optimization (10k+ concurrent users)
- EXIF/GPS enrichment beyond AI analysis (potential future enhancement)

## Constraints

- **Language/Stack:** Python backend (FastAPI recommended), modern JS/TS frontend (React or similar)
- **AI Models:** Use existing vision APIs (OpenAI GPT-4o, Anthropic Claude, or Google Gemini) — no custom training
- **Storage:** Cloud-based (S3-compatible or equivalent); local filesystem for dev
- **Vector DB:** ChromaDB, Qdrant, or Pinecone for semantic search
- **Database:** PostgreSQL for metadata (SQLite for local dev)
- **Auth:** JWT-based, simple email/password for V1
- **Timeline:** MVP-first — functional over polished
- **Performance:** Search results within a few seconds; batch upload must not block the UI

## Workstreams

| ID | Name | Objective | Dependencies | Size |
|---|---|---|---|---|
| WS-000 | Core Foundations | Prior art extraction, media identity model, metadata schema, storage model, DB schema, project setup, API scaffold | None | S |
| WS-001 | Ingestion Pipeline | File upload, validation, hashing, deduplication, file storage, background task pattern, upload API endpoints | WS-000 | M |
| WS-002 | AI Analysis Pipeline | Vision model integration, metadata extraction, structured output to DB, analysis API endpoints | WS-001 | M |
| WS-003 | Search & Retrieval | Embedding generation, vector indexing, natural language query, search API endpoint | WS-002 | M |
| WS-004 | Auth & API Hardening | Authentication middleware, API security, error handling, rate limiting, dev/demo mode | WS-001 | S |
| WS-005 | Frontend MVP | Upload UI, library browser, search interface | WS-003, WS-004 | M |

### WS-000: Core Foundations — Detail

WS-000 establishes the foundational decisions and shared abstractions that all subsequent workstreams depend on. It is small in code output but load-bearing for the entire phase.

#### Prior Art Extraction (Required)

Before defining the media identity model, metadata schema, or storage model, you MUST review the previous project at `Projects/marketing_asset_pipeline/` and extract reusable architectural patterns.

**Step 1 — Review the previous project.** Read:
- `app/pipeline.py` — ingestion patterns, hashing, deduplication, slug protection
- `app/schema.py` — metadata schema structure
- `app/db.py` — storage model, database design, asset identity
- `app/claude_vision.py` — AI integration patterns, image preparation, retry logic
- `app/semantic_search.py` — embedding generation, cache invalidation strategy
- `docs/ENGINEERING_PLAYBOOK.md` — safety mechanisms, what worked operationally

**Step 2 — Identify reusable components and decisions:**
- File identity strategy (hashing approach, what constitutes a unique asset)
- Metadata schema structures (fields, types, validation)
- Ingestion patterns (file validation, format handling, batch processing)
- Analysis pipeline patterns (AI output parsing, repair, normalization)
- Storage design decisions (database as system of record, multi-layer storage)
- What worked well and what caused issues

**Step 3 — Classify each finding:**
- **What worked** (keep or adapt for this project)
- **What failed** (avoid or redesign)
- **What must be redesigned** (patterns that fit the old project but not the new one)

**Step 4 — Produce a "Prior Art Summary"** as a required WS-000 deliverable:
- Reused decisions (adopted as-is with rationale)
- Modified decisions (adapted with explanation of what changed and why)
- Rejected decisions (not carried forward with justification)

**Step 5 — Use the summary to inform** the remaining WS-000 deliverables:
- Media identity model
- Metadata schema
- Storage model

**Constraints on prior art extraction:**
- Do NOT blindly copy code — extract patterns and decisions, not implementations
- Focus on architectural patterns, not project-specific details (marketing metadata fields, Streamlit UI, etc.)
- Ensure all reused patterns align with the current project's goals and constraints
- Prefer reuse over reinvention where the pattern is proven and applicable
- Record all reuse decisions in the project's `DECISION_LOG.md`

#### Remaining WS-000 Deliverables

After prior art extraction is complete:

1. **Media identity model** — how a file is uniquely identified (informed by prior art SHA256 approach)
2. **Metadata schema** — the structured output format that AI analysis produces, search indexes, and the API serves
3. **Storage model** — the relationship between file storage, metadata database, and vector store
4. **Database schema** — initial table design for media items and metadata
5. **Project setup** — environment configuration, dependency management, dev tooling
6. **API scaffold** — FastAPI application skeleton with core route structure (each subsequent workstream adds its endpoints)

## Implementation Order

1. **WS-000: Core Foundations** — No dependencies. Establishes shared abstractions: prior art review, identity model, metadata schema, storage model, project setup, and API scaffold. Must complete before any other workstream begins.
2. **WS-001: Ingestion Pipeline** — Depends on WS-000. Builds file upload, validation, deduplication, and storage on top of the defined identity model and storage model. Delivers upload API endpoints and background task pattern.
3. **WS-002: AI Analysis Pipeline** — Depends on WS-001. Sends stored files through vision AI, produces structured metadata conforming to the defined schema, writes to database. Delivers analysis API endpoints.
4. **WS-003: Search & Retrieval** — Depends on WS-002. Generates embeddings from enriched metadata, stores in vector DB, exposes natural language search. Delivers search API endpoint.
5. **WS-004: Auth & API Hardening** — Depends on WS-001. Adds authentication middleware, error handling, rate limiting, and dev/demo mode to the existing API. Can run in parallel with WS-002/003.
6. **WS-005: Frontend MVP** — Depends on WS-003 and WS-004. Consumes the hardened, authenticated API to provide upload, browse, and search UI.

## Exit Criteria

All of the following must be true to close this phase:

- [ ] All workstreams in this phase are completed per closeout checklist
- [ ] A user can upload images via the web UI
- [ ] Uploaded images are automatically analyzed and enriched with metadata
- [ ] Duplicate files are detected and not reprocessed
- [ ] A user can search their library with natural language and get relevant results within seconds
- [ ] Authentication prevents unauthorized access
- [ ] `CURRENT_STATE.md` reflects the new phase
- [ ] Phase closeout checklist is satisfied

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Vision API costs escalate with large batches | Medium | Implement caching, batch size limits, and cost tracking early |
| Semantic search quality is poor for niche queries | Medium | Test with diverse query types early; tune embedding model/prompt |
| File upload UX is clunky for large batches | Medium | Use chunked/resumable uploads; show progress feedback |
| Vector DB choice doesn't scale well | Low | Abstract the vector store behind an interface for easy swapping |
| Auth adds friction to MVP testing | Low | Provide a dev/demo mode that bypasses auth for local testing |

## Notes

- Tech stack decisions (specific framework, vector DB, cloud provider) will be finalized during WS-001 planning and recorded in the Decision Log.
- The API layer (WS-004) can be partially scaffolded early, but full integration testing happens after WS-001/002/003 are complete.
- The frontend (WS-005) should be kept minimal — functional over polished. Design refinement is a Phase 2 concern.
