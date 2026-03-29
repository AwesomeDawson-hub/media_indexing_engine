# Project AI Context — Media Indexing Engine

_This document defines the AI operating context for this specific project. It tells AI assistants what the project is, what it values, and how to behave when working on it._

_This is the **project-level** AI context. The **framework-level** AI context lives in the launcher at `Project Launcher/project_launcher/docs/AI_CONTEXT.md` and governs cross-project rules. This document governs project-specific behavior only._

## Project Identity

**Name:** Media Indexing Engine
**Description:** An AI-powered system that analyzes photos and videos, enriches their metadata, and enables fast semantic search across large media libraries.
**Location:** `Projects/media_indexing_engine/`

## Target Users

**Primary:**
- Photographers managing large volumes of photos who need automated organization, tagging, and retrieval
- Marketing teams who need to quickly find relevant, high-quality images for campaigns and content

**Secondary:**
- Content teams and small businesses managing growing media libraries

## Success Criteria

The project is successful when:

- Users can upload or connect a media source (folder, SD card, or cloud) and process it without manual tagging
- Media is automatically enriched with meaningful metadata (objects, scenes, context)
- Users can find specific images using natural language queries (e.g., "team meeting in office," "sunset beach portrait")
- Search results are relevant and returned quickly (within a few seconds)
- The interface is simple enough that a non-technical user can complete ingestion and search without guidance
- Previously processed media is not redundantly re-analyzed (deduplication / caching)

**Stretch:**
- The system handles large batches (thousands of files) reliably
- The system minimizes repeated AI inference through caching and efficient processing

## Constraints

- **Platform:** Web-based interface (hosted), accessible via browser
- **Auth:** Login required; subscription model deferred or basic in V1
- **Input sources (V1):** Local folder upload and drag-and-drop; cloud integrations (Google Drive) deferred
- **Media types:** Images first; video support limited or deferred in V1
- **AI Models:** Use existing vision models (no custom model training in V1)
- **Storage:** Cloud-based storage and metadata indexing required
- **Performance:** Must support batch uploads; extreme scale optimization not required in V1
- **Deduplication:** Must avoid reprocessing identical files (hash-based or equivalent)
- **Timeline:** Functional, user-friendly MVP before optimization or expansion

## Engineering Goals

_Ordered by priority._

1. Functional end-to-end pipeline (upload → analyze → search)
2. Reliable AI metadata extraction with structured output
3. Fast, relevant semantic search
4. Simple, intuitive user interface
5. Efficient processing (deduplication, caching, batch support)

## Development Philosophy

Changes should be:

- MVP-first — get the pipeline working end-to-end before optimizing
- Incremental — build each layer on a proven foundation
- Testable — each component should be independently verifiable
- User-focused — prioritize the experience of non-technical users

## Architecture Direction

The system is built as a layered pipeline:

```
Ingestion → AI Analysis → Indexing → Search → UI
```

Each layer is a distinct module with clear boundaries. The API layer connects them. The architecture should support swapping AI providers, vector databases, or storage backends without rewriting the pipeline.

## How AI Should Assist

When working on this project:

- Follow the approved workstream plan for the current phase (see `docs/WORKSTREAMS.md` for active work)
- Build each layer to be independently testable before integrating
- Prefer existing, proven libraries over custom implementations
- Keep the API surface clean — frontend should only talk to the API, never directly to internal modules
- Document non-obvious decisions in the project-level `docs/DECISION_LOG.md`

## What AI Must NOT Do

1. Never skip deduplication — every file must be checked before processing
2. Never store API keys or credentials in code — use environment variables
3. Never send unvalidated files to the AI vision API — validate format and size first
4. Never create project governance docs outside `docs/` — governance stays in the launcher
5. Never modify the launcher's framework documents without explicit operator approval
6. Never implement a list or search endpoint without scoping it to the authenticated user's `user_id` at the **database layer** — ChromaDB filters and application-layer checks are supplementary, not a substitute (see ADR-012)

## Document Ownership Note

This document owns **project-specific AI context only**. It does not duplicate:
- Framework rules → see launcher `AI_CONTEXT.md`
- Current system status → see project `docs/CURRENT_STATE.md`
- Work tracking → see project `docs/WORKSTREAMS.md`
- Architecture decisions → see project `docs/DECISION_LOG.md`
