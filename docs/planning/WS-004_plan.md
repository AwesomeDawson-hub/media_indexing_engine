# Workstream Plan: WS-004 — Auth & API Hardening

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-004 |
| **Phase** | Phase 1 — MVP |
| **Project** | Media Indexing Engine |
| **Dependencies** | WS-001 (Ingestion Pipeline) — Completed |
| **Estimated Size** | Small |
| **Created** | 2026-03-28 |
| **Status** | Draft — awaiting operator review |

## Objective

Replace the hardcoded dev user with real JWT-based authentication: email/password signup and login, bcrypt password hashing, token-protected routes on all existing endpoints, and a dev/demo mode bypass for local testing. Standardize API error responses across all routes. Add basic rate limiting. All 7 existing endpoints must work unchanged except for requiring an `Authorization` header in production mode.

## Scope

### In Scope

- `password_hash` column added to `users` table
- Password hashing via bcrypt
- User registration endpoint: `POST /api/v1/auth/register`
- User login endpoint: `POST /api/v1/auth/login`
- JWT token generation (HS256, configurable expiry)
- Auth middleware: replace `get_current_user_id()` dependency with JWT validation
- All 7 existing endpoints protected (require valid JWT)
- Dev/demo mode: when `auth.dev_mode: true` in settings, bypass auth and use auto-seeded dev user (existing behavior preserved)
- Standardized error response format across all routes
- Basic rate limiting on auth endpoints (prevent brute force)
- `GET /api/v1/auth/me` — return current user profile
- Configuration additions: `auth` section in settings (secret_key, algorithm, expiry, dev_mode)

### Out of Scope

- OAuth / social login (Phase 2)
- Email verification / password reset (Phase 2)
- Role-based access control (Phase 2)
- API key authentication (Phase 2)
- Session management / refresh tokens (Phase 2 — MVP uses short-lived access tokens only)
- Per-endpoint rate limiting (only auth endpoints for now)
- CORS configuration (WS-005 will add as needed for frontend)

## Constraints

- **JWT library:** `python-jose[cryptography]` (standard FastAPI recommendation) or `PyJWT`
- **Password hashing:** `bcrypt` via `passlib[bcrypt]`
- **Algorithm:** HS256 (per existing `settings.example.yaml`)
- **Token expiry:** Configurable, default 60 minutes (per existing config)
- **Secret key:** Read from `AUTH_SECRET_KEY` environment variable in production. Settings file value used as fallback for dev only.
- **Dev mode:** Must be explicitly enabled via `auth.dev_mode: true`. When enabled, all routes accept requests without `Authorization` header and use the auto-seeded dev user. When disabled (default for prod), every route requires a valid JWT.
- **Backwards compatibility:** All existing test infrastructure must continue to work. Tests override `get_current_user_id` via FastAPI dependency overrides — this pattern must be preserved.

## Governing Decisions

No new ADRs anticipated. The Phase 1 plan specified "JWT-based, simple email/password for V1" — this is a direct implementation of that requirement.

| Constraint Source | Decision | Impact on WS-004 |
|---|---|---|
| Phase 1 plan | JWT-based, simple email/password | Implement registration + login, JWT tokens |
| `settings.example.yaml` | HS256 algorithm, 60-min expiry | Use these as defaults in `AuthConfig` |
| PROJECT_AI_CONTEXT | Never store API keys or credentials in code | Secret key from env var, not hardcoded |
| Phase 1 plan | Dev/demo mode that bypasses auth for local testing | `auth.dev_mode` flag in settings |

## Database Schema Changes

### `users` table — add column

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `password_hash` | VARCHAR(255) | NULLABLE | NULL for dev user and pre-existing users. Required for new registrations. |

**Why nullable?** The existing dev user (auto-seeded in WS-001) has no password. Making the column NOT NULL would break existing DB state. Registration validates that a password is provided — the DB constraint doesn't need to enforce it.

## Auth Flow

### Registration

```
POST /api/v1/auth/register
{
  "email": "user@example.com",
  "password": "securepassword",
  "display_name": "Jane Doe"
}

1. Validate input (email format, password length >= 8)
2. Check email uniqueness in DB
3. Hash password with bcrypt
4. Create User record
5. Generate JWT token
6. Return token + user info
```

**Response (201):**
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "Jane Doe"
  }
}
```

**Error responses:**
- `400` — Invalid input (email format, password too short)
- `409` — Email already registered

### Login

```
POST /api/v1/auth/login
{
  "email": "user@example.com",
  "password": "securepassword"
}

1. Look up user by email
2. Verify password against bcrypt hash
3. Generate JWT token
4. Return token + user info
```

**Response (200):**
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "Jane Doe"
  }
}
```

**Error responses:**
- `401` — Invalid email or password (same message for both — don't leak which is wrong)

### JWT Token Structure

**Payload:**
```json
{
  "sub": "user-uuid",
  "exp": 1711612800
}
```

- `sub` — user ID (UUID string)
- `exp` — expiration timestamp (now + configured minutes)
- Signed with HS256 using the secret key

### Protected Route Flow

```
Request with header: Authorization: Bearer <token>

1. Extract token from Authorization header
2. Decode and verify JWT (signature, expiration)
3. Extract user_id from "sub" claim
4. Verify user exists in DB
5. Set user_id as the current user for the request
```

### Dev Mode Flow

```
When auth.dev_mode is true:

1. If Authorization header is present → validate normally (still works)
2. If Authorization header is missing → return dev user ID
3. Dev user auto-seeded on startup (existing behavior)
```

This means dev mode is a **fallback**, not a complete bypass. If a token is provided, it's still validated. This allows testing auth flows locally while also allowing quick access without tokens.

## Standardized Error Response Format

All error responses across the API will use a consistent structure:

```json
{
  "detail": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE"
}
```

**Error codes:**
- `VALIDATION_ERROR` — Invalid input data
- `AUTH_REQUIRED` — No token provided (and not in dev mode)
- `AUTH_INVALID` — Token is invalid or expired
- `NOT_FOUND` — Resource not found
- `CONFLICT` — Resource conflict (e.g., duplicate email, analysis in progress)
- `RATE_LIMITED` — Too many requests
- `UNSUPPORTED_FORMAT` — Invalid file format
- `FILE_TOO_LARGE` — File exceeds size limit

**Implementation:** A FastAPI exception handler that catches `HTTPException` and wraps the response in the standard format. Existing routes that raise `HTTPException` will automatically use the new format.

## Rate Limiting

Basic in-memory rate limiting on auth endpoints only (registration and login). Prevents brute-force password guessing.

- **Limit:** 5 requests per minute per IP on `/api/v1/auth/login`
- **Limit:** 3 requests per minute per IP on `/api/v1/auth/register`
- **Implementation:** Simple in-memory sliding window counter using a dict. Not distributed — suitable for MVP single-instance deployment.
- **Response when limited:** `429 Too Many Requests` with `error_code: "RATE_LIMITED"` and `Retry-After` header.

**Why not use a library?** Libraries like `slowapi` add external dependencies and configuration for what is, at MVP scale, a simple counter. A 30-line in-memory implementation is sufficient and transparent.

## Configuration Additions

Update `auth` section in settings:

```yaml
auth:
  secret_key: "dev-secret-change-in-production"
  algorithm: "HS256"
  access_token_expire_minutes: 60
  dev_mode: true    # Set to false in production
```

```python
@dataclass
class AuthConfig:
    secret_key: str = "dev-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    dev_mode: bool = True
```

**Production override:** The secret key should be overridden via the `AUTH_SECRET_KEY` environment variable. The `config.py` loader checks `os.environ.get("AUTH_SECRET_KEY")` and uses it if set, falling back to the settings file value.

## Implementation Steps

Each step has a validation checkpoint. Do not proceed to the next step until the current step's validation passes.

### Step 1: Dependencies and Configuration

**What:** Add `python-jose[cryptography]`, `passlib[bcrypt]`, `bcrypt` to project dependencies. Add `AuthConfig` to the settings system with `dev_mode` flag. Update settings files. Wire `AUTH_SECRET_KEY` env var override.

**Files to modify:**
- `pyproject.toml` — add `python-jose[cryptography]`, `passlib[bcrypt]`
- `src/config.py` — add `AuthConfig` dataclass, add to `Settings`, add env var override for secret key
- `config/settings.yaml` — add/update `auth` section with `dev_mode: true`
- `config/settings.example.yaml` — update `auth` section with `dev_mode` field

**Validation:**
- [ ] `pip install` succeeds with new dependencies
- [ ] `from jose import jwt` works
- [ ] `from passlib.context import CryptContext` works
- [ ] `settings.auth.dev_mode` returns `True` in dev config
- [ ] `settings.auth.secret_key` returns the configured value
- [ ] `AUTH_SECRET_KEY` env var overrides settings file value when set

### Step 2: Password Hashing Module

**What:** Create the password hashing utility using bcrypt via passlib.

**Files to create:**
- `src/auth/__init__.py`
- `src/auth/passwords.py`:
  - `hash_password(plain: str) → str` — returns bcrypt hash
  - `verify_password(plain: str, hashed: str) → bool` — constant-time comparison

**Validation:**
- [ ] `hash_password("test123")` returns a bcrypt hash string (starts with `$2b$`)
- [ ] `verify_password("test123", hash)` returns `True`
- [ ] `verify_password("wrong", hash)` returns `False`
- [ ] Hashing the same password twice produces different hashes (salt varies)

### Step 3: User Model Update

**What:** Add `password_hash` column to the `User` model.

**Files to modify:**
- `src/models.py` — add `password_hash: Mapped[str | None]` to `User`

**Validation:**
- [ ] Table creation succeeds with new column
- [ ] Existing dev user seed works (password_hash is NULL)
- [ ] New user can be created with password_hash set
- [ ] Existing tests still pass (no breakage from nullable column)

### Step 4: JWT Token Module

**What:** Create the JWT token creation and validation module.

**Files to create:**
- `src/auth/tokens.py`:
  - `create_access_token(user_id: str) → str` — creates signed JWT with sub and exp claims
  - `decode_access_token(token: str) → str` — validates and returns user_id, raises on invalid/expired
  - Uses `settings.auth.secret_key`, `settings.auth.algorithm`, `settings.auth.access_token_expire_minutes`

**Validation:**
- [ ] `create_access_token("user-123")` returns a JWT string
- [ ] `decode_access_token(token)` returns `"user-123"`
- [ ] Expired token raises an appropriate error
- [ ] Tampered token raises an appropriate error
- [ ] Token with missing `sub` claim raises an appropriate error

### Step 5: Auth Dependency (Replace Hardcoded User)

**What:** Replace `get_current_user_id()` in `dependencies.py` with a real auth dependency that extracts the user from a JWT token, with dev mode fallback.

**Files to modify:**
- `src/api/dependencies.py`:
  - `get_current_user_id(authorization: str | None = Header(None), db: AsyncSession)`:
    1. If token present → decode JWT → verify user exists in DB → return user_id
    2. If token missing and `settings.auth.dev_mode` → return `DEV_USER_ID`
    3. If token missing and not dev mode → raise 401
  - Keep `DEV_USER_ID` constant for dev mode and test compatibility

**Validation:**
- [ ] With valid JWT: returns correct user_id
- [ ] With invalid JWT: returns 401
- [ ] With expired JWT: returns 401
- [ ] Without token + dev_mode=true: returns dev user ID (backwards compatible)
- [ ] Without token + dev_mode=false: returns 401
- [ ] All existing tests still pass (they override `get_current_user_id`)

### Step 6: Registration and Login Endpoints

**What:** Create the auth API endpoints for user registration and login.

**Files to create:**
- `src/api/routes/auth.py`:
  - `POST /api/v1/auth/register` — validate input, check email uniqueness, hash password, create user, return JWT
  - `POST /api/v1/auth/login` — verify credentials, return JWT
  - `GET /api/v1/auth/me` — return current user profile (requires auth)
- `src/api/schemas.py` — add `RegisterRequest`, `LoginRequest`, `AuthResponse`, `UserProfileResponse`
- `src/api/app.py` — register auth router

**Validation:**
- [ ] Register new user → 201, JWT token returned, user in DB with bcrypt hash
- [ ] Register duplicate email → 409
- [ ] Register with short password (< 8 chars) → 400
- [ ] Login with valid credentials → 200, JWT token returned
- [ ] Login with wrong password → 401 (generic "invalid credentials" message)
- [ ] Login with non-existent email → 401 (same generic message)
- [ ] `GET /me` with valid token → 200, user profile
- [ ] `GET /me` without token (dev mode off) → 401

### Step 7: Standardized Error Handling

**What:** Add a global exception handler that wraps all error responses in a consistent format with `detail` and `error_code` fields.

**Files to create/modify:**
- `src/api/error_handlers.py`:
  - `ErrorResponse` Pydantic model
  - FastAPI exception handler for `HTTPException`
  - FastAPI exception handler for `RequestValidationError`
  - Error code mapping from status codes
- `src/api/app.py` — register exception handlers

**Update existing routes:** Where routes raise `HTTPException`, add the `error_code` to the `detail` dict or use a custom exception class that carries both message and code.

**Validation:**
- [ ] Upload invalid file → 400 with `{"detail": "...", "error_code": "UNSUPPORTED_FORMAT"}`
- [ ] Missing auth → 401 with `{"detail": "...", "error_code": "AUTH_REQUIRED"}`
- [ ] Invalid token → 401 with `{"detail": "...", "error_code": "AUTH_INVALID"}`
- [ ] Media not found → 404 with `{"detail": "...", "error_code": "NOT_FOUND"}`
- [ ] Duplicate email → 409 with `{"detail": "...", "error_code": "CONFLICT"}`
- [ ] Validation error (bad request body) → 422 with `{"detail": "...", "error_code": "VALIDATION_ERROR"}`

### Step 8: Rate Limiting on Auth Endpoints

**What:** Add basic in-memory rate limiting to registration and login endpoints.

**Files to create:**
- `src/api/rate_limit.py`:
  - `RateLimiter` class — sliding window counter keyed by IP address
  - `rate_limit(max_requests, window_seconds)` — FastAPI dependency that checks the limit
  - Raises 429 with `Retry-After` header when exceeded

**Files to modify:**
- `src/api/routes/auth.py` — add `RateLimiter` dependency to register and login endpoints

**Validation:**
- [ ] Login 5 times in 1 minute → all succeed
- [ ] 6th login attempt within 1 minute → 429 with `Retry-After` header
- [ ] After waiting, requests succeed again
- [ ] Rate limit is per-IP (different IPs have independent counters)
- [ ] Registration limited to 3 per minute

### Step 9: Integration Testing

**What:** End-to-end tests for auth flows and protected routes.

**Files to create:**
- `tests/test_auth.py` — registration, login, protected routes, dev mode, error format

**Test cases:**
- [ ] Register → 201, valid JWT in response
- [ ] Register duplicate → 409
- [ ] Register invalid input (short password, bad email) → 400
- [ ] Login valid → 200, valid JWT
- [ ] Login invalid → 401 (generic message)
- [ ] Use JWT to access upload endpoint → 201
- [ ] Use JWT to access media list → 200
- [ ] Use JWT to access search → 200
- [ ] Access protected endpoint without token (dev mode off) → 401
- [ ] Access with expired token → 401
- [ ] Dev mode: access without token → succeeds (falls back to dev user)
- [ ] Error responses use standardized format (detail + error_code)
- [ ] All 28 existing tests still pass

### Step 10: Dev Mode Validation and Startup Update

**What:** Ensure dev mode works correctly end-to-end. Update the app lifespan to conditionally seed the dev user only when `dev_mode` is true. Add a startup log warning when dev mode is active.

**Files to modify:**
- `src/api/app.py` — conditional dev user seed, startup warning log

**Validation:**
- [ ] With `dev_mode: true`: dev user seeded, no-auth requests work
- [ ] With `dev_mode: false`: dev user NOT seeded, all requests require JWT
- [ ] Startup log clearly indicates when dev mode is active
- [ ] Switching `dev_mode` in settings correctly changes behavior

### Step 11: PROJECT_MAP and Documentation Update

**What:** Update `PROJECT_MAP.md` with the new auth module and updated API module. Update the Data Model table for the `users` table change.

**Files to modify:**
- `docs/PROJECT_MAP.md`:
  - Add `src/auth/` module section
  - Update `src/api/` section with auth routes and error handlers
  - Update Data Model table for `users` (auth fields added)
  - Update `dependencies.py` description (JWT auth replaces hardcoded user)

**Validation:**
- [ ] `src/auth/` section lists all files with responsibilities
- [ ] API section reflects new routes and error handlers
- [ ] Data Model table updated for users table
- [ ] No stale references to "hardcoded dev user" as the primary auth mechanism

## Module Dependency Graph

```
src/config.py                         ← AuthConfig added (Step 1)
src/auth/
  passwords.py                        ← bcrypt hash/verify (Step 2)
  tokens.py                           ← JWT create/decode (Step 4)
src/models.py                         ← password_hash column (Step 3)
src/api/
  dependencies.py                     ← JWT auth dependency with dev mode fallback (Step 5)
  error_handlers.py                   ← standardized error responses (Step 7)
  rate_limit.py                       ← in-memory sliding window limiter (Step 8)
  schemas.py                          ← RegisterRequest, LoginRequest, AuthResponse, UserProfileResponse (Step 6)
  routes/auth.py                      ← register, login, me endpoints (Step 6)
  app.py                              ← auth router, error handlers, conditional dev seed (Step 6, 7, 10)
```

**Dependency flow within auth:**
```
routes/auth.py
  ├── auth/passwords.py (hash, verify)
  ├── auth/tokens.py (create JWT)
  ├── models.py (User ORM)
  └── schemas.py (request/response models)

dependencies.py (get_current_user_id)
  ├── auth/tokens.py (decode JWT)
  ├── models.py (verify user exists)
  └── config.py (dev_mode flag)
```

## Impact on Existing Code

WS-004 modifies shared code. Here is the full impact surface:

| File | Change | Risk |
|---|---|---|
| `src/models.py` | Add `password_hash` column | Low — nullable, backwards compatible |
| `src/api/dependencies.py` | Replace `get_current_user_id()` | Medium — all routes depend on this. Dev mode preserves existing behavior. Tests override via dependency injection. |
| `src/api/app.py` | Add auth router, error handlers, conditional dev seed | Low — additive changes |
| `src/api/schemas.py` | Add auth schemas | Low — additive |
| `config/settings.yaml` | Update auth section | Low — dev_mode defaults to true |
| `tests/conftest.py` | May need minor updates if auth dependency signature changes | Medium — test fixtures override `get_current_user_id`, signature change requires fixture update |

**Critical constraint:** The `get_current_user_id` dependency must maintain the same callable signature that FastAPI dependency overrides expect. Tests use `app.dependency_overrides[deps.get_current_user_id] = override_get_user` — this pattern must continue to work.

## Exit Criteria

All of the following must be true to close WS-004:

- [ ] Users can register with email/password and receive a JWT token
- [ ] Users can login with email/password and receive a JWT token
- [ ] Passwords are stored as bcrypt hashes, never in plaintext
- [ ] All 7 existing endpoints require a valid JWT when `dev_mode` is false
- [ ] Dev mode (`auth.dev_mode: true`) allows access without token using auto-seeded dev user
- [ ] `GET /api/v1/auth/me` returns the current user profile
- [ ] Error responses use standardized format (`detail` + `error_code`)
- [ ] Auth endpoints are rate-limited (5/min login, 3/min register)
- [ ] JWT secret key can be overridden via `AUTH_SECRET_KEY` env var
- [ ] All existing 28 tests still pass
- [ ] New auth integration tests pass
- [ ] No credentials stored in code or config files committed to git
- [ ] No files created inside the launcher repo
- [ ] `PROJECT_MAP.md` updated with new modules
- [ ] Closeout checklist completed

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Auth dependency signature change breaks existing tests | Medium | Keep `get_current_user_id` compatible with FastAPI DI override pattern. Test early (Step 5). |
| Dev mode accidentally left on in production | High | Log a loud WARNING at startup when dev mode is active. Document in settings.example.yaml. |
| In-memory rate limiter resets on restart | Low | Acceptable for MVP. Distributed limiter (Redis) is a Phase 2 concern. |
| JWT secret key leaked in config file | Medium | Use env var override for production. Default config value is clearly marked "change in production". |
| bcrypt version compatibility | Low | Pin `passlib[bcrypt]` in pyproject.toml. Well-established, stable library. |

## Notes

- **No refresh tokens in MVP.** Users get a single access token on login. When it expires, they log in again. Refresh token rotation is a Phase 2 enhancement.
- **Dev mode is the default for dev config.** `settings.yaml` ships with `dev_mode: true`. `settings.example.yaml` documents this. Production deployments must set `dev_mode: false` and provide `AUTH_SECRET_KEY`.
- **Rate limiting is auth-only.** General API rate limiting (per-user, per-endpoint) is a Phase 2 concern. WS-004 only rate-limits the endpoints most vulnerable to abuse (login, register).
- **The `password_hash` column is nullable** to preserve compatibility with the existing dev user and any pre-existing DB state. Registration enforces that passwords are provided — the DB schema is permissive, the application logic is strict.
- **Existing tests are unaffected** because they override `get_current_user_id` via FastAPI dependency injection. The override replaces the entire dependency — so even if the real dependency now reads JWTs, tests skip that logic entirely.
