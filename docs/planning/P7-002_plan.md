# Workstream Plan: P7-002 — Google Drive Connector (Root-Only)

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P7-002 |
| **Phase** | Phase 7 — Post-Phase 6 User-Value Features |
| **Project** | Media Indexing Engine |
| **Dependencies** | P5-003 complete; P6-001 complete; existing connector sync foundation and Google OAuth experience available |
| **Estimated Size** | Large |
| **Created** | 2026-04-05 |
| **Status** | Draft revised before approval pass — awaiting operator review |

## Architect Decision

`P7-002` should be implemented as the **first OAuth-backed connector on top of the existing connector foundation, using a Google Drive-specific OAuth/token manager, a provider-neutral connector container model, and the existing sync pipeline without introducing a new connector inheritance hierarchy**.

Reasoning:
- The existing connector foundation already solves the difficult ingestion-side problems: sync-run tracking, per-object idempotency memory, overlap prevention, encrypted connector secret storage, and reuse of the upload pipeline.
- Google Drive is the most valuable next connected source, but it introduces a different class of complexity than S3: delegated OAuth, refresh-token lifecycle management, provider-specific listing semantics, and non-path-based object identity.
- The simplest safe expansion is to keep `ConnectorBase` intact, add a dedicated token manager and connector factory, and evolve `source_connectors` from S3-named container semantics into provider-neutral remote container semantics.
- The first slice must stay intentionally narrow: `My Drive` root only, `drive.readonly` only, no folder picker, no Google-native docs import, and no coupling to login identity storage.

## Objective

Add the first Google Drive connector so a signed-in user can connect `My Drive`, manually trigger sync, and import supported image files through the existing ingestion pipeline, while preserving connector secret separation, user-scoped security, and reversible connector architecture.

## Scope

### In Scope

- Add one root-only Google Drive connector path on top of the existing connector foundation
- Add Drive-specific OAuth initiation and callback handling for connector authorization
- Add a dedicated Drive token-manager boundary for code exchange, access-token refresh, and refresh-token rotation persistence
- Evolve connector config storage from S3-named bucket semantics to provider-neutral remote container semantics
- Persist a non-secret authorized Google account snapshot for reconnect safety and UI visibility
- Add a connector factory/registry so sync orchestration remains provider-agnostic
- Extend the connector object contract to carry a user-facing filename/display name distinct from the stable remote object key
- Reuse the existing upload, dedup, quota, storage, and analysis pipeline for imported Drive files
- Add local validation and AWS beta rollout guidance for the new connector

### Explicit Non-Goals

- No Google Drive folder picker in this first slice
- No sync outside `My Drive` root in this workstream
- No Google-native Docs, Sheets, Slides, or shortcut ingestion
- No use of `oauth_accounts` for connector token storage
- No replacement of `ConnectorBase` with an OAuth-specific base class
- No scheduled sync or background polling loop beyond the existing manual-trigger sync model
- No provider-agnostic OAuth framework abstraction beyond the small token-manager boundary required now
- No Dropbox, OneDrive, or Box support in this workstream
- No remote delete propagation from Google Drive to the local library
- No hard-delete of sync history during disconnect/reconnect handling

## Locked Architectural Decisions

## 1. OAuth Initiation Boundary

### Decision

Google Drive authorization must start from an **authenticated SPA API call that returns an `authorization_url`**, not from a plain browser link to a protected backend route.

### Required flow

1. Frontend calls `POST /api/v1/sources/{source_id}/connector/google-drive/start` with the existing bearer token.
2. Backend verifies source ownership and source eligibility, creates short-lived signed state, sets browser-bound HTTP-only state cookie(s), and returns `{authorization_url}`.
3. Frontend redirects the browser to the returned Google authorization URL.
4. Google redirects to the backend callback.
5. Backend validates state, exchanges the authorization code, persists encrypted connector secrets, upserts the connector row, and redirects the browser back to the Sources page.

### Why

- The application is bearer-token based, not cookie-session based.
- A plain browser link would create a fragile auth boundary because top-level navigation is not the app’s normal authenticated API path.
- The authenticated start endpoint lets the backend enforce source ownership before any Google consent flow begins.

## 2. Callback State Protection

### Decision

The Google Drive callback must use **short-lived signed browser-bound state carrying user and source context**, but this workstream does **not** add a separate server-side one-time state store. Replay resistance is provided by signed browser-bound state, short expiry, and Google's single-use authorization code semantics.

### Required state contract

- State payload must bind: `user_id`, `source_id`, issued-at timestamp, and a one-time random nonce.
- The browser must receive the raw random value or equivalent browser-bound verifier only in an HTTP-only SameSite=Lax cookie scoped to the callback path.
- The callback must verify signature, age, and cookie match before exchanging the code.
- The callback must re-check source ownership and archived state after state validation and before persisting any connector tokens.
- This workstream does not add a DB-backed one-time state record; the plan must not claim stronger local single-use guarantees than that.
- Replay of a previously successful callback must fail at Google code exchange because the authorization code is single-use provider-side; that failure must be handled as an invalid/replayed callback outcome.
- Missing, invalid, expired, or replayed callback attempts are hard failures.

### Why

- This keeps the authorization flow aligned with the project’s no-session default while still giving strong request binding and replay protection.
- It mirrors the disciplined state handling style already introduced in the Google SSO workstream without incorrectly treating this as an OpenID login flow.

## 3. Authorized Account Snapshot and Reconnect Behavior

### Decision

The connector must persist a **non-secret authorized Google account snapshot** and use it to define safe disconnect/reconnect behavior.

### Required snapshot

On successful callback, the backend must fetch and persist a non-secret account snapshot from Google Drive account metadata, including:

- `authorized_account_provider_id` — stable provider-side account identifier exposed by the Drive account metadata surface, such as Drive `permissionId`
- `authorized_account_email` — current Google account email address when available
- `authorized_account_display_name` — current display name when available

These values are informational and operational metadata, not secrets, and should live in plain connector columns rather than encrypted secret storage.

### Disconnect behavior

- The Drive disconnect endpoint remains `DELETE /api/v1/sources/{source_id}/connector/google-drive`, but its semantics are **logical disconnect**, not historical erasure.
- Disconnect must clear encrypted token material and disable future sync for that connector.
- Disconnect must preserve non-secret account snapshot fields, container metadata, and historical `sync_runs` for auditability.

### Reconnect behavior

- If a source is reconnected to the **same** authorized Google account, the implementation may reuse existing `source_objects` rows for idempotent sync continuity.
- If a source is reconnected to a **different** authorized Google account, the implementation must purge existing `source_objects` rows for that source before the next sync is allowed to run.
- `sync_runs` history must be preserved even when the authorized account changes; it is historical audit data, not active sync memory.

### Why

- File IDs are only safe to reuse as object-memory keys within the same provider account context.
- Preserving a non-secret account snapshot gives the UI meaningful connected-state information and gives reconnect handling a defensible comparison point.
- `source_objects` is sync memory and may be reset; `sync_runs` is historical audit and should remain intact.

## 4. Callback Redirect Contract

### Decision

The backend callback must use a **fixed success/failure redirect contract** so the SPA can show deterministic post-authorization banners without inferring backend state.

### Required redirect shape

- Success redirect:
  - `{frontend_url}/sources?connector=google_drive&source_id={source_id}&connector_result=connected`
- Failure redirect:
  - `{frontend_url}/sources?connector=google_drive&source_id={source_id}&connector_result=error&error_code={error_code}`

### Required rules

- No secrets, authorization codes, refresh tokens, access tokens, or encrypted identifiers may appear in the redirect URL.
- `source_id` may appear because it is already user-scoped application state.
- `error_code` must come from a small documented set, for example: `access_denied`, `invalid_state`, `state_expired_or_replayed`, `exchange_failed`, `connector_disabled`, `source_not_found`, `source_archived`, `account_snapshot_failed`.
- The frontend Sources page must consume these query parameters to render a clear success or failure state and then clear them from the URL after display.

### Why

- This removes ambiguity from the callback completion UX.
- It prevents Engineer from improvising ad hoc redirect parameters or embedding secret material in URLs.

## 5. Token Storage Boundary

### Decision

Google Drive refresh tokens must live in **encrypted connector-secret storage** in `source_connectors.credentials_encrypted`, not in `oauth_accounts`.

### Why

- `oauth_accounts` is the app-login identity link table established by P6-001, not a delegated external-access token store.
- Drive connector tokens are source-scoped operational secrets and belong with other per-source connector secrets.
- Mixing login identity and connector access delegation would create avoidable long-term coupling.

### Required credential shape

The encrypted payload for the Drive connector should store only connector-secret material and rotation metadata, for example:

```json
{
  "refresh_token": "...",
  "refresh_token_issued_at": "2026-04-05T00:00:00Z",
  "granted_scopes": ["drive.readonly"]
}
```

Access tokens are transient runtime credentials and should not become the system-of-record secret.

## 6. Token Manager Boundary

### Decision

Add a dedicated Drive token-manager boundary that owns **authorization code exchange, access-token refresh, and refresh-token rotation persistence**, rather than scattering that logic across the callback route and connector implementation.

### Required boundary

- Suggested module: `src/connectors/google_drive_tokens.py`
- The callback route may call into the token manager to perform the initial code exchange.
- The connector may call into the token manager to obtain a valid access token.
- If Google returns a replacement refresh token during refresh, only the token manager is responsible for persisting that new token back into encrypted connector-secret storage.

### Why

- This keeps token lifecycle logic out of `list_objects()` and `download_object()`.
- It creates the smallest reusable pattern for future OAuth-backed connectors without prematurely introducing `OAuthConnectorBase`.

## 7. Provider-Neutral Connector Container Semantics

### Decision

Evolve `source_connectors` from S3-named `bucket_name` semantics to **provider-neutral remote container semantics**.

### Required schema evolution

- Rename `bucket_name` to `remote_container_id`
- Add `remote_container_label` as a nullable plain-text column
- Add `authorized_account_provider_id` as a nullable plain-text column
- Add `authorized_account_email` as a nullable plain-text column
- Add `authorized_account_display_name` as a nullable plain-text column

### Semantics

- For S3-compatible connectors:
  - `remote_container_id` = bucket name
  - `remote_container_label` = bucket name
- For the first Google Drive slice:
  - `remote_container_id` = `root`
  - `remote_container_label` = `My Drive`

### Why

- Reusing `bucket_name` for Drive folder/container semantics would create misleading schema debt immediately.
- This is the smallest migration that removes the S3-only naming problem without redesigning the entire connector table.

## 8. First Drive Slice Is Root-Only

### Decision

The first Google Drive connector slice is **root-only `My Drive` sync**. Folder picking is deferred.

### Why

- Folder-selection UI and API behavior add a second provider-specific workflow that is not required to prove the connector architecture.
- Root-only keeps the workstream smaller and more reversible while still delivering real user value.

### Consequence

- The connector always stores `remote_container_id='root'` and `remote_container_label='My Drive'` in this workstream.
- The UI should present this clearly instead of implying arbitrary folder selection already exists.

## 9. Google Drive Scope Lock

### Decision

The initial Google Drive connector uses **`drive.readonly` only**.

### Why

- It is the minimum viable scope that supports both listing metadata and downloading file bytes.
- `drive.metadata.readonly` is insufficient because the connector also needs downloads.
- `drive.file` is the wrong scope for a general library ingestion connector.

## 10. Drive Object Eligibility Rules

### Decision

The first Drive connector must enumerate only supported import candidates and exclude Drive-only objects that do not map to the existing media ingestion pipeline.

### Required exclusions

- Exclude trashed files
- Exclude shortcuts
- Exclude Google-native Docs, Sheets, Slides, and similar non-downloadable native object types
- Exclude files whose MIME type or filename extension cannot pass the existing upload pipeline

### Why

- The existing ingestion system expects real file bytes for supported image formats.
- Native Google document objects are a fundamentally different product surface and should not be backdoored into a file-ingestion workstream.

## 11. Stable Object Identity and Idempotency Marker

### Decision

For Google Drive, use **Google file ID as the stable remote object key** and **Drive `version` as the idempotency marker**.

### Result

- `RemoteObject.key` = Google file ID
- `RemoteObject.version` = Drive `version`
- `source_objects.external_object_key` stores the file ID
- `source_objects.external_version` stores the Drive `version`

### Why

- Google file IDs are the durable provider identity.
- File path semantics are not stable or sufficient for Drive.
- Drive `version` is the correct provider-side change marker for sync idempotency.

## 12. ConnectorBase Stays, Connector Factory Is Added

### Decision

Keep `ConnectorBase` as the base abstraction, but add a **connector factory/registry** and do not introduce `OAuthConnectorBase` in this workstream.

### Required boundary

- Suggested module: `src/connectors/factory.py`
- `sync_service.py` asks the factory to build the connector from a `SourceConnector` row and decrypted credentials
- The factory handles `s3_compatible` and `google_drive`

### Why

- One OAuth-backed connector is not enough evidence to justify a new inheritance hierarchy.
- The connector factory solves the real problem now: preventing connector-construction branching from spreading inside sync orchestration.

## 13. Filename / Display Name Contract

### Decision

The connector object contract must explicitly separate **stable remote identity** from **user-facing filename/display name**.

### Required interface evolution

Extend `RemoteObject` to include a required `display_name` field.

```python
@dataclass
class RemoteObject:
    key: str
    display_name: str
    version: str | None
    last_modified_at: datetime | None
    size: int | None
```

### Semantics

- For S3-compatible connectors, `display_name` is typically the basename of the object key.
- For Google Drive, `display_name` is the provider file name returned by Drive metadata.
- The sync pipeline uses `display_name` when handing off to the upload service; it does not derive filenames from `key` for non-path-based connectors.

### Why

- Drive file IDs are not filenames.
- The current connector foundation assumes path-like keys; that assumption must be corrected before the first non-path connector is implemented.

## Schema Changes

### New / changed schema work

#### Modify `source_connectors`

| Change | Type | Notes |
|---|---|---|
| Rename `bucket_name` → `remote_container_id` | migration | provider-neutral remote container identity |
| Add `remote_container_label` | `VARCHAR(255)` nullable | user-facing label such as `My Drive` |
| Add `authorized_account_provider_id` | `VARCHAR(255)` nullable | stable non-secret Drive account snapshot identifier |
| Add `authorized_account_email` | `VARCHAR(255)` nullable | latest non-secret connected account email |
| Add `authorized_account_display_name` | `VARCHAR(255)` nullable | latest non-secret connected account display name |

Keep existing fields for now:
- `prefix` stays nullable and remains unused for root-only Drive
- `region` stays nullable and is unused for Drive
- `endpoint_url` stays nullable and is unused for Drive
- `credentials_encrypted` remains the encrypted secret store

### No new connector-token table in this workstream

- Do not extend `oauth_accounts`
- Do not add a new provider-token table yet
- Keep connector token storage within encrypted connector-secret payloads

### Alembic migration plan

- `alembic/versions/<new_revision>_google_drive_connector.py`
- Must include the column rename from `bucket_name` to `remote_container_id`
- Must add `remote_container_label`
- Must preserve existing S3-compatible data during migration

## API and Module Changes

### New backend routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/sources/{source_id}/connector/google-drive/start` | authenticated initiation; returns `authorization_url` |
| `GET` | `/api/v1/connectors/google-drive/callback` | Google callback; validates state and upserts connector |
| `DELETE` | `/api/v1/sources/{source_id}/connector/google-drive` | logical disconnect; clears active secret material while preserving non-secret snapshot/history |

### Existing connector routes affected

- `GET /api/v1/sources/{source_id}/connector` must continue to return a provider-neutral `ConnectorResponse`
- `POST /api/v1/sources/{source_id}/sync` and `GET /api/v1/sources/{source_id}/sync-runs` remain unchanged at the route level but must work through the new connector factory
- The callback route must redirect using the fixed success/failure query contract defined above

### New / changed backend modules

- `src/auth/google_drive_oauth.py` — Drive authorization URL + signed state helpers
- `src/connectors/google_drive_tokens.py` — code exchange, access-token refresh, refresh-token rotation persistence
- `src/connectors/google_drive_connector.py` — `ConnectorBase` implementation for root-only Drive sync
- `src/connectors/factory.py` — provider registry / builder used by sync orchestration
- `src/connectors/sync_service.py` — updated to consume the factory and `display_name`
- `src/api/routes/connectors.py` or a sibling route module — Drive start/disconnect endpoints

### Frontend contract

- Sources page must call the authenticated Drive start endpoint through the existing API client
- Backend returns an `authorization_url`; frontend then redirects the browser explicitly
- Sources page must show deterministic success/failure banners based on `connector_result` and `error_code`
- Sources page must clear callback query parameters from the URL after rendering the post-callback state
- UI must present this workstream honestly as `Google Drive — My Drive` rather than implying arbitrary folder selection

## Config Changes

### New config block

Add a dedicated Google Drive connector config separate from Google SSO.

### Required fields

| Field | Source | Notes |
|---|---|---|
| `enabled` | `ENABLE_GOOGLE_DRIVE_CONNECTOR` | rollout gate, default OFF |
| `client_id` | `GOOGLE_DRIVE_CLIENT_ID` | Drive connector OAuth client |
| `client_secret` | `GOOGLE_DRIVE_CLIENT_SECRET` | backend only |
| `redirect_uri` | `GOOGLE_DRIVE_REDIRECT_URI` | explicit backend callback URL in production |
| `frontend_url` | `GOOGLE_DRIVE_FRONTEND_URL` | redirect target after callback |

### Required behavior

- The Drive connector feature must fail closed when the gate is OFF or credentials are absent
- Drive OAuth config must remain separate from Google SSO config even if both use Google OAuth under the hood

## Required ADRs

Record the following ADRs in `docs/DECISION_LOG.md`:

1. `ADR-021` — Delegated Connector OAuth Tokens Live in Encrypted Connector Storage, Not `oauth_accounts`
2. `ADR-022` — Connector OAuth Initiation Uses Authenticated SPA Start and Signed Browser-Bound Callback State
3. `ADR-023` — `source_connectors` Uses Provider-Neutral Remote Container Semantics
4. `ADR-024` — First Google Drive Connector Slice Is Root-Only and Uses `drive.readonly`
5. `ADR-025` — Connector Construction Uses a Registry/Factory and Dedicated Token Manager Without Introducing `OAuthConnectorBase`

## Implementation Steps

### Step 1: Lock Connector OAuth and Schema Decisions

**Goal:** freeze the Drive connector architecture before implementation starts.

**Files:**
- `docs/planning/P7-002_plan.md`
- `docs/DECISION_LOG.md`
- `docs/WORKSTREAMS.md`

**Outputs:**
- accepted Drive OAuth start boundary
- accepted state protection model
- accepted account snapshot / reconnect behavior
- accepted callback redirect contract
- accepted token storage boundary
- accepted provider-neutral connector container semantics
- accepted root-only scope and eligibility rules

### Step 2: Apply Provider-Neutral Connector Schema Migration

**Files to create/modify:**
- `alembic/versions/<new_revision>_google_drive_connector.py`
- `src/models.py`
- `src/api/schemas.py`
- `frontend/src/types/api.ts`

**Expected changes:**
- rename `bucket_name` to `remote_container_id`
- add `remote_container_label`
- add authorized-account snapshot fields
- keep existing S3 connector functionality intact
- update read/write schemas and UI contracts to use provider-neutral field names

### Step 3: Add Drive Config and OAuth / Token Modules

**Files to create/modify:**
- `src/config.py`
- `src/auth/google_drive_oauth.py`
- `src/connectors/google_drive_tokens.py`

**Expected behavior:**
- load dedicated Drive connector config from env
- build Google authorization URLs with signed state
- exchange authorization code for Drive tokens
- fetch authorized Google account snapshot metadata
- refresh access tokens on demand
- persist rotated refresh tokens back into encrypted connector-secret storage when necessary

### Step 4: Add Connector Factory and Drive Connector Implementation

**Files to create/modify:**
- `src/connectors/base.py`
- `src/connectors/factory.py`
- `src/connectors/google_drive_connector.py`
- `src/connectors/sync_service.py`

**Expected behavior:**
- `RemoteObject` includes `display_name`
- sync orchestration builds connectors through the factory
- Drive connector lists only eligible files from `My Drive` root
- Drive connector uses file ID as key and Drive version as version marker

### Step 5: Add Drive Start / Callback / Disconnect Endpoints

**Files to create/modify:**
- `src/api/routes/connectors.py` or a new adjacent route module
- `src/api/app.py`

**Expected behavior:**
- authenticated start endpoint returns `authorization_url`
- callback validates signed browser-bound state, enforces the redirect contract, and upserts the connector row with account snapshot metadata
- disconnect endpoint clears active secret material without erasing sync history
- all routes remain DB-user-scoped

### Step 6: Add Frontend Integration

**Files to create/modify:**
- `frontend/src/api/client.ts`
- `frontend/src/types/api.ts`
- `frontend/src/pages/SourcesPage.tsx`

**Expected behavior:**
- `Connect Google Drive` triggers the authenticated start endpoint
- browser redirects to Google using returned `authorization_url`
- Sources page shows connection success/failure clearly after callback redirect using the fixed query contract
- connected-state UI shows `Google Drive` and `My Drive`

### Step 7: Add Tests

**Files to create/modify:**
- `tests/test_google_drive_connector.py` or equivalent
- connector regression tests for S3 path if shared coverage is appropriate

**Required coverage:**
- start endpoint requires auth and source ownership
- start endpoint fails safely when Drive connector gate/config is OFF
- callback rejects missing/invalid/expired state and repeated callbacks with already-used provider auth codes
- callback success/failure redirects use the documented query contract only
- non-secret authorized account snapshot is persisted correctly
- disconnect preserves `sync_runs` but clears active Drive secret material
- same-account reconnect preserves usable `source_objects`
- different-account reconnect purges existing `source_objects` before next sync
- callback rejects archived or foreign source targets
- refresh token is stored only in encrypted connector-secret storage
- refresh-token rotation persistence path works when a new refresh token is returned
- connector factory builds both `s3_compatible` and `google_drive`
- Drive listing excludes trashed, shortcuts, and Google-native docs
- Drive sync uses file ID as key and Drive version as idempotency marker
- sync pipeline uses `display_name` rather than deriving filename from `key`
- S3-compatible connector behavior remains unchanged after the schema rename

### Step 8: Closeout Docs

**Files to update at closeout:**
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/WORKSTREAMS.md`
- `docs/CURRENT_STATE.md`
- `docs/PROJECT_HANDOFF.md`
- `docs/PROJECT_MAP.md`

## Acceptance Criteria

- A signed-in user can initiate Google Drive connector authorization from the Sources page through an authenticated API call
- The backend callback accepts only short-lived valid signed browser-bound state and rejects invalid or replayed attempts
- The backend callback persists a non-secret authorized Google account snapshot and applies the locked same-account / different-account reconnect rules
- Callback redirects to the SPA only through the documented success/failure query contract
- Google Drive refresh tokens are stored only in encrypted connector-secret storage, never in `oauth_accounts`
- `source_connectors` uses provider-neutral container semantics via `remote_container_id` and `remote_container_label`
- Existing S3-compatible connector behavior continues to work after the schema evolution
- The first Drive slice connects only `My Drive` root and does not expose folder selection UI
- The connector uses `drive.readonly` only
- Trashed files, shortcuts, and Google-native docs are excluded from sync
- The sync system uses Google file ID as the stable object key and Drive version as the idempotency marker
- The sync pipeline uses a user-facing display name instead of deriving filenames from non-path keys
- Sync orchestration builds connectors through a factory/registry and does not branch provider construction inline

## Validation Checklist

### Backend / Data Validation

- [ ] Migration preserves existing S3-compatible connector rows correctly
- [ ] `remote_container_id` / `remote_container_label` semantics are correct for both S3 and Drive
- [ ] Authorized account snapshot fields are populated correctly without storing secrets
- [ ] Drive config gate fails closed when disabled or incomplete
- [ ] Callback state validation rejects tampered or expired state and replayed callbacks fail safely at code exchange
- [ ] Same-account reconnect preserves valid object-memory reuse
- [ ] Different-account reconnect purges stale `source_objects` while preserving `sync_runs`
- [ ] Drive refresh token remains encrypted at rest
- [ ] Refresh-token rotation persistence updates encrypted connector storage safely
- [ ] Drive file ID and version mapping produce correct idempotent sync behavior

### Frontend / UX Validation

- [ ] Sources page starts the connector flow through an authenticated API request, not a plain link
- [ ] Success and failure states after callback are visible, recoverable, and driven by the fixed redirect contract
- [ ] UI clearly communicates `Google Drive — My Drive` root-only scope

### AWS Smoke Validation

- [ ] Drive connector OAuth redirect URI works behind the production reverse proxy
- [ ] A real Drive connection can be created for `My Drive`
- [ ] Manual sync imports supported image files and skips excluded Drive object types cleanly
- [ ] Existing S3-compatible connector still configures and syncs correctly after the migration

## AWS Rollout and Rollback

### Rollout

1. Back up AWS PostgreSQL before applying the migration.
2. Deploy code and migration with `ENABLE_GOOGLE_DRIVE_CONNECTOR=false`.
3. Set Drive connector env vars on the server.
4. Configure the Google Cloud console redirect URI for the Drive callback.
5. Smoke-test one real `My Drive` connection and one existing S3-compatible source while the flag remains OFF for general users.
6. Only after validation passes, set `ENABLE_GOOGLE_DRIVE_CONNECTOR=true`.

### Rollback

- If OAuth flow behavior is wrong, set `ENABLE_GOOGLE_DRIVE_CONNECTOR=false` first.
- If refresh-token lifecycle or sync behavior is incorrect, disable the Drive connector before touching the existing S3 path.
- If the migration is defective, restore the DB backup rather than hand-editing connector rows.
- Existing S3-compatible connector support and manual uploads must remain available throughout rollback.

## Risks and Open Questions

### Resolved in this plan

- Auth initiation boundary: authenticated SPA API start
- Callback protection: signed browser-bound state with user/source binding
- Token storage: encrypted connector-secret storage, not `oauth_accounts`
- Token lifecycle boundary: dedicated token manager
- Container semantics: provider-neutral `remote_container_id` / `remote_container_label`
- First scope: root-only `My Drive`
- Scope grant: `drive.readonly`
- Connector architecture: factory/registry, no `OAuthConnectorBase`
- Filename contract: `RemoteObject.display_name`

### Explicitly Deferred

- Folder picker and sub-folder targeting
- Additional OAuth-backed connectors
- Shared delegated token-management framework beyond the minimal Drive token manager
- Scheduled sync
- Google-native docs export/import support

### Residual Risks

- Google Drive API pagination and rate-limit behavior must be handled conservatively in implementation.
- Refresh-token rotation behavior varies by provider response; the token-manager persistence path must be tested explicitly.
- The provider-neutral container rename touches existing S3 connector contracts and therefore needs careful migration and regression coverage.
- Reconnect behavior across different Google accounts must be implemented exactly as locked here or stale Drive object memory may contaminate future sync runs.

## Notes for Engineer

- Keep this workstream additive on top of the existing connector foundation; do not redesign sync orchestration beyond introducing the factory and `display_name` support required here.
- Do not merge login identity storage and connector token storage.
- Do not implement folder selection, Google-native docs handling, or additional providers in this workstream.
- Treat disconnect as logical deauthorization, not historical erasure.
- Preserve DB-layer user scoping on every new list/read/write path.