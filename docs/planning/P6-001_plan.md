# Workstream Plan: P6-001 — Google SSO (Sign in with Google)

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P6-001 |
| **Phase** | Phase 6 — Identity & Access |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 5 complete; operator selected Google SSO as the first Phase 6 workstream |
| **Estimated Size** | Medium |
| **Created** | 2026-04-02 |
| **Status** | Draft revised after audit — awaiting operator review |

## Architect Decision

`P6-001` should be implemented as a **backend-managed Google OAuth2 flow that returns the existing JWT contract unchanged and stores Google identities in a provider-neutral `oauth_accounts` table**.

Reasoning:
- The current app already has a stable backend-issued JWT model; preserving it avoids downstream auth churn.
- Google SSO is high user-facing value and does not require a broader identity-system rewrite if it is implemented as an additive login method.
- A provider-neutral identity table avoids hardcoding Google-specific subject IDs onto `User` and keeps future SSO providers reversible.
- Backend-managed callback handling keeps Google client secrets off the frontend and gives the server full control over anti-CSRF state validation, account linking, and token issuance.

## Objective

Add “Sign in with Google” to the login and register experience while preserving existing email+password auth, automatically linking existing same-email accounts under explicit conflict rules, and continuing to issue the exact same JWT structure (`sub`, `exp`) and `AuthResponse` payload shape that the rest of the application already consumes.

## Scope

### In Scope

- Add Google OAuth2 sign-in and registration flow
- Add “Sign in with Google” entry points to the login and register pages
- Add backend Google OAuth2 start/callback/exchange endpoints
- Auto-link Google logins to existing accounts on verified email match
- Store external OAuth identity records in a provider-neutral relational table
- Keep JWT issuance identical to the existing backend contract
- Add config support for `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
- Add local validation and AWS beta rollout guidance

### Explicit Non-Goals

- No removal or weakening of existing email+password auth
- No replacement of JWT with sessions or external auth middleware
- No social-login expansion beyond Google in this workstream
- No Google Drive or other Google API scopes beyond identity / profile / email
- No user-facing account-link management UI in Phase 6
- No passwordless email magic-link flow
- No admin SSO / org-wide identity provider support
- No change to downstream bearer-token auth, route guards, or JWT decoding logic

## Locked Architectural Decisions

## 1. OAuth2 Library Choice

### Decision

Use **Authlib** for the OAuth2 / OpenID Connect client flow.

### Why

- It is a proven Python OAuth/OpenID library that fits FastAPI/Starlette patterns cleanly.
- It avoids hand-rolling code exchange, nonce/state management, token parsing, and Google discovery handling over raw `httpx`.
- It is lighter-weight and more app-integrated for this use case than adopting Google’s broader client libraries.

### Rejected

- Manual `httpx` flow: rejected because it recreates security-sensitive OAuth code by hand.
- Google’s own client library: rejected because it is more Google-specific than needed and does not improve the rest of the backend integration enough to justify the tighter coupling.

## 2. Callback Location

### Decision

The OAuth2 callback lives on the **backend**, not in the frontend.

### Required flow

1. Frontend button navigates to `GET /api/v1/auth/google/start`
2. Backend redirects to Google
3. Google returns to backend callback
4. Backend validates state and nonce, exchanges code, validates identity claims, finds or creates the user under the linking rules below, and prepares a one-time login completion record
5. Backend stores that completion as a short-lived server-side one-time record, sets an opaque completion cookie in the browser, and redirects the browser to a frontend callback route such as `/auth/google/callback?flow_id=...`
6. Frontend callback page calls a backend exchange endpoint with the non-secret `flow_id`, and the backend returns the standard `AuthResponse` only if the `flow_id` and completion cookie match a fresh unconsumed record

### Why

- Backend callback handling keeps `GOOGLE_CLIENT_SECRET` server-side only.
- It centralizes account linking and identity validation where the database is available.
- It avoids exposing the final JWT in query parameters.

### Locked completion handoff model

- The backend callback must create a **DB-backed one-time completion record** with a random opaque completion ID, a separate non-secret `flow_id`, the resolved `user_id`, issued/expiry timestamps, and a consumed flag.
- The opaque completion ID must be delivered only in an **HTTP-only, Secure, SameSite=Lax cookie** scoped to the Google auth completion flow.
- The `flow_id` may be included in the frontend redirect URL because it is not a bearer credential; it exists only to correlate the callback page with the completion record already bound to the browser cookie.
- `POST /api/v1/auth/google/exchange` must require both inputs: the completion cookie supplied automatically by the browser and the `flow_id` supplied by the frontend callback page.
- The completion record must expire quickly (target: 5 minutes or less), be **single-use**, be deleted or marked consumed immediately after a successful exchange, and be cleared on explicit failure paths where safe to do so.
- The final JWT must never appear in a URL, cookie, or redirect target; it is returned only in the exchange response body using the existing `AuthResponse` contract.

### Backend/frontend boundary

- Backend owns Google OAuth2 protocol handling.
- Frontend owns only the user entry point and completion page that stores the returned `AuthResponse` exactly like existing login/register flows.

## 3. Anti-CSRF State Parameter

### Decision

Implement request integrity using **both** a signed OAuth `state` value and an OpenID Connect `nonce`, with short-lived HTTP-only cookies and explicit nonce validation during callback processing.

### Required behavior

- Generate a cryptographically random `state` value and a separate cryptographically random OIDC `nonce`.
- Store request-integrity data in short-lived **HTTP-only cookies** with `SameSite=Lax`; production cookies must also set `Secure` and a narrow auth-route path.
- Sign and timestamp the server-managed state context before redirecting to Google.
- Include the signed state as the OAuth `state` parameter and include the nonce in the OIDC authorization request.
- On callback, verify state signature, age, and exact cookie match before any login completion work occurs.
- Validate the OIDC nonce through the Authlib ID-token validation path, and fail the callback if the nonce is missing, mismatched, expired, or already consumed.
- Treat both state and nonce as **single-use** request artifacts: clear their cookies after callback handling and do not permit reuse.
- Return a distinct callback error for invalid nonce / identity-claim binding failure rather than collapsing it into a generic callback error.

### Why

- The current app is JWT-based and does not already depend on server sessions.
- Signed cookies plus explicit OIDC nonce validation are the smallest secure addition that still gives proper request-CSRF and claim-replay protection without introducing a broader session system.

## 4. Account Linking Strategy

### Decision

Use **provider-link-first account resolution with verified-email fallback only when no Google link already exists**.

### Required rules

- First resolve by existing `oauth_accounts` row on `(provider='google', provider_user_id=sub)`.
- If that provider link already exists, authenticate only that linked local user; do not fall back to email matching for that login.
- If the linked local user is disabled, fail the login with the same disabled-account behavior used by password auth.
- Only when no provider link exists may the backend fall back to a normalized verified-email match against `users.email`.
- If the verified email matches an existing active local user with **no** Google link yet, create the `oauth_accounts` link for that user and do not create a duplicate user.
- If the verified email matches a disabled local user, fail login rather than linking or creating a new account.
- If the verified email matches a local user that is already linked to a different Google `sub`, fail with a link-conflict error; Phase 6 must not silently relink ownership.
- If no user exists, create a new user with `password_hash = null` and a display name derived from Google profile claims, then create the `oauth_accounts` row.
- If Google does not provide a verified email, login must fail rather than creating an ambiguous account.
- After the initial link is created, `provider_email` is informational only; later provider-email drift must never transfer or re-key account ownership.

### Why

- The operator explicitly requires no duplicate accounts when email matches.
- Provider-link-first resolution plus verified-email fallback is the safest user-friendly rule and avoids awkward explicit linking UI in the first SSO workstream.

## 5. External Identity Storage Model

### Decision

Store the Google `sub` in a **new `oauth_accounts` table**, not on the `User` model.

### Why

- This keeps the `User` model provider-neutral.
- It creates a clean path for future providers without adding `google_sub`, `github_sub`, etc. columns to `users`.
- It supports multiple providers per user in a normalized way if the product expands later, while still allowing Phase 6 to enforce one Google identity per local user.

### Result

- `User` remains the canonical app account.
- `OAuthAccount` becomes the external identity link table.
- Phase 6 must enforce at most one Google identity per local user via `UNIQUE (user_id, provider)`.

## 6. JWT Contract Preservation

### Decision

Google SSO must call the same JWT issuance helper used by password login and return the same `AuthResponse` structure and downstream auth behavior.

### Required behavior

- Final login completion must issue tokens via `create_access_token(user.id)`.
- JWT payload remains unchanged: `sub`, `exp` only.
- Google completion must return the exact existing `AuthResponse` schema and the same user payload fields already expected by the frontend.
- Disabled-account enforcement must apply identically to Google and password auth.
- `/api/v1/auth/me` and all downstream bearer-token-protected routes must remain unaware of auth origin.
- Downstream middleware, bearer headers, and frontend token storage must not require any special-case SSO handling.
- Google-created accounts remain standard local `User` records and must continue to work with later password-establishment flows without needing JWT contract changes.

## Schema Changes

### New table: `oauth_accounts`

Purpose: provider-neutral external identity links for application users.

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID |
| `user_id` | `VARCHAR(36)` FK → `users.id` | owning local user |
| `provider` | `VARCHAR(50)` | `google` in Phase 6 |
| `provider_user_id` | `VARCHAR(255)` | Google `sub` |
| `provider_email` | `VARCHAR(255)` nullable | Google email claim at link time |
| `provider_email_verified` | `BOOLEAN` | must be true for auto-link/create |
| `created_at` | `TIMESTAMPTZ` | row creation |
| `updated_at` | `TIMESTAMPTZ` | row update |
| `last_login_at` | `TIMESTAMPTZ` nullable | last successful SSO login |

### Required constraints / indexes

- UNIQUE on `(provider, provider_user_id)`
- UNIQUE on `(user_id, provider)`
- Index on `user_id`
- Optional index on `(provider, provider_email)` for support/debugging only; do not use it as the primary identity key

### User model impact

- No Google-specific columns are added to `users`
- `password_hash` already being nullable is sufficient for Google-created accounts

### Alembic migration plan

- `alembic/versions/a1b2c3d4e5f6_google_sso.py`
- `revision = "a1b2c3d4e5f6"`
- `down_revision = "f6a7b8c9d0e1"`

If the repository head changes before implementation starts, Engineer must preserve the schema content but update `down_revision` to the actual current Alembic head.

## Config Changes

### New dataclass

Add a `GoogleAuthConfig` dataclass in `src/config.py`, following the existing `EmailConfig` / `ConnectorConfig` pattern.

### Required fields

| Field | Source | Notes |
|---|---|---|
| `enabled` | `ENABLE_GOOGLE_SSO` env | required rollout gate, default `false` |
| `client_id` | `GOOGLE_CLIENT_ID` env | required for OAuth2 start |
| `client_secret` | `GOOGLE_CLIENT_SECRET` env | backend only |

### Optional defaults

- fixed backend callback path constant
- fixed frontend completion path constant
- helper property that is true only when `ENABLE_GOOGLE_SSO=true` and both Google credentials are present

## Required ADRs

Record the following ADRs in `docs/DECISION_LOG.md`:

1. `ADR-016` — Authlib Is the OAuth2 / OpenID Client Library for Google SSO
2. `ADR-017` — Google OAuth Callback Is Backend-Managed and Returns Existing JWT via Frontend Completion Exchange
3. `ADR-018` — OAuth Anti-CSRF Uses Signed State Cookie Comparison Rather Than Server Session Storage
4. `ADR-019` — Google SSO Auto-Links Accounts by Verified Email Match
5. `ADR-020` — External Provider Identities Live in `oauth_accounts`, Not on `users`

## Implementation Steps

### Step 1: Lock ADRs and Auth Contract

**Goal:** freeze the Google SSO architecture before implementation starts.

**Files:**
- `docs/DECISION_LOG.md`
- `docs/planning/P6-001_plan.md`
- `src/auth/tokens.py`

**Outputs:**
- accepted OAuth library
- accepted callback boundary
- accepted state strategy
- accepted account-linking strategy
- accepted identity storage model

### Step 2: Add Schema Support via Alembic

**Files to create/modify:**
- `alembic/versions/a1b2c3d4e5f6_google_sso.py`
- `src/models.py`

**Expected changes:**
- add `OAuthAccount` ORM model
- add relationships from `User`
- add uniqueness/index constraints described above

### Step 3: Add Google Auth Config and OAuth Service

**Files to create/modify:**
- `src/config.py`
- `src/auth/google_oauth.py` (new)
- optionally one small helper module under `src/auth/`

**Expected behavior:**
- load `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` from env
- load `ENABLE_GOOGLE_SSO` from env and default it to OFF
- expose a backend OAuth client wrapper using Authlib
- validate Google identity claims needed for account linking, including nonce validation

### Step 4: Add Backend Routes

**Files to create/modify:**
- `src/api/routes/auth.py`
- `src/api/schemas.py`
- `src/api/app.py` only if route registration changes are needed

**Preferred route shape:**

1. `GET /api/v1/auth/google/start`
   - generates signed state + nonce cookies and redirects to Google
2. `GET /api/v1/auth/google/callback`
   - validates state and nonce, exchanges code, validates claims, finds/creates/links user under the locked precedence rules, creates one-time completion record + cookie, redirects to frontend callback route with non-secret `flow_id`
3. `POST /api/v1/auth/google/exchange`
   - consumes the one-time completion record and returns the standard `AuthResponse`

**Required rules:**
- if Google SSO is disabled or Google config is absent, Google routes fail clearly and safely without affecting password auth
- exchange must require a fresh unconsumed completion record bound to the browser cookie and matching `flow_id`
- exchange must consume the completion record exactly once and clear the completion cookie after success
- password login/register/reset endpoints remain unchanged in behavior
- final JWT is produced by `create_access_token(user.id)`

### Step 5: Add Frontend Integration

**Files to create/modify:**
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/pages/RegisterPage.tsx`
- `frontend/src/pages/GoogleAuthCallbackPage.tsx` (new)
- `frontend/src/context/AuthContext.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/api.ts`
- `frontend/src/App.tsx`

**Expected behavior:**
- login and register pages show a `Sign in with Google` button only when the rollout gate enables it
- button triggers backend OAuth start route
- frontend callback page completes the exchange and stores the returned `AuthResponse` exactly like login/register do today
- error states are visible and recoverable

### Step 6: Add Tests

**Files to create/modify:**
- `tests/test_auth_google.py` (new)
- existing auth tests if shared coverage makes sense

**Required coverage:**
- Google routes remain disabled when the feature flag is OFF
- missing Google config fails safely
- start route generates state and redirect
- callback rejects bad/missing/expired state
- callback rejects bad/missing/expired nonce
- exchange rejects missing, expired, mismatched, or already-consumed completion handoff state
- callback rejects unverified Google email
- new Google user creates local account with `password_hash = null`
- existing same-email local account is auto-linked, not duplicated
- disabled linked user cannot sign in through Google
- existing `oauth_accounts` link wins over email fallback
- user cannot end up with two Google identities in Phase 6
- repeated login for same Google identity reuses linked account
- JWT returned from Google completion has the same structure as existing auth flow
- email+password login/register/reset continue working unchanged

### Step 7: Closeout Docs

**Files to update at closeout:**
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/WORKSTREAMS.md`
- `docs/CURRENT_STATE.md`
- `docs/PROJECT_HANDOFF.md`
- `docs/PROJECT_MAP.md`

## Acceptance Criteria

- When `ENABLE_GOOGLE_SSO` is enabled, the login page shows a `Sign in with Google` button
- When `ENABLE_GOOGLE_SSO` is enabled, the register page shows a `Sign in with Google` button
- Existing email+password accounts continue to work unchanged
- A Google sign-in can create a new local account when no matching email exists
- A Google sign-in auto-links to an existing local account on verified email match without creating a duplicate user
- Existing provider links are resolved before any email fallback logic runs
- Disabled accounts are blocked identically for Google and password auth
- Google exchange returns the exact existing `AuthResponse` schema and user payload shape
- JWT issued after Google SSO is identical in structure to the existing JWT contract
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are loaded from env via a typed config dataclass pattern
- `ENABLE_GOOGLE_SSO` gates Google UI and routes independently of schema deployment
- Google OAuth callback is backend-managed and does not expose the client secret to the frontend
- Anti-CSRF state and OIDC nonce validation reject invalid callback attempts
- Backend callback to frontend exchange uses a short-lived one-time completion record that is browser-bound, single-use, and quickly expired
- Google identity is stored in `oauth_accounts`, not as a Google-specific column on `users`
- Tests cover linking, duplicate prevention, callback validation, and password-auth regression protection

## Validation Checklist

### Backend / Data Validation

- [ ] Alembic migration applies cleanly to current head
- [ ] `oauth_accounts` uniqueness prevents duplicate provider identities
- [ ] `oauth_accounts` uniqueness also prevents more than one Google identity per user in Phase 6
- [ ] Google config loads from env and fails closed when absent
- [ ] Google feature flag can keep UI/routes dark until rollout approval
- [ ] Callback state validation rejects tampered or expired requests
- [ ] Callback nonce validation rejects replay or identity-claim binding failures
- [ ] One-time completion handoff expires quickly, is single-use, and clears after successful exchange
- [ ] Verified email auto-linking attaches to existing user instead of creating duplicate user
- [ ] Existing provider link lookup runs before verified-email fallback
- [ ] Disabled users cannot authenticate through Google SSO
- [ ] New Google-only accounts can exist with `password_hash = null`
- [ ] Password login/register/reset continue working unchanged
- [ ] Final JWT is created via the existing token helper and retains the same claims contract

### Frontend / UX Validation

- [ ] Login page button starts Google auth flow correctly
- [ ] Register page button starts Google auth flow correctly
- [ ] Frontend completion page stores the returned auth payload the same way as existing login/register
- [ ] Failure path shows actionable error and allows retry or fallback to email/password

### AWS Smoke Validation

- [ ] Google OAuth app configured with local and production callback URLs
- [ ] One existing email/password user can sign in with matching Google email and is linked to the same account
- [ ] One brand-new Google user can create/sign in successfully
- [ ] Disabled-account behavior matches password-login behavior for Google SSO attempts
- [ ] Existing protected routes accept the JWT from Google SSO with no downstream changes

## AWS Rollout and Rollback

### Rollout

1. Back up AWS PostgreSQL before applying the migration.
2. Deploy code and migration with `ENABLE_GOOGLE_SSO=false` so the feature remains dark.
3. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the server environment.
4. Configure Google Console redirect URIs for local and production callback URLs.
5. Smoke-test both new-user and existing-account auto-link flows while the flag remains OFF for general users.
6. Only after smoke validation passes, set `ENABLE_GOOGLE_SSO=true` to expose the Google button and routes.

### Rollback

- If the migration is healthy but the OAuth flow is wrong, set `ENABLE_GOOGLE_SSO=false` first to disable Google UI and routes while leaving schema in place.
- If account linking behaves incorrectly, disable Google SSO immediately rather than risking duplicate accounts.
- If migration is defective, restore the AWS DB backup rather than attempting ad hoc repair.
- Existing email+password auth remains the fallback path and must remain available throughout rollback.

## Risks and Open Questions

### Resolved in this plan

- OAuth library: `Authlib`
- Callback boundary: backend-managed
- Anti-CSRF state: signed state cookie plus OIDC nonce validation
- Account linking: provider-link-first with verified-email fallback under explicit conflict rules
- External identity storage: `oauth_accounts` table
- JWT compatibility: unchanged existing contract
- Rollout gate: mandatory `ENABLE_GOOGLE_SSO` feature flag

### Explicitly Deferred

- Additional identity providers
- Explicit account unlink/link management UI
- Session replacement for JWT auth
- Organization / enterprise SSO
- Passwordless magic links

### Residual Risks

- Google callback URL handling behind reverse proxies must be tested carefully in AWS.
- Auto-linking relies on Google verified email and correct nonce validation; any claim-validation bug could create the wrong account association, so implementation must be conservative.
- UI and backend errors must make it obvious when Google config is missing versus when the user denied consent.

## Notes for Engineer

- Keep Google SSO additive; do not refactor the whole auth system while implementing one provider.
- Preserve the current JWT contract exactly.
- Do not store provider-specific identity directly on `User`.
- Do not put final bearer tokens in query parameters.
- Treat the callback-to-exchange handoff as security-sensitive state, not as a convenience redirect token.
- Do not silently relink a user based on later Google email drift or conflicting existing Google links.