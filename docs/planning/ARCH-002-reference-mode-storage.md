# Reference-Mode Storage Pivot — Architecture Proposal

**Project:** Media Indexing Engine  
**Author:** Architect  
**Date:** 2026-04-05  
**Status:** Approved architectural basis for the reference-mode storage pivot; current implementation direction is Phase 9 remediation via `PHASE_9_arch002_gap_remediation_plan.md`, with `P9-001` as the next approved workstream

---

## 1. Architecture Verdict

**Verdict:** `Risky but viable` and directionally correct for the product.

This pivot is fundamentally the right direction **if the product intent is discovery, organization, search, and source-aware metadata operations rather than permanent original-file hosting**. It reduces long-term storage liability, aligns cloud-connected ingestion with user expectations that originals remain in their own systems, and creates a cleaner distinction between:

- the **source of truth for original assets**
- the **application-owned search and intelligence layer**
- the **preview layer required for fast UX**

However, this is **not** a small extension of the current model. It is a substantial architectural pivot that changes the meaning of ingestion, storage, download, metadata embedding, re-analysis, and availability guarantees.

### Direct answer to the product question

**Yes, this redesign direction is fundamentally correct for the product** if the operator wants the app to become:

- a search and organization layer
- a metadata intelligence layer
- a source-connected workflow tool

and **not** a hosted original-image vault.

### Direct answer on roadmap impact

**Yes, this requires a significant rewrite of the current Phase 5 / connector-storage assumptions.**

What survives from the current architecture:

- source and connector concepts
- encrypted connector secret storage
- sync-run tracking
- source-object identity memory
- user scoping, auth, search, metadata, and connector orchestration patterns

What does **not** survive unchanged:

- the assumption that every imported image becomes an app-stored full-resolution asset
- the assumption that `GET /media/{id}/file` can always serve the original
- the assumption that re-analysis and metadata embed/download can always use AWS-retained original bytes
- the assumption that browser upload should create a permanent AWS-stored copy

---

## 2. Major Implications

### A. The system must split into three asset layers

The current design treats one stored object as both:

- the permanent original
- the analysis input
- the gallery/display asset
- the download source

That coupling must be broken. The new model needs separate concepts for:

- **original asset** at source
- **transient analysis derivative** used during processing
- **retained preview/thumbnail asset** for gallery and UI

### B. Ingestion is no longer equivalent to ownership transfer

Today, upload or sync means "the app now owns a copy of the file." After the pivot, connector ingestion means:

- fetch enough bytes to analyze
- derive lightweight retained artifacts
- persist metadata and search state
- discard full-resolution bytes

That is a different contract and must be explicit in both backend design and UX.

### C. Full-resolution access becomes conditional, not guaranteed

Gallery, search, metadata, and thumbnails can remain available from AWS-retained data, but **original access becomes dependent on source reachability and authorization**.

That means the product must explicitly track and expose original availability state.

### D. Write-back becomes a first-class subsystem

The current system embeds metadata into downloaded bytes from app storage. In the new model, metadata write-back and rename operations must target the **origin asset**, not a hosted copy.

That introduces:

- capability differences by source type
- permission and token scope issues
- conflict handling
- auditability requirements
- retry / failure-state management

### E. Seamless live local-device management is impossible to do correctly from the browser alone

Cloud sources can be implemented server-to-provider. Local-device or local-drive sources require an **agent, desktop app, or bridge process** that can:

- enumerate local files
- generate or stream analysis derivatives
- perform write-back and rename locally
- surface availability back to the cloud app

This must be treated as a separate capability, not hand-waved as "upload but local."

However, the browser can still support a **user-assisted local working-folder model** when the user explicitly grants folder access. That is materially weaker than a live agent, but it is sufficient for a no-install workflow if the product accepts explicit re-selection and browser compatibility limits.

### F. Thumbnail / preview serving becomes a core platform concern

Once originals are no longer retained, the app’s retained preview assets are what keep the gallery usable and fast. Their storage pattern matters operationally.

---

## 3. Recommended Target Architecture

## 3.1 System Positioning

The target system should be:

- **System of record for metadata, search, and user-facing library organization**
- **Not** the long-term system of record for original full-resolution bytes
- **Owner of retained preview assets only**
- **Coordinator of source-aware write-back operations**

### Product boundary

AWS retains:

- media/item identity
- source linkage and origin locator
- extracted metadata
- search vectors and other index state
- lightweight visual derivatives for gallery / preview
- technical signals needed for dedup, sorting, and UX

AWS does **not** retain:

- long-term full-resolution originals for connector-sourced assets

---

## 3.2 Core Domain Model

The current `MediaItem` model is too storage-centric. The target architecture should conceptually separate these responsibilities, even if the first implementation evolves the current table additively.

### Canonical concepts

#### `MediaRecord`

The application-owned record representing one indexed item.

Owns:

- item ID
- user ownership
- source ID
- display state
- processing status
- metadata/search associations
- retained preview references
- origin availability status

#### `OriginAssetRef`

The source-side pointer to the original.

Owns:

- origin provider type (`google_drive`, `dropbox`, `local_agent`, `manual_copy`, etc.)
- stable provider object ID where possible
- path/locator snapshot where useful for display only
- revision/version markers if the source supports them
- origin capability flags

#### `PreviewAsset`

The application-retained visual derivative used for gallery and detail preview.

Owns:

- object storage key or URL reference
- mime type
- width/height
- file size
- checksum
- variant type (`thumb`, `preview`)

#### `WriteBackOperation`

A durable operation record for metadata write-back and rename.

Owns:

- target source asset reference
- desired operation (`metadata_write`, `rename`)
- requested payload
- last attempt status
- error state
- actor and timestamps

This should become a real subsystem, not an ad hoc call from a route handler.

#### `SourceMutationHistory`

A durable history of what the source asset used to be versus what the system changed it to.

Owns:

- original source filename at first import
- prior source filename before each rename
- current source filename after the latest successful rename
- metadata revision identifiers or timestamps
- last successful metadata payload written back
- actor, operation type, and completion timestamp

This is required so the system can explain both the current state and the pre-mutation state of each asset.

#### `SourceCapabilitySnapshot`

A source-level capability and health record shown in Connections and used by the backend to gate behavior.

Owns:

- source display name
- source type and provider
- location or container label visible to the user
- current auth or connectivity state
- last successful scan time
- last successful original-fetch check
- rename capability
- embedded metadata write-back capability
- original-read capability
- item count and last seen item activity

This should be modeled explicitly. It must not be inferred loosely from unrelated connector status strings.

---

## 3.3 Source-of-Truth Model

### Originals

**Source of truth:** the external source system or local agent-managed filesystem.

Examples:

- Google Drive file
- Dropbox file
- local desktop filesystem file exposed through an agent
- explicit manual-copy upload if product policy still allows it

### Metadata / search / index

**Source of truth:** AWS application database plus vector/index infrastructure.

This includes:

- titles, descriptions, tags, people, OCR, mood, context
- search embeddings and retrieval metadata
- dedup and perceptual-hash signals
- source linkage
- availability state
- write-back audit state

### Thumbnails / previews

**Source of truth:** application-managed object storage, referenced from the relational database.

The DB should own the metadata and pointer; object storage should own the bytes.

### Write-back operations

**Source of truth:** application database for operation intent and state; original source for the resulting file mutation.

Meaning:

- the app owns the fact that a rename/write-back was requested, attempted, succeeded, or failed
- the origin owns the final filename and embedded metadata bytes

### Mandatory write-back contract

For this product direction, generated metadata and the computed target filename are not optional side outputs. They are part of the intended end state of the original asset.

That means:

- after analysis completes, the system should attempt to apply the new filename and metadata to the source asset **as soon as the source is writable**
- if immediate source mutation is possible, it should happen right away
- if immediate source mutation is not possible because the source is unavailable, permissions are missing, or user folder access is not currently granted, the system must record a pending write-back state and surface it clearly
- the system must preserve a record of what the asset used to be before the change

"ASAP" in this design means: attempt in the same post-analysis flow or in the immediately queued follow-up write-back job, not as an undefined future sync.

### No silent AWS-original fallback rule

The storage pivot is not allowed to degrade into a hidden permanent-copy mode when source mutation is difficult.

That means:

- browser drag-drop and local-folder flows must not silently fall back to permanent AWS retention of originals
- cloud-source mutation failures must not be "resolved" by keeping a permanent AWS-hosted original and mutating that copy instead
- when the source cannot yet be mutated, the system must classify the item as `pending_writeback` or `blocked_writeback`, not pretend the architectural rule no longer applies

---

## 3.4 Source Capability Model for Rename and Metadata Editing

The product must distinguish between two different kinds of "editing":

1. **source-side rename / title change**
2. **embedded file-metadata write-back** to the actual image bytes

They are not the same operation and should not be represented as one generic "edit metadata" capability.

### Rename support

#### Google Drive

- **Yes, rename is supported.**
- This is a provider metadata update on the Drive file object, not a byte-level image rewrite.
- It is a good candidate for early support.

#### Dropbox and similar cloud file providers

- **Usually yes, rename is supported.**
- This is again a provider-side path or object rename operation.
- It should be modeled separately from embedded EXIF/IPTC/XMP mutation.

#### S3-compatible object storage

- **Not truly rename-in-place.**
- The practical implementation is copy + delete.
- That is more operationally risky than provider-native rename and should be treated as a separate capability class.

### Embedded metadata write-back support

#### Google Drive

- **Not natively supported as an in-place image metadata patch.**
- To change EXIF/IPTC/XMP inside the file, the system would need to download the image bytes, mutate them, and upload a new revision of the file.
- This is possible in principle, but it is a **content rewrite**, not a lightweight metadata edit.
- It changes the file revision and must be treated as a write-back job with conflict and failure handling.

#### Dropbox and similar cloud file providers

- Same practical rule: embedded metadata write-back generally means rewrite-and-reupload, not a provider-native metadata patch.
- That makes it possible in some cases, but not a cheap or universal guarantee.

#### Local-agent sources

- **Best fit for true embedded metadata write-back.**
- A local agent can open the file, modify embedded metadata, and write it back in place with full filesystem awareness.

### Product decision

The product should expose and reason about these capabilities separately:

- `can_read_original`
- `can_rename_at_source`
- `can_write_embedded_metadata`
- `writeback_required`

### Recommended support policy

For the first cloud-backed reference-mode slices:

- **Rename must be applied at the source as part of the normal workflow** where the provider natively supports it.
- **Embedded file-metadata write-back remains source-specific**, but if the product requires it for a source, then that source is not considered feature-complete until the rewrite/re-upload path exists.
- Treat embedded metadata write-back for cloud providers as a source-specific mutation workflow because it requires content rewrite semantics.

### Reconciliation with completed P7-002 Google Drive foundation

P7-002 intentionally delivered a **read-only Google Drive connector foundation**:

- root-only `My Drive`
- `drive.readonly`
- ingest and sync only

That foundation remains valid, but it is not sufficient for the P7-004 source-mutation contract.

### Locked P7-004 decision

P7-004 includes a Google Drive mutation slice that expands eligible Drive connectors from `drive.readonly` to a writable Drive scope and adds the write-back path needed for source mutation.

Practically, this means:

- P7-002 is the read-only foundation, not the final Drive contract
- P7-004 must add Drive re-consent / reconnect for writable capability
- existing Drive connectors that remain on the old read-only grant may still support analysis and preview generation, but they cannot reach `fully_applied` when source mutation is required
- those read-only connectors must surface as `blocked_writeback` until the user reconnects with the upgraded scope

This keeps the finished P7-002 work valid while making the source-mutation contract implementable.

### Operator-level cloud metadata fallback rule

For cloud providers, the preferred path is still embedded metadata write-back to the source bytes when that can be done safely.

When native embedded mutation is impossible, lossy, or intentionally deferred, use this rule:

- `fully_applied` is allowed only if the source filename was applied and the metadata was written through an **operator-approved source-side fallback representation** for that provider
- the fallback representation must exist at the source system itself, not only inside AWS application state
- fallback mode must be recorded explicitly so the system can distinguish `embedded_writeback` from `source_fallback_writeback`
- application-only metadata persistence does not satisfy `fully_applied`
- permanent AWS retention of the original does not satisfy fallback and is prohibited by the storage pivot

Operationally:

- use `pending_writeback` when a safe rewrite/re-upload or approved fallback write is queued and no user action is required
- use `blocked_writeback` when the connector lacks writable permission, the provider has no approved fallback mode, or the mutation path is unsafe or terminally failed

### Google Drive rule for P7-004

For Google Drive in P7-004, **fallback-only completion is not approved as the normal success path**. The expected success path is:

- source rename at Drive
- embedded metadata write-back through a rewrite-and-reupload mutation workflow

So for Drive:

- `fully_applied` requires the writable-scope connector plus successful rename and rewrite/reupload metadata mutation
- `pending_writeback` is valid while the rewrite/reupload job is actively queued or retrying without user action
- `blocked_writeback` is required when the connector is still `drive.readonly`, needs re-consent, or the Drive mutation path fails terminally

This means the user-facing answer is:

- **Yes, renaming files on Google Drive or similar cloud services is generally possible.**
- **Editing embedded image metadata on those cloud services is not usually a simple native capability; it generally requires rewriting and re-uploading the file, so the system must treat it as an explicit write-back job rather than a lightweight patch.**

### Required source-mutation history

For every successful or attempted source mutation, the application should preserve:

- the first-seen original filename
- the prior filename immediately before rename
- the new applied filename
- whether embedded metadata write-back succeeded
- when the change happened
- what source and capability path performed it

This is how the system remains able to say "what this image used to be" after it has been renamed and updated.

---

## 3.5 Recommended Retained Asset Pattern

The cleanest target is to retain **one lightweight preview derivative** and optionally generate smaller thumbnail variants from it.

### Recommendation

- Generate an **analysis derivative** transiently during ingest, capped for AI input.
- Generate and retain a **preview derivative** in application object storage.
- Optionally generate a smaller **thumbnail variant** for grid-heavy views if needed later.
- Do **not** retain the original full-resolution bytes for connector-sourced items.

### Concrete policy recommendation

For connector-sourced images, AWS should retain:

- one preview image at a capped longest edge, for example `1280px` or `1600px`
- optional tiny grid thumbnail variants only if performance data justifies them

This is better than retaining only a tiny thumbnail because:

- Gallery and detail view remain visually useful
- search results and previews stay fast
- the app avoids acting like a full-res host
- UI does not degrade into postage-stamp-only media interaction

If product policy insists on the word "thumbnail" only, then define that retained thumbnail as a **preview-class derivative**, not a 150px icon.

---

## 3.6 Availability State Model for Originals

The system should explicitly track original availability at the item level or derivable from source state plus last fetch result.

### Minimum required states

| State | Meaning | UX effect |
|---|---|---|
| `available` | Source reachable and original fetch likely to succeed | Original actions enabled |
| `auth_required` | Source exists but authorization expired or missing | Show reconnect CTA |
| `temporarily_unreachable` | Source or agent appears offline / timed out | Show retry message |
| `not_found` | Original no longer exists at source | Keep item + preview, mark original unavailable |
| `writeback_unsupported` | Source connected but cannot support requested write-back action | Disable write-back UI |
| `unknown` | System has not recently checked original availability | Allow best-effort fetch with clear fallback |

### Additional operation state for write-back

For rename and metadata write-back, track:

- `pending`
- `succeeded`
- `failed_retryable`
- `failed_terminal`
- `blocked_user_action`

These should not be collapsed into the same field as original-read availability.

### Source-level visibility requirement

Availability must exist at both:

- the **item level** for user actions on one image
- the **source level** for Connections visibility and operator health checks

At the source level, the system should track at minimum:

- `available`
- `auth_required`
- `offline_or_unreachable`
- `degraded`
- `not_configured`

`degraded` is important when previews and indexed items remain usable but original fetch or write-back is impaired.

---

## 3.7 Minimum Viable Cloud-First Architecture Without Blocking Future Local Expansion

The minimum viable path is:

1. **Cloud sources first** using provider connectors already aligned with the current connector model.
2. Introduce a provider-neutral **origin-access abstraction** now.
3. Support a **no-install local re-link source** as a user-assisted workflow.
4. Reserve a future `local_agent` source type only if the product later needs seamless live local-source access.

### Required abstraction boundary

Define a source capability interface around operations, not storage:

- list assets
- fetch analysis bytes
- fetch original bytes on demand
- rename asset
- write metadata back
- report capabilities

Google Drive and Dropbox can implement this server-side.

The no-install local re-link model can implement a limited form of this interface through browser-granted folder access during explicit user actions. A future local agent could later implement the full interface through an authenticated desktop relay without redesigning the cloud data model.

That is the minimum viable path that supports cloud first, provides a workable no-install local workflow, and does not paint future local expansion into a corner.

---

## 3.8 No-Install Local Re-Link Source Model

The product may support a local-file workflow without installing software, but it must be modeled accurately as a **user-assisted re-link source**, not a live managed local source.

### What this mode is

- The user selects a local folder explicitly in the browser.
- The app scans files from that folder at the user's request.
- The app stores retained preview assets, metadata, search/index state, and a remembered origin record.
- The app does **not** retain live background access to the folder afterward.
- Future modify or write-back operations require the user to re-confirm folder access.

### What the app stores for this mode

- source label visible to the user
- local origin hint
- relative path inside the selected folder when available
- original filename snapshot
- file fingerprint used for later matching
- last successful scan time
- last successful re-link confirmation time

### Matching rules

Path and filename are hints only. Matching should be authoritative based on a stored fingerprint such as:

- content hash when available
- file size
- modified timestamp
- optional secondary image fingerprint if needed for recovery

### Automatic lookup behavior

The system may automatically try the remembered location **only within a folder the user has currently granted access to in that session**.

If the file is not found there or does not match confidently:

- tell the user the file is no longer at the remembered location
- ask the user to select the containing folder again
- rescan and attempt to re-link by fingerprint

### Privacy recommendation

Do not make raw absolute local paths the primary long-term identifier if they are not needed. Prefer:

- user-visible source label
- relative path inside the selected folder
- fingerprint-based matching

Absolute paths may be stored only if the operator explicitly accepts that privacy tradeoff.

---

## 3.9 Connections Tab as Source Inventory and Availability Surface

The Connections tab should become the canonical user-visible inventory of image-providing sources.

It should answer two questions clearly:

1. **What sources have contributed images to my library?**
2. **Can the system currently reach originals in those sources?**

### Required source-level fields in Connections

For each source, the UI should show:

- source name
- source type (`google_drive`, `dropbox`, `local_relink`, `manual_copy`, and optionally future `local_agent`)
- human-readable location label
   - examples: `My Drive`, `Vacation Photos`, `Dropbox / Camera Uploads`, `Local Folder: Family Archive`, `Sarah's MacBook / Pictures`
- item count indexed from that source
- current original-availability state
- auth/connectivity state
- last scan time
- last successful original access check time
- last successful rename time
- last successful metadata write-back time
- pending write-back count or state
- capability badges
   - `rename supported`
   - `metadata write-back supported`
   - `original access supported`

### Required behavior

- A user must be able to identify which devices, cloud accounts, folders, or locations have supplied images.
- The system must surface whether originals are currently reachable from each source.
- The user must not need to open individual items to learn that a whole source is disconnected.
- Source-level health must be visible even when previews and search still work.

### Required relationship to item detail

Item detail should inherit and display its source status, but Connections is the authoritative overview surface.

### Product policy recommendation

For no-install local re-link sources, the Connections label should show a clear local folder label and indicate that future edits require folder re-selection.

For local-agent sources, if they are ever approved later, the Connections label should explicitly identify the device or agent instance, not just a generic folder name.

For cloud sources, the Connections view should show both:

- provider account identity where safe and appropriate
- container or folder label where applicable

This is required so users can understand which locations have been scanned and whether the originals remain accessible.

---

## 4. Thumbnail Storage Recommendation

## Decision

**Thumbnails and preview derivatives should not live in the relational database as blobs. They should be stored in object storage or file storage, with only references and metadata in the relational database.**

For AWS deployment, the replacement pattern should be:

- preview and thumbnail bytes in **S3-compatible object storage**
- deterministic object keys
- DB columns for key/reference, dimensions, byte size, mime type, checksum, and variant type
- optional CDN or cache layer in front of those objects later

### Why this is the correct decision

Thumbnail delivery is operationally much closer to **media serving** than to classic relational data access.

Even though thumbnails are small, they are:

- binary assets
- read-heavy
- cacheable
- frequently served repeatedly
- suitable for CDN distribution

That profile is a poor match for relational blob storage once the product grows beyond a very small beta.

---

## 4.1 Decision Analysis: DB Blob vs Object Storage + DB Pointer

| Factor | DB blob storage | Object storage + DB pointer | Architect recommendation |
|---|---|---|---|
| Database growth | Grows primary DB rapidly; mixes hot relational data with binary payloads | Keeps DB focused on metadata and pointers | Object storage |
| Query performance | Larger rows, worse cache locality, heavier replication and backup load | Small DB rows; thumbnail bytes fetched only when needed | Object storage |
| Operational simplicity | Simpler at tiny scale because one datastore | Simpler at real scale because concerns are separated | Object storage |
| Backup / restore impact | Backups become much larger and slower; restore time balloons | DB backup remains lightweight; object store managed separately | Object storage |
| AWS cost profile | Higher DB storage and IO cost on RDS; poor economics for blobs | Cheap S3 storage and egress patterns; better tiering options | Object storage |
| CDN / cache friendliness | Poor; app/DB must front asset delivery | Strong; easy to front with CDN or proxy cache later | Object storage |
| Deletion / cleanup complexity | Simple row deletion conceptually, but hard to decouple retention | Simple with deterministic keys and lifecycle cleanup jobs | Object storage |
| Beta scale | Technically possible | Still preferred because current stack already has file/object storage primitives | Object storage |
| Later growth | Becomes painful quickly | Scales naturally | Object storage |
| Delivery semantics | Treats thumbnails like data rows | Treats thumbnails like media assets, which they are | Object storage |

---

## 4.2 Detailed Comparison

### A. Database growth

With DB blobs, every gallery-visible asset grows the relational store. Even small previews become expensive once multiplied across:

- many users
- many images per user
- multiple variants
- replicas and backups

This is the wrong growth vector for the primary transactional database.

### B. Query performance

Relational queries for lists, filters, and search results should return metadata quickly. Blob-bearing rows degrade:

- cache efficiency
- page density
- replication throughput
- ORM fetch behavior if not handled carefully

Keeping only pointers in the DB preserves clean query behavior.

### C. Operational simplicity

At very small beta scale, one-store simplicity is attractive, but it is false economy here because the current system already has storage abstractions and AWS object storage assumptions. The app is not blob-store-free today.

### D. Backup and restore

The app’s backup posture should preserve:

- relational metadata
- vector/index state as needed
- lightweight preview assets separately

Mixing preview bytes into the DB turns every restore into a media restore event.

### E. AWS cost profile

RDS storage and IO are materially more expensive than S3 for this pattern. The retained asset layer should sit on the cheapest suitable tier.

### F. CDN and cache friendliness

Preview delivery is ideal for:

- HTTP caching
- CDN edge caching
- immutable object keys
- browser reuse

Object storage aligns with that immediately. DB blobs do not.

### G. Deletion and cleanup

Use deterministic keys such as:

- `{user_id}/{media_item_id}/preview.jpg`
- `{user_id}/{media_item_id}/thumb-sm.jpg`

and run cleanup from application delete flows plus periodic reconciliation jobs.

### H. Beta and future scale

For a tiny private beta, DB blobs would work. That is not the right standard. The redesign itself is about preventing a future operational trap; thumbnail storage should not introduce a new one.

### I. Media serving vs data access

**Thumbnail delivery should be treated as media serving, not relational data access.**

That is the decisive conceptual point.

---

## 4.3 Recommended Thumbnail / Preview Storage Pattern

### Recommended pattern

- Store preview and thumbnail bytes in S3-compatible object storage
- Store only references and metadata in the relational database
- Use deterministic, immutable object keys
- Serve through authenticated application routes initially if needed for user isolation
- Add signed URLs or CDN later only if authorization and cache policy are nailed down

### Suggested DB fields

Whether kept in `media_items` initially or moved to a dedicated preview table later, the app should persist:

- `preview_storage_key`
- `preview_mime_type`
- `preview_width`
- `preview_height`
- `preview_file_size`
- `preview_checksum`
- optional `thumbnail_storage_key` if a second variant is retained

---

## 5. Existing Assumptions and Components That Must Change

## 5.1 Data model assumptions

The following current assumptions must change:

- `media_items.storage_path` currently implies app-owned original bytes
- `content_hash` is tightly associated with the retained object path
- one retained file currently supports preview, analysis, download, and metadata embedding

The target model needs:

- explicit original reference fields
- explicit preview reference fields
- explicit retained-asset mode
- explicit original availability state
- durable write-back operation state
- durable source filename and metadata mutation history

## 5.2 Ingestion pipeline assumptions

`src/ingestion/upload_service.py` currently means:

- validate
- hash
- dedup
- save full file
- create DB record
- queue analysis

That pipeline must split into:

- **browser-local working-folder ingest** for user-selected local folders and drag-drop intake
- **reference-mode ingest** for connector and future live-source paths

Reference-mode ingest must:

- fetch bytes transiently
- compute technical signals
- run analysis
- generate preview
- persist metadata and preview only
- discard original bytes

## 5.3 Analysis assumptions

`src/analysis/processor.py` currently reads bytes from `file_store.read(media_item.storage_path)`.

That assumption breaks for reference-mode items. Analysis and re-analysis need one of:

- transient pre-discard analysis during ingest
- or a source fetch path for re-analysis

## 5.4 Download assumptions

`src/api/routes/download.py` currently embeds metadata into a locally retained original and returns the result.

That must become source-aware:

- for browser-local working-folder items, export/write-back targets the user-selected local folder when access is granted
- for reference-mode items, write-back and rename target the origin asset
- download-original becomes best-effort fetch from source

## 5.5 File-serving assumptions

`GET /media/{id}/file` currently returns raw retained file bytes.

After the pivot, that route should serve the retained preview asset, not assume original ownership.

## 5.6 Metadata embedding assumptions

The current enrichment module is a download-time transformer. In the redesigned system it becomes part of a **write-back subsystem** and may also remain part of export workflows where a user explicitly requests a modified copy.

The app must stop treating metadata embedding as a download-only embellishment. In the new model it becomes part of the standard source-mutation workflow.

## 5.7 Connector and source assumptions

The connector foundation remains useful, but its success criteria change from "import file into AWS storage" to "establish durable indexed reference with retained preview."

## 5.8 Drag-drop and local-source assumptions

### Decision

**The product should not keep original images in AWS as a permanent copy, including for browser drag-drop flows.**

### Recommended product policy

Keep three explicit modes:

1. **Connected cloud reference source**
   - preferred long-term model
   - originals remain at source
   - rename must be applied at source where provider capability exists
   - embedded metadata write-back is source-specific and may require rewrite/re-upload
   - mutation history must be preserved so the system knows prior and current names

2. **No-install local working-folder source**
   - user-assisted local workflow
   - user must choose a local working/export folder before local processing is allowed
   - drag-dropped images are copied into that local working folder on the user's device when browser capabilities permit
   - app stores preview, metadata, search state, and origin hints, but not the original permanently in AWS
   - future source-side modification requires folder re-confirmation and fingerprint rematch unless folder access is still granted
   - when folder access is granted, rename and metadata write-back should be attempted immediately and recorded in mutation history

3. **Manual ephemeral intake**
   - ad hoc file selection or drag-drop is allowed only as intake into the current local working folder or an equivalent transient processing flow
   - it must not create a permanent AWS-stored original
   - if the browser cannot support local-folder writing for this workflow, the product should fall back to cloud-source onboarding rather than silently reverting to permanent AWS copy storage

This avoids blocking the product while preserving the new direction.

### What not to do

Do not pretend browser drag-and-drop is "live local reference mode." It is not. The no-install local working-folder flow is user-assisted and requires user-granted folder access, browser support, and renewed folder confirmation for later source-side changes.

### Browser capability requirement

This local workflow depends on browser file-system capabilities such as explicit directory selection and writable handles. The product must treat that support as a compatibility requirement, not as a guaranteed universal capability across all browsers and contexts.

If the required browser capabilities are not available, local no-install processing should be marked unsupported in that environment.

---

## 6. Expected UX Behavior

## 6.1 Cloud-connected sources

Examples: Google Drive, Dropbox.

### Expected behavior

- User connects the source through OAuth.
- App indexes supported files and retains preview assets only.
- Gallery and Search work from retained previews and metadata even when the original is not actively fetched.
- "Open original," "Download original," "Rename at source," and "Write metadata back" are live-source operations.
- If auth expires, the item remains visible in the library but original-specific actions show reconnect requirements.

### UX requirements

- Show source badge and current availability state
- Distinguish "preview available" from "original available"
- Show reconnect CTA when auth is expired
- Never imply that the app permanently stores the original when it does not
- Expose source-level state in Connections so users can see which cloud locations have supplied items and whether originals are reachable now
- Show whether source mutations are up to date, pending, or blocked

## 6.2 No-install local working-folder sources

### Expected behavior

- Before local processing is enabled, the user selects a local working or export folder in the browser.
- When the user drags in files, the browser copies them into that selected local working folder when current browser capabilities allow it.
- The app scans files from that folder and stores preview assets, metadata, search state, and remembered origin hints.
- The app does not keep live background access afterward.
- If the user later wants to modify the original again, the app first tries the remembered location within the currently granted folder access.
- If the file is not found, the app prompts the user to select the containing folder and rescans to re-link by fingerprint.

### UX requirements

- Require the user to select a local working/export folder before allowing drag-drop local processing
- Explain that dropped files are being placed into the selected local folder on the user's device, not stored permanently in AWS
- Show that this is a remembered local source, not a live connected source
- Show the local source label in Connections
- Show whether the original was recently re-confirmed or needs re-selection
- Explain clearly when the user must reselect the containing folder before a new source-side edit can proceed
- If the browser lacks the needed file-system capabilities, explain that local no-install processing is unavailable in this browser and direct the user to a supported browser or a cloud source
- Show whether the filename and metadata have already been applied to the local originals or are waiting for user re-confirmation

## 6.3 Future local-agent sources (optional later)

### Expected behavior

- Only relevant if the operator later approves installed local software.
- A local agent would provide seamless live access, rename, and embedded metadata write-back without repeated folder re-selection.

### UX requirements

- Show device online/offline state
- Show original availability as dependent on that device or agent session
- Distinguish this mode clearly from the no-install local re-link workflow

## 6.4 Unavailable / disconnected sources

### Expected behavior

- Indexed item remains in the library
- Thumbnail / preview remains visible
- Metadata and search remain usable
- Original-only actions become disabled or fail with explicit status

### Required user message shape

The UI should say the original is unavailable from the current source/session/device, not show a generic download error.

Examples:

- "Original unavailable. Google Drive connection needs to be reconnected."
- "Original unavailable. Please reselect the folder containing this local file so we can find it again."
- "Original unavailable. The file no longer exists at its source."

### Connections page behavior

Connections should show source-level statuses like:

- `Available`
- `Reconnect required`
- `Offline`
- `Degraded`
- `Preview-only access`

`Preview-only access` is especially important for this product because it tells the truth: the library entry still works, but live original access does not.

---

## 7. Hidden Failure Modes and Tradeoffs

These are the main risks the redesign introduces.

### A. Origin drift after indexing

The original file may change at source after the app indexed it. That creates drift between:

- retained preview
- indexed metadata
- current source bytes

Product policy must decide whether to:

- treat the app as a snapshot until next sync
- or detect and invalidate stale indexed state aggressively

### B. Re-analysis is no longer always available

If the original is unavailable, re-analysis cannot run for reference-mode items unless the retained preview is considered sufficient input. That is a product-quality tradeoff.

### C. Write-back conflicts

Metadata or rename operations may fail because:

- token expired
- source permissions insufficient
- file moved or deleted
- external system blocked metadata mutation
- local file locked by another application

Write-back must be treated as auditable operations with clear failure semantics.

### D. Required write-back may be blocked by source conditions

Because the product now requires filename and metadata application as part of the normal workflow, any blocked write-back becomes a first-class product state, not a minor warning. The UI and data model must treat this explicitly.

### E. Source identifier instability

Some providers offer stable IDs; local re-link flows do not. Local path-based references are weaker and require fingerprint rematching plus user-assisted revalidation.

### F. User confusion about what is actually stored

If the UI still behaves like a hosting product, the system will generate support problems. Product language must clearly say:

- preview retained
- original remains at source
- some actions require source availability

### G. Security and privacy tradeoff is improved but not zero

Not storing full originals reduces retained sensitive data, but retained previews may still contain sensitive content. They still require user isolation, deletion guarantees, and access control.

### H. Browser-local intake depends on browser capability

The no-install local workflow is viable only if the browser can hold user-granted folder access and write to a selected local folder. That dependency must be acknowledged explicitly in product behavior and support policy.

### I. Backup semantics change

Restoring the app after a disaster restores the searchable library and previews, but not origin availability. That is acceptable only if the product boundary is clearly understood.

---

## 8. Proposed Phased Plan / Workstreams

This pivot should be executed as a new architecture-driven phase or sub-phase. It is too large to bury inside ordinary connector enhancement work.

## Phase A: Architecture Lock and Product Policy

### WS-A1: Reference-Mode Contract Approval

Lock the product rules for:

- originals stay at source for connector and agent sources
- no-install local re-link source policy
- retained preview policy
- browser-local working-folder policy
- original availability states
- write-back and rename semantics
- required source-mutation history semantics
- preview retention size policy

### WS-A2: Data Model Redesign Plan

Define the concrete additive schema evolution for:

- origin asset references
- retained preview references
- media storage mode
- availability state
- write-back operation tracking
- source filename history and mutation audit fields

## Phase B: Cloud-First Reference Mode Foundation

### WS-B1: Preview Asset Storage Foundation

- introduce preview / thumbnail generation service
- object-storage-backed preview retention
- DB pointer fields
- authenticated preview serving contract

### WS-B2: Reference-Mode and Local Working-Folder Ingestion Pipeline

- split browser-local working-folder ingest and reference-mode ingest
- transient analysis bytes
- retained preview only; no permanent AWS original retention
- preserve dedup, dimensions, pHash, OCR, embeddings

### WS-B3: Original Fetch Service

- provider-neutral fetch-original abstraction
- live-source retrieval for Google Drive first
- structured origin-unavailable errors

## Phase C: Source-Aware User Experience

### WS-C1: Preview vs Original UX Split

- gallery and detail view consume retained preview assets
- original actions show availability state
- reconnect and unavailable messaging

### WS-C2: Library State and Availability Indicators

- show source type
- show current availability
- distinguish preview-ready from original-ready

### WS-C3: No-Install Local Working-Folder UX

- required local working/export folder selection flow
- drag-drop into local working folder when browser support exists
- remembered origin hints
- reselect-folder fallback flow
- fingerprint rematch behavior and user messaging

## Phase D: Write-Back and Rename

### WS-D1: Write-Back Operation Framework

- durable operation log / job table
- capability matrix by source type
- retry and error semantics
- mandatory immediate post-analysis mutation attempts
- blocked-user-action and pending-state handling
- source filename / metadata mutation history

### WS-D2: Google Drive Metadata Write-Back and Rename

- rename at source
- source-side metadata update where technically possible
- operator-approved fallback behavior where native metadata embedding is impossible or lossy
- preserve original and prior filenames across each successful rename

### WS-D3: Cross-Source Mutation State UX

- show current filename versus original filename history
- show whether metadata and filename are already applied at the source
- show pending, blocked, retryable, and failed mutation states in item detail and Connections

Note: product policy must be realistic here. Some cloud providers do not support the exact same embedded-metadata mutation model as a local file rewrite workflow.

## Phase E: Browser Intake Repositioning

### WS-E1: Drag-Drop as Local Working-Folder Intake

- relabel browser upload clearly as local working-folder intake
- require local working/export folder selection before processing local files
- remove any product behavior that silently turns drag-drop into permanent AWS original storage
- define unsupported-browser fallback behavior

## Phase F: Optional Future Local-Agent Support

### WS-F1: Local Agent Architecture

- only if later approved after the no-install local workflow proves insufficient
- authenticated desktop or agent channel
- local enumeration, fetch, rename, metadata write-back
- device/session availability state

### WS-F2: Local Agent UX and Reliability

- offline detection
- local-origin unavailable messaging
- explicit upgrade path from no-install local re-link mode if needed

## Phase G: Migration and Cost Reduction

### WS-G1: Existing Connector Item Conversion

- evaluate whether existing app-stored originals from connector sources should be migrated to preview-only retention or left as grandfathered full-copy items

### WS-G2: Storage Cleanup and Reporting

- storage-mode reporting
- cost dashboard
- cleanup jobs for deprecated full copies where policy allows

---

## 9. Concrete First Implementation Recommendation

If the operator wants the minimum viable path, the first approved implementation slice should be:

1. **Cloud sources first, Google Drive first**
2. Introduce **reference-mode ingestion** only for connector-sourced items
3. Retain **preview asset in object storage**
4. Keep browser local intake only as working-folder onboarding, not permanent AWS copy storage
5. Support no-install local working-folder sources later in the phase plan without requiring device install
6. Treat source-side rename and metadata application as mandatory product behavior, delivered through the write-back operation framework

This is the smallest path that proves the product direction while keeping local workflows possible without requiring device install or permanent AWS original retention.

---

## 10. Approval Recommendation

### Recommended approval stance

**Approve the pivot direction, but do not approve it as a single implementation workstream.**

Approve these points now:

- the product should not be a long-term host for connector-sourced originals
- the product should not be a long-term host for browser-dropped originals either
- AWS should remain the metadata, search, and preview layer
- thumbnails/previews should live in object storage with DB references, not DB blobs
- cloud-first reference mode should land before any optional local-agent support
- no-install local working-folder sources are an acceptable local workflow if the operator wants to avoid device install
- browser drag-drop should feed a user-selected local working folder or be disallowed in unsupported environments; it should not create a permanent AWS copy

Do **not** yet claim the pivot is complete until these policies are locked:

- exact retained preview size and variant policy
- write-back semantics by source type
- migration policy for already-stored originals
- whether re-analysis is blocked or degraded when origin is unavailable

### Final architectural recommendation

Proceed with the redesign. It is the right product direction, but treat it as a **storage-model pivot with new source-of-truth rules**, not a connector feature tweak.

### Candidate ADR if approved

If the operator approves this direction, record a new ADR after the next accepted workstream plan. Do **not** reuse old ADR numbers or treat this proposal as already accepted.