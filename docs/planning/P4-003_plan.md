# P4-003: Source Registry & Source-Aware Media — Implementation Plan

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P4-003 |
| **Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Status** | In Progress |
| **Started** | 2026-04-01 |
| **Dependencies** | P4-001 complete, P4-002 complete |
| **Estimated Size** | M-L |

---

## Objective

Treat sources as first-class user objects so the system can remember where images came from, allow multiple saved sources per user, support soft-delete/archive/restore for deleted sources, and expose source-backed filtering in Gallery.

---

## Context

The current system has no `Source` model. `MediaItem` has no `source_id` column. The Sources page (`UploadPage.tsx`) is a renamed upload drop-zone — the word "Source" is cosmetic only. The Gallery source filter dropdown exists in the UI but is not backed by any real data.

This workstream makes sources real.

---

## Changes

1. Add a `Source` data model with soft-delete (`archived_at`) support.
2. Add `source_id` nullable FK to `MediaItem`.
3. API: create source, list sources (with optional archived), archive, restore.
4. Upload endpoints accept optional `source_id`; validate ownership before use.
5. Gallery `GET /api/v1/media` accepts `source_id` filter parameter.
6. Sources page redesigned as a sources hub: list saved sources, create new, archive/restore, upload-to-source picker.
7. Gallery source filter dropdown pulled from real API.

---

## Implementation Steps

### Step 1 — Model + Migration

**`src/models.py`** — changes:
- Add `Source` class (above `MediaItem`):
  - `id`, `user_id` (FK users), `name` (String 200), `source_type` (String 50, default "manual"), `archived_at` (DateTime nullable), `created_at`, `updated_at`
  - Relationships: `user` → User, `media_items` → MediaItem list
- Add to `MediaItem`: `source_id` (String 36, FK sources.id, nullable), `source` relationship
- Add to `User`: `sources: Mapped[list["Source"]]` relationship

**`alembic/versions/a1b2c3d4e5f6_source_registry.py`** — new migration:
- `upgrade`: CREATE TABLE sources (all columns + ix_sources_user_id index); ALTER TABLE media_items ADD COLUMN source_id + FK
- `downgrade`: DROP FK/column from media_items; DROP TABLE sources

### Step 2 — Schemas

**`src/api/schemas.py`** — add:
- `SourceResponse`: id, name, source_type, archived_at, created_at (`from_attributes = True`)
- `SourceCreateRequest`: name (1–200 chars), source_type (default "manual")
- `MediaItemResponse`: add `source_id: str | None = None`

### Step 3 — Sources API routes

**`src/api/routes/sources.py`** — new file:

| Endpoint | Method | Behaviour |
|---|---|---|
| `POST /api/v1/sources` | Create | name + source_type; user-scoped |
| `GET /api/v1/sources` | List | `?include_archived=false`; user-scoped |
| `POST /api/v1/sources/{id}/archive` | Archive | set archived_at = now; idempotent |
| `POST /api/v1/sources/{id}/restore` | Restore | clear archived_at; idempotent |

- All routes return 401 if unauthenticated.
- `{id}` routes return 404 if source does not belong to current user.

Register router in `src/api/app.py`.

### Step 4 — Media list filter

**`src/api/routes/media.py`**:
- Add `source_id: str | None = Query(None)` to `GET /api/v1/media`
- When provided: `.where(MediaItem.source_id == source_id)` (safe — all media queries already scope to `user_id`)

### Step 5 — Upload source association

**`src/api/routes/upload.py`**:
- Add `source_id: str | None = Form(None)` to `POST /upload` and `POST /upload/batch`
- Before proceeding: if `source_id` provided, verify `SELECT source WHERE id=source_id AND user_id=user_id`; return HTTP 403 if not found
- Pass validated `source_id` to `_upload_service.process_upload()`

**`src/ingestion/upload_service.py`**:
- `process_upload()` accepts `source_id: str | None = None`
- Sets `MediaItem.source_id = source_id` on creation

### Step 6 — Frontend: Sources page redesign

**`frontend/src/pages/UploadPage.tsx`** — two-section layout:

**Top — Saved Sources Hub:**
- On mount: `GET /api/v1/sources` (active only by default)
- Render source cards: name, type, archived badge if applicable
- Per-card actions: Archive (active) / Restore (archived)
- "Upload to this source" button sets selected source for upload section
- "+ New Source" inline form: name input → `POST /api/v1/sources`
- "Show archived" toggle to reveal archived sources

**Bottom — Upload (existing, unchanged):**
- Add "Source (optional)" `<select>` above the upload button
- Populated from active sources; includes "— None —" option
- Selected source ID sent as `source_id` form field in upload API calls

**`frontend/src/types/api.ts`** — add:
```ts
export interface SourceResponse {
  id: string;
  name: string;
  source_type: string;
  archived_at: string | null;
  created_at: string;
}
```
Add `source_id: string | null` to `MediaItemResponse`.

**`frontend/src/api/client.ts`** — add 4 functions:
- `createSource(name, source_type?)` → `SourceResponse`
- `listSources(includeArchived?)` → `SourceResponse[]`
- `archiveSource(id)` → `void`
- `restoreSource(id)` → `void`

Update `listMediaFiltered()` to pass `source_id` param when provided.

### Step 7 — Frontend: Gallery source filter

**`frontend/src/pages/GalleryPage.tsx`**:
- On mount: `listSources()` → populate source dropdown options
- Source filter state: `selectedSourceId: string | null`
- Write to URL: `source_id` param (same pattern as existing filters)
- Pass to `listMediaFiltered()` and search API calls

### Step 8 — Tests

**`tests/test_sources.py`** — 8 tests:
1. `test_create_source` — POST → 201, name/type returned
2. `test_list_sources_scoped` — two users; each sees only their own
3. `test_archive_source` — archived_at set; idempotent
4. `test_restore_source` — archived_at cleared
5. `test_archive_not_owned` — 404 for other user's source
6. `test_upload_with_source_id` — media item has source_id set
7. `test_upload_with_invalid_source_id` — 403 returned
8. `test_gallery_filter_by_source` — only items from that source returned

---

## Exit Criteria

- [ ] A user can have multiple saved sources.
- [ ] Gallery source filter is backed by real persisted data from the API.
- [ ] Deleting (archiving) a source sets `archived_at`; media items retain their `source_id`.
- [ ] Archived sources can be restored.
- [ ] Local/manual source type is fully supported end-to-end.
- [ ] Upload with `source_id` links media to that source.
- [ ] Upload with cross-user `source_id` is rejected (403).
- [ ] All new tests pass; existing 91/91 tests continue to pass.
- [ ] TypeScript build clean.

---

## Validation Checklist (Local Smoke)

1. Create source "Holiday 2025" → appears in Sources list
2. Upload 2 files to "Holiday 2025" → quota consumed; source_id set on both
3. Gallery filter by "Holiday 2025" → shows only those 2 files
4. Create second source "Work Docs" → both visible
5. Archive "Work Docs" → badge shows archived; not in upload dropdown
6. Restore "Work Docs" → reappears active
7. Upload 1 file with no source → source_id null; does not appear in source filter
8. Gallery with no source filter → shows all items

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `source_id` nullable on MediaItem | Yes | Pre-P4-003 media has no source; coercing to a default source is worse than null |
| Auto-create "Manual" source on upload with no source_id | No | Simpler; avoids phantom sources; user explicitly opts in |
| Archived sources in active filter dropdown | No — exclude | Archived = historical; still linked to media but not selectable |
| Cross-user source reference error code | 403 Forbidden | Not 404 — leaking existence of another user's source is an IDOR risk |
| `source_type` field now | Persist but only enforce "manual" | Connector abstraction lands cleanly later without a schema change |
| Broad connector rollout | Out of scope | Source model first, connectors additive after model is stable |
