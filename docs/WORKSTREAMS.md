# Workstreams

This document tracks all work items for the Media Indexing Engine through their lifecycle. It is the **single source of truth** for what work is planned, in progress, and completed.

## How Workstreams Move Between Sections

### Planned → In Progress
- Operator approves the workstream to start
- A plan exists (created from phase plan or equivalent)
- `CURRENT_STATE.md` is updated to reflect the active workstream

### In Progress → Completed
- All implementation work is done
- Validation confirms the work meets its objectives
- Closeout checklist has been followed
- A summary is written to `IMPLEMENTATION_STATUS.md`
- `CURRENT_STATE.md` is updated to clear the active workstream

### Cancellation
- Operator may cancel a workstream at any stage
- Cancelled workstreams move to Completed with status "Cancelled" and a reason
- All document updates still apply (state must remain consistent)

---

## Planned

_Post-Phase 6 workstreams are being planned incrementally as the beta product expands beyond identity and the initial connector foundation._

_No planned workstreams currently queued._

---

## Future

### Future: Dropbox Connector
- **Objective:** Add Dropbox ingestion on top of the connector foundation.
- **Phase:** Later than Phase 5
- **Status:** Deferred — same connector/OAuth expansion risk as Google Drive.

### Future: Local Watched Folder Connector
- **Objective:** Support automatic ingestion from a user's local filesystem.
- **Phase:** Later than Phase 5
- **Status:** Deferred — requires an agent or bridge component not present in the current hosted architecture.

---

## In Progress

_No workstreams currently in progress._

---

## Completed (Phase 7)

### P7-003: Navigation & UX Redesign (Add Media Hub)
- **Objective:** Eliminate Source management friction from user-facing flows. Introduce `/add-media` as the single ingestion entry point. Rename Sources → Connections. Enable Google Drive OAuth without a pre-existing Source.
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Status:** Completed — 2026-04-05
- **Size:** Medium
- **Architect review:** Complete — approved 2026-04-05
- **Plan:** `docs/planning/ARCH-001-navigation-ux-redesign.md`
- **Sub-workstreams:**
  - WS-01: Silent upload source — auto-create hidden `__uploads__` source; remove source picker from UploadPage ✅
  - WS-05: Rename Sources → Connections in nav + page ✅
  - WS-03: `POST /api/v1/connectors/google-drive/quick-connect` endpoint ✅
  - WS-02: New `AddMediaPage.tsx` at `/add-media`; retire `/upload` in nav ✅
  - WS-04: OAuth callback redirect `/sources` → `/add-media` ✅
  - WS-06: Connections page cleanup (hide system sources, add "+ Add connection" link) ✅
- **Summary:** `IMPLEMENTATION_STATUS.md` — P7-003 entry

### P7-002: Google Drive Connector (Root-Only)
- **Objective:** Add the first OAuth-backed connector on top of the existing connector foundation so users can connect `My Drive` and manually sync supported image files through the current ingestion pipeline.
- **Phase:** Phase 7 — Post-Phase 6 User-Value Features
- **Status:** Completed — 2026-04-05
- **Size:** Large
- **Architect review:** Complete — approved for implementation
- **Plan:** `docs/planning/P7-002_plan.md`
- **Summary:** `IMPLEMENTATION_STATUS.md` — P7-002 entry

---


## Post-Phase 4 Improvements (Applied 2026-04-02)

_These improvements were applied directly without formal workstreams, after P4-006 closeout. Commits: `f7f6336` through `f6ea7dc`._

- **Mobile swipe navigation (MediaDetailPage):** Touch swipe left/right to navigate prev/next media item. Full-page swipe zone, viewport-fixed arrow buttons for desktop. Swipe up/down destructive actions (delete/download) were prototyped then removed after user feedback — left/right nav retained. Keyboard arrow keys also supported. Commits: `f7f6336`, `2f44bd3`, `b6d9336`, `6ff34c8`, `35757a5`. AWS deployed. _(Original scope from Planned section delivered in reduced form — swipe-up/down dropped.)_
- **Case-insensitive email uniqueness fix:** Auth issue where `Beta@Test.com` and `beta@test.com` were treated as different accounts. Alembic migration adds `LOWER(email)` functional index on `users` table; all existing emails normalized to lowercase. Commit: `3c3ace3`. AWS deployed.
- **Performance: multi-layer image and API caching:** (1) Module-level `blobCache: Map<string, string>` in `useAuthImage.ts` — blob URLs persist across component unmounts, avoiding repeat fetches. `clearAuthImageCache()` revokes all blobs on logout. `prefetchAuthImage(url)` fires background fetch. (2) 60s in-memory `_apiCache` in `client.ts` for `getMedia` and `getAnalysis` (terminal states only — polling still works). `invalidateMediaCache(id)` wired into `reanalyze`/`deleteBatch`. `clearApiCache()` called on logout in `AuthContext.tsx`. (3) `MediaDetailPage.tsx` prefetches neighbor image URLs via `useEffect([prevId, nextId])`. Commit: `977fafa`. AWS deployed.
- **Password reset email infrastructure:** `src/email_service.py` created — boto3 SES, `send_password_reset(to, token)`, graceful no-op when `EMAIL_FROM` is unset, HTML + plain text, errors logged but not raised. `EmailConfig` added to `src/config.py` with env overrides (`EMAIL_FROM`, `EMAIL_AWS_REGION`). `src/api/routes/auth.py` wired to call `send_password_reset` after token creation when not in dev_mode. Frontend: `ForgotPasswordPage.tsx` (email form → API call → confirmation message), `ResetPasswordPage.tsx` (reads `?token=` param, validates passwords, redirects to `/login` on success), `/forgot-password` and `/reset-password` routes added to `App.tsx` as public routes, "Forgot your password?" link + post-reset success banner added to `LoginPage.tsx`. `requestPasswordReset` and `confirmPasswordReset` API functions already existed in `client.ts`. Commit: `f6ea7dc`. AWS deployed.
- **AWS SES domain setup:** `noreply@vyzindex.com` identity configured in SES. DNS records added to Route 53: 3 CNAME (DKIM), 1 MX (mail.vyzindex.com), 2 TXT (SPF + DMARC). Production access request submitted; awaiting AWS approval. Email service will activate once `EMAIL_FROM=noreply@vyzindex.com` is added to server `.env`.
- **Admin role granted to beta test accounts:** `beta@test.com`, `smoketest@test.com`, and the `+dup` variant all set to `role='admin'` via direct psql UPDATE. 3 rows updated.
- **Gallery empty-state bug fixed:** After bulk-deleting all items on the current page, the gallery now re-fetches from page 1 when remaining items exist (was showing empty state). Both browse mode and search mode `onDeleteSuccess` handlers updated in `GalleryPage.tsx`. Commit: `04333ce`. AWS deployed.

---

## Post-Phase 3 Bug Fixes (Applied 2026-03-29, commit fd5013e)

_These production bug fixes were applied directly without a formal workstream, after Phase 3 closeout:_
- **nginx upload limit:** `frontend/nginx.conf` — `client_max_body_size` raised from 1M (default) to 50M. Files >1MB were returning HTTP 413.
- **Search security fix (defense-in-depth):** `src/search/search_service.py` — `MediaItem.user_id == user_id` added to DB WHERE clauses in `search_media()`. ChromaDB already filtered by `user_id`; DB now enforces it independently at the read path.
- **Search sort after login:** `frontend/src/pages/GalleryPage.tsx` — `handleSubmit` now calls `doSearch()` directly (not relying solely on URL `useEffect`), tracks `lastSubmittedQuery` ref to prevent double-fire, resets `sort_by` to relevance when switching browse→search. First search after login now correctly returns relevance-ranked results.

---

## Post-Phase 1 Improvements (Applied 2026-03-28)

_These changes were applied directly without a formal workstream, after Phase 1 closeout:_
- Search filters: people, orientation, aspect ratio (7 standard + Other), file type, mood, sort order
- AVIF file support (backend + frontend)
- Image dimensions stored on upload (`width`, `height` columns)
- Upload UX improvements (header buttons, scrollable queue)
- Dark mode UI
- Long filename truncation, authenticated image loading

---

## Completed

### P6-001: Google SSO (Sign in with Google)
- **Objective:** Add Google-based sign-in and registration while preserving existing email+password auth, automatically linking same-email accounts, and keeping the existing JWT contract unchanged.
- **Phase:** Phase 6 — Identity & Access
- **Status:** Completed
- **Started:** 2026-04-04
- **Completed:** 2026-04-04
- **Outcome:** Full Google SSO flow implemented end-to-end. Alembic migration `a3b4c5d6e7f8` adds `oauth_accounts` and `google_completion_records` tables. `GoogleAuthConfig` dataclass added to `config.py` with env overrides (`ENABLE_GOOGLE_SSO`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GOOGLE_FRONTEND_URL`). `authlib>=1.3.0` and `httpx>=0.27.0` added as main dependencies. `src/auth/google_oauth.py`  created: HMAC-SHA256 signed state, nonce generation, OIDC token exchange via httpx, Authlib JWKS validation. `src/api/routes/google_auth.py` created: `GET /api/v1/auth/config`, `GET /api/v1/auth/google/start`, `GET /api/v1/auth/google/callback`, `POST /api/v1/auth/google/exchange`. Account resolution uses provider-link-first lookup with email fallback and disabled/link-conflict error handling. One-time completion records (public `flow_id` in URL + secret `completion_id` in HTTP-only cookie). Frontend: `GoogleAuthCallbackPage.tsx` (reads `flow_id`/`error` from URL, calls exchange, redirects); `LoginPage.tsx` and `RegisterPage.tsx` show Google button when `google_sso_enabled=true`; `AuthContext.tsx` gains `loginWithGoogle`; `App.tsx` adds `/auth/google/callback` as standalone route. 20 new tests all passing.

### P5-003: Connector Sync Foundation & First Connector
- **Objective:** Extend Source Registry into a real connected-ingestion system with sync state, idempotent import behavior, and one production-ready S3-compatible connector.
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Status:** Completed
- **Started:** 2026-04-03
- **Completed:** 2026-04-03
- **Outcome:** Full connector sync foundation. Alembic migration `f6a7b8c9d0e1` adds `connector_status`/`last_synced_at` to `sources`; creates `source_connectors`, `sync_runs`, `source_objects` tables. `ConnectorConfig` with `credentials_key` + `max_objects_per_sync` in config.py (env `CONNECTOR_CREDENTIALS_KEY`). `src/connectors/` package: `secrets.py` (Fernet encrypt/decrypt, fail-closed guard), `base.py` (RemoteObject, ConnectorBase ABC), `s3_connector.py` (S3Connector + factory), `sync_service.py` (trigger_sync, _run_sync, idempotency, overlap prevention, quota reservation, per-object error isolation). 4 new connector API endpoints under `/api/v1/sources/{id}`. Frontend: connector status badge, S3 config form, sync trigger button, sync runs table. 18 new tests all passing. See `IMPLEMENTATION_STATUS.md` for full details.

### P5-002: AI Best-Photo Selection
- **Objective:** Score images inside near-duplicate groups and recommend the strongest candidate so users can curate burst shots faster.
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Status:** Completed
- **Started:** 2026-04-02
- **Completed:** 2026-04-02
- **Outcome:** AI quality scoring for near-duplicate groups. `curation_scores` table (Alembic migration `a1b2c3d4e5f6`). `CurationScore` ORM model + `curation_score` relationship on `MediaItem`. `CurationConfig.enable_ai_scoring` feature gate (default OFF, env `ENABLE_AI_SCORING`). `src/curation/scoring_service.py`: `score_group()`, `load_scores_for_items()`, `find_best_pick()`, `SCORING_SYSTEM_PROMPT`. `POST /api/v1/media/{id}/score-group` endpoint. `GET /api/v1/media/{id}/similar` extended with quality scores + best-pick flags. Frontend: "Find best pick" button, 👑 crown on best pick, quality score badges. 16 new tests. See `IMPLEMENTATION_STATUS.md` for full details.

### P5-001: Near-Duplicate Detection Core
- **Objective:** Detect visually similar images per user, generate near-duplicate groups, and surface those groups in the Gallery without changing the existing exact-dedup upload rules.
- **Phase:** Phase 5 — Smart Curation & Connected Ingestion
- **Status:** Completed
- **Started:** 2026-04-03
- **Completed:** 2026-04-03
- **Outcome:** Perceptual hash (64-bit pHash, `imagehash` library) stored on `media_items`. Upload pipeline hashes new files post-commit (non-fatal). Gallery page shows "N similar" badge when gate ON. `GET /api/v1/media/{id}/similar` returns near-duplicate list. Backfill script for existing items. 16 new tests. Feature gated via `ENABLE_DUPLICATE_DETECTION` (default OFF). See `IMPLEMENTATION_STATUS.md` for full details.

### P4-006: OCR Search Enrichment
- **Objective:** Extract text from images using Tesseract OCR, store alongside AI metadata, and incorporate into semantic search.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Outcome:** `pytesseract>=0.3.10` added to stack; `tesseract-ocr` installed in Dockerfile. `ocr_text` nullable Text column added to `media_metadata` (migration `d5e6f7a8b9c0`). `src/ocr/ocr_service.py` extracts text using `--psm 11 --oem 1` (sparse text mode, best for mixed-content images), upscales small images before OCR, collapses newline fragments to single-line output, and filters garbled texture-noise via word-ratio quality check (discards if <20% of tokens are word-like). OCR runs after AI analysis in the processor; result stored in DB and forwarded to indexing. `build_embedding_text()` and `build_embedding_text_from_db()` include OCR text in semantic search vectors. `MetadataFields` schema returns `ocr_text` in API responses. Frontend displays "Extracted Text (OCR)" in Additional Search Data section (120px capped, scrollable). 11 new tests; **158/158 total tests pass**. Commits: `5dc4837`, `6c2002e`, `fa17515`. AWS deployed.

### P4-005: Billing Groundwork & Commercial Modeling
- **Objective:** Measure image-processing cost, codify plan tiers, and implement Stripe test-mode billing groundwork without enabling live paid launch.
- **Phase:** Phase 4 --- Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Plan:** \docs/planning/P4-005_plan.md- **Outcome:** StripeConfig added to config.py (secret_key, webhook_secret, price IDs, test_mode). User model extended with stripe_customer_id, stripe_subscription_id, billing_status (default: none). StripeEvent table added for webhook idempotency. Alembic migration \c3d4e5f6a7b8\ creates billing columns and stripe_events table. \src/billing/billing_service.py\ implements checkout session creation, portal session creation, webhook signature verification, and apply_subscription_event() with idempotency. Billing routes: GET /api/v1/billing/status, POST /create-checkout-session, POST /create-portal-session, POST /webhook. AdminUserSummary and AdminUpdateUserRequest extended with billing fields; admin PATCH handler supports billing_status override with validation against allowed values. Frontend: BillingPage.tsx (plan comparison, upgrade/manage buttons, session success/cancel URL param handling), Billing nav link in Layout, billing API functions in client.ts, BillingStatus types in api.ts. 12 new tests in test_billing.py; **147/147 total tests pass**. Commit: Ćd5c6\. AWS deployed.

### P4-004: Admin Console & User Profile Management
- **Objective:** Add admin-only user management, backend RBAC, audited admin actions, self-service profile updates, verified email change, and account recovery.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Plan:** `docs/planning/P4-004_plan.md`
- **Outcome:** Full RBAC + admin console + user profile self-service implemented across all steps. Alembic migration `b2c3d4e5f6a7` adds `role`, `phone`, `company`, `icon_url`, `disabled_at` to users plus new `admin_audit_log` and `pending_tokens` tables. `require_admin` dependency enforces admin-only routes. Admin routes: `GET /admin/users` (paginated, searchable), `GET /admin/users/{id}` (detail + quota_this_month), `PATCH /admin/users/{id}` (role/plan/limit/disable/email with audit entry per change), `GET /admin/audit-log`. Auth routes extended: `PATCH /me` self-service, expanded `GET /me` (role/phone/company/plan/limit), verified email-change flow (bcrypt-hashed PendingToken, 30-min expiry, dev_mode token return), password-reset flow (no enumeration, 2-hr expiry). Disabled user login returns HTTP 403 `account_disabled`. Email normalized to lowercase on register + login. Frontend: `ProfilePage.tsx` (edit profile, change email, change password), `AdminPage.tsx` (users tab with edit modal, audit log tab with pagination). App routes `/profile` and `/admin` added. Layout nav shows Profile link + conditional Admin link for role=admin users. AuthContext exposes `user.role`. 20 new tests (`test_admin.py` + `test_profile.py`); **135/135 total tests pass**. Commit: `cb3326c`.
- **AWS deploy status:** Complete — migration ran on AWS postgres, dev user seeded as admin. All endpoints validated.

### P4-003: Source Registry & Source-Aware Media
- **Objective:** Persist named sources, associate media with sources, add archive/restore behavior for deleted sources, and establish the connector abstraction for future online sources.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Plan:** `docs/planning/P4-003_plan.md`
- **Outcome:** Full source registry implemented across all 8 steps. Alembic migration `a1b2c3d4e5f6` adds `sources` table (id, user_id FK, name, source_type, archived_at soft-delete, created_at, updated_at) and `source_id` nullable FK on `media_items`. `Source` model with user and media_items relationships. 4 API endpoints: `POST /api/v1/sources` (create, 201), `GET /api/v1/sources` (list, excludes archived by default, `?include_archived=true`), `POST /api/v1/sources/{id}/archive` (soft-delete, idempotent), `POST /api/v1/sources/{id}/restore` (idempotent). `source_id` filter on `GET /api/v1/media`. Upload endpoints accept `source_id: str | None = Form(None)` with ownership validation (404 if not found, 403 if cross-user IDOR protection). Frontend: source selector + inline create-source form on UploadPage; Source dropdown filter in GalleryPage FilterPanel, wired to URL params. 24 new tests in `tests/test_sources.py`; **115/115 total tests pass**. TypeScript clean. Commits: `13e9c69` (Step 1), `003e67d` (Steps 2+3), `a96d81a` (Steps 4+5), `4a3e5b7` (Steps 6+7), `30bb319` (Step 8).

### P4-002: Plans, Quotas & Analysis Confirmation
- **Objective:** Enforce monthly image-processing limits, add quota-aware confirmation on the Sources page, and protect capture date/geo-location from overwrite.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Plan:** `docs/planning/P4-002_plan.md`
- **Started:** 2026-03-31
- **Completed:** 2026-03-31
- **Outcome:** Quota enforcement fully implemented, smoke-tested locally and on AWS beta. Alembic migration `7a8b9c0d1e2f` adds `plan_name`/`monthly_limit` to `users` and creates `quota_events` ledger. `QuotaService` implements reserve/consume/release with `SELECT FOR UPDATE` concurrency. `GET /api/v1/quota/status` endpoint live. Upload and re-analysis routes enforce quota (single: 429+cleanup; batch: per-item error). Processor consumes on success, releases on failure. Frontend modal shows plan, period, selected count, used/limit, available, overwrite note, geo note; confirm button disabled when exhausted. `ApiRequestError` fast-fail on 429. 5 new quota tests; 91/91 total tests pass. TypeScript clean. ADR-013 recorded. Bug fix: batch delete clears quota_events before media_items (FK constraint). Migration ran on AWS postgres; upload→analysis→consumed (1) and delete (with quota_events) validated on AWS beta 2026-03-31. Commits: `c147790`, `6a1d20d`, `5ca5ee6`.

### P4-001: Gallery & Detail UX Continuity
- **Objective:** Keep filters visible, add dimensions filtering, simplify status display, reorganize Media Detail, and preserve Gallery state when returning from details. Source-backed filtering is explicitly deferred to P4-003.
- **Phase:** Phase 4 — Beta Operations & Commercial Foundations
- **Status:** Completed
- **Started:** 2026-03-31
- **Completed:** 2026-03-31
- **Plan:** `docs/planning/P4-001_plan.md`
- **Outcome:** All 6 changes delivered plus 5 smoke-discovered fixes. Filters always visible (toggle removed). Source button removed from Gallery header. Size bucket filter (Small/Medium/Large) wired to backend `min_width`/`max_width`. StatusBadge hides `completed` status. MetadataDisplay split into Metadata + Additional Search Data sections. Back-to-Gallery Link restores full gallery URL state. Smoke fixes: poll terminal-status allowlist; Delete button on Media Detail; Clear Search button in filter panel; btn-danger CSS; sort + filter state both written to URL immediately on every change. All 7 local and 7 AWS smoke flows pass. Final commits: `e8dedcf` (original 6) through `d91975c` (filter persistence).

### P3-004: Production Deployment
- **Objective:** Implement S3-compatible `S3FileStore`, add a health endpoint (`GET /api/v1/health`), validate PostgreSQL end-to-end, and produce a Docker + docker-compose stack for the full system (backend, frontend, ChromaDB, PostgreSQL).
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** `GET /api/v1/health` returns `{"status":"ok","version":"0.1.0"}` with no auth. `S3FileStore` implemented via boto3 in thread executor; `get_file_store()` factory selects backend by `storage.provider` config/env. `StorageConfig` extended with S3 fields; env override chain extended with `DATABASE_URL`, `STORAGE_PROVIDER`, `S3_BUCKET`, `S3_REGION`. `Dockerfile` (backend) and `frontend/Dockerfile` (multi-stage nginx) created. `docker-compose.yml` defines all four services. `.env.example` documents all required env vars. README updated with production deployment guide. 12 unit tests for S3FileStore; **82/82 tests pass**. ADR-009, ADR-010, ADR-011 recorded.

### P3-003: Bulk Operations
- **Objective:** Add bulk re-analysis and bulk delete API endpoints. Implement `LocalFileStore.delete()` and `ChromaDBVectorStore.delete_items()`. Integrate Re-analyze and Delete actions into the Gallery SelectionBar UI.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** `POST /api/v1/media/reanalyze-batch` and `DELETE /api/v1/media/batch` added. `delete_items()` added to `VectorStore` protocol and `ChromaDBVectorStore`. `remove_items()` added to `IndexingService`. `BatchOperationRequest` (1–50 media_ids) and response schemas added. SelectionBar updated with Re-analyze + Delete buttons. GalleryPage passes `onDeleteSuccess` callbacks. 8 new integration tests; 70/70 tests pass.

### P3-002: Database Migrations
- **Objective:** Install Alembic migration framework, generate the initial migration from the current schema, and integrate migration execution into startup so the drop-and-recreate pattern is retired.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Alembic installed and configured with async SQLAlchemy support. `alembic upgrade head` creates the full 4-table schema on a fresh database. Production startup calls `run_migrations()`; dev/test keeps `create_all()`. 62/62 tests pass unaffected. README updated with migration instructions.

### P3-001: UI Polish & API Cleanup
- **Objective:** Five targeted improvements: fix metadata comment prefix; use AI title as download filename for all formats; expose image dimensions throughout stack; merge Library + Search into unified Gallery page; rename "Upload" → "Source" throughout UI.
- **Phase:** Phase 3 — Polish & Production Readiness
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** All 5 changes delivered. `field_mapping.py` prefix removed. `download.py` extended with `_MIME_TO_EXT` dict — AI title used as filename for all formats. `schemas.py`, `types/api.ts`, and `MediaDetailPage.tsx` updated with `width`/`height`. `media.py` rewritten with full filter+sort params and aspect-ratio post-query filtering. New `GalleryPage.tsx` replaces `LibraryPage.tsx` and `SearchPage.tsx`. Nav updated to "Gallery / Source". 62/62 tests pass.

### P2-004: List View + Multi-Select + Batch Download
- **Objective:** Grid/list view toggle on Library and Search pages, checkbox multi-select, batch ZIP download
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Grid/list view toggle on Library and Search pages. List view with per-row checkboxes, "Select all", floating selection bar with "Download Selected" (batch ZIP). View preference persisted in localStorage. 3 new components: ViewToggle, MediaListRow, SelectionBar. API client: `downloadBatch()`.

### P2-003: Frontend Download Button
- **Objective:** Download with metadata button on media detail page; BMP/GIF convert-to-PNG option
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** "Download (with metadata)" button on MediaDetailPage for embeddable formats (JPEG, WebP, PNG, TIFF). BMP/GIF: "Download" button + "Convert to PNG with metadata" button. API client additions: `downloadFile()`, `downloadBatch()`, `convertToPng()`.

### P2-002: Download Endpoints
- **Objective:** Backend download endpoints: single file with metadata embedded, batch ZIP, convert-to-PNG
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** 3 new API endpoints in `src/api/routes/download.py`: `GET /media/{id}/download` (single enriched file), `POST /media/download-batch` (ZIP archive), `POST /media/{id}/convert-png` (BMP/GIF to PNG with metadata). BMP/GIF downloads use AI title as filename. 8 new tests, 62 total pass.

### P2-001: Metadata Embedder Module
- **Objective:** Embed AI-extracted metadata (title, description, tags, etc.) into image file headers at download time
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** 8 new files in `src/enrichment/`: `MetadataEmbedder` dispatcher, EXIF writer (JPEG/WebP/AVIF/TIFF), IPTC writer, PNG XMP writer, AVIF writer, WebP writer, field mapping, XMP builder. Supports JPEG (EXIF+IPTC), WebP (EXIF), AVIF (EXIF), PNG (XMP via iTXt), TIFF (EXIF+IPTC). BMP/GIF pass-through with convert-to-PNG fallback. 16 new tests, 54 total pass.

### P2-005: Search as Nav Tab
- **Objective:** Make Search accessible as a primary nav link rather than only via the search bar
- **Phase:** Phase 2
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Search added as third nav link in the header Layout component. Users can navigate directly to the Search page without a pre-existing query.

### WS-005: Frontend MVP
- **Objective:** Upload UI, library browser, search interface
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** React+TS+Vite SPA with dark mode. Auth pages, drag-drop upload, paginated library with auto-polling, media detail with 13 metadata fields, natural language search with scores. 22+ frontend files, file serving endpoint, CORS. 38 backend tests pass. Manual integration test verified.

### WS-004: Auth & API Hardening
- **Objective:** Authentication middleware, API security, error handling, rate limiting, dev/demo mode
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** JWT auth (register/login/me), bcrypt passwords, dev mode fallback, standardized error responses, rate limiting. 3 new auth endpoints. 38 total tests pass (10 new).

### WS-003: Search & Retrieval
- **Objective:** Embedding generation, vector indexing, natural language query, search API endpoint
- **Phase:** Phase 1
- **Started:** 2026-03-28
- **Completed:** 2026-03-28
- **Status:** Completed
- **Outcome:** Full semantic search pipeline operational. Local sentence-transformer embeddings, ChromaDB vector store, auto-indexing on analysis, user-scoped search with relevance scores. 1 new API endpoint, rebuild script. 28 total tests pass (7 new).

### WS-002: AI Analysis Pipeline
- **Objective:** Vision model integration, metadata extraction, structured output to DB, analysis API endpoints
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** Full AI analysis pipeline operational. Anthropic Claude vision integration with VisionProvider abstraction. MediaMetadata table with 13 ADR-005 fields. Image resize/prep, 3-stage JSON parsing, retry logic. 2 new API endpoints. 21 total tests pass (8 new). Smoke test verified with real API.

### WS-001: Ingestion Pipeline
- **Objective:** File upload, validation, hashing, deduplication, file storage, background task pattern, upload API endpoints
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** Full ingestion pipeline operational. 15 source files, 4 API endpoints, 13 passing integration tests. Implements ADR-001 (SHA256 identity), ADR-003 (normalized entities), ADR-004 (content-addressed storage). Background task pattern ready for WS-002.

### WS-000: Core Foundations
- **Objective:** Prior art extraction from marketing_asset_pipeline, media identity model, metadata schema, storage model, DB schema, project setup, API scaffold
- **Phase:** Phase 1
- **Started:** 2026-03-27
- **Completed:** 2026-03-27
- **Status:** Completed
- **Outcome:** All design deliverables produced and approved. 8 ADRs recorded. Ready for WS-001.

<!-- Entry format:
### WS-XXX: [Workstream Name]
- **Objective:** [What this workstream accomplished]
- **Phase:** [Which roadmap phase this belonged to]
- **Started:** [Date]
- **Completed:** [Date]
- **Status:** Completed | Cancelled
- **Outcome:** [Brief summary — detail lives in IMPLEMENTATION_STATUS.md]
-->
