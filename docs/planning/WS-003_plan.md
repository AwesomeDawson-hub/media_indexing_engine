# Workstream Plan: WS-003 — Search & Retrieval

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-003 |
| **Phase** | Phase 1 — MVP |
| **Project** | Media Indexing Engine |
| **Dependencies** | WS-002 (AI Analysis Pipeline) — Completed |
| **Estimated Size** | Medium |
| **Created** | 2026-03-27 |
| **Status** | Draft — awaiting operator review |

## Objective

Build the search and retrieval pipeline: generate text embeddings from AI-extracted metadata, index them in a vector database (ChromaDB for dev), expose a natural language search endpoint that returns ranked results with relevance scores. Embedding generation must happen automatically when analysis completes and update when metadata changes via re-analysis.

## Scope

### In Scope

- Embedding text construction — combine metadata fields into a rich text document for embedding
- Embedding generation via a sentence-transformer model (local, no external API)
- Vector store abstraction (`VectorStore` protocol) for future backend swaps
- ChromaDB implementation for dev (per ADR-006)
- Auto-indexing — after analysis completes, generate embedding and index the media item
- Re-indexing — after re-analysis, update the existing embedding
- Natural language query processing — embed the query, search vector store, return ranked results
- Search API endpoint: `GET /api/v1/search?q=...` with pagination and relevance scores
- User-scoped search — users only see their own media in results
- Configuration additions: `search` section in settings (provider, collection name, embedding model, top_k)

### Out of Scope

- Authentication (WS-004 — continue using dev user)
- Frontend search UI (WS-005)
- Advanced query syntax (filters, facets, date ranges — Phase 2)
- Hybrid search (combining vector + keyword/full-text — Phase 2)
- Multi-modal embeddings from image pixels (we embed the text metadata, not the image itself)
- Qdrant or Pinecone backends (ChromaDB only for MVP; interface supports future addition)
- Embedding model fine-tuning
- Cross-user search or shared libraries

## Constraints

- **Vector DB:** ChromaDB (embedded, no external service for dev) per ADR-006
- **Embedding model:** `all-MiniLM-L6-v2` via `sentence-transformers` (384-dim, fast, good quality for short text). Runs locally — no external API call needed.
- **Embedding source:** Text only — constructed from the 13 metadata fields in `media_metadata`. Not from the image itself.
- **Search scope:** Per-user. A search query returns only the requesting user's media items.
- **Result limit:** Configurable `top_k` (default 20). Paginated via `page` and `per_page` query params.
- **Latency target:** Search results within a few seconds (per project success criteria).
- **No external services:** Both ChromaDB and sentence-transformers run locally — no API keys needed for search.

## Governing Decisions

| ADR | Decision | Impact on WS-003 |
|---|---|---|
| ADR-002 | Database as sole system of record | Metadata lives in DB; vector store is derived and rebuildable |
| ADR-005 | Metadata schema (13 fields) | Defines the text fields used to construct the embedding document |
| ADR-006 | Three-store architecture | ChromaDB for vectors (dev); vector store is the third store |

## Architecture Overview

```
Analysis completes (WS-002)
    │
    ▼
Embedding text constructed from media_metadata fields
    │
    ▼
Sentence-transformer encodes text → 384-dim vector
    │
    ▼
Vector + metadata stored in ChromaDB (keyed by media_item_id, filtered by user_id)
    │
    ▼
Search query → embed query text → ChromaDB similarity search (filtered by user_id)
    │
    ▼
Ranked results with scores → join with DB for full media item details → API response
```

**Key design principle (ADR-006):** The vector store is **derived** from the database. It can be completely rebuilt from `media_metadata` at any time. The database remains the system of record. If vector store data is lost, a rebuild script regenerates all embeddings from the DB.

## Embedding Text Construction

The embedding document is a single text string composed from the metadata fields, weighted by search relevance:

```
{title}

{description}

Tags: {tags joined by ", "}
Objects: {objects joined by ", "}
Scenes: {scenes joined by ", "}
Context: {context}
Mood: {mood}
Colors: {colors joined by ", "}
People: {people joined by ", "} ({people_count} people)
Orientation: {orientation}
Location: {location_hint or "Unknown"}
```

**Design rationale:**
- Title and description appear first — they carry the highest semantic weight in most embedding models.
- Each field is labeled (e.g., "Tags:", "Objects:") to give the embedding model context about what the terms mean.
- `quality_notes` is excluded — it describes image defects, not searchable content.
- `location_hint` uses "Unknown" as fallback so the field structure is consistent.
- Lists are comma-joined for natural reading.

## Vector Store Design

### ChromaDB Collection Structure

- **Collection name:** `media_embeddings` (configurable)
- **ID:** `media_item_id` (string) — one embedding per media item
- **Embedding:** 384-dimensional float vector from sentence-transformer
- **Metadata stored in ChromaDB:**
  - `user_id` (string) — for filtering search to the requesting user
  - `title` (string) — for result display without a DB round-trip
  - `original_filename` (string) — for result display
- **Document:** The full embedding text (stored for debugging/inspection)

### Why store `user_id` in ChromaDB metadata?

ChromaDB supports `where` filters on metadata. Filtering by `user_id` at query time is more efficient than fetching all results and filtering in Python. This is the standard pattern for multi-tenant vector search.

### Upsert Pattern

- **New analysis:** `collection.upsert(ids=[media_item_id], embeddings=[vector], metadatas=[...], documents=[text])`
- **Re-analysis:** Same upsert call — ChromaDB's `upsert` overwrites by ID.
- **No delete needed for update** — upsert handles both insert and update atomically.

## Search Flow

```
User sends: GET /api/v1/search?q=sunset beach portrait

1. Embed query text using the same sentence-transformer model
2. Query ChromaDB:
   collection.query(
       query_embeddings=[query_vector],
       n_results=top_k,
       where={"user_id": current_user_id}
   )
3. Receive ranked results with distances
4. Convert distances to relevance scores (1 - distance for cosine, normalized)
5. Load full media item details from DB for each result ID
6. Return combined response: media item + metadata + relevance score
```

## API Endpoint

### `GET /api/v1/search`

Search media items using natural language.

**Query params:**
- `q` (required) — natural language search query
- `page` (optional, default 1) — page number
- `per_page` (optional, default 20, max 50) — results per page

**Response (200):**
```json
{
  "query": "sunset beach portrait",
  "total": 3,
  "page": 1,
  "per_page": 20,
  "results": [
    {
      "media_item": {
        "id": "uuid",
        "original_filename": "sunset_beach.jpg",
        "mime_type": "image/jpeg",
        "status": "completed",
        "created_at": "2026-03-27T12:00:00Z"
      },
      "metadata": {
        "title": "Golden Sunset on Pacific Beach",
        "description": "A vibrant sunset over a sandy beach ...",
        "tags": ["sunset", "beach", "ocean"],
        "mood": "serene"
      },
      "score": 0.87
    }
  ]
}
```

**Notes on response shape:**
- `metadata` in search results is a subset — `title`, `description`, `tags`, and `mood`. Full metadata available via `GET /api/v1/media/{id}/analysis`.
- `score` is a normalized relevance score (0.0 to 1.0, higher = more relevant).
- Results are ordered by score descending.
- Empty query returns 400.
- No results returns 200 with empty `results` array.

**Error responses:**
- `400` — Missing or empty `q` parameter

## Configuration Additions

New `search` section in `settings.yaml` and `config.py`:

```yaml
search:
  provider: "chromadb"
  collection_name: "media_embeddings"
  embedding_model: "all-MiniLM-L6-v2"
  top_k: 20
  persist_directory: "./chromadb_data"
```

```python
@dataclass
class SearchConfig:
    provider: str = "chromadb"
    collection_name: str = "media_embeddings"
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = 20
    persist_directory: str = "./chromadb_data"
```

## Integration with Analysis Pipeline

WS-003 hooks into WS-002's analysis processor so that embedding generation happens automatically after analysis completes. The integration point is in `processor.py`:

**After metadata upsert (Step 6 in processor flow):**
1. Construct embedding text from the metadata result.
2. Generate embedding via sentence-transformer.
3. Upsert into ChromaDB.

This means:
- **New upload → analysis → auto-indexed.** No manual step needed.
- **Re-analysis → metadata updated → embedding re-indexed.** Keeps search in sync.
- **If indexing fails, analysis still succeeds.** Vector store is derived — it can be rebuilt. A failed index logs a warning but does not fail the processing job.

The processor change is minimal: after the `_upsert_metadata` call, invoke the indexing service. The indexing service is a separate module — the processor does not know about ChromaDB directly.

## Implementation Steps

Each step has a validation checkpoint. Do not proceed to the next step until the current step's validation passes.

### Step 1: Dependencies and Configuration

**What:** Add `chromadb` and `sentence-transformers` to project dependencies. Add `SearchConfig` to the settings system. Add `search` section to settings files.

**Files to modify:**
- `pyproject.toml` — add `chromadb`, `sentence-transformers`
- `src/config.py` — add `SearchConfig` dataclass, add to `Settings`, add to `load_settings()`
- `config/settings.yaml` — add `search` section
- `config/settings.example.yaml` — add `search` section

**Validation:**
- [ ] `pip install` succeeds with new dependencies
- [ ] `import chromadb` works
- [ ] `from sentence_transformers import SentenceTransformer` works
- [ ] `settings.search.provider` returns `"chromadb"`
- [ ] `settings.search.embedding_model` returns `"all-MiniLM-L6-v2"`

### Step 2: Embedding Text Builder

**What:** Create the module that constructs embedding text from a `MediaMetadataResult` or from the DB `MediaMetadata` model.

**Files to create:**
- `src/search/embedding_text.py`:
  - `build_embedding_text(metadata: MediaMetadataResult) → str` — from Pydantic result (used during analysis flow)
  - `build_embedding_text_from_db(meta: MediaMetadata) → str` — from ORM model (used during rebuild)

**Validation:**
- [ ] Given a complete metadata result, produces a well-formatted text document
- [ ] Title and description appear first
- [ ] All searchable fields included, `quality_notes` excluded
- [ ] JSON array fields (tags, objects, etc.) are comma-joined
- [ ] Null `location_hint` → "Unknown" fallback
- [ ] Empty `people` list → gracefully handled (no crash, no "People: ")

### Step 3: Embedding Generator

**What:** Create the embedding generation module using sentence-transformers.

**Files to create:**
- `src/search/embedder.py`:
  - `Embedder` class wrapping `SentenceTransformer`
  - `embed_text(text: str) → list[float]` — encode single text to 384-dim vector
  - `embed_texts(texts: list[str]) → list[list[float]]` — batch encode for rebuild
  - Model loaded once at init, reused across calls

**Validation:**
- [ ] `Embedder` loads `all-MiniLM-L6-v2` model successfully
- [ ] `embed_text("sunset on a beach")` returns list of 384 floats
- [ ] Same text produces same embedding (deterministic)
- [ ] Different texts produce different embeddings
- [ ] Batch encode returns correct number of embeddings

### Step 4: Vector Store Interface and ChromaDB Implementation

**What:** Create the `VectorStore` protocol and the `ChromaDBVectorStore` implementation.

**Files to create:**
- `src/search/vector_store.py` — `VectorStore` protocol:
  - `upsert(media_item_id, embedding, metadata, document) → None`
  - `search(query_embedding, user_id, top_k) → list[SearchHit]`
  - `delete(media_item_id) → None`
  - `count() → int`
- `src/search/chromadb_store.py` — `ChromaDBVectorStore` implementation:
  - Init: create/get ChromaDB collection with persistent storage
  - `upsert`: uses `collection.upsert()` with id, embedding, metadata, document
  - `search`: uses `collection.query()` with `where={"user_id": user_id}` filter
  - `delete`: uses `collection.delete()` by id
  - `count`: uses `collection.count()`
- `src/search/models.py` — `SearchHit` dataclass (media_item_id, score, metadata)

**Validation:**
- [ ] ChromaDB collection created/opened without error
- [ ] Upsert adds a document; count increases
- [ ] Search with matching query returns the upserted document
- [ ] Search with `user_id` filter excludes other users' documents
- [ ] Delete removes the document; count decreases
- [ ] Upsert same ID twice → one document (update, not duplicate)
- [ ] Persistent storage: data survives restart (directory-based persistence)

### Step 5: Indexing Service

**What:** Create the indexing service that orchestrates text construction → embedding → vector store upsert. This is the module the processor calls.

**Files to create:**
- `src/search/indexing_service.py`:
  - `IndexingService` class (takes `Embedder` and `VectorStore`)
  - `index_media_item(media_item_id, user_id, original_filename, metadata_result) → None`
    - Build embedding text → generate embedding → upsert to vector store
  - `remove_media_item(media_item_id) → None`
    - Delete from vector store

**Validation:**
- [ ] `index_media_item()` with valid metadata → document appears in vector store
- [ ] After indexing, search for a relevant query → media item found
- [ ] After indexing with same ID (re-index) → only one document, content updated
- [ ] `remove_media_item()` → document removed from vector store

### Step 6: Hook Into Analysis Processor

**What:** Modify the analysis processor to auto-index after metadata persistence. Add indexing service initialization.

**Files to modify:**
- `src/analysis/processor.py` — after `_upsert_metadata()` succeeds, call `indexing_service.index_media_item()`. If indexing fails, log warning but do not fail the job.
- `src/api/routes/upload.py` — instantiate `IndexingService` at module level (same pattern as `_vision_provider`)
- `src/api/routes/analysis.py` — pass indexing service to reanalyze flow

**Integration pattern:**
```python
# In processor.py, after _upsert_metadata:
try:
    indexing_service.index_media_item(
        media_item_id=media_item.id,
        user_id=media_item.user_id,
        original_filename=media_item.original_filename,
        metadata_result=metadata_result,
    )
except Exception as e:
    logger.warning("Indexing failed for %s (non-fatal): %s", media_item.id, e)
```

**Validation:**
- [ ] Upload new image → analysis runs → embedding indexed in ChromaDB
- [ ] Re-analyze → embedding updated in ChromaDB
- [ ] If ChromaDB is unavailable → analysis still completes (warning logged, not failed)
- [ ] ChromaDB collection count matches number of analyzed media items

### Step 7: Search Service

**What:** Create the search service that processes a natural language query and returns ranked results with DB-joined details.

**Files to create:**
- `src/search/search_service.py`:
  - `SearchService` class (takes `Embedder`, `VectorStore`)
  - `search(query, user_id, db, page, per_page) → SearchResult`
    1. Embed query text
    2. Query vector store with user_id filter
    3. Load media items + metadata from DB for matched IDs
    4. Combine into ranked results with scores
  - `SearchResult` — total count, page, results list
  - `SearchResultItem` — media item info + metadata subset + score

**Validation:**
- [ ] Index 3 images with different metadata, search for one topic → correct item ranked first
- [ ] Score is normalized 0.0–1.0, higher = more relevant
- [ ] User A's search does not return User B's items
- [ ] Empty results → valid response with empty list
- [ ] Pagination: page 2 with per_page 1 → returns second result

### Step 8: Search API Endpoint

**What:** Create the search API endpoint.

**Files to create/modify:**
- `src/api/routes/search.py` — `GET /api/v1/search`
- `src/api/schemas.py` — add `SearchResponse`, `SearchResultItemResponse` models
- `src/api/app.py` — register search router

**Validation:**
- [ ] `GET /api/v1/search?q=sunset` → 200 with ranked results
- [ ] `GET /api/v1/search` (no q param) → 400
- [ ] `GET /api/v1/search?q=` (empty q) → 400
- [ ] `GET /api/v1/search?q=xyznonexistent` → 200 with empty results
- [ ] `GET /api/v1/search?q=beach&page=1&per_page=5` → paginated response
- [ ] Results include `score`, `media_item`, and `metadata` subset

### Step 9: Rebuild Script

**What:** Create a script that rebuilds the entire vector store from the database. This proves the "derived store" principle from ADR-006 — if ChromaDB data is lost, it can be fully regenerated.

**Files to create:**
- `scripts/rebuild_vector_store.py`:
  - Load all `media_metadata` records from DB (joined with `media_items` for user_id)
  - For each: build embedding text → generate embedding → upsert to vector store
  - Print progress and summary

**Validation:**
- [ ] Delete ChromaDB data directory
- [ ] Run rebuild script
- [ ] Vector store count matches DB count of analyzed media items
- [ ] Search works correctly after rebuild

### Step 10: Integration Testing

**What:** End-to-end tests that exercise the full search flow through the API.

**Files to create/modify:**
- `tests/test_search.py` — search integration tests
- `tests/conftest.py` — add search fixtures (in-memory ChromaDB, embedder, indexing service)

**Test cases:**
- [ ] Upload + analyze (mock) + search → item found with relevant query
- [ ] Search returns correct score ordering (most relevant first)
- [ ] Search is user-scoped (user A's items not visible to user B)
- [ ] Search with no matches → 200, empty results
- [ ] Missing query param → 400
- [ ] Pagination works correctly
- [ ] Re-analysis updates search results (re-indexed)
- [ ] Multiple items indexed → search ranks correctly

### Step 11: PROJECT_MAP and Documentation Update

**What:** Update `PROJECT_MAP.md` with the implemented search modules.

**Files to modify:**
- `docs/PROJECT_MAP.md` — document `src/search/` module files and responsibilities

**Validation:**
- [ ] `src/search/` section lists all new files with responsibilities
- [ ] Architecture Direction updated to reflect vector search integration
- [ ] No stale references

## Module Dependency Graph

```
src/config.py                         ← SearchConfig added (Step 1)
src/search/
  embedding_text.py                   ← text construction from metadata (Step 2)
  embedder.py                         ← sentence-transformer wrapper (Step 3)
  models.py                           ← SearchHit dataclass (Step 4)
  vector_store.py                     ← VectorStore protocol (Step 4)
  chromadb_store.py                   ← ChromaDB implementation (Step 4)
  indexing_service.py                 ← orchestrator: text → embed → upsert (Step 5)
  search_service.py                   ← query → embed → search → join DB (Step 7)
src/analysis/
  processor.py                        ← modified: calls indexing_service after metadata upsert (Step 6)
src/api/
  app.py                              ← search router registered (Step 8)
  schemas.py                          ← SearchResponse added (Step 8)
  routes/search.py                    ← GET /api/v1/search (Step 8)
  routes/upload.py                    ← IndexingService instantiation (Step 6)
scripts/
  rebuild_vector_store.py             ← full rebuild from DB (Step 9)
```

**Dependency flow within `src/search/`:**
```
search_service.py
  ├── embedder.py (encode query)
  ├── vector_store.py (search)
  └── models.py (SearchHit)

indexing_service.py
  ├── embedding_text.py (construct text)
  ├── embedder.py (encode text)
  └── vector_store.py (upsert)

chromadb_store.py
  └── vector_store.py (implements protocol)
```

## Exit Criteria

All of the following must be true to close WS-003:

- [ ] Embedding text builder produces correct documents from all 13 metadata fields
- [ ] Sentence-transformer generates 384-dim embeddings locally (no external API)
- [ ] `VectorStore` interface defined; `ChromaDBVectorStore` implements it
- [ ] ChromaDB collection created with persistent storage
- [ ] Auto-indexing: analysis completion triggers embedding generation and vector store upsert
- [ ] Re-indexing: re-analysis updates the existing embedding (no duplicates)
- [ ] `GET /api/v1/search?q=...` returns ranked results with relevance scores
- [ ] Search is user-scoped (users see only their own media)
- [ ] Pagination works correctly
- [ ] Rebuild script regenerates the full vector store from the database
- [ ] All integration tests pass
- [ ] No files created inside the launcher repo
- [ ] `PROJECT_MAP.md` updated with new modules
- [ ] Closeout checklist completed

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Sentence-transformer model is large (~80MB download on first use) | Low | Model cached locally after first download. No runtime API cost. |
| Search quality poor for short/vague queries | Medium | Embedding text is rich (13 fields). Test with diverse queries. Tune in Phase 2 if needed. |
| ChromaDB performance degrades with large collections | Low | MVP scale is small. Abstract interface allows swapping to Qdrant/Pinecone later (ADR-006). |
| Embedding model doesn't capture domain-specific photography terms | Medium | `all-MiniLM-L6-v2` is general-purpose; good enough for MVP. Can upgrade model later — config-driven. |
| ChromaDB data loss | Low | Vector store is derived (ADR-006). Rebuild script regenerates from DB. |
| Indexing failure blocks analysis | Low | Indexing is non-fatal — logs warning, analysis still succeeds. |

## Notes

- **Text-based embeddings only.** WS-003 embeds the metadata text, not the image pixels. This is simpler, cheaper, and sufficient for MVP semantic search. Multi-modal embeddings (CLIP, etc.) are a Phase 2 consideration.
- **`all-MiniLM-L6-v2`** was chosen for balance: 384 dimensions, fast inference, good quality on short passages. It runs locally via PyTorch — no API key needed. The model name is configurable if a better model is identified later.
- **ChromaDB persistence** uses a directory on disk. In production (Qdrant per ADR-006), this would be a remote service. The `VectorStore` interface hides this difference.
- **Metadata subset in search results** (`title`, `description`, `tags`, `mood`) balances response size with usefulness. Full metadata is one API call away via `GET /api/v1/media/{id}/analysis`.
- **No `media_metadata` schema changes.** WS-003 reads from the existing table — it does not add columns. The vector store is a separate, derived store.
