# Workstream Plan: P5-003 — Connector Sync Foundation & First Connector

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P5-003 |
| **Phase** | Phase 5 — Smart Curation & Connected Ingestion |
| **Project** | Media Indexing Engine |
| **Dependencies** | P5-001 complete; P5-002 complete; Phase 5 plan approved |
| **Estimated Size** | Large |
| **Created** | 2026-04-02 |
| **Status** | Draft — awaiting operator review |

## Architect Decision

`P5-003` should be implemented as the **connector foundation plus one manual-trigger S3-compatible connector**.

Reasoning:
- S3-compatible sync fits the current hosted architecture and existing boto3/S3 operational footprint.
- It avoids OAuth, browser redirect, and token-refresh complexity that would over-expand this final Phase 5 workstream.
- It exercises the hard architectural problems that matter now: secret handling, sync state, idempotent import behavior, and safe reuse of the existing ingestion pipeline.
- Manual-trigger only keeps the workstream sprint-sized and reversible while still proving the connected-ingestion model for beta.

## Objective

Extend Source Registry into a real connected-ingestion foundation by adding protected connector configuration, sync-run state, per-object sync memory, and one production-ready S3-compatible connector path that imports through the existing upload pipeline without bypassing deduplication, quota enforcement, or user isolation.

## Scope

### In Scope

- Add one connector-ready foundation for connected sources
- Implement one S3-compatible connector path for beta use
- Add secure per-source connector credential storage
- Add sync-run records with actionable status and counters
- Add per-object sync tracking so repeated syncs are idempotent
- Reuse the existing upload, dedup, quota, and analysis pipeline for imported files
- Add manual sync trigger APIs and minimal sync-history visibility
- Add local validation and AWS beta smoke validation

### Explicit Non-Goals

- No OAuth-based providers in Phase 5 (`Google Drive`, `Dropbox` remain deferred)
- No local watched-folder agent or desktop bridge
- No broad scheduler/orchestration system
- No fully automatic recurring sync in Phase 5
- No delete propagation from remote source to local media library
- No bidirectional sync or upstream write-back
- No connector-specific UI beyond setup, trigger, and status visibility required for beta
- No bypass of existing exact dedup, quota, or analysis rules
- No framework replacement or new infrastructure tier unless later approved by ADR

## Locked Architectural Decisions

## 1. First Connector Choice

### Decision

The first connector in Phase 5 is **S3-compatible bucket sync**.

### Why

- It aligns with the existing S3-compatible storage direction already in the codebase.
- It can be implemented with existing backend patterns and avoids introducing OAuth/UI lifecycle complexity.
- It is a good foundation for future connector abstraction without forcing provider-specific browser flows into this workstream.

## 2. Connector Config Placement

### Decision

Connector configuration must live in a **new connector-specific table**, not on the existing `sources` table.

### Why

- `sources` currently owns user-facing source identity (`name`, `source_type`, archive state) and should remain stable as the human-facing registry.
- Connector-specific state includes sensitive credentials, endpoint details, validation timestamps, and operational status that should not bloat the generic `sources` contract.
- A separate table keeps manual sources simple while allowing connected sources to evolve without turning `sources` into a sparse connector blob.

### Result

- Keep `sources` as the source registry and lightweight summary surface.
- Add a one-to-one `source_connectors` table keyed to `source_id`.

## 3. Connector Credential / Secret Storage

### Decision

Per-source connector credentials must be stored **encrypted at rest in the database** using an application-managed encryption key from environment configuration.

### Why

- Connector credentials are user- or source-specific and therefore cannot live only in static environment variables.
- Plaintext database storage is not acceptable for this workstream.
- Application-managed encryption allows secure storage without introducing a new paid secrets vendor or external dependency.

### Required contract

- Add an env-configured encryption key, for example `CONNECTOR_CREDENTIALS_KEY`.
- Store encrypted credential payload in `source_connectors.credentials_encrypted`.
- Do not return decrypted credentials in API responses.
- Do not log credentials, decrypted payloads, Authorization headers, or signed URLs.
- If the encryption key is not configured, connector create/update/sync paths must refuse to run.

### Storage shape

- Sensitive material such as `access_key_id` and `secret_access_key` lives inside the encrypted payload.
- Non-secret operational fields such as `bucket_name`, `prefix`, `region`, and optional `endpoint_url` may live in plain columns for queryability and validation.

## 4. Sync-Run Record Model

### Decision

Use a dedicated `sync_runs` table for sync execution state and a dedicated `source_objects` table for per-object sync memory.

### Why

- `processing_jobs` is media-item-centric and should not be overloaded with connector-run semantics.
- Sync visibility needs run-level counters and failure summaries, not just per-file job records.
- Idempotent re-sync requires durable memory of remote object identity and last-seen import state.

### Run states

- `pending`
- `running`
- `completed`
- `completed_with_errors`
- `failed`
- `cancelled` is deferred unless implementation needs it naturally; do not design around cancellation in Phase 5

### `sync_runs` required columns

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID |
| `source_id` | `VARCHAR(36)` FK → `sources.id` | source being synced |
| `user_id` | `VARCHAR(36)` FK → `users.id` | DB-layer scoping + list filters |
| `connector_type` | `VARCHAR(50)` | `s3_compatible` in Phase 5 |
| `trigger_type` | `VARCHAR(20)` | `manual` only in Phase 5 |
| `status` | `VARCHAR(30)` | run lifecycle state |
| `started_at` | `TIMESTAMPTZ` | set when actual sync work begins |
| `completed_at` | `TIMESTAMPTZ` nullable | set on terminal state |
| `discovered_count` | `INTEGER` | objects listed from remote source |
| `imported_count` | `INTEGER` | new media items created |
| `duplicate_count` | `INTEGER` | objects whose content already existed for this user |
| `skipped_count` | `INTEGER` | unchanged or unsupported objects |
| `failed_count` | `INTEGER` | object-level failures |
| `error_summary` | `TEXT` nullable | short actionable failure note |
| `created_at` | `TIMESTAMPTZ` | row creation |
| `updated_at` | `TIMESTAMPTZ` | row update |

### `source_objects` required columns

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID |
| `source_id` | `VARCHAR(36)` FK → `sources.id` | owning source |
| `user_id` | `VARCHAR(36)` FK → `users.id` | DB-layer scoping |
| `external_object_key` | `VARCHAR(1024)` | remote object key/path |
| `external_version` | `VARCHAR(255)` nullable | ETag/version marker for change detection |
| `external_last_modified_at` | `TIMESTAMPTZ` nullable | remote timestamp |
| `external_size` | `BIGINT` nullable | remote object size |
| `last_sync_run_id` | `VARCHAR(36)` nullable FK → `sync_runs.id` | last run that touched the record |
| `last_imported_media_item_id` | `VARCHAR(36)` nullable FK → `media_items.id` | imported media row if one exists |
| `last_content_hash` | `VARCHAR(64)` nullable | exact hash after download/import |
| `state` | `VARCHAR(30)` | `imported`, `duplicate`, `skipped`, `failed` |
| `last_error` | `TEXT` nullable | object-level last failure note |
| `created_at` | `TIMESTAMPTZ` | row creation |
| `updated_at` | `TIMESTAMPTZ` | row update |

### Idempotency rule

- A repeated sync should skip unchanged remote objects when `external_object_key` and `external_version` still match the stored state.
- If metadata changes remotely without a usable version marker, Phase 5 may conservatively re-download and rely on existing content-hash dedup.
- Delete propagation is explicitly deferred.

## 5. Boundary Between Connector Sync and Existing Ingestion Pipeline

### Decision

Connector sync must **reuse** the existing ingestion pipeline rather than inventing a parallel import path.

### Required boundary

- Connector code is responsible for:
  - validating connector config
  - listing remote objects
  - downloading remote file bytes
  - filtering unsupported or unchanged objects
  - recording sync-run and source-object state
- Existing ingestion code remains responsible for:
  - file validation
  - MIME detection
  - exact deduplication
  - storage
  - media-item creation
  - processing-job creation
  - quota enforcement
  - downstream analysis enqueue

### Why

- This preserves one authoritative ingest path.
- It ensures connector imports inherit exact dedup and quota behavior automatically.
- It avoids architectural drift where sync imports behave differently from manual uploads.

## 6. Triggering Model for Phase 5

### Decision

Phase 5 supports **manual-trigger only**.

### Why

- Manual trigger proves the sync foundation without introducing a scheduler, cron service, or queue orchestration layer.
- It keeps this final Phase 5 workstream scoped to source connectivity rather than background-job platform design.
- Scheduling can be added later only after one connector proves its state and failure semantics.

### Explicit deferral

- No periodic scheduler
- No “sync every N minutes” settings
- No global background polling loop

## Schema Changes

### New / extended tables

#### Extend `sources`

Add only lightweight connector summary fields that help the UI and list views without exposing secrets:

| Column | Type | Notes |
|---|---|---|
| `connector_status` | `VARCHAR(30)` nullable | summary status: `manual`, `configured`, `syncing`, `error` |
| `last_synced_at` | `TIMESTAMPTZ` nullable | latest successful or partial sync completion |

Do **not** put credentials or provider-specific configuration on `sources`.

#### New table: `source_connectors`

Purpose: one-to-one connector configuration for connected sources.

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID |
| `source_id` | `VARCHAR(36)` FK → `sources.id` UNIQUE | one connector config per connected source |
| `user_id` | `VARCHAR(36)` FK → `users.id` | DB-layer scoping |
| `connector_type` | `VARCHAR(50)` | `s3_compatible` |
| `bucket_name` | `VARCHAR(255)` | required |
| `prefix` | `VARCHAR(500)` nullable | optional object prefix |
| `region` | `VARCHAR(100)` nullable | optional for compatible providers |
| `endpoint_url` | `VARCHAR(500)` nullable | optional for non-AWS S3-compatible providers |
| `credentials_encrypted` | `TEXT` | encrypted payload |
| `config_validated_at` | `TIMESTAMPTZ` nullable | last successful validation |
| `last_validation_error` | `TEXT` nullable | last validation failure |
| `created_at` | `TIMESTAMPTZ` | row creation |
| `updated_at` | `TIMESTAMPTZ` | row update |

#### New table: `sync_runs`

Use the shape defined above.

#### New table: `source_objects`

Use the shape defined above.

### Alembic migration plan

Use a single migration for the initial connector foundation:

- `alembic/versions/b2c3d4e5f6a7_connector_sync_foundation.py`
- `revision = "b2c3d4e5f6a7"`
- `down_revision = "a1b2c3d4e5f6"`

If the live repository has advanced Alembic heads at implementation time, Engineer must preserve this plan’s schema content but update `down_revision` to the actual current head so Alembic history remains valid.

## Required ADRs

Record the following ADRs in `docs/DECISION_LOG.md` before or during implementation start:

1. `ADR-014` — Connector Configuration Uses Split Tables and Encrypted Per-Source Credentials
2. `ADR-015` — Manual-Triggered Sync Foundation Reuses Existing Ingestion Pipeline

Both are architectural decisions, not implementation details.

## Implementation Steps

### Step 1: Lock Connector Data Model and ADRs

**Goal:** freeze the connector schema and sync boundary before any implementation starts.

**Files:**
- `docs/DECISION_LOG.md`
- `src/models.py`
- `docs/planning/P5-003_plan.md`

**Outputs:**
- accepted table split (`sources` vs `source_connectors`)
- accepted sync-run model
- accepted manual-trigger-only rule

### Step 2: Add Schema via Alembic

**Files to create/modify:**
- `alembic/versions/b2c3d4e5f6a7_connector_sync_foundation.py`
- `src/models.py`

**Expected changes:**
- extend `Source`
- add `SourceConnector`
- add `SyncRun`
- add `SourceObject`
- add required indexes and uniqueness constraints

### Step 3: Add Connector Config and Encryption Support

**Files to create/modify:**
- `src/config.py`
- `src/connectors/__init__.py`
- `src/connectors/secrets.py`

**Expected behavior:**
- config includes `CONNECTOR_CREDENTIALS_KEY`
- encryption helper can encrypt/decrypt connector credential payloads
- connector features fail closed when encryption key is missing

### Step 4: Add Connector Abstractions and S3-Compatible Connector

**Files to create/modify:**
- `src/connectors/base.py`
- `src/connectors/s3_connector.py`
- optionally a small dataclass/schema module under `src/connectors/`

**Expected behavior:**
- validate S3-compatible config
- list remote objects under bucket/prefix
- download object bytes safely
- expose a simple interface usable by sync orchestration

### Step 5: Add Sync Orchestration Service

**Files to create/modify:**
- `src/connectors/sync_service.py`
- `src/ingestion/upload_service.py` (only if a small helper extraction is needed)
- `src/ingestion/job_manager.py` only if a small utility is useful; do not overload `ProcessingJob`

**Expected behavior:**
- create `sync_runs` row
- prevent overlapping runs for the same source
- enumerate remote objects
- compare against `source_objects`
- call existing upload/integration path for new or changed files
- update per-object state and run counters

### Step 6: Add API Surface

**Files to create/modify:**
- `src/api/routes/sources.py`
- `src/api/routes/connectors.py` (new, preferred)
- `src/api/schemas.py`
- `src/api/app.py`

**Preferred API shape:**

1. `POST /api/v1/sources/{id}/connector/s3`
   - create or replace connector config for that source
2. `POST /api/v1/sources/{id}/sync`
   - manual trigger only
3. `GET /api/v1/sources/{id}/sync-runs`
   - paginated recent run history
4. extend `GET /api/v1/sources`
   - include connector summary fields and last sync summary when present

**Required rules:**
- all endpoints are DB-layer user-scoped
- secret fields are never returned
- source ownership is enforced with `404`/`403` semantics consistent with existing source routes

### Step 7: Add Frontend Support

**Files to modify/create:**
- `frontend/src/types/api.ts`
- `frontend/src/api/client.ts`
- `frontend/src/pages/SourcesPage.tsx`
- optionally one or two small components under `frontend/src/components/`

**Expected behavior:**
- show connector status for connected sources
- allow S3-compatible connector setup/edit
- allow manual sync trigger
- show recent sync runs and top-level counters/errors
- do not surface credentials after save

### Step 8: Add Tests

**Files to create:**
- `tests/test_connectors.py`
- optionally `tests/test_connector_sync.py` if separation is cleaner

**Required coverage:**
- connector config validation
- missing encryption key fails closed
- encrypted credential payload not returned by API
- per-user source ownership and DB scoping
- no concurrent run overlap for same source
- unchanged object re-sync is idempotent
- changed object import flows through existing dedup/quota logic
- failure reporting updates `sync_runs` and `source_objects`

### Step 9: Closeout Docs

**Files to update at closeout:**
- `docs/DECISION_LOG.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/WORKSTREAMS.md`
- `docs/CURRENT_STATE.md`
- `docs/PROJECT_HANDOFF.md`
- `docs/PROJECT_MAP.md`

## Acceptance Criteria

### Phase-Plan Criteria Mapping

- Source records can represent one connected source type beyond `manual`
- A beta user can configure the first connector and trigger a sync successfully
- Sync imports new objects through the existing ingestion pipeline and respects exact dedup/quota rules
- Sync status/history is visible enough to debug failures
- Secret/config handling is secure and excluded from logs/responses
- Tests cover connector config validation, user scoping, idempotent re-sync behavior, and failure reporting

### Additional Workstream Criteria

- Connector config is stored in `source_connectors`, not overloaded into `sources`
- Per-source credentials are encrypted at rest and fail closed when encryption config is absent
- `sync_runs` captures terminal state plus actionable counters and error summary
- `source_objects` prevents re-import of unchanged remote objects on repeated manual sync
- Only one active sync run per source is allowed at a time
- Manual sync remains the only trigger mode in Phase 5
- Connector imports do not bypass existing exact dedup, quota, validation, or analysis enqueue rules
- No secrets appear in API responses, structured logs, or UI state after save

## Validation Checklist

### Backend / Data Validation

- [ ] Alembic migration applies cleanly to current head
- [ ] Existing manual upload flow is unchanged
- [ ] Connector config create/update is user-scoped and encrypted at rest
- [ ] Manual sync creates `sync_runs` and updates counters correctly
- [ ] Repeated sync skips unchanged objects idempotently
- [ ] Changed or new objects reuse the existing ingestion path
- [ ] Connector imports respect quota enforcement
- [ ] Secret material is excluded from logs and API payloads
- [ ] Overlapping sync triggers for the same source are rejected safely

### Frontend / UX Validation

- [ ] Sources UI can configure the S3-compatible connector cleanly
- [ ] Manual sync trigger is available only for eligible connected sources
- [ ] Sync history/status is visible enough for beta debugging
- [ ] Saved connector credentials are never redisplayed
- [ ] Error states are actionable but do not leak secrets

### AWS Smoke Validation

- [ ] Test bucket/prefix configured for one beta account
- [ ] Manual sync imports new objects end-to-end
- [ ] Re-run of the same sync produces idempotent results
- [ ] A bad credential or bad endpoint produces visible failure state without crashing unrelated features

## AWS Rollout and Rollback

### Rollout

1. Back up AWS PostgreSQL before deploying schema changes.
2. Deploy code with connector UI hidden behind a feature gate if implementation needs one.
3. Run Alembic migration.
4. Configure `CONNECTOR_CREDENTIALS_KEY` in AWS environment before creating any connector config.
5. Create one test S3-compatible source for an internal/beta account.
6. Validate manual sync, repeated sync, and failure visibility.
7. Only then expose the connector UI to wider beta users.

### Rollback

- If schema is healthy but sync behavior is wrong, disable connector UI and sync-trigger routes first while leaving schema in place.
- If credential handling is defective, disable the connector feature immediately and rotate any impacted test credentials.
- If the migration is defective, restore the AWS DB backup rather than improvising partial schema repair.
- Imported media that already came through the standard ingestion path should be treated as normal media items; rollback should not attempt dangerous bulk deletion unless the operator explicitly approves it.

## Risks and Open Questions

### Resolved in this plan

- **First connector choice:** S3-compatible only
- **Credential handling:** encrypted-at-rest DB storage with env-managed key
- **Config placement:** new `source_connectors` table, not `sources`
- **Run visibility:** dedicated `sync_runs` table
- **Idempotency memory:** dedicated `source_objects` table
- **Trigger mode:** manual only in Phase 5
- **Ingestion boundary:** reuse existing upload/dedup/quota pipeline

### Explicitly Deferred

- Scheduled sync and polling orchestration
- OAuth connector families
- Remote delete propagation
- Cursor-based large-scale connector scheduling beyond the single-run beta model
- Connector health dashboards broader than per-source status and recent runs

### Residual Risks

- Large buckets may expose runtime limits if manual sync tries to enumerate too much at once; Engineer should bound page sizes and keep counters incremental.
- Secret handling is security-sensitive; implementation must be conservative and fail closed.
- Duplicate Alembic revision drift already exists in recent docs/history; Engineer must confirm the live Alembic head before creating the migration file.

## Notes for Engineer

- Keep connected-ingestion additive to the existing manual-source model rather than replacing it.
- Do not create a second ingest pipeline for connector imports.
- Do not add scheduling because “it would be easy while we are here.” It is explicitly out of scope.
- Prefer a narrow S3-compatible contract that can later generalize, rather than a prematurely generic connector abstraction.