# Phase 2 Feature Plan: Metadata Embedding + Download System

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 2 — Enhancements |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 1 complete, post-Phase 1 improvements applied |
| **Estimated Size** | Medium-Large (3 backend workstreams + 2 frontend workstreams) |
| **Created** | 2026-03-28 |
| **Status** | Completed — all workstreams (P2-001 through P2-005) delivered 2026-03-28 |

## Objective

Enable users to download their images with AI-extracted metadata embedded directly in the file's standard metadata fields (EXIF/XMP/IPTC), making the enrichment portable — when a user downloads and opens a file in Lightroom, Finder, or any photo tool, the AI-generated title, description, tags, and other fields are already there. Support single and batch (ZIP) downloads with a selection UI.

## Feature Scope

### Feature 1: Metadata Embedding into Image Files
Write AI metadata into image files using industry-standard metadata fields so it travels with the file.

### Feature 2: Download Endpoints
Single file download (enriched) and batch download (ZIP of enriched files).

### Feature 3: Frontend Download Button
Download button on media detail page.

### Feature 4: Frontend List View + Multi-Select + Batch Download
List/grid view toggle on Library and Search pages. List view has checkboxes for multi-select. Selected items can be batch-downloaded.

### Feature 5: Search as Nav Tab
Add Search to the navigation bar as a first-class tab alongside Library and Upload.

---

## Architectural Decision: Metadata Embedding Strategy

### Which metadata standard for each format?

**Constraint: Every format gets metadata embedded. No sidecar-only fallback.**

| Format | Embedding Strategy | Library | Notes |
|---|---|---|---|
| **JPEG** | EXIF + IPTC | `piexif` + `iptcinfo3` | Full coverage: EXIF (title, description, UserComment) + IPTC (headline, caption, keywords, categories, location) |
| **TIFF** | EXIF + IPTC | `piexif` + `iptcinfo3` | Same as JPEG — TIFF natively supports both standards |
| **WebP** | EXIF | `piexif` via Pillow | Pillow loads WebP, piexif generates EXIF bytes, Pillow saves with `exif=` parameter |
| **PNG** | XMP via iTXt chunk | `Pillow` (manual iTXt) | PNG iTXt chunk with keyword `XML:com.adobe.xmp` — the standard used by Adobe tools, Lightroom, Finder, etc. Pure Python: construct XMP XML string, write as iTXt chunk via Pillow |
| **AVIF** | EXIF | `pillow-heif` + `piexif` | `pillow-heif` registers AVIF support with Pillow, enabling EXIF write on save via `exif=` parameter |
| **BMP/GIF** | **No embedding** — downloaded as-is. Optional user-initiated conversion to PNG with XMP in library view. | `Pillow` | BMP and GIF have no metadata container. Downloads return the original file unchanged. The library UI offers an explicit "Convert to PNG with metadata" action for these formats. Conversion creates a new media item (PNG) alongside the original. |

### Recommended approach: On-demand at download time

**Decision: Generate enriched files on-demand when the user requests a download, not inline during analysis.**

**Reasoning:**
1. **Storage efficiency.** Storing an enriched copy alongside the original doubles storage. The original is the system of record (ADR-002 — database is the authority). The enriched file is a derived artifact — like the vector index.
2. **Metadata freshness.** If the user re-analyzes, the enriched file would be stale. On-demand generation always uses the latest metadata.
3. **Simplicity.** No second storage path to manage, no cache invalidation, no background job for embedding.
4. **Performance is acceptable.** Embedding metadata into a JPEG/PNG takes <100ms even for large files. The bottleneck in batch download is ZIP compression, not metadata writing.

**Trade-off:** Every download re-generates the enriched file. For single downloads this is invisible. For large batch downloads (100+ files), it adds processing time. Acceptable for MVP; a caching layer can be added if needed.

### Universal embedding — no sidecar fallback

Every downloaded file has metadata embedded directly. No exceptions, no sidecars.

**Format tiers:**

| Tier | Formats | Embedding Method |
|---|---|---|
| **Full (EXIF+IPTC)** | JPEG, TIFF | `piexif` for EXIF + `iptcinfo3` for IPTC — title, description, keywords, categories, location, extended UserComment |
| **EXIF** | WebP, AVIF | `piexif`-generated EXIF bytes injected via Pillow's `exif=` save parameter. AVIF requires `pillow-heif`. |
| **XMP via PNG iTXt** | PNG | XMP XML written as a PNG iTXt chunk (keyword: `XML:com.adobe.xmp`). Readable by Lightroom, Finder, Bridge, exiftool. Pure Python — no C dependency. |
| **No embedding** | BMP, GIF | Downloaded as-is — these formats have no metadata container. The library UI offers an explicit "Convert to PNG with metadata" action that creates a new PNG media item with XMP embedded. User-initiated, not automatic. |

**Why not `python-xmp-toolkit` for all?** It requires `libxmp` (Exempi), a C library that's complex to install cross-platform (especially Windows). Instead, we use a lightweight pure-Python XMP approach: manually construct a standards-compliant XMP XML string and embed it as a PNG iTXt chunk. This covers PNG, and JPEG/TIFF/WebP/AVIF are better served by EXIF+IPTC anyway (more widely read by photo tools).

### XMP XML construction for PNG

The XMP is a standard `x:xmpmeta` document with Dublin Core (`dc:`) and IPTC Core (`Iptc4xmpCore:`) namespaces:

```xml
<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"
      xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
      <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>
      <dc:description><rdf:Alt><rdf:li xml:lang="x-default">{description}</rdf:li></rdf:Alt></dc:description>
      <dc:subject>
        <rdf:Bag>
          <rdf:li>{tag1}</rdf:li>
          <rdf:li>{tag2}</rdf:li>
          ...
        </rdf:Bag>
      </dc:subject>
      <photoshop:Headline>{title}</photoshop:Headline>
      <Iptc4xmpCore:Location>{location_hint}</Iptc4xmpCore:Location>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
```

This is a simple template string — no XML library needed for construction. The `dc:subject` bag holds all tags + objects combined (the standard way to represent keywords in XMP).

### Metadata field mapping

| AI Field | EXIF Tag | IPTC Tag | Notes |
|---|---|---|---|
| `title` | `ImageDescription` (0x010E) | `Headline` (2:105) | Short title |
| `description` | `UserComment` (0x9286) | `Caption/Abstract` (2:120) | Longer description |
| `tags` | — | `Keywords` (2:25) | Array → semicolon-separated in IPTC |
| `objects` | — | `Supplemental Categories` (2:20) | Mapped to supplemental categories |
| `mood` | — | — | No standard IPTC/EXIF field; included in UserComment |
| `location_hint` | — | `City` (2:90) or `Sub-location` (2:92) | Best-effort mapping |
| `context` | — | `Special Instructions` (2:40) | Contextual info |
| `scenes` | — | — | No standard field; included in UserComment |
| `people` | — | — | No standard field; included in UserComment |
| `colors` | — | — | No standard field; included in UserComment |
| `people_count` | — | — | Included in UserComment |
| `orientation` | — | — | Already encoded in image dimensions |
| `quality_notes` | — | — | Not embedded (quality assessment is internal) |

**UserComment strategy:** Fields without a standard IPTC/EXIF mapping are included in an extended `UserComment` block as structured text:

```
AI-generated description: {description}

Context: {context}
Mood: {mood}
Scenes: {scenes joined}
People: {people joined} ({people_count})
Colors: {colors joined}
```

This ensures all AI metadata is accessible even in basic photo viewers that read EXIF UserComment.

---

## Workstream Breakdown

This feature set is broken into 5 implementation sub-workstreams. They can be executed sequentially (1→2→3→4→5) or with partial parallelism (1 and 5 are independent; 3+4 depend on 2).

| ID | Name | Scope | Dependencies | Size |
|---|---|---|---|---|
| P2-001 | Metadata Embedder Module | Backend: embed metadata into image files | None | S |
| P2-002 | Download Endpoints | Backend: single + batch download API | P2-001 | S |
| P2-003 | Frontend: Download Button | Detail page download button | P2-002 | XS |
| P2-004 | Frontend: List View + Multi-Select + Batch Download | Library/Search list view, checkboxes, batch download | P2-002 | M |
| P2-005 | Frontend: Search as Nav Tab | Nav bar update | None (can be done first or in parallel) | XS |

---

## P2-001: Metadata Embedder Module

### Objective

Create a backend module that takes image bytes + `MediaMetadataResult` and returns enriched image bytes with metadata embedded in EXIF/IPTC fields.

### Files to Create

- `src/enrichment/__init__.py`
- `src/enrichment/embedder.py` — `MetadataEmbedder` class:
  - `embed(file_bytes, mime_type, metadata) → EnrichmentResult`
  - `EnrichmentResult` — dataclass with `enriched_bytes`, `output_mime_type`, `output_filename` (may differ from input if BMP/GIF → PNG conversion)
- `src/enrichment/exif_writer.py` — EXIF/IPTC writing for JPEG/TIFF using `piexif` + `iptcinfo3`
- `src/enrichment/webp_writer.py` — EXIF writing for WebP via Pillow + piexif
- `src/enrichment/avif_writer.py` — EXIF writing for AVIF via `pillow-heif` + piexif
- `src/enrichment/png_writer.py` — XMP embedding via PNG iTXt chunk using Pillow
- `src/enrichment/xmp_builder.py` — Construct standards-compliant XMP XML from metadata fields
- `src/enrichment/field_mapping.py` — Maps `MediaMetadataResult` fields to EXIF/IPTC tags, UserComment text, and XMP fields

### Dependencies to Add

- `piexif` — EXIF read/write for JPEG/TIFF/WebP (pure Python)
- `iptcinfo3` — IPTC read/write for JPEG/TIFF (pure Python)
- `pillow-heif` — AVIF/HEIF support for Pillow (enables EXIF write on AVIF save)

### Implementation Steps

**Step 1: Dependencies**
- Add `piexif`, `iptcinfo3`, `pillow-heif` to `pyproject.toml`
- Verify imports: `import piexif`, `import iptcinfo3`, `from pillow_heif import register_heif_opener`

**Step 2: Field Mapping + XMP Builder**
- `field_mapping.py`:
  - `build_exif_dict(metadata) → dict` — maps to piexif tag format (ImageDescription, UserComment)
  - `build_iptc_dict(metadata) → dict` — maps to iptcinfo3 format (headline, caption, keywords, categories, location)
  - `build_user_comment(metadata) → str` — extended text block for all fields without standard EXIF/IPTC tags
- `xmp_builder.py`:
  - `build_xmp_xml(metadata) → str` — constructs XMP XML with Dublin Core (title, description, subject/keywords), IPTC Core (location), and Photoshop (headline) namespaces
  - Pure string template — no XML library dependency

**Step 3: Format-Specific Writers (all 6 formats)**
- `exif_writer.py`:
  - `embed_jpeg(file_bytes, metadata) → bytes` — piexif load → merge AI EXIF → dump → insert; then iptcinfo3 for IPTC fields
  - `embed_tiff(file_bytes, metadata) → bytes` — same EXIF+IPTC approach as JPEG
  - Preserve existing EXIF data (camera info, GPS) — only add/overwrite AI fields
- `webp_writer.py`:
  - `embed_webp(file_bytes, metadata) → bytes` — Pillow load → piexif build EXIF bytes → Pillow save with `exif=` param
- `avif_writer.py`:
  - `embed_avif(file_bytes, metadata) → bytes` — register pillow-heif opener → Pillow load → piexif build EXIF bytes → Pillow save with `exif=` param
- `png_writer.py`:
  - `embed_png(file_bytes, metadata) → bytes` — Pillow load PNG → build XMP XML → add as iTXt chunk (keyword `XML:com.adobe.xmp`) → Pillow save

**Step 4: Orchestrator**
- `embedder.py`: `MetadataEmbedder.embed()` routes by MIME type:
  - `image/jpeg` → `embed_jpeg()` (EXIF+IPTC)
  - `image/tiff` → `embed_tiff()` (EXIF+IPTC)
  - `image/webp` → `embed_webp()` (EXIF)
  - `image/avif` → `embed_avif()` (EXIF)
  - `image/png` → `embed_png()` (XMP via iTXt)
  - `image/bmp`, `image/gif` → returns `EnrichmentResult` with `embedded=False`, original bytes unchanged
- Returns `EnrichmentResult`:
  - `enriched_bytes` — the output bytes (enriched or original)
  - `embedded` — bool, whether metadata was actually embedded
  - `output_mime_type` — same as input for all current formats
  - `output_filename` — same as input
- Separate method: `convert_to_png_with_metadata(file_bytes, metadata) → EnrichmentResult`
  - Used by the explicit conversion endpoint (see P2-002)
  - Converts any image to PNG via Pillow, then embeds XMP

**Step 5: Tests**
- `tests/test_enrichment.py`:
  - JPEG: embed → read back with piexif → verify EXIF fields present
  - JPEG: embed → read back with iptcinfo3 → verify IPTC fields present
  - TIFF: embed → read back → verify EXIF+IPTC
  - WebP: embed → read back → verify EXIF present
  - PNG: embed → read back → verify iTXt chunk with XMP present, parse XML, check fields
  - AVIF: embed → read back → verify EXIF present
  - BMP: embed → `embedded=False`, original bytes returned unchanged
  - GIF: embed → `embedded=False`, original bytes returned unchanged
  - `convert_to_png_with_metadata()`: BMP in → PNG out with XMP embedded
  - `convert_to_png_with_metadata()`: GIF in → PNG out with XMP embedded
  - Preserve existing EXIF (camera data not overwritten by AI fields)
  - Round-trip: embed → Pillow can open enriched file without errors
  - Unicode: embed metadata with Unicode title/tags → no encoding errors

### Validation

- [ ] JPEG: title, description, keywords in EXIF+IPTC; readable by `piexif.load()` and `iptcinfo3`
- [ ] TIFF: title, description, keywords in EXIF+IPTC
- [ ] WebP: title, description in EXIF; readable by `piexif.load()`
- [ ] PNG: XMP iTXt chunk present; parseable XML with dc:title, dc:description, dc:subject
- [ ] AVIF: title, description in EXIF
- [ ] BMP: `embedded=False`, original bytes unchanged
- [ ] GIF: `embedded=False`, original bytes unchanged
- [ ] `convert_to_png_with_metadata()`: BMP/GIF → valid PNG with XMP
- [ ] Existing EXIF (camera model, GPS) preserved — not overwritten
- [ ] All enriched files openable in standard image viewers
- [ ] Module does not modify the original file in storage

---

## P2-002: Download Endpoints

### Objective

Two new API endpoints: single file download (enriched) and batch download (ZIP).

### Endpoints

#### `GET /api/v1/media/{id}/download`

Download the metadata-enriched image file.

**Response:** File bytes with `Content-Disposition: attachment; filename="original_filename.jpg"` and correct `Content-Type`.

**Flow:**
1. Load media item (verify ownership)
2. Load media metadata from DB
3. Read original file from storage
4. Call `MetadataEmbedder.embed(file_bytes, mime_type, metadata_result)`
5. Build download filename:
   - For BMP/GIF (`embedded=False`): use the AI-generated title as filename, sanitized for filesystem safety (replace special chars, truncate to reasonable length), preserving the original extension. Example: `IMG_4532.gif` → `Sunset_Beach.gif`.
   - For all other formats: use the original filename.
6. Return bytes with `Content-Disposition: attachment; filename="..."` using the resolved filename

**Filename sanitization for BMP/GIF:**
- Take `metadata.title`, replace non-alphanumeric chars (except spaces, hyphens, underscores) with underscores
- Replace spaces with underscores
- Truncate to 60 characters (before extension)
- Append original extension (`.gif`, `.bmp`)
- Fallback to original filename if title is empty or sanitization produces an empty string

This means if a user later converts the GIF to PNG, `Sunset_Beach.gif` → `Sunset_Beach.png` — the names match.

**Error responses:**
- `404` — Media item not found
- `409` — Analysis not yet completed (no metadata to embed)

#### `POST /api/v1/media/download-batch`

Download multiple enriched files as a ZIP.

**Request:**
```json
{
  "media_ids": ["id1", "id2", "id3"]
}
```

**Response:** ZIP file bytes with `Content-Disposition: attachment; filename="media_export.zip"` and `Content-Type: application/zip`.

**ZIP structure:**
```
media_export.zip
├── sunset_beach.jpg           ← enriched JPEG (EXIF+IPTC embedded)
├── portrait.png               ← enriched PNG (XMP embedded via iTXt)
├── landscape.webp             ← enriched WebP (EXIF embedded)
├── photo.avif                 ← enriched AVIF (EXIF embedded)
└── logo.gif                   ← original GIF (no metadata container — downloaded as-is)
```

Files that support metadata have it embedded. BMP/GIF are included as-is (user can convert them separately via the library UI).

**Constraints:**
- Max 50 files per batch (configurable)
- Only items belonging to the requesting user
- Only items with completed analysis (skip items without metadata, include count in response headers)
- ZIP generated in-memory using `zipfile.ZipFile` with `io.BytesIO`

**Error responses:**
- `400` — Empty media_ids list or exceeds batch limit
- `404` — None of the requested items found/accessible

#### `POST /api/v1/media/{id}/convert-png`

Convert a BMP/GIF media item to PNG with metadata embedded. Creates a **new** media item (the original is preserved).

**Flow:**
1. Load media item (verify ownership, verify format is BMP or GIF)
2. Load media metadata from DB (must be analyzed)
3. Read original file from storage
4. `MetadataEmbedder.convert_to_png_with_metadata(file_bytes, metadata)` → PNG bytes with XMP
5. Compute SHA256 of new PNG, check dedup
6. Store new PNG via FileStore, create new MediaItem (status: `completed`), copy metadata record
7. Return new media item info

**Response (201):**
```json
{
  "id": "new-uuid",
  "original_filename": "Sunset_Beach.png",
  "mime_type": "image/png",
  "status": "completed",
  "message": "Converted from GIF to PNG with embedded metadata"
}
```

**Error responses:**
- `400` — Media item is not BMP or GIF (already supports embedding natively)
- `404` — Media item not found
- `409` — Analysis not yet completed

### Files to Create/Modify

- `src/api/routes/download.py` — new router with download + batch + convert endpoints
- `src/api/schemas.py` — add `BatchDownloadRequest`, `ConvertResponse`
- `src/api/app.py` — register download router
- `src/config.py` — add `download` config (max_batch_size: 50)
- `config/settings.yaml` — add `download` section

### Implementation Steps

**Step 1: Configuration**
- Add `DownloadConfig` (max_batch_size: 50) to settings

**Step 2: Single Download Endpoint**
- `GET /api/v1/media/{id}/download`
- Load item + metadata, enrich (or pass-through for BMP/GIF), return with Content-Disposition

**Step 3: Batch Download Endpoint**
- `POST /api/v1/media/download-batch`
- Validate IDs, load items + metadata, enrich each (BMP/GIF included as-is), ZIP, return

**Step 4: Convert-to-PNG Endpoint**
- `POST /api/v1/media/{id}/convert-png`
- Validate format is BMP/GIF, convert to PNG with XMP, store as new media item, copy metadata

**Step 5: Tests**
- `tests/test_download.py`:
  - Single download of JPEG returns enriched file with correct headers
  - Single download of BMP returns original BMP bytes, filename uses AI title (`Sunset_Beach.bmp`)
  - Single download of unanalyzed item → 409
  - Batch download returns ZIP with correct files
  - Batch with mixed formats: JPEG enriched, PNG enriched, GIF as-is
  - Batch limit enforced
  - Auth required, user-scoped
  - Convert BMP → new PNG media item with title-based filename (`Sunset_Beach.png`), XMP embedded, original preserved
  - Convert JPEG → 400 (already supports embedding)
  - BMP/GIF download filename matches the PNG that conversion would create (same title stem, different extension)

### Validation

- [ ] Single download: Content-Disposition header triggers browser download
- [ ] Single download: JPEG/PNG/WebP/AVIF/TIFF have metadata embedded
- [ ] Single download: BMP/GIF returned as-is (no metadata), but filename uses AI title (e.g., `Sunset_Beach.gif`)
- [ ] Batch download: ZIP contains all files; embeddable formats enriched, BMP/GIF as-is
- [ ] Batch limit (50) enforced
- [ ] Unanalyzed items rejected (single) or skipped (batch)
- [ ] Convert endpoint: BMP/GIF → new PNG media item with XMP, original preserved
- [ ] Convert endpoint: non-BMP/GIF → 400
- [ ] Auth required, user-scoped

---

## P2-003: Frontend Download Button

### Objective

Add a download button on the media detail page.

### Implementation

- **Media detail page** (`MediaDetailPage.tsx`): Add "Download" button below the image when analysis is completed.
- **API client** (`client.ts`): Add `downloadFile(id)` function that fetches the download endpoint and triggers a browser download via blob URL + `<a>` click.
- **UX:** Button shows "Download (with metadata)" when analysis is completed and format supports embedding (JPEG/TIFF/WebP/AVIF/PNG). Disabled when analysis is pending/failed. For BMP/GIF: show "Download" (original file, no metadata) and a separate "Convert to PNG with metadata" button that calls `POST /api/v1/media/{id}/convert-png`, then refreshes the page to show the new PNG item.

### Files to Modify

- `frontend/src/api/client.ts` — add `downloadFile(id)`, `downloadBatch(ids)`, `convertToPng(id)`
- `frontend/src/pages/MediaDetailPage.tsx` — add download button + convert button for BMP/GIF
- `frontend/src/types/api.ts` — add `BatchDownloadRequest`, `ConvertResponse` types

### Validation

- [ ] Download button visible when analysis is completed (JPEG/TIFF/WebP/AVIF/PNG)
- [ ] BMP/GIF: "Download" button returns original file; "Convert to PNG" button triggers conversion
- [ ] After conversion: page refreshes/navigates to new PNG media item
- [ ] Button disabled/hidden when analysis is pending/failed
- [ ] Click triggers browser download with original filename
- [ ] Downloaded JPEG has metadata embedded

---

## P2-004: Frontend List View + Multi-Select + Batch Download

### Objective

Add a list/grid view toggle to Library and Search pages. List view shows checkboxes for multi-select. Selected items can be batch-downloaded.

### Component Design

**ViewToggle:** Small toggle button (grid icon / list icon) in the page header.

**List View Row:**
```
┌─────────────────────────────────────────────────────────────────┐
│ [✓]  [thumb]  sunset_beach.jpg    ● Completed   2.4 MB  Mar 28 │
│ [ ]  [thumb]  portrait.png        ● Processing   1.1 MB  Mar 28 │
│ [✓]  [thumb]  team_photo.jpg      ● Completed   3.2 MB  Mar 27 │
└─────────────────────────────────────────────────────────────────┘
```

**Selection bar** (appears when items selected):
```
┌──────────────────────────────────────────────────────────────┐
│  3 selected  |  [Download Selected]  |  [Clear Selection]    │
└──────────────────────────────────────────────────────────────┘
```

**BMP/GIF indicator in list view:** Items with `image/bmp` or `image/gif` MIME type show a small label "No metadata embedding" and a "Convert to PNG" action button inline. Clicking it calls `POST /api/v1/media/{id}/convert-png` and adds the new PNG to the library.

**Grid view:** Existing behavior (MediaCard grid). No checkboxes in grid view — selection is a list-view feature only.

### Implementation

**New components:**
- `frontend/src/components/ViewToggle.tsx` — grid/list toggle with icon buttons
- `frontend/src/components/MediaListRow.tsx` — list view row with checkbox, thumbnail, filename, status, size, date
- `frontend/src/components/SelectionBar.tsx` — floating bar showing count + batch download button

**Modified pages:**
- `LibraryPage.tsx` — add view toggle state, render grid or list, manage selection state, batch download
- `SearchPage.tsx` — same view toggle + selection support

**Selection state:** `useState<Set<string>>` for selected media IDs. Checkbox toggles membership. "Select all on page" checkbox in list header. Selection cleared on page change.

**Batch download flow:**
1. User selects items in list view (checkboxes)
2. Clicks "Download Selected" in selection bar
3. Frontend calls `POST /api/v1/media/download-batch` with selected IDs
4. Response is a ZIP blob → trigger browser download
5. Show progress indicator during download

### Files to Create

- `frontend/src/components/ViewToggle.tsx`
- `frontend/src/components/MediaListRow.tsx`
- `frontend/src/components/SelectionBar.tsx`

### Files to Modify

- `frontend/src/pages/LibraryPage.tsx` — view toggle, list view, selection
- `frontend/src/pages/SearchPage.tsx` — view toggle, list view, selection
- `frontend/src/api/client.ts` — `downloadBatch(ids)` function

### Validation

- [ ] View toggle switches between grid and list on Library page
- [ ] View toggle switches between grid and list on Search page
- [ ] List view shows checkboxes, thumbnail, filename, status, size, date
- [ ] Checkbox selection adds/removes from selection set
- [ ] "Select all on page" works
- [ ] Selection bar appears when items selected
- [ ] "Download Selected" triggers batch download (ZIP)
- [ ] Selection cleared on page change
- [ ] Grid view unchanged (no checkboxes)
- [ ] View preference persisted in localStorage

---

## P2-005: Frontend Search as Nav Tab

### Objective

Add Search as a navigation tab in the header alongside Library and Upload, so users can reach the search page without typing in the header search bar first.

### Implementation

**Single change in `Layout.tsx`:**
```tsx
<nav className="app-nav">
  <Link to="/" className="nav-link">Library</Link>
  <Link to="/upload" className="nav-link">Upload</Link>
  <Link to="/search" className="nav-link">Search</Link>
</nav>
```

**Behavior:** Clicking the Search nav tab navigates to `/search` with no query (shows the search page with the input focused and ready). The header SearchBar continues to work as before — typing there and pressing Enter also navigates to `/search?q=...`.

### Files to Modify

- `frontend/src/components/Layout.tsx` — add Search nav link

### Validation

- [ ] Search appears as third nav tab
- [ ] Click navigates to `/search`
- [ ] Active state highlighted when on search page
- [ ] Header search bar still works independently
- [ ] No visual regression on other pages

---

## Implementation Order

```
P2-005 (Search nav tab)           ← Independent, XS — do first
    │
P2-001 (Metadata embedder)       ← Backend foundation
    │
P2-002 (Download endpoints)      ← Depends on P2-001
    │
    ├── P2-003 (Download button)  ← Can start when P2-002 done
    │
    └── P2-004 (List view + batch download)  ← Can parallel with P2-003
```

**Recommended execution:**
1. **P2-005** — 15 minutes. One line change + validation.
2. **P2-001** — Backend metadata embedding module. Pure library code, independently testable.
3. **P2-002** — Download endpoints consuming P2-001.
4. **P2-003** — Download button (quick frontend addition).
5. **P2-004** — List view + multi-select (largest frontend change).

## Dependencies to Add

| Package | Purpose | Added In |
|---|---|---|
| `piexif` | EXIF read/write for JPEG/TIFF/WebP/AVIF | P2-001 |
| `iptcinfo3` | IPTC read/write for JPEG/TIFF | P2-001 |
| `pillow-heif` | AVIF/HEIF support for Pillow (enables EXIF write) | P2-001 |

No new frontend dependencies — all features use existing React + fetch.

## Exit Criteria (Full Feature Set)

- [ ] JPEG/TIFF files: metadata embedded in EXIF + IPTC (title, description, keywords, etc.)
- [ ] WebP files: metadata embedded in EXIF (title, description)
- [ ] PNG files: metadata embedded via XMP in iTXt chunk (dc:title, dc:description, dc:subject)
- [ ] AVIF files: metadata embedded in EXIF
- [ ] BMP/GIF files: downloaded as-is; explicit "Convert to PNG" action creates new PNG with XMP
- [ ] Convert endpoint: creates new media item (PNG), preserves original BMP/GIF
- [ ] `GET /api/v1/media/{id}/download` returns enriched file with Content-Disposition
- [ ] `POST /api/v1/media/download-batch` returns ZIP (embeddable formats enriched, BMP/GIF as-is)
- [ ] `POST /api/v1/media/{id}/convert-png` converts BMP/GIF to PNG with XMP
- [ ] Download button on media detail page (enabled when analysis complete)
- [ ] Library page: grid/list view toggle
- [ ] Search page: grid/list view toggle
- [ ] List view: checkboxes for multi-select
- [ ] Selection bar with batch download
- [ ] Search accessible as nav tab
- [ ] Existing EXIF data (camera, GPS) preserved — not overwritten
- [ ] All existing 38 backend tests still pass
- [ ] New enrichment + download tests pass
- [ ] `PROJECT_MAP.md` updated

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `piexif` doesn't handle all JPEG EXIF variants | Medium | piexif is well-established. Wrap in try/except — log warning and return original bytes as last resort. |
| `iptcinfo3` may have encoding issues with Unicode | Medium | Test with Unicode titles/descriptions. Encode as UTF-8 explicitly. |
| Large batch ZIPs consume too much memory | Medium | 50-file limit. For 50 × 50MB files (theoretical max) = 2.5GB. In practice, most photos are 2-10MB → 100-500MB ZIP. Stream ZIP to response if memory is a concern. |
| WebP EXIF support varies by viewer | Low | Embedding is still better than nothing. Major tools (Lightroom, exiftool) read WebP EXIF. |
| AVIF EXIF via `pillow-heif` may not work on all AVIF variants | Medium | `pillow-heif` is actively maintained. Test with real AVIF files. If a specific AVIF file fails, fall back to returning original bytes with warning logged. |
| PNG XMP iTXt chunk not read by all tools | Low | The `XML:com.adobe.xmp` keyword is the Adobe standard — supported by Lightroom, Bridge, Finder, exiftool. Basic viewers may not show it, but the data is there. |
| BMP/GIF users may not realize metadata isn't embedded | Low | Library UI shows indicator for formats without embedded metadata + explicit "Convert to PNG" action. |
| Existing EXIF corruption on embed | Medium | Always read existing EXIF first, merge AI fields, write back. Test with diverse real-world JPEGs. |

## Notes

- **Original file is never modified in storage.** The enriched file is generated on-the-fly at download time. The file store retains the original upload. This aligns with ADR-002 (database is the system of record) and ADR-004 (content-addressed storage — modifying the file would change the hash).
- **No sidecars.** Embeddable formats (JPEG, TIFF, WebP, AVIF, PNG) always have metadata written directly into the file. BMP/GIF are downloaded as-is since they have no metadata container — the user can explicitly convert them to PNG with metadata via the library UI.
- **The `MetadataEmbedder` module is stateless.** It takes bytes in, returns bytes out. No database access, no file system access. This makes it easy to test and easy to call from any context.
- **`iptcinfo3` vs `python-iptc`:** `iptcinfo3` is the maintained fork of `iptcinfo`. It's pure Python and handles the common IPTC fields well.
- **XMP for PNG is pure Python.** The XMP XML is a template string — no XML library needed for construction. The iTXt chunk is written via Pillow's `PngInfo` API. No C dependencies.
- **`pillow-heif`** adds HEIF/AVIF codec support to Pillow. After calling `register_heif_opener()`, Pillow can open/save AVIF files with EXIF data via the standard `exif=` parameter.
