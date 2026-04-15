# ARCH-004 — Source Capture Metadata Preservation Hardening

## Status

Architect decision note — implementation-ready hardening slice definition.

This note intentionally does **not** merge metadata-preservation hardening into `P12-002`.
`P12-002` remains measurement-first. This note defines a separate prerequisite hardening slice that should be approved independently if the operator wants capture-date and source-location correctness locked before remembered-photo benchmark implementation expands search expectations.

## Objective

Lock the contract for preserving source-authored capture metadata so the product can support reliable date-taken behavior and safe metadata write-back without allowing AI inference to overwrite authoritative source fields.

The slice is narrowly scoped to:

- source-truth capture metadata extraction and persistence
- safe metadata write-back preservation rules
- search-by-date correctness contract
- focused preservation tests for capture time and GPS

This slice does **not** include:

- remembered-photo benchmark implementation
- retrieval or ranking changes
- metadata-schema expansion for richer AI search semantics
- multimodal work
- general metadata-authoring redesign

---

## Current Risk

The current system preserves some existing EXIF during JPEG/TIFF enrichment, but it does not yet lock a full source-truth contract for capture date/time and GPS.

Observed risks in the current codebase:

- original capture date/time and GPS do not appear to be stored as first-class DB fields at ingest time
- date-taken behavior would therefore have to rely on rereading mutable files or on missing data
- `location_hint` is AI-inferred but is currently mapped into standard source-location fields such as IPTC city and XMP `Iptc4xmpCore:Location`
- PNG XMP embedding currently replaces the XMP packet rather than performing a source-preserving merge

That combination is too weak for reliable date-taken search and too risky for source-authored metadata preservation.

---

## Locked Decisions

## D1 — Original capture date/time and GPS must be extracted and stored in the DB at ingest time

### Decision

Yes. Source-authored capture metadata must be extracted during ingest and stored in first-class DB fields rather than being treated as file-only metadata.

### Locked reason

- search/filter correctness cannot depend on mutable enriched files
- connector-backed reference items may not have app-retained originals available later
- re-analysis and write-back are allowed to change AI-authored metadata, so source-truth capture fields must live outside the AI metadata payload

### Locked storage rule

This slice should add additive nullable first-class fields for source-truth capture metadata on the app side.

Minimum required fields:

- `source_capture_datetime_utc`
- `source_capture_datetime_raw`
- `source_capture_time_offset_minutes`
- `source_gps_latitude`
- `source_gps_longitude`

Optional only if cheaply available in the same extraction pass:

- `source_gps_altitude_meters`

### Implementation boundary

For this hardening slice, store these as first-class DB fields on the queryable media record boundary used by search and filtering. Do not defer the authoritative date-taken contract to enriched-file rereads.

## D2 — Date-taken search must depend on DB fields, not rereading mutated files

### Decision

Yes. Any date-taken search or filtering contract must read from the DB fields populated at ingest or backfill time.

### Locked rule

- ingest/backfill is the only place where source capture metadata is normalized into the app contract
- search-by-date must query the stored DB fields
- re-reading mutated files at query time is not part of the search contract

### Consequence

Connector-backed items, preview-only items, and future write-back changes all remain compatible with one stable date-taken contract.

## D3 — Which metadata fields are authoritative and must never be overwritten by AI inference?

### Decision

AI inference must never overwrite source-authored capture-time or source-location fields.

### Locked authoritative field categories

The following categories are source-truth and must be preserved when present:

1. capture date/time
   - EXIF `DateTimeOriginal`
   - EXIF `DateTimeDigitized`
   - EXIF offset fields such as `OffsetTimeOriginal` when present
   - equivalent source-authored XMP date-created fields when present

2. GPS coordinates
   - EXIF GPS latitude / longitude
   - EXIF GPS altitude when present
   - equivalent source-authored XMP GPS fields when present

3. standard source-location descriptors
   - IPTC city / sub-location / province-state / country fields
   - XMP IPTC location fields

### Locked overwrite rule

AI-authored metadata may enrich descriptive fields, but it must not replace, blank out, or remap the authoritative source-truth categories above.

## D4 — AI `location_hint` must stop writing into IPTC city or other standard source-location fields

### Decision

Yes. AI `location_hint` must no longer write into IPTC city, XMP IPTC location, EXIF GPS, or any other standard source-location field.

### Locked reason

`location_hint` is inference, not source-truth capture metadata. Writing it into standard location fields corrupts provenance and can silently destroy or falsify source-authored location meaning.

### Locked write-back rule

- do not map AI `location_hint` into IPTC city
- do not map AI `location_hint` into XMP `Iptc4xmpCore:Location`
- do not derive EXIF GPS from AI `location_hint`

If the product still wants to persist AI location-like text into exported metadata, it must be written only into a clearly non-authoritative app-defined descriptive field or omitted entirely until such a field exists.

## D5 — PNG/XMP preservation requires merge behavior, not whole-packet replacement

### Decision

Yes. PNG XMP handling must use merge-preservation behavior rather than whole-packet replacement.

### Locked rule

- if a PNG already contains XMP, existing source-authored XMP content must be preserved
- AI-authored fields may be added or updated only through a merge strategy that does not discard unrelated existing namespaces/properties
- if safe merge cannot be completed for a file, fail closed: preserve the existing XMP packet and skip destructive rewrite

### Consequence

The product must not destroy source-authored XMP simply to add AI-authored title/description/keywords.

---

## Source-Truth Capture Metadata Contract

### First-class app fields

The app-side authoritative capture metadata contract is:

- `source_capture_datetime_utc`: normalized UTC timestamp used for search/filter correctness
- `source_capture_datetime_raw`: original source string or raw normalized source value for auditability
- `source_capture_time_offset_minutes`: parsed source offset when available
- `source_gps_latitude`: source-authored decimal latitude
- `source_gps_longitude`: source-authored decimal longitude
- `source_gps_altitude_meters`: optional additive altitude when available

### Field ownership rule

These fields are source-truth metadata, not AI metadata. They must not be overwritten by re-analysis, metadata edit flows, or AI write-back.

### Population rule

These fields must be populated from source-authored metadata during:

- initial ingest where metadata is available
- any explicit backfill/remediation script created for historical rows

---

## Write-Back Preservation Rules

1. Preserve existing EXIF capture-time and GPS fields across JPEG/TIFF/WebP/AVIF write-back.
2. Preserve existing IPTC/XMP standard source-location fields; do not map AI `location_hint` into them.
3. Restrict AI-authored write-back to clearly descriptive, non-authoritative fields such as headline, description, keywords, and app-defined descriptive extensions.
4. For PNG, merge XMP non-destructively. If safe merge is not possible, preserve the original packet and skip destructive AI XMP replacement.
5. Re-analysis may update AI metadata fields, but it must not mutate the first-class source-truth capture metadata DB fields unless an explicit metadata re-extraction/backfill operation is running.

---

## Search-By-Date Contract

1. Date-taken search/filter behavior must read from `source_capture_datetime_utc`.
2. Query-time file rereads are not part of the search contract.
3. If the source file has no trustworthy capture date, the DB field remains null and the item is excluded from date-taken filtering unless future product rules say otherwise.
4. `analyzed_at`, upload time, or mutation/write-back timestamps must not masquerade as date taken.

---

## Required Tests

Minimum required tests for this hardening slice:

1. ingest extracts `DateTimeOriginal` and stores normalized `source_capture_datetime_utc`
2. ingest preserves the original source capture timestamp in `source_capture_datetime_raw`
3. ingest extracts GPS latitude/longitude into DB fields when present
4. re-analysis does not overwrite stored source capture datetime or GPS fields
5. JPEG/TIFF enrichment preserves pre-existing `DateTimeOriginal` and GPS EXIF data after AI metadata embed
6. AI `location_hint` is not written into IPTC city or XMP IPTC location fields
7. PNG enrichment preserves existing XMP when present and merges AI metadata without dropping unrelated source-authored fields
8. if PNG XMP merge cannot be performed safely, the writer leaves the original XMP intact rather than replacing it destructively

---

## Implementation Shape

This hardening slice should be implemented in four small parts:

1. add first-class DB fields for source capture datetime and GPS
2. add ingest-time extraction and historical backfill path for those fields
3. tighten enrichment/write-back mapping so authoritative source fields are preserved and AI `location_hint` is no longer written into standard location fields
4. add focused preservation tests for `DateTimeOriginal`, GPS, and PNG XMP merge behavior

---

## Recommendation

Do not merge this work into `P12-002` by default.

Recommended workflow outcome:

- keep `P12-002` as the measurement-first benchmark slice
- approve this metadata-preservation hardening note as a separate prerequisite or adjacent hardening slice if the operator wants capture-date search correctness locked before broader search-quality work begins

That keeps benchmark work, metadata-preservation work, and later richer search-schema work separated enough to remain auditable and implementation-safe.