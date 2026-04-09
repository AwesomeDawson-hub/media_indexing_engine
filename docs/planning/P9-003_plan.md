# P9-003 Plan — Additive Origin/Preview Domain Split

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 9 — ARCH-002 Gap Remediation |
| **Project** | Media Indexing Engine |
| **Workstream** | P9-003 |
| **Created** | 2026-04-09 |
| **Author** | Architect |
| **Status** | Architect scope accepted — awaiting Auditor pass before Engineer handoff |
| **Dependencies** | P9-001 completed; P9-002 completed; `ARCH-002-reference-mode-storage.md`; `PHASE_9_arch002_gap_remediation_plan.md` |

## Objective

Introduce first-class origin and preview records behind the existing `MediaItem` aggregate without destabilizing the beta data model. This workstream exists to make origin identity item-owned instead of being inferred indirectly from source-scoped sync memory, and to make retained preview assets explicit instead of representing them only through `MediaItem.thumbnail_path`.

This workstream is additive. It does **not** replace `MediaItem`, does **not** replace `SourceObject`, and does **not** introduce `WriteBackOperation` or `SourceCapabilitySnapshot` yet.

---

## Architect Decision Summary

### 1. `OriginAssetRef` does not replace `SourceObject`

`OriginAssetRef` is a new **1:1 child table of `MediaItem`**.

It is the **item-owned canonical origin locator** used by the application layer.

`SourceObject` remains in place as the **source-scoped connector sync-memory record** used for:

- idempotent object tracking
- last sync/import state
- connector error and state reporting
- tracking the last imported media item for a remote object

The boundary is:

- `SourceObject` answers: "what did the connector see and what happened during sync?"
- `OriginAssetRef` answers: "what origin does this media item currently point at?"

For connector-backed items, `OriginAssetRef` may point at a `SourceObject` row, but it still duplicates the media-item-owned locator fields needed by downstream consumers. This is intentional. `WriteBackOperation`, source-aware reads, and future origin availability logic must target an item-owned origin record, not a source-owned sync-memory row.

### 2. `OriginAssetRef` applies to all media items, not only connector items

`OriginAssetRef` is required for every `MediaItem`.

Initial locked `provider_type` values in this workstream:

- `google_drive`
- `s3`
- `local_folder`
- `app_upload`

Interpretation:

- connector-backed items use their connector provider type and may link to `SourceObject`
- browser local working-folder items use `provider_type='local_folder'`
- app-retained manual uploads use `provider_type='app_upload'`

Manual-upload items therefore do get an `OriginAssetRef`; they simply have no `source_object_id`.

### 3. P9-003 is a prerequisite for P9-004 as currently defined

`SourceCapabilitySnapshot` could technically be introduced using `Source` plus `SourceConnector` before `OriginAssetRef` exists, but `WriteBackOperation` should not be implemented on top of the current `MediaItem` plus `SourceObject` field smear.

Therefore the locked workflow decision is:

- do **not** start P9-004 before P9-003 lands
- do **not** scope P9-003 down to `PreviewAsset` only
- keep P9-003 narrow by limiting `OriginAssetRef` to identity and locator concerns, not capability state or write-back orchestration

That is the lowest-risk sequencing that still gives P9-004 the correct target contract.

---

## Locked Schema for P9-003

## New Table: `origin_asset_refs`

One row per `MediaItem`.

### Columns

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `String(36)` | No | PK, UUID |
| `media_item_id` | `String(36)` | No | FK to `media_items.id`, UNIQUE |
| `user_id` | `String(36)` | No | FK to `users.id`, indexed for scoped queries |
| `source_id` | `String(36)` | Yes | FK to `sources.id`; denormalized join helper, mirrors `MediaItem.source_id` |
| `source_object_id` | `String(36)` | Yes | FK to `source_objects.id`; nullable because not all items are connector-backed |
| `provider_type` | `String(50)` | No | Locked values for this slice: `google_drive`, `s3`, `local_folder`, `app_upload` |
| `provider_object_id` | `String(1024)` | Yes | Stable provider object identifier where one exists; for current connectors this is initially copied from `SourceObject.external_object_key` |
| `locator_snapshot` | `String(1024)` | Yes | Display-oriented path/key snapshot; for initial connector backfill this is the same value as `external_object_key` |
| `revision_marker` | `String(255)` | Yes | Version / revision / etag marker; initially copied from `SourceObject.external_version` when available |
| `app_storage_path` | `String(500)` | Yes | Canonical app-retained original path for `app_upload` items |
| `local_file_fingerprint` | `String(64)` | Yes | Canonical local-folder fingerprint; replaces `MediaItem.source_file_fingerprint` as the authoritative origin field |
| `created_at` | `DateTime(timezone=True)` | No | Default UTC now |
| `updated_at` | `DateTime(timezone=True)` | No | Default UTC now / on update |

### Constraints and indexes

- `UNIQUE (media_item_id)`
- index on `user_id`
- index on `source_id`
- index on `source_object_id`
- optional composite index on `(provider_type, provider_object_id)` for future lookup support

### Explicit non-goals in this table

Do **not** add these to `OriginAssetRef` in P9-003:

- rename capability flags
- write-back capability flags
- operation status fields
- retry/error state
- preview-path fields

Those remain out of scope until P9-004.

## New Table: `preview_assets`

One row per retained preview derivative.

### Columns

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `String(36)` | No | PK, UUID |
| `media_item_id` | `String(36)` | No | FK to `media_items.id` |
| `user_id` | `String(36)` | No | FK to `users.id`, indexed |
| `variant_type` | `String(20)` | No | Locked initial value: `thumbnail`; future-safe for `preview` |
| `storage_path` | `String(500)` | No | Object-store path for the retained preview bytes |
| `mime_type` | `String(50)` | No | For current slice this will normally be `image/jpeg` |
| `width` | `Integer` | Yes | Stored derivative dimensions |
| `height` | `Integer` | Yes | Stored derivative dimensions |
| `file_size` | `BigInteger` | Yes | Optional preview byte size |
| `checksum` | `String(64)` | Yes | Optional checksum/content hash of the preview derivative |
| `created_at` | `DateTime(timezone=True)` | No | Default UTC now |
| `updated_at` | `DateTime(timezone=True)` | No | Default UTC now / on update |

### Constraints and indexes

- `UNIQUE (media_item_id, variant_type)`
- index on `user_id`
- index on `storage_path`

---

## Backfill Rules

## `origin_asset_refs`

Create one row for every existing `MediaItem`.

### Connector-backed items

Backfill strategy:

- set `provider_type` from the connected source/provider
- set `source_id` from `MediaItem.source_id`
- set `source_object_id` only when there is an explicit current link via `SourceObject.last_imported_media_item_id = MediaItem.id`
- copy `provider_object_id` from `SourceObject.external_object_key` when linked
- copy `locator_snapshot` from `SourceObject.external_object_key` when linked
- copy `revision_marker` from `SourceObject.external_version` when linked
- leave `app_storage_path` null
- leave `local_file_fingerprint` null

Do **not** try to infer missing `source_object_id` values through fuzzy hash/path matching in this migration.

### Local-folder items

Backfill strategy:

- `provider_type='local_folder'`
- `source_id = MediaItem.source_id`
- `source_object_id = NULL`
- `local_file_fingerprint = MediaItem.source_file_fingerprint`
- `app_storage_path = NULL`

### Manual upload / app-retained items

Backfill strategy:

- `provider_type='app_upload'`
- `source_id = MediaItem.source_id`
- `source_object_id = NULL`
- `app_storage_path = MediaItem.storage_path`
- `local_file_fingerprint = NULL`

## `preview_assets`

Create one `variant_type='thumbnail'` row for every `MediaItem` with non-null `thumbnail_path`.

Backfill strategy:

- `storage_path = MediaItem.thumbnail_path`
- `mime_type = 'image/jpeg'` when existing code guarantees JPEG thumbnails; otherwise preserve best-known MIME from the generating path
- width/height/file_size/checksum may be left null in the first migration if deriving them would require opening all preview objects

---

## Locked MediaItem Field Treatment

## True migrations with compatibility mirrors

### `MediaItem.storage_path`

- **Authoritative target in P9-003:** `OriginAssetRef.app_storage_path`
- **Treatment in P9-003:** keep `MediaItem.storage_path` as a compatibility mirror
- **Read rule during rollout:** prefer `origin_asset_refs.app_storage_path`, fall back to `media_items.storage_path`
- **Write rule during rollout:** app-retained upload flows must write both fields
- **Long-term intent:** remove direct ownership from `MediaItem` after downstream compatibility risk is gone

This field is a **true migration**, not a permanent `MediaItem` field.

### `MediaItem.thumbnail_path`

- **Authoritative target in P9-003:** `PreviewAsset.storage_path` for `variant_type='thumbnail'`
- **Treatment in P9-003:** keep `MediaItem.thumbnail_path` as a compatibility mirror
- **Read rule during rollout:** prefer `preview_assets`, fall back to `media_items.thumbnail_path`
- **Write rule during rollout:** thumbnail-producing code must create/update the `PreviewAsset` row and mirror `MediaItem.thumbnail_path`
- **Long-term intent:** stop treating `MediaItem.thumbnail_path` as the canonical preview record

This field is also a **true migration**, with additive compatibility maintained in this workstream.

### `MediaItem.source_file_fingerprint`

- **Authoritative target in P9-003:** `OriginAssetRef.local_file_fingerprint`
- **Treatment in P9-003:** keep `MediaItem.source_file_fingerprint` as a compatibility mirror
- **Read rule during rollout:** prefer `origin_asset_refs.local_file_fingerprint`, fall back to `media_items.source_file_fingerprint`
- **Write rule during rollout:** local-folder flows must update both fields
- **Long-term intent:** remove origin-specific fingerprint ownership from `MediaItem`

This field is a **true migration**, not a permanent aggregate field.

## Left unchanged in P9-003

### `MediaItem.source_id`

Stays on `MediaItem` permanently.

Reason: it is the aggregate's owning source link, not just an origin-locator implementation detail.

`OriginAssetRef.source_id` exists only as a denormalized helper for simpler item-origin queries and backfill clarity.

### `MediaItem.storage_mode`

Stays on `MediaItem` permanently.

Reason: it is aggregate display/availability state (`full`, `preview_only`, `reference`), not a pure origin-ref field.

### Mutation / write-back fields on `MediaItem`

These stay unchanged and authoritative in P9-003:

- `mutation_state`
- `first_seen_source_filename`
- `prior_source_filename`
- `source_filename_applied_at`
- `last_writeback_at`
- `last_mutation_attempted_at`
- `last_mutation_error_code`
- `last_mutation_error_message`

Reason: P9-003 is **not** the write-back refactor. These remain the current aggregate summary state until P9-004 introduces `WriteBackOperation`.

`SourceMutationHistory` also remains unchanged and continues to be the durable history table.

---

## Compatibility Layer Requirements

Engineer must implement a compatibility layer, not a flag day.

### ORM / model rules

- add ORM models for `OriginAssetRef` and `PreviewAsset`
- add one-to-one relationship: `MediaItem.origin_asset_ref`
- add one-to-many relationship: `MediaItem.preview_assets`
- do **not** remove existing `MediaItem` columns in this workstream

### Read precedence

- original app-storage path: `OriginAssetRef.app_storage_path` first, fallback `MediaItem.storage_path`
- local fingerprint: `OriginAssetRef.local_file_fingerprint` first, fallback `MediaItem.source_file_fingerprint`
- thumbnail path: `PreviewAsset(variant='thumbnail')` first, fallback `MediaItem.thumbnail_path`

### Write precedence

- new authoritative writes go to the new tables first
- compatibility mirrors on `MediaItem` must still be updated in the same transaction during rollout

### Explicit non-goals for P9-003 compatibility work

- do not attempt to remove all old-column reads in one slice
- do not rewrite every caller to depend only on the new tables before the migration lands cleanly
- do not mix capability-state or write-back-operation logic into these models

---

## Boundary Between P9-003 and P9-004

## P9-003 includes

- Alembic migration for `origin_asset_refs`
- Alembic migration for `preview_assets`
- ORM models and relationships
- backfill from existing `MediaItem` / `SourceObject` data
- compatibility read-through and write-mirroring layer
- targeted updates to code that produces or reads thumbnail/origin identity data so the new tables are populated going forward

## P9-003 explicitly excludes

- dropping old `MediaItem` columns
- replacing `SourceObject`
- moving mutation/write-back state off `MediaItem`
- adding `SourceCapabilitySnapshot`
- adding `WriteBackOperation`

## P9-004 must assume

- `OriginAssetRef` is the canonical item-owned origin locator
- `PreviewAsset` is the canonical retained preview record
- `MediaItem` mutation fields are still summary fields until P9-004 deliberately decides what remains mirrored there

That means `WriteBackOperation` should target `OriginAssetRef`, not `SourceObject` and not raw `MediaItem.storage_path` / `source_file_fingerprint` fields.

---

## Architect Verdict

The locked P9-003 scope is:

1. add both `OriginAssetRef` and `PreviewAsset`
2. keep `SourceObject` as connector sync memory
3. make `OriginAssetRef` the item-owned locator for **all** media items, including manual uploads
4. migrate `storage_path`, `thumbnail_path`, and `source_file_fingerprint` into the new model with compatibility mirrors
5. leave mutation/write-back fields on `MediaItem` unchanged for this slice
6. treat P9-003 as a prerequisite for P9-004 rather than trying to build `WriteBackOperation` on the old field smear

This is the smallest scope that resolves the model ambiguity cleanly enough for implementation without taking on the migration risk of a broader aggregate rewrite.