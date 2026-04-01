# Workstream Plan: P4-002 — Plans, Quotas & Analysis Confirmation

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P4-002 |
| **Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Project** | Media Indexing Engine |
| **Dependencies** | P4-001 complete; revised Phase 4 plan approved |
| **Estimated Size** | Medium-Large |
| **Created** | 2026-03-31 |
| **Status** | Draft — awaiting operator review |

## Objective

Introduce a transactional, server-enforced monthly quota system for analysis work and surface a clear confirmation step on the Source flow before analysis begins. This workstream establishes plan metadata on the user account, a quota ledger as the sole authority for usage, API visibility into current quota state, and frontend confirmation behavior that informs the user without becoming the enforcement authority.

## Scope

### In Scope

- Add `plan_name` and `monthly_limit` to the `users` table via Alembic
- Add a `quota_events` ledger table via Alembic
- Implement a quota service in `src/quota/quota_service.py`
- Introduce a backend `QuotaExceededError` path that returns HTTP 429 with structured JSON
- Reserve quota before analysis work is enqueued
- Consume quota on successful analysis completion
- Release quota when analysis fails before success
- Add `GET /api/v1/quota/status`
- Add a frontend confirmation modal on the current Source flow before upload + analysis proceeds
- Disable confirmation in the UI when selected count exceeds remaining quota
- Display existing metadata overwrite warning plus the note that original capture date and geo-location are preserved
- Add ADR-013 to `docs/DECISION_LOG.md` at workstream start/closeout

### Explicit Non-Goals

- No billing, Stripe, checkout, or live paid-plan launch (`P4-005`)
- No admin UI or account-recovery work (`P4-004`)
- No persisted source model or source registry changes (`P4-003`)
- No source-backed Gallery filter (`P4-003`)
- No OCR extraction or OCR-aware search changes (`P4-006`)
- No new metadata-preservation implementation for capture date or geo-location; this workstream only surfaces the existing guarantee in the modal
- No mutable quota counter design; the ledger is authoritative

## Critical Preflight Note

The supplied live-database context for `users` (`id, email, hashed_password, created_at, is_active`) does **not** match the currently checked-in ORM shape observed in the workspace. Before generating the migration, the Engineer must verify the actual application model and live schema alignment and use the **live Alembic baseline** as the source of truth.

This is not a blocker for planning, but it is a required implementation step because quota columns must be added safely to the real schema, not to an outdated assumption.

## Quota Semantics

These semantics are mandatory and define the workstream boundary:

- **Authority model:** `quota_events` is the sole quota record. There is no mutable consumed counter on `users`.
- **Period definition:** `period_month` is the first day of the current calendar month in UTC.
- **Counted event:** quota is counted per newly accepted analysis request for a user-owned media item.
- **Reservation timing:** quota is reserved transactionally before analysis is enqueued.
- **Successful completion:** the reservation becomes `consumed` when the analysis job completes successfully.
- **Failure behavior:** if the job fails before success, the reservation becomes `released`.
- **Duplicate uploads:** exact duplicates that do not enqueue new analysis do not reserve or consume quota.
- **Re-analysis:** manual re-analysis consumes quota and must pass the same reservation check.
- **Frontend role:** quota displayed in the UI is advisory only; the backend reservation transaction is authoritative.

## Schema Definitions

### Users Table Changes

Add via Alembic:

| Column | Type | Constraints | Default |
|---|---|---|---|
| `plan_name` | `VARCHAR(50)` | `NOT NULL` | `'basic'` |
| `monthly_limit` | `INTEGER` | `NOT NULL` | `500` |

**Planning note:** the migration should backfill existing users with `plan_name='basic'` and `monthly_limit=500` before making the columns non-null.

### Quota Events Table

Create `quota_events` with:

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID / String(36) | PK | Generated UUID |
| `user_id` | UUID / String(36) | FK → `users.id`, NOT NULL, indexed | Owner of the quota event |
| `event_type` | Enum(`reserved`, `consumed`, `released`) | NOT NULL, indexed | Reservation lifecycle |
| `media_item_id` | UUID / String(36) | FK → `media_items.id`, NULLABLE, indexed | Nullable to preserve flexibility for future account-level adjustments |
| `period_month` | DATE | NOT NULL, indexed | First day of calendar month in UTC |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | Creation timestamp |

**Recommended indexes:**
- `(user_id, period_month)`
- `(user_id, period_month, event_type)`
- optional uniqueness guard on active reservation semantics if implementation chooses one reservation per media item per month pattern

## Concurrency Approach

`reserve(user_id, media_item_id, month)` must be transactional and safe under concurrent requests.

### Recommended approach

Use a single DB transaction that:

1. Loads and locks the target user row with `SELECT ... FOR UPDATE`
2. Aggregates current `reserved` and `consumed` counts for that `user_id` and `period_month` inside the same transaction
3. Computes `remaining = monthly_limit - consumed - reserved`
4. If `remaining < 1`, raises `QuotaExceededError`
5. Otherwise inserts a `quota_events` row with `event_type='reserved'`
6. Commits before enqueueing the background analysis task

### Why this approach

- Locking the `users` row serializes quota decisions per user without needing a mutable counter column
- It avoids overrun from simultaneous upload/re-analysis requests
- It is simpler and easier to reason about than a serializable transaction across aggregate reads on multiple tables

### Fallback

If `SELECT FOR UPDATE` semantics become awkward in SQLite-based tests, keep the production code on row locking and adapt tests to PostgreSQL-like behavior as needed. Do **not** weaken the production concurrency design to match SQLite limitations.

## Files to Create or Modify by Step

## Step 1: Preflight Schema Reconciliation

**Goal:** verify the real current user schema and reconcile naming differences before adding new columns.

**Files to read/verify:**
- `src/models.py`
- `alembic/versions/cce0c99946e6_initial_schema.py`
- `src/api/routes/auth.py`
- any live-schema inspection notes used by the operator

**Expected outcome:** Engineer confirms whether the authoritative column is `hashed_password` or `password_hash`, whether `display_name` is still live, and whether `is_active` exists in production. The migration for `plan_name`/`monthly_limit` must target the real schema.

**Test requirement:** no code test here; this is a schema-verification gate to prevent a bad migration.

## Step 2: Add Alembic Migration for User Plan Fields and Quota Ledger

**Files to modify/create:**
- `alembic/versions/<new_revision>_p4_002_quota_and_plan_fields.py` (new)
- possibly `src/models.py` if new ORM classes/fields are added in the same step

**Implementation details:**
- Add `plan_name` and `monthly_limit` to `users`
- Backfill existing rows with defaults
- Create `quota_events`
- Add indexes
- Add enum type if using PostgreSQL enum; if cross-DB simplicity is preferred, a constrained string column is acceptable for the ORM with DB check constraint where supported

**Test requirements:**
- Migration upgrade applies cleanly to a database at current head
- Migration downgrade path is defined and reviewed, even if not exercised automatically
- Model metadata and Alembic schema stay aligned

## Step 3: Extend ORM Models and Shared Types

**Files to modify/create:**
- `src/models.py`
- `src/api/schemas.py`
- optionally `src/config.py` only if quota defaults need config support beyond DB defaults

**Implementation details:**
- Add `plan_name` and `monthly_limit` to `User`
- Add `QuotaEvent` model
- Add response model for `GET /api/v1/quota/status`
- Add structured quota-exceeded response schema if the project uses explicit response models for errors

**Test requirements:**
- ORM model tests or integration coverage proving inserts/reads work for `QuotaEvent`
- Schema serialization tests for quota status payload

## Step 4: Implement Quota Service

**Files to create/modify:**
- `src/quota/__init__.py` (new)
- `src/quota/quota_service.py` (new)
- optionally `src/quota/errors.py` (new) if a dedicated exception module improves clarity

**Required service API:**
- `get_monthly_usage(user_id, month)`
- `get_remaining(user_id, month)`
- `reserve(user_id, media_item_id, month)`
- `consume(reservation_id)`
- `release(reservation_id)`

**Implementation details:**
- `get_monthly_usage()` counts `consumed`
- `get_remaining()` computes `monthly_limit - consumed - reserved`
- `reserve()` performs the transactional row lock + aggregate + insert
- `consume()` changes `reserved → consumed`
- `release()` changes `reserved → released`
- defend against double-consume and double-release with explicit guards

**Test requirements:**
- happy path reservation
- over-limit rejection
- remaining-count computation with mixed reserved/consumed/released events
- consume after success
- release after failure
- invalid state transition protection
- concurrent-reservation test proving limit cannot be exceeded

## Step 5: Add Quota Status API

**Files to create/modify:**
- `src/api/routes/quota.py` (new)
- `src/api/app.py`
- `src/api/schemas.py`

**Endpoint:**
- `GET /api/v1/quota/status`

**Response shape:**
```json
{
  "plan_name": "basic",
  "monthly_limit": 500,
  "consumed": 10,
  "reserved": 2,
  "remaining": 488,
  "period_month": "2026-03-01"
}
```

**Auth:** required via existing JWT dependency

**Test requirements:**
- authenticated success response
- user-scoped counts
- correct month formatting and remaining calculation

## Step 6: Wire Quota into Analysis and Upload-to-Analysis Flow

**Files to modify:**
- `src/api/routes/analysis.py`
- `src/api/routes/upload.py`
- `src/analysis/processor.py`
- possibly `src/ingestion/upload_service.py` if reservation metadata needs to be threaded into the pipeline

**Required behavior:**
- Reserve quota before enqueueing a new analysis job
- On analysis success, consume the reservation
- On analysis failure/error path, release the reservation
- Return HTTP 429 with structured JSON when reservation fails

**Planning note on touchpoints:**
- The current upload route immediately enqueues `analyze_media_item` after upload
- The current re-analysis route creates a new `ProcessingJob` and enqueues analysis
- Both first-time analysis and re-analysis must go through the same quota-reservation rules
- The processor must receive enough context to know which reservation to consume or release

**Recommended implementation shape:**
- include `reservation_id` in the background-task call signature
- keep consumption/release inside `analyze_media_item` so success/failure accounting follows the actual job outcome

**Test requirements:**
- upload path reserves quota and enqueues only when allowed
- re-analysis path also reserves quota
- 429 response shape is correct
- failure path releases reservation
- success path converts reservation to consumed

## Step 7: Frontend Quota Status + Confirmation Modal

**Files to modify/create:**
- `frontend/src/pages/UploadPage.tsx` (current Source-branded page in the workspace)
- `frontend/src/api/client.ts`
- `frontend/src/types/api.ts`
- optionally `frontend/src/components/QuotaConfirmationModal.tsx` (new)

**Important note:** the workspace currently uses `UploadPage.tsx` as the Source-branded page. The plan should target the actual current file, not the stale `SourcePage.tsx` path.

**Required behavior:**
- after file selection, fetch quota status
- before upload/analysis begins, show a confirmation modal with:
  - selected count
  - remaining quota
  - metadata overwrite warning
  - note that original date and geo-location are preserved
- disable confirm when selected count exceeds remaining quota
- after confirm, proceed with the existing upload/analysis flow
- if backend still returns 429 because another request consumed quota first, surface the backend error clearly

**Test requirements:**
- API client quota-status call
- confirm-disabled UI when selection exceeds remaining
- manual validation that stale advisory quota does not override backend authority

## Step 8: Error Handling and Structured 429 Response

**Files to modify:**
- `src/api/error_handlers.py` or route-local handling, depending on current project pattern
- `src/api/routes/upload.py`
- `src/api/routes/analysis.py`

**Required response:**
```json
{
  "error": "quota_exceeded",
  "remaining": 0,
  "limit": 500
}
```

**Planning note:** if the project standard requires `detail` + `error_code`, preserve that standard while still including `error=quota_exceeded`, `remaining`, and `limit`. The Engineer should align with the current API error contract rather than inventing an inconsistent one.

**Test requirements:**
- exact 429 payload fields
- consistent behavior across upload-triggered analysis and re-analysis

## Step 9: Docs and ADR Closeout

**Files to modify at closeout:**
- `docs/DECISION_LOG.md` (ADR-013)
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/WORKSTREAMS.md`
- `docs/CURRENT_STATE.md`
- `docs/PROJECT_HANDOFF.md`
- `docs/PROJECT_MAP.md` if new modules/routes are added

**Test requirement:** governance consistency check before moving workstream to Completed.

## Test Requirements by Area

### Backend Integration

- migration applies cleanly
- quota status endpoint returns correct counts
- upload-triggered analysis respects quota
- re-analysis respects quota
- duplicate upload does not consume quota
- failure releases reservation
- success consumes reservation
- over-limit returns 429
- two concurrent requests cannot both reserve the final remaining slot

### Frontend Validation

- modal appears before upload/analysis proceeds
- modal content reflects selected count and current remaining quota
- confirm button disables when selection exceeds remaining
- backend 429 still surfaces correctly if quota changes between modal display and confirm

### Why These Tests Matter

- the quota ledger is the billing foundation for later phases
- concurrency is the main architectural failure mode
- duplicate/re-analysis semantics are easy to get wrong and will create user trust issues if miscounted

## Local Smoke Flow

1. Start backend and frontend locally
2. Log in as a normal user with default `basic` plan / limit 500
3. Open the Source page (current workspace route: `/upload`)
4. Select a small number of files under the limit
5. Confirm the modal shows selected count, remaining quota, overwrite warning, and date/geo preservation note
6. Confirm upload + analysis proceeds after approval
7. Verify `GET /api/v1/quota/status` reflects reservation and then consumption after success
8. Trigger re-analysis and verify remaining quota decreases again
9. Simulate or configure an over-limit case and confirm the modal disables confirm
10. Force a backend over-limit case and verify HTTP 429 is returned with the structured payload
11. Validate duplicate upload behavior does not reduce quota

## AWS Deploy Procedure

### Pre-Deploy

1. Ensure all local tests pass
2. Complete the local smoke flow
3. Prepare the Alembic migration revision for deployment
4. **Take a database backup before deployment**
   - use `pg_dump` against the AWS beta PostgreSQL instance
   - store the backup with timestamp and workstream label
5. Record the migration revision ID being deployed

### Deploy

1. Deploy application changes to the AWS beta stack
2. Run `alembic upgrade head`
3. Verify the new columns and `quota_events` table exist
4. Verify `GET /api/v1/quota/status` on the deployed stack
5. Run the AWS smoke flow with a test user

### Post-Deploy Verification

1. Confirm quota modal appears in the Source flow
2. Confirm successful analysis transitions `reserved → consumed`
3. Confirm a forced failure path results in `reserved → released`
4. Confirm 429 payload shape on over-limit

## Rollback Path

If deployment must be rolled back:

1. Stop or roll back the application release
2. If the migration caused schema or data issues, restore the pre-deploy PostgreSQL backup
3. Downgrade Alembic only if the downgrade path has been verified safe for the live data state; otherwise prefer DB restore over ad hoc downgrade
4. Re-deploy the last known-good application revision

**Architectural guidance:** because this workstream introduces a new authoritative ledger, database restore is the safer rollback path than trying to manually unwind partially written quota events in production.

## ADR-013 Content for `docs/DECISION_LOG.md`

### ADR-013: Monthly Quota Uses Reservation Ledger Semantics

- **Date:** 2026-03-31
- **Workstream:** P4-002
- **Status:** Accepted
- **Context:** The system needs enforceable monthly analysis limits that remain correct under concurrent requests and can later support billing reconciliation. A mutable counter on `users` is simple but does not preserve an audit trail, makes refund/release handling brittle, and is difficult to reconcile when failures occur.
- **Decision:** Use a `quota_events` ledger as the authoritative monthly-usage record. Reserve quota before analysis is enqueued, convert the reservation to consumed on success, and release it on failure. Compute remaining quota as `monthly_limit - consumed - reserved` for the current month.
- **Reasoning:** The ledger preserves history, supports concurrency-safe reservation semantics, and provides a clean bridge into future billing and admin reconciliation. Row-level locking on the `users` row serializes quota decisions per user without introducing a mutable counter.
- **Alternatives considered:** Mutable `used_this_month` integer on `users` (rejected: weak auditability and race handling), app-memory counters (rejected: invalid in distributed deployments), eventual reconciliation from processing jobs (rejected: too indirect and failure-prone).
- **Consequences:** All analysis-triggering paths must reserve quota before enqueueing work. Background job success/failure paths must finalize reservation state. Future billing and admin tooling should read from the ledger rather than inventing parallel counters.

## Exit Criteria

- [ ] `plan_name` and `monthly_limit` exist on `users`
- [ ] `quota_events` exists as the authoritative usage ledger
- [ ] Reservation, consume, and release paths are implemented and tested
- [ ] Upload-triggered analysis and re-analysis both enforce quota
- [ ] `GET /api/v1/quota/status` is live and user-scoped
- [ ] Source flow shows confirmation modal with correct advisory quota info
- [ ] Over-limit returns HTTP 429 with structured payload
- [ ] Local validation is complete
- [ ] AWS deploy includes DB backup and successful smoke validation
- [ ] ADR-013 is recorded in `docs/DECISION_LOG.md`

## Notes for Engineer

- Do not weaken the ledger model into a mutable counter during implementation.
- Use the real workspace file paths, not stale planning assumptions like `SourcePage.tsx`.
- Treat the live-schema vs. checked-in-model mismatch as a first-class implementation concern before generating the migration.