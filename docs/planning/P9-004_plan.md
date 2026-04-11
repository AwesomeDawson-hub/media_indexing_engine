# P9-004 Plan — Source Capability and Durable Write-Back Operations

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 9 — ARCH-002 Gap Remediation |
| **Project** | Media Indexing Engine |
| **Workstream** | P9-004 |
| **Created** | 2026-04-09 |
| **Author** | Architect |
| **Status** | Locked implementation plan — current approval gate; ready for Auditor pass and operator approval |
| **Dependencies** | P9-001 complete; P9-002 complete; P9-003 complete; `PHASE_9_arch002_gap_remediation_plan.md`; `P9-003_plan.md`; `P7-004_plan.md` |

## Objective

Finish the operational side of the ARCH-002 migration by introducing:

- a structured current capability record for each connected source
- a durable write-back intent record that becomes the canonical backend state for rename and metadata-write operations

This workstream replaces the current ad hoc Drive write-back orchestration that mutates `MediaItem.mutation_state`, `last_mutation_error_code`, `last_writeback_at`, and related fields directly. Those `MediaItem` fields remain in place as additive compatibility mirrors in this slice.

P9-004 is Google Drive focused. It does not change `SourceObject`, does not add new write-back providers beyond Drive execution, and does not drop any compatibility columns from `MediaItem`.

---

## Architect Decision Summary

## Q1 — `SourceCapabilitySnapshot` cardinality

### Locked decision

There is **one current `SourceCapabilitySnapshot` row per `SourceConnector`**.

This is the canonical current-state capability record for a connected source.

### Why this is the correct boundary

- `Source` is too coarse: a source can be reconnected with different OAuth scope while retaining the same `source_id`.
- `(Source, provider_scope)` tuples would incorrectly turn a current-state snapshot into an append-only history table.
- `SourceConnector` already represents the live connector binding, auth configuration, and current granted scopes.

The snapshot is therefore a **current connector-state cache**, not a capability history ledger.

### Consequence

- reconnect / scope-upgrade updates the existing snapshot row in place
- capability history is out of scope; if needed later, it should be a separate audit table rather than multiple snapshots per scope tuple

## Q2 — `WriteBackOperation` target FK

### Locked decision

`WriteBackOperation` uses a **direct non-null FK to `origin_asset_refs.id`** as its canonical target.

It also stores a **non-null denormalized `media_item_id` FK** for convenience because existing API flows, compatibility mirrors, and test fixtures are item-centric.

### Canonical boundary

- `origin_asset_ref_id` is the authoritative target of the write-back intent
- `media_item_id` is a denormalized convenience key used for fast lookup, mirror updates, and existing route ergonomics
- `SourceObject` is not a target and is not modified in this workstream

### Why this is the correct boundary

P9-003 explicitly established `OriginAssetRef` as the item-owned origin locator. Building `WriteBackOperation` directly on `MediaItem` would continue the old locator smear. Building it on `SourceObject` would make the target connector-specific and source-owned rather than item-owned.

## Q3 — compatibility mirror update strategy

### Locked decision

Use **same-transaction mirror updates**.

`drive_mutation_service` and any helper used by the retry endpoint must update both:

1. the canonical `WriteBackOperation` row
2. the compatibility mirror fields on `MediaItem`

in the **same database transaction**.

### Rejected options

- read-time reconciliation queries: rejected because existing routes and tests expect `MediaItem` to already hold the current mutation state without special read paths
- DB triggers: rejected because they increase SQLite test complexity and hide important business logic in a cross-environment-sensitive layer

### Mirror mapping locked in this slice

- `WriteBackOperation.state = applied` -> `MediaItem.mutation_state = fully_applied`
- `WriteBackOperation.state = pending` -> `MediaItem.mutation_state = pending_writeback`
- `WriteBackOperation.state = failed` -> `MediaItem.mutation_state = pending_writeback`
- `WriteBackOperation.state = blocked` -> `MediaItem.mutation_state = blocked_writeback`

`failed` is intentionally distinguished at the operation layer while still mirroring to `pending_writeback` for compatibility, because the old API contract has no separate `failed` state.

## Q4 — capability check granularity

### Locked decision

`SourceCapabilitySnapshot.can_write` is a **connector-level precondition**, not a per-file success guarantee.

The snapshot asserts only that the current connector binding appears eligible for write-back based on the last verified OAuth scope and connector health.

The live Drive API call still verifies:

- file-level ACL / permission
- file existence
- provider-side transient failures
- token validity at call time

### Boundary definition

- snapshot check answers: "should the system attempt write-back for this connector at all?"
- live Drive PATCH answers: "did this specific file-level write actually succeed?"

### Consequence

- `can_write=False` blocks execution before the Drive call
- Drive 403/404 on an attempted write does **not** invalidate the snapshot automatically, because those can be file-specific conditions rather than connector-scope conditions
- Drive token/auth failures may update the snapshot into a non-current error state when they indicate connector-level auth breakage

## Q5 — existing test contract preservation

### Locked decision

No existing assertions in `tests/test_mutation_completion.py` need to change.

P9-004 must preserve the current `MediaItem` compatibility mirror behavior so the existing tests continue to pass as written.

### Required compatibility behavior

- `attempt_drive_rename_after_analysis()` keeps the same public signature and still mutates `MediaItem` mirror fields before returning
- `POST /media/{id}/retry-writeback` still returns `MutationStateResponse` sourced from `MediaItem`
- rows created in tests that manually set `MediaItem.mutation_state` without creating a `WriteBackOperation` must still work

### Locked safeguard

Add a small compatibility bootstrap path for Drive items:

- if the retry endpoint finds `MediaItem.mutation_state` in a retryable state but no `WriteBackOperation` row exists yet, it must create one from the current mirror fields before retrying

This keeps historical rows, partially migrated environments, and the existing tests compatible without forcing assertion changes.

---

## Locked Schema

## New Table: `source_capability_snapshots`

Current connector capability record. One row per `SourceConnector`.

### Columns

| Column | Type | Null | FK | Notes |
|---|---|---|---|---|
| `id` | `String(36)` | No | — | PK, UUID |
| `source_id` | `String(36)` | No | `sources.id` | Denormalized join helper; UNIQUE |
| `source_connector_id` | `String(36)` | No | `source_connectors.id` | Canonical parent; UNIQUE |
| `user_id` | `String(36)` | No | `users.id` | User-scoped queries |
| `provider_type` | `String(50)` | No | — | Locked initial value in this slice: `google_drive` |
| `can_read` | `Boolean` | No | — | Whether connector can currently enumerate/read source objects |
| `can_write` | `Boolean` | No | — | Whether connector currently has writable OAuth scope |
| `can_refetch` | `Boolean` | No | — | Whether source re-fetch is currently expected to work |
| `scope_text` | `Text` | Yes | — | Exact raw granted-scope string snapshot |
| `scope_tier` | `String(20)` | No | — | `unknown` / `read_only` / `writable` |
| `verification_state` | `String(20)` | No | — | `current` / `stale` / `error` |
| `last_verified_at` | `DateTime(timezone=True)` | Yes | — | When scope/capability was last verified |
| `last_error_code` | `String(50)` | Yes | — | Connector-level capability error |
| `last_error_message` | `Text` | Yes | — | Operator-safe summary |
| `created_at` | `DateTime(timezone=True)` | No | — | Default UTC now |
| `updated_at` | `DateTime(timezone=True)` | No | — | Default UTC now / on update |

### Constraints and indexes

- `UNIQUE (source_id)`
- `UNIQUE (source_connector_id)`
- index on `user_id`
- index on `(provider_type, verification_state)`

### Notes

- The table is provider-neutral in shape, but only Google Drive rows are populated in P9-004.
- `verification_state` is the freshness/health indicator. This slice does not add historical capability records.

## New Table: `writeback_operations`

Durable current write-back intent row. One current row per `MediaItem` and `operation_type`.

### Columns

| Column | Type | Null | FK | Notes |
|---|---|---|---|---|
| `id` | `String(36)` | No | — | PK, UUID |
| `media_item_id` | `String(36)` | No | `media_items.id` | Denormalized convenience FK |
| `origin_asset_ref_id` | `String(36)` | No | `origin_asset_refs.id` | Canonical target |
| `user_id` | `String(36)` | No | `users.id` | User-scoped queries |
| `source_id` | `String(36)` | Yes | `sources.id` | Denormalized source lookup |
| `source_connector_id` | `String(36)` | Yes | `source_connectors.id` | Present for Drive-connected items |
| `provider_type` | `String(50)` | No | — | Initial live execution path: `google_drive` |
| `operation_type` | `String(30)` | No | — | `rename` or `metadata_write` |
| `state` | `String(20)` | No | — | `pending` / `applied` / `failed` / `blocked` |
| `requested_filename` | `String(255)` | Yes | — | Target filename for rename operations |
| `requested_metadata_payload` | `Text` | Yes | — | JSON payload for metadata-write operations |
| `requested_metadata_payload_hash` | `String(64)` | Yes | — | Hash of requested metadata payload |
| `attempt_count` | `Integer` | No | — | Retries mutate the same row |
| `last_attempted_at` | `DateTime(timezone=True)` | Yes | — | Most recent execution attempt |
| `applied_at` | `DateTime(timezone=True)` | Yes | — | When operation reached `applied` |
| `last_error_code` | `String(50)` | Yes | — | Retryable or blocking error code |
| `last_error_message` | `Text` | Yes | — | Operator-safe summary |
| `created_at` | `DateTime(timezone=True)` | No | — | Default UTC now |
| `updated_at` | `DateTime(timezone=True)` | No | — | Default UTC now / on update |

### Constraints and indexes

- `UNIQUE (media_item_id, operation_type)`
- index on `origin_asset_ref_id`
- index on `user_id`
- index on `source_id`
- index on `source_connector_id`
- index on `(state, operation_type)`

### Notes

- Retries update the same durable intent row rather than creating a new current row.
- Detailed per-attempt audit history remains in `SourceMutationHistory`.
- `metadata_write` is schema-supported in this slice even though Drive execution remains rename-first.

---

## Migration Strategy (Alembic)

## Schema migration

Create a single new Alembic migration that:

1. creates `source_capability_snapshots`
2. creates `writeback_operations`
3. adds all indexes and uniqueness constraints listed above
4. adds no drops and removes no existing `MediaItem` columns

## Data migration policy

Do **not** perform large row backfills inside the Alembic migration.

Reason:

- SQLite test environments should stay fast and deterministic
- production data backfills should be rerunnable and operator-visible
- P9-003 already established the pattern of separate backfill scripts for additive model backfills

## Post-migration application behavior

- application code must tolerate empty snapshot / operation tables immediately after migration
- capability and write-back records become live through service writes and the dedicated backfill script described below

---

## Service Layer Changes

## 1. New capability service

Add a focused service module, for example `src/analysis/source_capability_service.py`, responsible for:

- deriving Google Drive capability from current `SourceConnector.granted_scopes`
- computing `scope_tier`
- upserting `SourceCapabilitySnapshot`
- exposing a read helper for write-back gating

### Locked refresh triggers

Refresh the snapshot when:

- Google Drive OAuth callback persists or updates `granted_scopes`
- Drive scope-upgrade flow completes
- `attempt_drive_rename_after_analysis()` needs a snapshot and finds it missing or stale

Do **not** recompute capability from `granted_scopes` on every ordinary read path.

## 2. `drive_mutation_service.py`

Refactor `attempt_drive_rename_after_analysis()` so it:

1. loads `OriginAssetRef` for the item
2. upserts or loads the durable `WriteBackOperation(operation_type='rename')`
3. checks `SourceCapabilitySnapshot` before attempting the Drive rename
4. updates the operation row state and fields
5. updates the `MediaItem` compatibility mirror in the same transaction
6. continues writing `SourceMutationHistory` per attempt

### Locked behavior by outcome

#### Capability gate fails before Drive call

- operation -> `blocked`
- mirror -> `blocked_writeback`
- `last_error_code` / `last_mutation_error_code` set to capability-level reason (`no_write_scope`, `capability_stale`, `connector_unavailable`)

#### Drive PATCH returns 200

- operation -> `applied`
- mirror -> `fully_applied`
- `requested_filename` preserved on the operation
- `prior_source_filename`, `source_filename_applied_at`, and mirror error fields updated as today

#### Drive PATCH returns retryable error (5xx / transport)

- operation -> `failed`
- mirror -> `pending_writeback`
- retry endpoint remains allowed

#### Drive PATCH returns blocking error (401 auth breakage, 403 permission, 404 not found)

- operation -> `blocked`
- mirror -> `blocked_writeback` for non-retryable cases
- if the error implies connector-level auth failure, refresh the snapshot into `verification_state='error'`

## 3. `retry-writeback` endpoint

Refactor `POST /media/{id}/retry-writeback` so it:

1. loads the item by current ownership rules
2. loads the canonical rename `WriteBackOperation`
3. lazily bootstraps the operation from the `MediaItem` mirror for compatibility when the mirror indicates an old retryable state but the operation row does not yet exist
4. allows retry when operation state is `pending` or `failed`
5. returns 422 when operation state is `blocked` or `applied`
6. returns the same `MutationStateResponse` shape sourced from the updated `MediaItem` mirror

### Locked compatibility bootstrap

The endpoint must create the missing rename operation from the existing mirror when all are true:

- item is Google Drive-backed
- `MediaItem.mutation_state` is non-null
- no rename `WriteBackOperation` exists yet

This preserves historical behavior and keeps the current tests intact.

## 4. Capability consumers in connector surfaces

### Locked change

Keep the existing external API shape for connector responses.

`ConnectorResponse.has_write_scope` should now prefer `SourceCapabilitySnapshot.can_write` when a snapshot exists, and only fall back to `scope_has_write(connector.granted_scopes)` when the snapshot has not yet been created.

### Explicit non-change

Do **not** broaden P9-004 to gate normal sync reads or connector configuration writes on the new snapshot. This slice is about write-back gating and structured capability state, not a full sync-read capability rewrite.

---

## Compatibility Mirror Strategy

## Canonical write path

The canonical state is written to `WriteBackOperation` first, then mirrored onto `MediaItem` in the same transaction.

## Mirror fields that remain in scope

These fields stay on `MediaItem` and must be updated from the latest relevant `WriteBackOperation` row:

- `mutation_state`
- `last_mutation_error_code`
- `last_mutation_error_message`
- `last_mutation_attempted_at`
- `last_writeback_at`
- `source_filename_applied_at`
- `prior_source_filename`

## Locked mirror rules

### Rename operations

- update `mutation_state`
- update `last_mutation_error_code`
- update `last_mutation_error_message`
- update `last_mutation_attempted_at`
- on success, update `prior_source_filename` and `source_filename_applied_at`

### Metadata-write operations

- update `mutation_state` using the same state mapping
- update `last_mutation_error_code`
- update `last_mutation_error_message`
- update `last_mutation_attempted_at`
- on success, update `last_writeback_at`

## Read path rule

Existing APIs and frontend schemas keep reading the mirror fields in P9-004.

This slice does **not** convert frontend/API consumers to read `WriteBackOperation` directly.

---

## Backfill Script Spec

## File

Create `scripts/backfill_p9_004_capabilities_writeback.py`.

## Shape

Follow the same operational pattern as `scripts/backfill_p9_003_origin_preview.py`:

- async script entry point
- `--dry-run`
- `--batch-size`
- `--stop-after`
- `--user-id`
- `--source-id`
- `--sleep-seconds`
- idempotent rerun behavior
- non-zero exit code when any item fails

## Phase 1 — capability snapshot backfill

Candidates:

- all `SourceConnector` rows where `connector_type='google_drive'`
- no existing `SourceCapabilitySnapshot` row for that connector

Backfill rules:

- `provider_type='google_drive'`
- `source_id`, `source_connector_id`, `user_id` copied from connector
- `scope_text = connector.granted_scopes`
- `scope_tier = writable` when `scope_has_write(granted_scopes)` else `read_only` or `unknown`
- `can_read = True` for configured Drive connectors unless connector state is clearly broken
- `can_write = scope_has_write(granted_scopes)`
- `can_refetch = True` for Drive connectors with stored auth material unless connector state is clearly broken
- `verification_state = current` when derived cleanly from stored connector state, else `error`
- `last_verified_at = now()`

## Phase 2 — write-back operation backfill

Candidates:

- all `MediaItem` rows with non-null `mutation_state`
- joined to `OriginAssetRef`
- no existing `WriteBackOperation` row for the candidate operation type

### Mandatory rename operation backfill

Create a `rename` operation row for every candidate item.

State mapping:

- `fully_applied` -> `applied`
- `pending_writeback` -> `failed` when `last_mutation_attempted_at` is non-null, else `pending`
- `blocked_writeback` -> `blocked`

Backfilled fields:

- `origin_asset_ref_id` from `OriginAssetRef.id`
- `media_item_id`, `user_id`, `source_id`
- `source_connector_id` when the item is connector-backed
- `provider_type` from `OriginAssetRef.provider_type`
- `requested_filename` from latest rename entry in `SourceMutationHistory.new_filename` when present
- `attempt_count` from count of matching `SourceMutationHistory` rows for the operation type
- `last_attempted_at` from `MediaItem.last_mutation_attempted_at`
- `applied_at` from `MediaItem.source_filename_applied_at` for rename or `last_writeback_at` for metadata-write rows
- `last_error_code` / `last_error_message` from mirror fields

### Metadata-write backfill

Create a `metadata_write` operation row only when there is concrete evidence that one existed or succeeded:

- `last_writeback_at` is non-null, or
- `SourceMutationHistory.operation_type='metadata_write'` exists

### Scope limitation

Drive execution and retry support are Google Drive only in P9-004, but the backfill script may create compatibility rows for other provider types when `mutation_state` already exists. Those rows are compatibility data, not a commitment to provider execution support in this slice.

---

## Test Inventory

Target: 12–18 new tests. Existing 423 tests must continue to pass.

## New tests for `SourceCapabilitySnapshot`

1. Drive connector with read-only scope backfills snapshot with `can_write=False`, `scope_tier='read_only'`
2. Drive connector with writable scope backfills snapshot with `can_write=True`, `scope_tier='writable'`
3. OAuth reconnect / scope-upgrade path updates existing snapshot row rather than creating a second row
4. `ConnectorResponse.has_write_scope` prefers snapshot value when snapshot exists

## New tests for `WriteBackOperation`

5. `attempt_drive_rename_after_analysis()` creates or upserts a rename operation row
6. successful Drive rename sets operation `state='applied'` and keeps `MediaItem.mutation_state='fully_applied'`
7. transient Drive failure sets operation `state='failed'` and keeps mirror `pending_writeback`
8. capability gate failure sets operation `state='blocked'` before any Drive PATCH call
9. blocking Drive 403/404 sets operation `state='blocked'` while preserving mirror compatibility
10. `SourceMutationHistory` rows still record per-attempt audit entries unchanged

## New tests for retry endpoint compatibility

11. retry endpoint accepts existing rename operation in `failed` state
12. retry endpoint accepts existing rename operation in `pending` state
13. retry endpoint rejects `blocked` state with 422
14. retry endpoint bootstraps a missing rename operation from the old mirror state and then retries successfully

## New tests for backfill

15. dry-run counts Google Drive capability snapshot candidates correctly
16. backfill maps `pending_writeback` + attempted timestamp to rename operation `failed`
17. backfill maps `blocked_writeback` to `blocked`
18. rerunning the backfill is idempotent and does not duplicate operation rows or capability snapshots

## Existing test contract that must remain unchanged

- `tests/test_mutation_completion.py` assertions on `MediaItem.mutation_state` remain valid
- `tests/test_mutation_completion.py` does not need assertion changes
- `tests/test_mutation_completion.py` route and service tests must continue to pass with the existing response schema and function signature

---

## Out of Scope

- dropping `MediaItem.mutation_state`, `last_mutation_error_code`, `last_writeback_at`, or `last_mutation_attempted_at`
- changing `SourceObject`
- introducing non-Drive execution support for write-back
- reworking local-browser mutation execution into the new operation engine
- expanding `ConnectorResponse` into a full capability DTO beyond the existing bool summary
- storing capability history rather than a current snapshot
- DB triggers for mirror updates
- converting frontend/API consumers to read `WriteBackOperation` directly in this slice
- changing current `SourceMutationHistory` semantics beyond continuing to write it as the per-attempt audit log

---

## Architect Verdict

P9-004 should introduce exactly two new persistent concepts:

1. `SourceCapabilitySnapshot` as the current connector capability cache, one row per `SourceConnector`
2. `WriteBackOperation` as the canonical durable write-back intent row, targeted at `OriginAssetRef`

The workstream stays additive by keeping `MediaItem` mutation fields as same-transaction mirrors, preserving the existing API and test contract while moving backend orchestration onto stable, explicit records.

That is the correct boundary for finishing the ARCH-002 operational model without destabilizing the already-landed P9-003 domain split.