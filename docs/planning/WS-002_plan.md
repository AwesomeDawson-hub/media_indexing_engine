# Workstream Plan: WS-002 — AI Analysis Pipeline

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-002 |
| **Phase** | Phase 1 — MVP |
| **Project** | Media Indexing Engine |
| **Dependencies** | WS-001 (Ingestion Pipeline) — Completed |
| **Estimated Size** | Medium |
| **Created** | 2026-03-27 |
| **Status** | Draft — awaiting operator review |

## Objective

Build the AI analysis pipeline: pick up pending processing jobs created by WS-001, send images to Anthropic Claude's vision API, extract structured metadata conforming to the 13-field schema (ADR-005), persist results in a new `media_metadata` table, and expose analysis status/re-analysis API endpoints. The AI provider must be abstracted behind an interface for future swaps.

## Scope

### In Scope

- `media_metadata` table — the 4th entity from ADR-003 with 13 fields from ADR-005
- AI provider interface abstraction (`VisionProvider` protocol)
- Anthropic Claude vision implementation via official `anthropic` SDK (per ADR-008)
- Image preparation — resize large images before API submission (cost/latency optimization)
- Prompt engineering for structured metadata extraction (13 fields)
- Output parsing — extract structured JSON from Claude's response
- Output validation — validate parsed metadata against the ADR-005 schema
- Replace WS-001's `placeholder_processor` with real AI analysis processor
- Job status transitions: `pending` → `running` → `completed` | `failed`
- Retry logic with configurable max attempts (default 3 per `ProcessingConfig`)
- MediaItem status transitions: `uploaded` → `processing` → `completed` | `error`
- Analysis API endpoints: get analysis status, trigger re-analysis
- Configuration additions: `analysis` section in settings (provider, model, max image dimension, max concurrent)

### Out of Scope

- Vector embeddings / search indexing (WS-003)
- Multiple AI providers simultaneously (only Anthropic for now; interface enables future additions)
- Video analysis (deferred per project constraints)
- Authentication (WS-004 — continue using dev user)
- Frontend display of metadata (WS-005)
- Rate limiting / cost tracking (WS-004)
- Streaming responses or real-time progress updates
- Custom model training or fine-tuning

## Constraints

- **AI Provider:** Anthropic Claude via official `anthropic` Python SDK (per ADR-008)
- **Model:** `claude-sonnet-4-20250514` (capable vision, cost-efficient for batch analysis)
- **Max image dimension:** 1568px on longest side (Claude's recommended max for optimal token/quality balance)
- **Output format:** JSON conforming to ADR-005 schema — must be machine-parseable
- **Retry budget:** Max 3 attempts per job (per `settings.processing.max_attempts`)
- **No external task queue:** Continue using FastAPI BackgroundTasks (established in WS-001)
- **Database:** Async SQLAlchemy on SQLite (dev), PostgreSQL (prod) — same as WS-001

## Governing Decisions

| ADR | Decision | Impact on WS-002 |
|---|---|---|
| ADR-002 | Database as sole system of record | Metadata stored in DB only — no JSON sidecar files |
| ADR-003 | Normalized entity model | Create `media_metadata` table with FK to `media_items` |
| ADR-005 | Metadata schema (13 fields) | Defines exact output structure: title, description, tags, objects, scenes, context, mood, people, people_count, orientation, colors, location_hint, quality_notes |
| ADR-007 | Defer review workflow | No approval gates — analysis runs automatically, results go straight to DB |
| ADR-008 | Anthropic Claude as initial provider | Use `anthropic` SDK, abstract behind interface for future swaps |

## Database Schema

### `media_metadata` table

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID (String 36) | PK, default uuid4 | Internal reference key |
| `media_item_id` | UUID (String 36) | FK → media_items.id, UNIQUE, NOT NULL | One metadata record per media item |
| `title` | VARCHAR(200) | NOT NULL | AI-generated title |
| `description` | TEXT | NOT NULL | Natural language description |
| `tags` | TEXT (JSON array) | NOT NULL | General-purpose tags |
| `objects` | TEXT (JSON array) | NOT NULL | Detected objects |
| `scenes` | TEXT (JSON array) | NOT NULL | Scene descriptions |
| `context` | TEXT | NOT NULL | Situational context |
| `mood` | VARCHAR(100) | NOT NULL | Emotional tone / atmosphere |
| `people` | TEXT (JSON array) | NOT NULL | People descriptions (no PII) |
| `people_count` | INTEGER | NOT NULL | Number of people detected |
| `orientation` | VARCHAR(20) | NOT NULL | landscape / portrait / square |
| `colors` | TEXT (JSON array) | NOT NULL | Dominant colors |
| `location_hint` | VARCHAR(200) | NULLABLE | Inferred location (may not be determinable) |
| `quality_notes` | TEXT | NULLABLE | Notes on image quality issues |
| `ai_provider` | VARCHAR(50) | NOT NULL | Provider used (e.g., "anthropic") |
| `ai_model` | VARCHAR(100) | NOT NULL | Model used (e.g., "claude-sonnet-4-20250514") |
| `analyzed_at` | TIMESTAMP | NOT NULL | When analysis completed |
| `created_at` | TIMESTAMP | NOT NULL, default now | Record creation time |

**Unique constraint:** `media_item_id` — one metadata record per media item. Re-analysis overwrites the existing record (UPDATE, not INSERT).

**Note on JSON arrays:** Stored as JSON-serialized text. SQLAlchemy handles serialization. In PostgreSQL, these could use native JSON columns — but TEXT with JSON works across both SQLite and PostgreSQL.

## AI Provider Interface

```python
class VisionProvider(Protocol):
    """Abstract interface for vision AI providers."""

    async def analyze_image(
        self, image_bytes: bytes, mime_type: str
    ) -> MediaMetadataResult:
        """Analyze an image and return structured metadata."""
        ...
```

- `MediaMetadataResult` is a dataclass/Pydantic model matching the 13-field schema.
- The interface takes raw image bytes (already resized) and returns structured metadata.
- The implementation handles: prompt construction, API call, response parsing, validation.
- Future providers (OpenAI, Gemini) implement the same interface — no upstream changes needed.

## Image Preparation

Before sending to the API, images are resized to optimize cost and latency:

1. **Read image** from storage path using Pillow (`PIL`).
2. **Check dimensions** — if longest side > 1568px, resize proportionally.
3. **Convert to JPEG** for API submission (standardizes format, reduces payload size). Preserve original format on disk — this is for API submission only.
4. **Encode to base64** for the Anthropic API's image content block.

Why 1568px: Anthropic's documentation recommends this as the maximum useful dimension. Larger images are downscaled by the API anyway, costing more tokens without quality benefit.

## Prompt Design

The system prompt instructs Claude to analyze the image and return structured JSON:

```
You are an image analysis assistant. Analyze the provided image and return a JSON object
with exactly these fields:

{
  "title": "Short descriptive title (under 100 characters)",
  "description": "2-3 sentence natural language description of what the image shows",
  "tags": ["tag1", "tag2", ...],         // 5-15 general-purpose tags
  "objects": ["object1", "object2", ...], // Physical objects visible in the image
  "scenes": ["scene1", "scene2", ...],    // Scene/setting descriptions
  "context": "Situational context — what is happening, what event or activity",
  "mood": "Emotional tone or atmosphere (e.g., cheerful, dramatic, serene)",
  "people": ["description1", ...],        // Descriptions of people (no names/PII)
  "people_count": 0,                      // Integer count of people visible
  "orientation": "landscape|portrait|square",
  "colors": ["color1", "color2", ...],    // 3-5 dominant colors
  "location_hint": "Inferred location or null if not determinable",
  "quality_notes": "Notes on quality issues (blur, noise, exposure) or null if good"
}

Rules:
- Return ONLY the JSON object, no markdown fences, no explanation.
- Tags should be lowercase, single words or short phrases.
- people array contains descriptions only, never names or identifying information.
- orientation is based on image dimensions, not content.
- location_hint should be null if location cannot be reasonably inferred.
- quality_notes should be null if the image quality is acceptable.
```

## Output Parsing and Validation

Claude's response goes through a three-stage pipeline:

1. **Extract JSON** — strip any markdown fences or surrounding text, find the JSON object.
2. **Parse** — `json.loads()` into a Python dict.
3. **Validate** — check against the schema:
   - All 13 required fields present
   - Correct types (strings, lists, integers)
   - `people_count` is a non-negative integer
   - `orientation` is one of: landscape, portrait, square
   - Lists are non-empty where required (tags, objects, scenes, colors)
   - `location_hint` and `quality_notes` may be null

If parsing or validation fails, the job retries (up to max attempts). The error message records what went wrong for debugging.

## Processing Flow

```
Background task picks up pending job
    │
    ▼
1. Load ProcessingJob + associated MediaItem from DB
2. Update job: status → running, started_at → now, attempts += 1
3. Update media_item: status → processing
    │
    ▼
4. Read file bytes from storage (using FileStore)
5. Prepare image: resize if needed, convert to JPEG, base64 encode
    │
    ▼
6. Call VisionProvider.analyze_image()
   ├── Anthropic SDK: create message with image content block
   ├── Parse response → JSON
   └── Validate against schema → MediaMetadataResult
    │
    ├── SUCCESS ──▼
    │   7a. Upsert media_metadata record (INSERT or UPDATE if re-analysis)
    │   8a. Update media_item: status → completed
    │   9a. Update job: status → completed, completed_at → now
    │
    └── FAILURE ──▼
        7b. Check attempts < max_attempts
        ├── YES → Update job: status → pending (will be retried)
        │         Log error for debugging
        └── NO  → Update job: status → failed, error_message → details
                  Update media_item: status → error
```

## API Endpoints

### `GET /api/v1/media/{id}/analysis`

Get analysis status and metadata for a media item.

**Response (200, analysis complete):**
```json
{
  "media_item_id": "uuid",
  "status": "completed",
  "metadata": {
    "title": "Sunset over the Pacific",
    "description": "A vibrant sunset ...",
    "tags": ["sunset", "ocean", "landscape"],
    "objects": ["sun", "ocean", "clouds"],
    "scenes": ["coastal sunset"],
    "context": "Natural landscape photography of sunset",
    "mood": "serene",
    "people": [],
    "people_count": 0,
    "orientation": "landscape",
    "colors": ["orange", "purple", "blue"],
    "location_hint": "Pacific coast",
    "quality_notes": null
  },
  "ai_provider": "anthropic",
  "ai_model": "claude-sonnet-4-20250514",
  "analyzed_at": "2026-03-27T12:00:00Z"
}
```

**Response (200, analysis pending/running):**
```json
{
  "media_item_id": "uuid",
  "status": "pending",
  "metadata": null,
  "job": {
    "id": "job-uuid",
    "status": "pending",
    "attempts": 0,
    "created_at": "2026-03-27T12:00:00Z"
  }
}
```

**Response (200, analysis failed):**
```json
{
  "media_item_id": "uuid",
  "status": "failed",
  "metadata": null,
  "job": {
    "id": "job-uuid",
    "status": "failed",
    "attempts": 3,
    "error_message": "JSON parsing failed after 3 attempts"
  }
}
```

### `POST /api/v1/media/{id}/reanalyze`

Trigger re-analysis for a media item. Creates a new processing job (or resets the existing failed one).

**Preconditions:** Media item must exist and belong to the current user.

**Response (202):**
```json
{
  "media_item_id": "uuid",
  "job_id": "new-job-uuid",
  "message": "Re-analysis queued"
}
```

**Error responses:**
- `404` — Media item not found
- `409` — Analysis already in progress (job status is `pending` or `running`)

## Configuration Additions

New `analysis` section in `settings.yaml` and `config.py`:

```yaml
analysis:
  provider: "anthropic"
  model: "claude-sonnet-4-20250514"
  max_image_dimension: 1568
  max_concurrent: 5        # max concurrent API calls (future use)
  timeout_seconds: 60      # per-request timeout
```

```python
@dataclass
class AnalysisConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_image_dimension: int = 1568
    max_concurrent: int = 5
    timeout_seconds: int = 60
```

The `ANTHROPIC_API_KEY` is read from the environment variable (never from settings files — per PROJECT_AI_CONTEXT.md rule: "Never store API keys or credentials in code").

## Implementation Steps

Each step has a validation checkpoint. Do not proceed to the next step until the current step's validation passes.

### Step 1: Configuration and Dependencies

**What:** Add `anthropic` and `Pillow` to project dependencies. Add `AnalysisConfig` to the settings system. Add `analysis` section to `settings.yaml`.

**Files to modify:**
- `pyproject.toml` — add `anthropic`, `Pillow` dependencies
- `src/config.py` — add `AnalysisConfig` dataclass, add to `Settings`
- `config/settings.yaml` — add `analysis` section
- `config/settings.example.yaml` — add `analysis` section

**Validation:**
- [ ] `pip install` succeeds with new dependencies
- [ ] `from anthropic import AsyncAnthropic` works
- [ ] `from PIL import Image` works
- [ ] `settings.analysis.provider` returns `"anthropic"`
- [ ] `settings.analysis.model` returns `"claude-sonnet-4-20250514"`

### Step 2: MediaMetadata Model and Table

**What:** Add the `MediaMetadata` ORM model to `models.py`. Add the relationship to `MediaItem`. Ensure table creation on startup.

**Files to modify:**
- `src/models.py` — add `MediaMetadata` class, add relationship on `MediaItem`

**Validation:**
- [ ] `media_metadata` table created on startup (via existing `create_tables()`)
- [ ] `media_item_id` UNIQUE constraint enforced
- [ ] FK from `media_metadata.media_item_id` → `media_items.id` works
- [ ] `media_item.metadata` relationship loads correctly
- [ ] All 13 ADR-005 fields present plus `ai_provider`, `ai_model`, `analyzed_at`

### Step 3: Image Preparation Module

**What:** Create the image preparation module that resizes and encodes images for API submission.

**Files to create:**
- `src/analysis/image_prep.py`:
  - `prepare_image(file_bytes, mime_type, max_dimension) → (base64_str, media_type)`
  - Loads image with Pillow, resizes if needed, converts to JPEG, returns base64

**Validation:**
- [ ] Large image (e.g., 4000x3000) resized to fit within 1568px longest side
- [ ] Small image (e.g., 800x600) passed through unchanged (except JPEG conversion)
- [ ] Output is valid base64 string
- [ ] MIME type returned is `image/jpeg`
- [ ] Transparent PNGs converted without error (alpha channel handled)

### Step 4: Metadata Result Schema

**What:** Create the structured result model that sits between the AI response and the database.

**Files to create:**
- `src/analysis/schemas.py`:
  - `MediaMetadataResult` — Pydantic model with all 13 fields
  - Validation rules: people_count >= 0, orientation in allowed values, non-empty lists where required
  - `parse_ai_response(raw_text) → MediaMetadataResult` — extracts JSON from response, validates

**Validation:**
- [ ] Valid JSON → parses to `MediaMetadataResult` successfully
- [ ] Missing required field → raises validation error
- [ ] Wrong type (e.g., string for people_count) → raises validation error
- [ ] JSON wrapped in markdown fences → still parses correctly
- [ ] `orientation` not in [landscape, portrait, square] → raises validation error

### Step 5: Vision Provider Interface and Anthropic Implementation

**What:** Create the `VisionProvider` protocol and the `AnthropicVisionProvider` implementation.

**Files to create:**
- `src/analysis/provider.py` — `VisionProvider` protocol definition
- `src/analysis/anthropic_provider.py`:
  - `AnthropicVisionProvider` implementing `VisionProvider`
  - Uses `AsyncAnthropic` client
  - Constructs message with system prompt + image content block
  - Calls Claude API, extracts text response
  - Passes response through `parse_ai_response()` → `MediaMetadataResult`
  - Handles API errors (rate limit, timeout, auth) with clear error messages

**Validation:**
- [ ] `AnthropicVisionProvider` conforms to `VisionProvider` protocol
- [ ] With valid API key and test image: returns `MediaMetadataResult` with all 13 fields populated
- [ ] With invalid API key: raises clear error (not a raw SDK exception)
- [ ] Response timeout: raises clear error with timeout details
- [ ] Provider is instantiated with config values (model, timeout) from settings

### Step 6: Analysis Processor (Replace Placeholder)

**What:** Create the real analysis processor that replaces WS-001's `placeholder_processor`. Implements the full processing flow: load file → prepare image → call AI → parse → validate → persist metadata → update statuses.

**Files to create/modify:**
- `src/analysis/processor.py`:
  - `analyze_media_item(job_id) → None` — the background task entry point
  - Handles the full flow described in "Processing Flow" above
  - Retry logic: on failure, reset job to `pending` if attempts < max; otherwise mark `failed`
  - Upsert pattern for metadata: INSERT on first analysis, UPDATE on re-analysis
- `src/ingestion/job_manager.py` — remove `placeholder_processor`, update imports
- `src/api/app.py` — update background task dispatch to use `analyze_media_item` instead of `placeholder_processor`

**Validation:**
- [ ] Upload a file → background task runs real AI analysis (not placeholder)
- [ ] `processing_jobs` record transitions: pending → running → completed
- [ ] `media_items` record transitions: uploaded → processing → completed
- [ ] `media_metadata` record created with all 13 fields populated
- [ ] On API failure (simulated): job retries up to max_attempts, then fails
- [ ] On retry failure: job status = `failed`, media_item status = `error`, error_message recorded
- [ ] Re-analysis of already-analyzed item: metadata record UPDATED (not duplicated)

### Step 7: Analysis API Endpoints

**What:** Create API endpoints for checking analysis status and triggering re-analysis.

**Files to create:**
- `src/api/routes/analysis.py`:
  - `GET /api/v1/media/{id}/analysis` — returns metadata + job status
  - `POST /api/v1/media/{id}/reanalyze` — queues re-analysis
- `src/api/schemas.py` — add `AnalysisResponse`, `ReanalyzeResponse` models
- `src/api/app.py` — register analysis router

**Validation:**
- [ ] `GET /api/v1/media/{id}/analysis` for analyzed item → 200 with metadata
- [ ] `GET /api/v1/media/{id}/analysis` for pending item → 200 with job status, no metadata
- [ ] `GET /api/v1/media/{id}/analysis` for failed item → 200 with error details
- [ ] `GET /api/v1/media/{bad-id}/analysis` → 404
- [ ] `POST /api/v1/media/{id}/reanalyze` for completed item → 202, new job queued
- [ ] `POST /api/v1/media/{id}/reanalyze` for pending/running item → 409 conflict
- [ ] After re-analysis completes: metadata record updated (one record, not two)

### Step 8: Integration Testing

**What:** End-to-end tests that exercise the full analysis flow. Tests use a mock vision provider (no real API calls in CI).

**Files to create/modify:**
- `src/analysis/mock_provider.py` — `MockVisionProvider` that returns canned metadata (implements `VisionProvider`)
- `tests/test_analysis.py` — integration tests using mock provider
- `tests/conftest.py` — add analysis fixtures, mock provider injection

**Test cases:**
- [ ] Upload file → analysis runs (mock) → metadata persisted correctly
- [ ] All 13 metadata fields present and correct types in DB
- [ ] Job status transitions: pending → running → completed
- [ ] Media item status transitions: uploaded → processing → completed
- [ ] Simulated failure → job retries, then fails after max attempts
- [ ] Re-analysis → existing metadata overwritten, not duplicated
- [ ] `GET /api/v1/media/{id}/analysis` → correct response for each status
- [ ] `POST /api/v1/media/{id}/reanalyze` → correct behavior for each state
- [ ] Mock provider conforms to same interface as real provider

### Step 9: Manual Smoke Test (Operator-Assisted)

**What:** Run a real end-to-end test with the Anthropic API to verify the full pipeline works with a real AI model. This requires a valid `ANTHROPIC_API_KEY` environment variable.

**Procedure:**
1. Set `ANTHROPIC_API_KEY` environment variable
2. Start the server: `uvicorn src.api.app:app`
3. Upload a test image: `POST /api/v1/upload`
4. Wait for background analysis to complete (check logs)
5. Check analysis result: `GET /api/v1/media/{id}/analysis`
6. Verify: metadata is populated, all 13 fields present, values make sense for the image
7. Test re-analysis: `POST /api/v1/media/{id}/reanalyze`
8. Verify: metadata updated, only one metadata record exists

**Validation:**
- [ ] Real API call succeeds
- [ ] Metadata quality is reasonable (title makes sense, objects match image, etc.)
- [ ] No raw SDK errors leak to API response
- [ ] Performance acceptable (analysis completes in < 30 seconds for a single image)

### Step 10: PROJECT_MAP and Documentation Update

**What:** Update `PROJECT_MAP.md` with the implemented analysis modules. Update `media_metadata` in the Data Model table.

**Files to modify:**
- `docs/PROJECT_MAP.md` — document `src/analysis/` module files and responsibilities, update Data Model table

**Validation:**
- [ ] `src/analysis/` section lists all new files with responsibilities
- [ ] Data Model table shows `MediaMetadata` with table name and purpose
- [ ] No stale references to placeholder processor

## Module Dependency Graph

```
src/config.py                    ← AnalysisConfig added (Step 1)
src/models.py                    ← MediaMetadata model added (Step 2)
src/analysis/
  image_prep.py                  ← Pillow resize + base64 encode (Step 3)
  schemas.py                     ← MediaMetadataResult + parse_ai_response (Step 4)
  provider.py                    ← VisionProvider protocol (Step 5)
  anthropic_provider.py          ← Anthropic SDK implementation (Step 5)
  mock_provider.py               ← Mock for testing (Step 8)
  processor.py                   ← Full analysis pipeline (Step 6)
src/ingestion/
  job_manager.py                 ← placeholder_processor removed (Step 6)
src/api/
  app.py                         ← analysis router registered, task dispatch updated (Step 6, 7)
  schemas.py                     ← AnalysisResponse, ReanalyzeResponse added (Step 7)
  routes/analysis.py             ← GET analysis, POST reanalyze (Step 7)
```

**Dependency flow within `src/analysis/`:**
```
processor.py
  ├── provider.py (VisionProvider protocol)
  ├── anthropic_provider.py (concrete implementation)
  ├── image_prep.py (resize + encode)
  ├── schemas.py (parse + validate)
  └── models.py (MediaMetadata ORM, ProcessingJob, MediaItem)
```

## Exit Criteria

All of the following must be true to close WS-002:

- [ ] `media_metadata` table created and functional with all ADR-005 fields
- [ ] `VisionProvider` interface defined; `AnthropicVisionProvider` implements it
- [ ] Image preparation resizes and encodes images correctly
- [ ] Structured metadata extraction works: prompt → Claude → JSON → validated result
- [ ] WS-001's placeholder processor fully replaced with real analysis
- [ ] Job retry logic works (up to 3 attempts, then fail)
- [ ] MediaItem status transitions correctly: uploaded → processing → completed | error
- [ ] `GET /api/v1/media/{id}/analysis` returns metadata or job status
- [ ] `POST /api/v1/media/{id}/reanalyze` queues re-analysis correctly
- [ ] Re-analysis updates existing metadata (no duplicates)
- [ ] All integration tests pass (mock provider)
- [ ] Manual smoke test passes with real Anthropic API
- [ ] No API keys or credentials in code
- [ ] No files created inside the launcher repo
- [ ] `PROJECT_MAP.md` updated with new modules
- [ ] Closeout checklist completed

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Claude returns malformed JSON | Medium | Three-stage parse pipeline (extract → parse → validate) with clear errors. Retry on failure. |
| API rate limiting during batch uploads | Medium | Sequential processing (one job at a time via BackgroundTasks). `max_concurrent` config ready for future throttling. |
| API costs escalate with large libraries | Medium | Image resize reduces token usage. Cost tracking deferred but config supports limits. |
| Anthropic SDK breaking changes | Low | Pin SDK version in pyproject.toml. Interface abstraction isolates upstream changes. |
| Image preparation loses important detail | Low | 1568px max is Anthropic's own recommendation. Original file preserved on disk. |
| Metadata quality varies by image type | Medium | Prompt designed for general photography. Quality issues surface in WS-003 search testing. |

## Notes

- The `MockVisionProvider` created in Step 8 returns deterministic canned data — it does NOT call any external API. All automated tests use the mock. Only the manual smoke test (Step 9) touches the real API.
- WS-002 does NOT create embeddings or index metadata for search — that is WS-003's responsibility. WS-002 produces the structured metadata that WS-003 will embed.
- The `media_metadata.ai_provider` and `media_metadata.ai_model` columns track provenance. When future providers are added, these columns show which model analyzed each image.
- Re-analysis is an UPDATE (upsert), not a DELETE + INSERT. The `media_metadata.media_item_id` UNIQUE constraint enforces one metadata record per media item at all times.
- The processor reads file bytes through the `FileStore` interface established in WS-001 — it does not access the filesystem directly.
