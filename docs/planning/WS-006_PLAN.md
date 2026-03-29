# Workstream Plan: WS-006 — UI Polish & API Cleanup

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-006 |
| **Phase** | Phase 2 — Enhancements |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 1 complete, P2-001/P2-002 complete (enrichment + download) |
| **Estimated Size** | Medium |
| **Created** | 2026-03-28 |
| **Status** | Draft — awaiting operator review |

## Objective

Five targeted improvements: fix metadata comment formatting, use AI titles for all download filenames, expose image dimensions throughout the stack, merge Library and Search into a unified Gallery page, and rename Upload to Source.

---

## Change 1: Fix Metadata Comment Prefix

**Problem:** `build_user_comment()` in `field_mapping.py` outputs `"AI-generated description: {description}"`. The prefix is unnecessary — the description should stand on its own.

### Files to Modify

| File | Change |
|---|---|
| `src/enrichment/field_mapping.py` | In `build_user_comment()`, change `parts = [f"AI-generated description: {metadata.description}"]` to `parts = [metadata.description]` |

### Validation

- [ ] UserComment no longer starts with "AI-generated description:"
- [ ] Description appears as the first line, followed by Context, Mood, etc.
- [ ] Existing enrichment tests still pass (update expected strings if assertions check the prefix)

---

## Change 2: Fix Download Filenames — Use AI Title for ALL Formats

**Problem:** `_sanitize_filename()` exists in `download.py` but is only used for BMP/GIF (the `not enrichment.embedded` branch). All other formats use the raw `original_filename` (e.g., `IMG_4532.jpg`). The AI-generated title should be the download filename for every format.

### Files to Modify

| File | Change |
|---|---|
| `src/api/routes/download.py` — `download_file()` | Remove the `if not enrichment.embedded:` branching. Always compute the download name as `_sanitize_filename(meta.title, ext) or item.original_filename`. The extension comes from the **output** MIME type (not original filename), so a BMP→PNG conversion still gets `.png`. |
| `src/api/routes/download.py` — `download_batch()` | Same change: use `_sanitize_filename(meta.title, ext)` for the ZIP entry name instead of `item.original_filename`. Dedup logic (counter suffix) stays the same. |

### Current Code (download_file)

```python
# Current: only BMP/GIF get title-based names
if not enrichment.embedded:
    ext = os.path.splitext(item.original_filename)[1]
    download_name = _sanitize_filename(meta.title, ext) or item.original_filename
else:
    download_name = item.original_filename
```

### Target Code (download_file)

```python
# All formats get title-based names
import mimetypes
ext = mimetypes.guess_extension(enrichment.output_mime_type) or os.path.splitext(item.original_filename)[1]
download_name = _sanitize_filename(meta.title, ext) or item.original_filename
```

### Same Pattern in download_batch

Replace:
```python
zip_name = item.original_filename
```

With:
```python
ext = mimetypes.guess_extension(enrichment.output_mime_type) or os.path.splitext(item.original_filename)[1]
zip_name = _sanitize_filename(meta.title, ext) or item.original_filename
```

### Validation

- [ ] JPEG download: filename is `Sunset_Beach.jpg` (not `IMG_4532.jpg`)
- [ ] PNG download: filename uses AI title with `.png` extension
- [ ] BMP/GIF download: still uses AI title (unchanged behavior)
- [ ] Fallback: if title is empty/unsanitizable, falls back to original filename
- [ ] Batch ZIP: entry names use AI titles, dedup counter still works for collisions
- [ ] Extension comes from output MIME type (handles edge cases like `.jpe` → `.jpg`)

---

## Change 3: Expose Image Dimensions

**Problem:** `width` and `height` exist on `MediaItem` in the DB (added post-Phase 1) and are populated during upload (via Pillow in `upload_service.py`). But they are absent from all API response schemas, frontend types, and UI.

### Backend — API Schemas

| File | Change |
|---|---|
| `src/api/schemas.py` — `MediaItemResponse` | Add `width: int \| None = None` and `height: int \| None = None` |
| `src/api/schemas.py` — `SearchMediaItem` | Add `width: int \| None = None` and `height: int \| None = None` |

`MediaItemResponse` already uses `model_config = {"from_attributes": True}` so adding the fields is sufficient — SQLAlchemy populates them automatically.

`SearchMediaItem` is built manually in `search.py` so the route code needs updating too.

### Backend — Search Route

| File | Change |
|---|---|
| `src/api/routes/search.py` | In the `SearchMediaItem(...)` constructor, add `width=r.width, height=r.height`. This requires the `SearchService` result objects to carry width/height — check `search_service.py` `SearchResultItem` dataclass. |
| `src/search/search_service.py` | Add `width: int \| None` and `height: int \| None` to the `SearchResultItem` dataclass. Populate from the DB join in the `search()` method. |

### Frontend — Types

| File | Change |
|---|---|
| `frontend/src/types/api.ts` — `MediaItemResponse` | Add `width?: number; height?: number;` |
| `frontend/src/types/api.ts` — `SearchResultItem.media_item` | Add `width?: number; height?: number;` |

### Frontend — Media Detail Page

| File | Change |
|---|---|
| `frontend/src/pages/MediaDetailPage.tsx` | In the `media-detail-meta` div, add dimensions display: `{media.width && media.height && <span>{media.width} × {media.height}</span>}` |

### Frontend — Sort Options

Dimension sort already exists in SearchPage (`largest`/`smallest` options in the sort dropdown). After the Gallery merge (Change 4), these sort options will be available on the unified page.

No additional sort work needed — the backend `search_service.py` already handles `sort_by=largest` and `sort_by=smallest` using the width/height columns.

### Validation

- [ ] `GET /api/v1/media` returns items with `width` and `height` fields
- [ ] `GET /api/v1/media/{id}` returns `width` and `height`
- [ ] `GET /api/v1/search` results include `width` and `height` in `media_item`
- [ ] Media detail page shows "1920 × 1080" (or similar) in the info section
- [ ] Null dimensions (pre-existing items without Pillow extraction) display gracefully (omitted or "Unknown")

---

## Change 4: Merge Library + Search into Gallery

**Problem:** Library and Search are separate pages with duplicated UI patterns (grid/list toggle, pagination, selection, view persistence). Library shows all media but has no search or filters. Search requires a query. Merge them into a single Gallery page that shows all media by default and adds search/filters when a query is entered.

### Behavior

| State | What shows |
|---|---|
| No query (`/` or `/?q=`) | All media, paginated, sorted by newest. Filter panel available. No relevance scores. |
| With query (`/?q=sunset`) | Search results from vector DB, ranked by relevance. Filter panel available. Scores shown. |

### Backend Change — Media List with Filters and Sort

The current `GET /api/v1/media` endpoint only supports `page`, `per_page`, and `status` filters. The Gallery needs the same filter/sort options that `GET /api/v1/search` has (orientation, mood, mime_type, aspect_ratio, has_people, tags, sort_by) when browsing without a search query.

| File | Change |
|---|---|
| `src/api/routes/media.py` — `list_media()` | Add the same filter query params as `search.py`: `has_people`, `orientation`, `mood`, `mime_type`, `min_width`, `max_width`, `min_height`, `max_height`, `aspect_ratio`, `tags`, `sort_by`. Apply them as WHERE clauses on the SQLAlchemy query. Sort options: `newest` (default, current behavior), `oldest`, `largest`, `smallest`. This requires joining `media_metadata` for metadata-based filters. |

### Files to Delete

| File | Reason |
|---|---|
| `frontend/src/pages/SearchPage.tsx` | Merged into GalleryPage |

### Files to Create

| File | Purpose |
|---|---|
| `frontend/src/pages/GalleryPage.tsx` | Replaces both LibraryPage and SearchPage. Combines all media listing, search, filters, grid/list view, selection, and batch download. |

### Files to Modify

| File | Change |
|---|---|
| `frontend/src/pages/LibraryPage.tsx` | **Delete** (replaced by GalleryPage) |
| `frontend/src/App.tsx` | Replace `LibraryPage` and `SearchPage` imports/routes with `GalleryPage`. Route `/` → `GalleryPage`. Remove `/search` route. |
| `frontend/src/components/Layout.tsx` | Nav links: remove "Library" and "Search" links. Add "Gallery" link pointing to `/`. |
| `frontend/src/components/SearchBar.tsx` | Change navigation target from `/search?q=` to `/?q=` (same page, query param). |
| `frontend/src/pages/MediaDetailPage.tsx` | Change "Back to Library" link text to "Back to Gallery". Keep href as `/`. |
| `frontend/src/api/client.ts` | Add `listMediaFiltered()` function that calls `GET /api/v1/media` with filter params (same signature as `search()` minus the required `q`). Or modify existing `listMedia()` to accept optional filters. |

### GalleryPage Design

The GalleryPage combines the best of both existing pages:

**From LibraryPage:**
- Default view: all media, paginated, sorted by newest
- Grid/list view toggle with localStorage persistence
- Selection + batch download in list view
- Auto-polling for items in processing state
- Empty state ("No media yet") when no items exist
- "Source" button (was "Upload") in header

**From SearchPage:**
- Search input at the top of the page
- Filter panel (people, orientation, aspect ratio, file type, mood, sort)
- Relevance scores displayed when a search query is active
- Search result card layout in grid view (shows title, description, tags, mood, score)

**Unified behavior:**
- When `q` param is empty/absent: call `GET /api/v1/media` with filters/sort → show paginated media grid. No scores.
- When `q` param has a value: call `GET /api/v1/search?q=...` with filters/sort → show ranked results with scores.
- Filter panel is always available (regardless of search state).
- Grid view: uses `MediaCard` for browse mode, search result cards (with title/description/score) for search mode.
- List view: same for both modes, but search mode adds a score column.
- URL reflects state: `/?q=sunset&orientation=landscape&sort_by=relevance&page=2`

### Validation

- [ ] `/` with no query → shows all media (current Library behavior)
- [ ] `/?q=sunset` → shows search results with scores
- [ ] Filters work in both browse and search modes
- [ ] Sort works in both modes (newest/oldest/largest/smallest + relevance when searching)
- [ ] Grid/list toggle works, persisted in localStorage
- [ ] Selection + batch download works in list view
- [ ] Auto-polling for processing items works
- [ ] Empty state shows when no media exists
- [ ] Empty results shows when search finds nothing
- [ ] Header search bar navigates to `/?q=...`
- [ ] "Back to Gallery" link on media detail page
- [ ] No `/search` route exists (old URLs could redirect or 404)
- [ ] SearchPage.tsx deleted, LibraryPage.tsx deleted

---

## Change 5: Rename Upload to Source

**Problem:** "Upload" is too narrow — the system enriches existing media and will eventually support cloud imports. "Source" better describes the action of providing media to the system.

### Files to Modify

| File | Change |
|---|---|
| `frontend/src/components/Layout.tsx` | Nav link text: `"Upload"` → `"Source"`. Href stays `/upload`. |
| `frontend/src/pages/UploadPage.tsx` | Page heading: `"Upload Media"` → `"Source"`. DropZone prompt text (if any visible label says "Upload"). Button text: `"Upload N files"` → `"Add N files"` or keep "Upload" for the action verb — the page title is what changes. |
| `frontend/src/pages/GalleryPage.tsx` (new) | The "Upload" button in the page header → `"Source"` or `"Add Media"`. Link still goes to `/upload`. |
| `frontend/src/pages/MediaDetailPage.tsx` | No change needed (no Upload references). |

**Note:** The route `/upload` stays as-is. Only user-facing text changes. Backend endpoints are unchanged (`POST /api/v1/upload` etc.).

### Validation

- [ ] Nav shows "Source" (not "Upload")
- [ ] Source page heading says "Source"
- [ ] Gallery page header button says "Source" or "Add Media"
- [ ] Empty state in Gallery links to Source page with correct label
- [ ] Route `/upload` still works
- [ ] No user-visible instances of the word "Upload" remain (except possibly the action button text during the upload process, which is acceptable)

---

## Implementation Order

```
Change 1: Fix metadata comment prefix        ← 1 line, independent
Change 2: Fix download filenames             ← small, independent
Change 3: Expose image dimensions            ← backend + frontend, independent
Change 4: Merge Library + Search → Gallery   ← largest change, depends on Change 3 (dimensions in schemas)
Change 5: Rename Upload → Source             ← small, do alongside or after Change 4
```

**Recommended:**
1. **Changes 1 + 2** together (both in backend, both quick fixes)
2. **Change 3** (dimensions — backend schemas + search service + frontend types + detail page)
3. **Change 4** (Gallery merge — the big one. Backend filter endpoint + new GalleryPage + delete old pages + routing)
4. **Change 5** (Source rename — text-only, do last since it touches GalleryPage)

## Exit Criteria

- [ ] UserComment has no "AI-generated description:" prefix
- [ ] All downloaded files use AI title as filename (not original camera filename)
- [ ] `width` and `height` in all API responses and displayed on media detail page
- [ ] Single Gallery page replaces Library + Search
- [ ] Gallery shows all media when no query, search results when query is active
- [ ] Filters and sort work in both browse and search modes
- [ ] "Upload" renamed to "Source" in all user-facing text
- [ ] SearchPage.tsx and LibraryPage.tsx deleted
- [ ] All existing backend tests pass
- [ ] `PROJECT_MAP.md` updated
