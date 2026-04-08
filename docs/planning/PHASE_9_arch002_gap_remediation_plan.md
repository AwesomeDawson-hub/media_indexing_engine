# Phase 9 Plan — ARCH-002 Gap Remediation

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 9 |
| **Project** | Media Indexing Engine |
| **Created** | 2026-04-08 |
| **Author** | Architect |
| **Status** | Approved — operator direction locked 2026-04-08 |
| **Dependencies** | `ARCH-002-reference-mode-storage.md` approved; P8-001, P8-002, and P8-003 completed |

## Objective

Close the remaining gap between the approved ARCH-002 reference-mode architecture and the current beta implementation by eliminating transient full-original retention for connector ingestion, hardening subsystems that still assume app-retained originals, and beginning the additive domain split needed for source-aware originals, preview assets, capability state, and durable write-back operations.

This phase exists because Phase 8 solved the retention end-state for many connector items, but it did not yet solve the ingestion boundary. Connector sync still writes the full original to app storage first and only deletes it later. That behavior is a real architectural violation of ARCH-002, not a cosmetic mismatch.

## Executive Recommendation

## 1. Fix the ingestion boundary first

Connector ingestion should be refactored so connector imports never call `file_store.save()` for the original at all.

The system already performs most of the needed work from in-memory bytes:

- validation
- SHA-256 dedup
- thumbnail generation
- dimensions extraction
- pHash computation

The part that truly depends on app-retained storage today is the analysis pipeline, because `analyze_media_item()` reads from `media_item.storage_path`. That contract should be replaced by an explicit analysis-input abstraction that can operate on either:

- transient in-memory bytes for connector ingestion
- retained app storage for manual uploads and any other storage-owning flows that still need it

This is the first priority because it closes the ARCH-002 violation directly and prevents future work from continuing to inherit the wrong ingestion boundary.

## 2. Do not block on a big-bang model rewrite

The domain-model gap is real, but the right move is additive evolution, not a stop-the-world replacement of `MediaItem`.

ARCH-002 already allowed additive evolution of the current table shape. That remains the correct approach in beta with real data.

The right order is:

1. close the ingestion-boundary violation
2. harden all consumers that still assume `storage_path`
3. add first-class origin and preview models while keeping `MediaItem` as the aggregate root for now
4. introduce a durable write-back subsystem once origin references are first-class

## 3. Treat the retry model as an explicit product decision

Once connector originals are no longer staged in app storage, a failed in-flight connector analysis job cannot rely on S3 replay of the original bytes.

That should not be "solved" by preserving transient storage. It should be solved by an explicit retry contract:

- either synchronous connector analysis inside the sync flow for the first zero-transient slice
- or replay by re-fetching from the source connector when retrying analysis

The recommended long-term contract is source re-fetch on retry. That is more aligned with ARCH-002 and avoids rebuilding a hidden storage dependency.

## What Breaks If Connector Ingestion Stops Calling `file_store.save()`

## Analysis pipeline

### Current state

`analyze_media_item()` reads `media_item.storage_path` and uses `file_store.read()` as its analysis-input contract.

### Break

Connector items cannot be analyzed through the current path if no original was ever stored.

### Recommendation

Introduce an additive analysis-input abstraction, for example an `AnalysisInput` or `AnalysisSource` contract, so the processor logic can operate on bytes provided from:

- in-memory connector downloads
- app-retained storage for manual-upload flows

Do not fork analysis behavior into a permanently separate connector-only metadata pipeline. Keep one metadata/OCR/indexing/write-back outcome path, but decouple it from `storage_path` as the only byte source.

## Dedup

### Current state

Dedup uses the content hash computed from bytes before storage.

### Break

None architecturally.

### Recommendation

Keep dedup where it is conceptually. It already belongs before any storage decision.

## Thumbnail generation

### Current state

Thumbnail generation already works from bytes and only saves the derived preview asset.

### Break

None.

### Recommendation

Keep this behavior. Connector ingestion should continue to persist only the thumbnail/preview derivative.

## pHash

### Current state

pHash is already computed from bytes before the stored-original path becomes relevant.

### Break

None.

### Recommendation

Keep pHash in the ingest preparation stage, independent of whether an original is retained.

## Startup replay / retry semantics

### Current state

The system can replay some analysis jobs because app-retained originals still exist long enough to be reread.

### Break

Connector retries cannot assume the original remains in app storage.

### Recommendation

Lock the retry model explicitly:

- Phase 9 first slice may run connector analysis synchronously within sync/orchestration to reduce crash-window complexity.
- The durable target contract should be source replay: on retry, fetch bytes again from the connector rather than relying on app-retained originals.

## Domain Model Recommendation

## Recommendation

Defer the full domain-model rewrite as a foundational cleanup, but do not defer the first additive split for origin and preview concepts.

### Do now

- Keep `MediaItem` as the aggregate root for beta continuity.
- Add `OriginAssetRef` first so connector original identity stops being smeared across `SourceObject`, `Source`, and `MediaItem` fields.
- Add `PreviewAsset` next so retained preview bytes stop being represented only by a loose `thumbnail_path` string.

### Do later in the same phase

- Add `SourceCapabilitySnapshot` once original-availability semantics, capability gating, and Connections UX need explicit structured state instead of `connector_status` strings and implicit connector presence checks.
- Add `WriteBackOperation` after origin references are first-class and the source-aware original contract is hardened.

### Do not do now

- Do not replace `MediaItem` wholesale.
- Do not try to land every ARCH-002 concept in one migration wave before the ingestion-boundary fix.

## Proposed Phase 9 Workstreams

## P9-001 — Zero-Transient Connector Ingestion

### Objective

Refactor connector ingestion so connector-synced originals are never written to app storage, even transiently.

### Scope

- split storage-owning manual ingestion from connector ingestion
- introduce an analysis-input abstraction or equivalent additive processor contract
- allow connector imports to validate, hash, dedup, thumbnail, pHash, analyze, index, and persist metadata from transient bytes only
- persist source identity before item finalization
- create connector-backed records directly in reference-mode semantics rather than creating a stored-original record and pivoting it later
- include an audit and cleanup pass for historical connector items that still retain originals because of old failure paths

### Why first

This closes the explicit ARCH-002 violation and removes the failure-path retention leak from new connector ingest.

## P9-002 — Source-Aware Original Access Hardening

### Objective

Audit and harden every subsystem that still assumes `storage_path` means the original is readable from app storage.

### Minimum surfaces to address

- enriched download endpoints
- batch ZIP download
- convert-to-PNG path if it assumes retained originals
- curation scoring path
- re-analysis and any future retry paths

### Required outputs

For each surface, choose one approved behavior:

- source-aware fetch on demand
- controlled source-aware error response
- temporary disablement for connector-backed preview-only items until source fetch exists

### Why second

The codebase is currently half reference-mode and half storage-mode. That ambiguity will keep spreading until consumer paths are forced to declare the right contract.

## P9-003 — Additive Origin/Preview Domain Split

### Objective

Begin the ARCH-002 model cleanup without destabilizing the beta aggregate model.

### Scope

- add `OriginAssetRef`
- add `PreviewAsset`
- migrate `MediaItem` away from directly owning raw storage-path semantics for concepts that are actually origin or preview concerns
- preserve existing behavior through additive compatibility fields during rollout

### Why third

This creates the correct foundation for future source-aware download, re-analysis, availability state, and connector expansion without delaying the ingestion fix.

## P9-004 — Source Capability and Durable Write-Back Operations

### Objective

Finish the operational side of the ARCH-002 model by making source capability state and write-back intent durable first-class subsystems.

### Scope

- add `SourceCapabilitySnapshot`
- add `WriteBackOperation`
- move ad hoc rename / metadata application orchestration onto durable operation records and capability-gated execution
- make retry/audit semantics explicit for future connectors beyond Google Drive

### Why fourth

This is the clean completion of ARCH-002, but it should build on stable origin references and source-aware original-access semantics rather than trying to establish both at once.

## Operator Direction Locked Before Implementation

## 1. Close the transient-write gap now

Approved. The current behavior is no longer accepted as steady-state beta architecture. Phase 9 begins by closing this gap rather than deferring it behind model cleanup.

## 2. Use source re-fetch as the long-term retry rule

Approved:

- long-term retry uses source re-fetch, not app-retained originals
- first zero-transient slice may use synchronous connector analysis inside sync flow if that is the safest rollout path

## 3. Use controlled source-aware errors first for storage-assuming features

Approved interim rule for download, re-analysis, scoring, and similar surfaces:

- controlled "original at source" error

If on-demand source fetch is already cheap and reliable enough for a surface, Engineer may implement source-aware fetch directly instead of the temporary error path.

This is now explicit guidance for P9-002.

## 4. Use additive domain evolution, not a big-bang `MediaItem` replacement

Approved. Fix the ingestion boundary first, then add structured origin and preview models behind the existing aggregate.

## 5. Include an operational audit/cleanup of already-retained connector originals

Approved. Because some connector items can still remain `full` indefinitely after analysis failure, the cleanup requirement is not hypothetical.

## Recommended Order of Approval

1. Phase 9 direction approved.
2. P9-001 is the immediate next workstream.
3. Retry and interim source-aware access rules are locked.
4. Engineer handoff can proceed without reopening these decisions.

## Architect Verdict

The right remediation path is not a full model rewrite first. It is:

1. zero-transient connector ingestion now
2. source-aware consumer hardening next
3. additive origin/preview model split after the boundary is correct
4. durable capability/write-back subsystems after the data model supports them cleanly

That sequence closes the real ARCH-002 violation quickly while still moving the codebase toward the intended long-term architecture.