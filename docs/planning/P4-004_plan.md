# P4-004: Admin Console & User Profile Management — Implementation Plan

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P4-004 |
| **Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Status** | In Progress |
| **Started** | 2026-04-01 |
| **Dependencies** | P4-002 complete, P4-003 complete |
| **Estimated Size** | L |

---

## Objective

Add a backend-enforced RBAC model with an explicit admin role; an admin-only area for inspecting and operating user accounts; self-service profile management for standard users; a verified email-change flow; password reset/account recovery for beta users; and audit logging for all admin actions that touch identity, status, limits, or billing-relevant metadata.

---

## Context

The current system has a single user role (implicit: all authenticated users are equal). The `User` model has only `id`, `email`, `display_name`, `password_hash`, `plan_name`, `monthly_limit`, `created_at`, and `updated_at`. There is no admin concept, no profile page for users to update their own info, no email-change flow, and no audit trail. The `GET /api/v1/auth/me` endpoint returns minimal `UserProfile` (id, email, display_name only).

This workstream makes account management real.

---

## Changes

1. Add `role` (admin/user) and extended profile fields (`phone`, `company`, `icon_url`) to the `User` model via Alembic migration.
2. Create an `admin_audit_log` table for durable admin action records.
3. Add `get_current_user` dependency that fetches the full `User` object; add `require_admin` dependency that rejects non-admins with 403.
4. Admin API routes (`/api/v1/admin/...`): list users, get user detail, update user fields, disable/enable account, change plan + limit.
5. Extend `GET /api/v1/auth/me` and add `PATCH /api/v1/auth/me` for self-service profile updates (display_name, phone, company, icon_url — not email/plan/role).
6. Verified email-change flow: `POST /api/v1/auth/email-change/request` → store pending token; `POST /api/v1/auth/email-change/confirm` → verify token, apply new email.
7. Password reset: `POST /api/v1/auth/password-reset/request` → store reset token; `POST /api/v1/auth/password-reset/confirm` → verify token, hash and apply new password.
8. Frontend: AdminPage for admin area; ProfilePage for self-service updates; nav conditionally shows "Admin" link for admin users; me-endpoint now returns role + profile fields.
9. Tests: admin auth enforcement, profile CRUD, email-change flow, password-reset flow, audit log creation.

---

## Design Decisions

### Role model
Single string column `role` on `User`. Values: `"user"` (default), `"admin"`. Normalized via `Enum`-like string, not a foreign-key role table — avoids over-engineering for a two-role system.

### Password reset and email-change tokens
Stored in a `pending_tokens` table (id, user_id, token_type, token_hash, new_value, expires_at, used_at). Token type values: `"password_reset"`, `"email_change"`. Tokens are bcrypt-hashed before storage. Expiry: 30 minutes for email-change, 2 hours for password-reset. Tokens are single-use (marked used on first consumption). In dev/beta, token is returned in the API response payload (no email server required). In production, token delivery switches to email (future).

### Admin audit log
`admin_audit_log` table: id, acting_admin_id (FK users), target_user_id (FK users, nullable for non-user-specific actions), action (String 100), detail (Text, JSON string), created_at. Written within the same DB transaction as the change itself.

### Email uniqueness
`users.email` already has a `unique=True` constraint. The PATCH profile endpoint does not allow email mutation (email goes through the verified change flow only). The admin "change email" action goes through the same token-less confirmation path used in the admin console (admin-confirmed = trusted), but still writes an audit record.

### Icon storage
`icon_url` stored as a URL string — no file upload in this workstream. Users (and admins) may provide a URL (e.g., gravatar or external CDN). Future: add icon upload endpoint after S3 storage path is validated for user assets.

### Dev/beta password-reset and email-change
Because beta has no email server, the token is returned directly in the API response (only in dev_mode). In production, the response says "check your email" and the token is not returned. This approach avoids blocking progress on email delivery infrastructure.

---

## Implementation Steps

### Step 1 — Model + Migration

**`src/models.py`** — changes to `User`:
- Add `role: Mapped[str]` — `String(20)`, nullable=False, default `"user"`
- Add `phone: Mapped[str | None]` — `String(50)`, nullable=True
- Add `company: Mapped[str | None]` — `String(200)`, nullable=True
- Add `icon_url: Mapped[str | None]` — `String(500)`, nullable=True
- Add `disabled_at: Mapped[datetime | None]` — `DateTime(timezone=True)`, nullable=True
- Add relationship `admin_audit_logs_acting` → AdminAuditLog (acting)
- Add relationship `admin_audit_logs_target` → AdminAuditLog (target)

**`src/models.py`** — new `AdminAuditLog` class (below `User`):
- `id`: String(36), PK, default _new_uuid
- `acting_admin_id`: String(36), FK users.id, nullable=False
- `target_user_id`: String(36), FK users.id, nullable=True
- `action`: String(100), nullable=False
- `detail`: Text, nullable=True (JSON string)
- `created_at`: DateTime(timezone=True), default _utcnow
- Index: `ix_audit_log_acting_admin_id`

**`src/models.py`** — new `PendingToken` class:
- `id`: String(36), PK, default _new_uuid
- `user_id`: String(36), FK users.id, nullable=False
- `token_type`: String(30), nullable=False (values: `"password_reset"`, `"email_change"`)
- `token_hash`: String(255), nullable=False
- `new_value`: String(500), nullable=True (new email for email_change, null for password_reset)
- `expires_at`: DateTime(timezone=True), nullable=False
- `used_at`: DateTime(timezone=True), nullable=True
- Index: `ix_pending_tokens_user_id`

**`alembic/versions/b2c3d4e5f6a7_admin_profile.py`** — new migration:
- `upgrade`:
  - ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'
  - ALTER TABLE users ADD COLUMN phone VARCHAR(50)
  - ALTER TABLE users ADD COLUMN company VARCHAR(200)
  - ALTER TABLE users ADD COLUMN icon_url VARCHAR(500)
  - ALTER TABLE users ADD COLUMN disabled_at TIMESTAMP WITH TIME ZONE
  - CREATE TABLE admin_audit_log (id, acting_admin_id FK, target_user_id FK nullable, action, detail, created_at) + index
  - CREATE TABLE pending_tokens (id, user_id FK, token_type, token_hash, new_value, expires_at, used_at) + index
- `downgrade`: reverse all of the above

### Step 2 — Dependencies + Schemas

**`src/api/dependencies.py`** — additions:
- `get_current_user(user_id=Depends(get_current_user_id), db=Depends(get_db)) -> User`: fetches the full User row; raises 401 if not found (shouldn't happen, just defensive)
- `require_admin(user=Depends(get_current_user)) -> User`: raises 403 if `user.role != "admin"` or `user.disabled_at is not None`
- Keep `get_current_user_id` unchanged so existing routes are unaffected

**`src/api/schemas.py`** — additions:
- Extend `UserProfile`:
  - Add `role: str`, `phone: str | None`, `company: str | None`, `icon_url: str | None`, `disabled_at: datetime | None`, `plan_name: str`, `monthly_limit: int`
  - `model_config = {"from_attributes": True}`
- `ProfileUpdateRequest`: `display_name: str | None = None` (min 1, max 100), `phone: str | None = None` (max 50), `company: str | None = None` (max 200), `icon_url: str | None = None` (max 500)
- `AdminUserSummary`: id, email, display_name, role, phone, company, icon_url, plan_name, monthly_limit, disabled_at, created_at (from_attributes)
- `AdminUserDetailResponse`: all AdminUserSummary fields + `quota_this_month: int` (consumed this calendar month)
- `AdminUpdateUserRequest`: `email: str | None`, `display_name: str | None`, `phone: str | None`, `company: str | None`, `icon_url: str | None`, `plan_name: str | None`, `monthly_limit: int | None` (ge=0), `role: str | None` (must be "user" or "admin"), `disabled: bool | None`
- `AuditLogEntry`: id, action, detail, target_user_id, created_at
- `EmailChangeRequest`: `new_email: str`
- `EmailChangeConfirmRequest`: `token: str`
- `PasswordResetRequest`: `email: str`
- `PasswordResetConfirmRequest`: `token: str`, `new_password: str` (min 8)

### Step 3 — Admin Routes

**`src/api/routes/admin.py`** — new file:
- All routes use `router = APIRouter(prefix="/api/v1/admin", tags=["admin"])` and `require_admin` dependency on the router
- `GET /users` — list all users (paginated: `page=1`, `per_page=50`, `search` optional ilike on email/display_name), returns `list[AdminUserSummary]` with total
- `GET /users/{user_id}` — full user detail including quota consumed this month (join quota_events WHERE period_month = current YYYY-MM and event_type='consumed')
- `PATCH /users/{user_id}` — update allowed fields from `AdminUpdateUserRequest`; for each changed field, write one audit log entry; email changes go through the admin-trusted path (direct update, no token); setting `disabled=true` sets `disabled_at=now()`, `disabled=false` clears it
- `GET /audit-log` — recent admin audit log (paginated, optional `target_user_id` filter)

Admin helper `_write_audit(db, acting_admin_id, target_user_id, action, detail_dict)` — inserts `AdminAuditLog` row. Called by PATCH handler within the same session before commit.

### Step 4 — Auth Route Extensions

**`src/api/routes/auth.py`** — changes:
- `GET /api/v1/auth/me` — update to return expanded `UserProfile` (role, phone, company, icon_url, disabled_at, plan_name, monthly_limit). Raise 403 if `user.disabled_at is not None`.
- `PATCH /api/v1/auth/me` — new endpoint; accepts `ProfileUpdateRequest`; validates non-empty display_name if provided; updates only allowed fields; returns updated `UserProfile`
- `POST /api/v1/auth/email-change/request` — requires auth; validates new_email format + uniqueness; generates secure 32-byte random token; hashes with bcrypt; stores `PendingToken(type="email_change", new_value=new_email, expires_at=now+30min)`; in dev_mode returns `{"token": <plaintext>}`, otherwise `{"message": "Check your email"}`
- `POST /api/v1/auth/email-change/confirm` — requires auth; looks up non-expired, unused `PendingToken` for this user where type="email_change"; bcrypt-verifies token; re-checks new_email uniqueness; updates user.email; marks token used; returns updated `UserProfile`
- `POST /api/v1/auth/password-reset/request` — no auth; accepts `{"email": "..."}"`; looks up user by email; always returns 200 with generic message (no enumeration); if user found: generates token, hashes, stores `PendingToken(type="password_reset", expires_at=now+2h)`; in dev_mode returns token in response body
- `POST /api/v1/auth/password-reset/confirm` — no auth; looks up the most recent non-expired, unused password_reset token that bcrypt-matches the submitted token across the users matching the email in the body (or add `user_id` to the confirm request to avoid full-table scan); applies new password hash; marks token used; returns `{"message": "Password updated"}`

### Step 5 — Login: reject disabled users

**`src/api/routes/auth.py`** — `login` endpoint:
- After successful password verify, check `user.disabled_at is not None` → raise HTTP 403 `{"error_code": "account_disabled", "message": "Your account has been disabled. Contact support."}`
- Do NOT return 401 (which would hint wrong password) — use 403 so it's distinguishable

### Step 6 — Register account: ensure lowercase email

**`src/api/routes/auth.py`** — `register` endpoint:
- Normalise `body.email.lower().strip()` before uniqueness check and insert. This makes the existing `unique` constraint case-insensitive by convention.

### Step 7 — Frontend: Profile Page

**`frontend/src/pages/ProfilePage.tsx`** — new file:
- Fetches `GET /api/v1/auth/me` on mount
- Shows current values in a form: display_name, phone, company, icon_url, email (read-only with "Change email" link/button)
- "Save Changes" button → `PATCH /api/v1/auth/me`
- "Change Email" section: input for new email + "Request Change" button → `POST /api/v1/auth/email-change/request`; in dev mode the response contains the token; show a "Confirm" form that accepts the token → `POST /api/v1/auth/email-change/confirm`
- "Change Password" section: new password input + confirm + submit → `POST /api/v1/auth/password-reset/request` (populates via logged-in user's email); in dev mode show confirm form inline
- Show plan_name and monthly_limit as read-only (plan is managed by admin/billing)

**`frontend/src/types/api.ts`** — extend `UserProfile`:
- Add `role`, `phone`, `company`, `icon_url`, `disabled_at`, `plan_name`, `monthly_limit`

**`frontend/src/api/client.ts`** — additions:
- `updateProfile(data: ProfileUpdateRequest): Promise<UserProfile>`
- `requestEmailChange(new_email: string): Promise<{token?: string; message: string}>`
- `confirmEmailChange(token: string): Promise<UserProfile>`
- `requestPasswordReset(email: string): Promise<{token?: string; message: string}>`
- `confirmPasswordReset(token: string, new_password: string): Promise<{message: string}>`
- Admin methods: `listAdminUsers(page, per_page, search): Promise<...>`, `getAdminUser(id): Promise<...>`, `updateAdminUser(id, data): Promise<...>`, `getAuditLog(page, target_user_id?): Promise<...>`

**`frontend/src/App.tsx`** — add `/profile` route → `ProfilePage`

**`frontend/src/components/Layout.tsx`** — add "Profile" nav link; conditionally add "Admin" nav link if `user.role === "admin"`

### Step 8 — Frontend: Admin Page

**`frontend/src/pages/AdminPage.tsx`** — new file:
- Route: `/admin`; if current user is not admin → shows a plain "Access denied" message (no redirect leak)
- Users tab: paginated table of all users with search box; columns: email, display_name, role, plan_name, monthly_limit, disabled (badge), created_at, "Edit" button
- Edit user modal/panel: inline form with all `AdminUpdateUserRequest` fields; "Save" → `PATCH /api/v1/admin/users/{id}`
- Audit Log tab: paginated log entries; optional user_id filter

### Step 9 — Tests

**`tests/test_admin.py`** — new test file (integration):
- `test_admin_list_users` — admin can list all users
- `test_admin_forbidden_non_admin` — non-admin gets 403 on every admin route
- `test_admin_update_user_fields` — admin PATCH changes display_name, plan_name, monthly_limit; audit log row written
- `test_admin_disable_enable_account` — disabled=true sets disabled_at; login attempt by disabled user returns 403
- `test_admin_change_user_email` — admin email change updates user.email and writes audit
- `test_admin_audit_log_list` — GET /admin/audit-log returns entries in reverse chronological order

**`tests/test_profile.py`** — new test file (integration):
- `test_get_me_returns_extended_profile` — /auth/me now returns role, plan_name, monthly_limit etc.
- `test_patch_me_updates_allowed_fields` — update display_name, phone, company, icon_url
- `test_patch_me_cannot_change_email` — email field ignored in PATCH /me
- `test_email_change_flow` — request → confirm → new email visible in /me
- `test_email_change_token_expired` — expired token rejected
- `test_email_change_token_reuse` — used token rejected
- `test_email_change_conflict` — new_email already taken → 409
- `test_password_reset_flow` — request → confirm → login with new password
- `test_password_reset_wrong_token` — wrong token rejected
- `test_disabled_user_cannot_login` — 403 after admin disables

---

## Out of Scope

- Email delivery infrastructure (SMTP/SendGrid); tokens are returned in response in dev_mode
- Icon file upload — icon_url is a URL string only
- Multi-factor authentication
- OAuth/SSO login
- Session invalidation when account is disabled mid-session (deferred: current JWT tokens remain valid until expiry; admin disable blocks future logins only)

---

## Exit Criteria

- Non-admin users never see admin UI/routes.
- Non-admin users cannot access admin APIs even by direct request (403 returned).
- Admin can inspect and update user operational fields.
- Standard users can update their own profile info (display_name, phone, company, icon_url).
- Email uniqueness is guaranteed by DB constraint; email changes require the verified flow.
- Password reset/account recovery works for beta users (token returned in dev_mode).
- Admin actions are audit logged (same-transaction write to admin_audit_log).
- Disabled users cannot log in.
- All tests pass (target: 115 existing + ~16 new = ~131 total).

---

## Validation Requirements

- Backend tests: admin auth enforcement, profile CRUD, email-change flow (happy + expired + reused + conflict), password-reset flow, disabled-user login rejection, audit log creation.
- Frontend build passes (TypeScript clean).
- Manual local smoke: admin login → admin area → edit a user → check audit log; normal user → profile page → update fields → change email (dev token confirm).
- Manual AWS smoke: same flows using at least one admin and one non-admin account after deploy.
- Alembic migration runs cleanly against local DB and AWS DB (backup AWS DB before migrating).

---

## AWS Deploy Notes

- This workstream requires an Alembic migration (`b2c3d4e5f6a7`).
- **Before AWS deploy:** take a DB backup with `docker exec media_indexing_engine-postgres-1 pg_dump -U media media_indexing > backup_pre_p4004.sql`
- After pull + rebuild, run migration via `docker exec media_indexing_engine-backend-1 alembic upgrade head` (or it runs automatically at startup in production mode).
- To make the dev user an admin on AWS: `docker exec -i media_indexing_engine-postgres-1 psql -U media media_indexing -c "UPDATE users SET role='admin' WHERE id='00000000-0000-0000-0000-000000000001';"`
