# ARCH-001: Navigation & UX Redesign — Add Media Hub

**Document type:** Architect Design Recommendation  
**Status:** APPROVED — 2026-04-05  
**Author:** Architect  
**Date:** 2026-04-05  
**Phase:** Phase 7  
**Project:** Media Indexing Engine (https://vyzindex.com)

---

## Executive Summary

The current split between the Upload page and the Sources page exposes an internal data-engineering abstraction (`Source`) as a top-level navigation concept. This causes real friction — most obviously, connecting Google Drive requires 4–6 steps across two pages. The fix is not a schema rewrite. The data model is sound. The problem is entirely in the UX layer and one backend contract.

**Recommendation:** Option B — introduce a single "Add Media" entry point that unifies file upload and connector setup, backed by one new additive backend endpoint that creates a Source implicitly as part of initiating Google Drive OAuth. Source management becomes a secondary "Connections" management page, demoted from the primary workflow.

---

## 1. Root Cause Analysis

### The real problem: an internal concept is masquerading as a user concept

A `Source` row is a **data-provenance record** — it exists so the system knows where a `MediaItem` came from and can associate sync history with it. It is an implementation detail of the ingestion pipeline.

The mistake is that `Source` was promoted to a **first-class navigation concept** that users must interact with explicitly, even when it provides them no value. This surfaces in two ways:

**For upload users:** The Upload page today requires the user to either select an existing Source or create a new one before files can be uploaded. From the user's perspective, this is pure friction. They do not care which Source their photos land in — they just want their photos indexed.

**For Google Drive users:** The friction is compounded by a specific backend contract: the OAuth initiation endpoint (`POST /api/v1/sources/{source_id}/connector/google-drive/start`) requires a `source_id` as a URL path parameter. This means a Source must already exist before OAuth can begin. From the user's point of view, they are being asked to create an invisible container for a thing they haven't yet connected. The workflow is:

```
[Upload page] Create a named Source
       ↓
[Navigate to Sources page] Find the new source row
       ↓
[Sources page] Expand the connector panel
       ↓
[Sources page] Click "Connect Google Drive" → redirect to Google
       ↓
[Sources page — OAuth callback] Banner appears: "Google Drive connected. Choose a folder."
       ↓
[Sources page] Choose sync folder and target collection, click Sync
```

That is **6 user interactions across 2 pages** to accomplish something the user thinks of as one action: "Connect my Google Drive."

### Secondary causes

- **Naming:** "Sources" is developer vocabulary. Users do not think "I am adding a source." They think "I am connecting my Google Drive" or "I am uploading photos."
- **Navigation overload:** Five non-utility nav items (Gallery, Upload, Sources, Collections, Billing) are all peer-level, suggesting equal importance. Upload and Sources are not equal to Gallery in terms of access frequency.
- **Post-OAuth landing:** The OAuth callback currently redirects to `/sources?connector=google_drive&...`. This URL is hardcoded in the backend. It assumes the Sources page is always the home for the connector setup flow. This couples the backend routing logic to the frontend page structure.

---

## 2. Proposed Mental Model

### What users should think

| Current (internal term) | Proposed (user-facing term) |
|---|---|
| Source | Connection (for synced connectors) / invisible (for file uploads) |
| SourceConnector | — (never shown) |
| "Upload" page | "Add Media" — with upload as one method |
| "Sources" page | "Connections" — a management/status page, not a workflow entry point |

### The user's conceptual model should be:

```
My Library (Gallery)
└── Everything I've added

Add Media ← single entry point for getting new media in
├── Upload files — drag-drop from computer
├── Connect Google Drive — sync a Drive folder automatically
└── Connect S3 bucket — power user, named connection

My Connections ← secondary management view (not primary nav)
├── "Marketing Drive" — Google Drive · last synced 2h ago
├── "Work S3" — S3 · last synced 1d ago
└── [+ Add connection] → goes to Add Media

Collections ← how I organize media I've already added
```

The key conceptual shift: **"adding media" is one idea with three implementations**. Today it is split into two separate pages with no hierarchy between them.

---

## 3. Navigation Redesign Options

---

### Option A — Minimal (Small effort)

**Premise:** Keep the two-page structure. Eliminate the worst friction points with targeted fixes.

**UI changes:**
- Rename nav item "Sources" → "Connections"
- On the Upload page: make source selection fully optional (auto-assign to a hidden default `uploads` source per user if none selected). Remove the "Create new source" form from the Upload page entirely.
- Add a prominent "Connect Google Drive" button on the Upload page. When clicked, it auto-creates a Source named `My Google Drive` (if one doesn't exist) and immediately initiates OAuth — no separate step required. Redirect returns to `/connections` (renamed Sources page) where the folder-config step is already shown.

**Backend changes:**
- One new endpoint: `POST /api/v1/connectors/google-drive/quick-connect` — creates a Source with a default name and starts OAuth in one call. Returns the OAuth redirect URL. No `source_id` required upfront.
- `_resolve_source_id` in `upload.py` auto-creates or reuses a default upload source if none is passed.

**Trade-offs:**
- ✅ Very low risk — additive backend, minimal frontend changes
- ✅ Google Drive friction drops from 6 steps to 2 (click "Connect Google Drive" on Upload page → OAuth → configure folder on Connections page)
- ⚠️ Upload and Connections are still conceptually separate — the UX is patched, not redesigned
- ⚠️ "Connect Google Drive" living on the Upload page is slightly unintuitive for users who don't think of Drive as uploading
- ⚠️ Rename alone doesn't communicate "this is where Drive syncing lives"

**Effort:** ~3–5 days total (1 backend endpoint + frontend patches)

---

### Option B — Moderate (Medium effort) ← **Recommended**

**Premise:** Introduce a new "Add Media" page as the single ingestion entry point. Resources currently split across Upload and Sources are unified here. The Sources/Connections page becomes a management-only view.

**UI changes:**
- New `/add-media` route and nav item replaces `/upload` in nav (redirect `/upload` → `/add-media`)
- Add Media page has three method panels:
  - **Upload Files** — embeds the current DropZone/FileQueue component. No source selection required.
  - **Connect Google Drive** — single "Connect" button. If already connected, shows connection status + "Sync now" button inline. If not connected, clicking "Connect" starts OAuth immediately (via the new quick-connect endpoint).
  - **Connect S3** — a collapsible form (preserves the named-source + credentials UX that S3 power users need).
- After Google Drive OAuth callback: redirect to `/add-media?connected=google_drive` instead of `/sources`. The Add Media page shows a configuration panel (choose Drive folder + optional target collection). User completes setup on the same page they started from.
- Rename Sources → Connections in nav. Connections page is still accessible, shows status of all active connections, and provides a "Manage" / "Disconnect" / "Sync now" UI. Add an "+ Add connection" button that links to `/add-media`.
- Source creation/selection is hidden from all user-facing flows. Sources are created automatically with system-generated names (or user-chosen names for S3, since S3 naming is meaningful for multi-bucket users).

**Backend changes:**
- New endpoint: `POST /api/v1/connectors/google-drive/quick-connect` — accepts an optional `source_name` (default: `Google Drive — {email}` populated after OAuth). Creates a Source and returns the OAuth redirect URL. The existing callback remains unchanged except for one thing below.
- OAuth callback redirect URL: currently hardcoded to `{frontend_url}/sources`. Change to `{frontend_url}/add-media`. This is a one-line config/code change and not a breaking API contract change (it is a server-side redirect).
- Upload endpoint: make `source_id` truly optional. Auto-resolve to a per-user default upload source (create if not exists, hidden, named `Uploads`).
- No schema changes. No data migration.

**Trade-offs:**
- ✅ Google Drive: 2-step flow (click "Connect Google Drive" → OAuth → configure on same page)
- ✅ Upload: zero source management friction
- ✅ Connections page is retained for power-user management — S3 users unaffected
- ✅ Fully additive — no existing endpoints broken, no schema migration
- ✅ Route change (`/upload` → `/add-media`) has one redirect; 254 existing tests unaffected since they call API routes, not frontend routes
- ⚠️ Medium frontend effort — new page + rerouting + post-OAuth configuration panel
- ⚠️ S3 configuration stays on Add Media page but remains verbose; acceptable since S3 is a power-user path

**Effort:** ~8–12 days total (1 backend endpoint + callback URL change + frontend page + routing)

---

### Option C — Full (Large effort)

**Premise:** Sources become a completely internal concept, invisible at all times. All ingestion is managed through a unified Add Media hub. Sync status and connection health are surfaced in the Gallery sidebar and a Settings page, not a dedicated page.

**UI changes:**
- Sources/Connections page eliminated from nav entirely
- Gallery gets a persistent "Media Sources" sidebar panel showing live sync status
- All ingestion (upload, Drive, S3) flows through Add Media
- Sources are entirely auto-named; users never name them
- S3 management moves into Profile/Settings

**Backend changes:**
- Sources API remains (data model intact), but all CRUD is internal
- New sync status endpoint for the Gallery sidebar

**Trade-offs:**
- ✅ Cleanest user experience — Sources fully disappear from user vocabulary
- ✅ Matches consumer app patterns (Google Photos, Lightroom Cloud)
- ❌ High frontend effort — Gallery layout change, new sidebar, Settings restructuring
- ❌ S3 power users lose a familiar named-connections management page
- ❌ Sync status buried in a sidebar is harder to find when troubleshooting
- ❌ Disproportionate scope for Phase 7 constraints ("MVP-first")
- ❌ Highest risk to the 254-test suite (more surface changed)

**Effort:** ~25–35 days. Out of scope for Phase 7.

---

## 4. Recommended Option

**Option B.**

It solves the identified problem completely without an architectural overhaul. The root cause is two-fold: (a) Google Drive OAuth requires a pre-existing Source, and (b) the ingestion workflow is split across two pages. Option B fixes both with one new endpoint and a new frontend page. Option A patches only (b) partially and leaves the two-page UX intact. Option C solves everything but is too large for Phase 7.

The specific constraint that makes Option B feasible without risk is that the data model does not change. `Source` rows continue to be created — they are just created *implicitly* by the backend rather than *explicitly* by the user. The `Source`, `SourceConnector`, `SyncRun`, `SourceObject`, and `MediaItem` chain can remain exactly as-is. The 254-test suite operates at the API layer and is unaffected by frontend routing changes.

The one backend contract that must change — the OAuth callback redirect URL hardcoded to `/sources` — is a single-line change in `google_drive_connector.py` and carries no data risk.

---

## 5. Implementation Workstreams

The following workstreams are ordered by dependency. WS-01 and WS-05 are independent and can be done in parallel.

---

### WS-01: Silent upload source

| Field | Value |
|---|---|
| **ID** | WS-01 |
| **Name** | Silent upload source |
| **Size** | Small |
| **Dependencies** | None |

**Objective:** Remove the source selection/creation UI from the file upload flow. Users drop files and they go in — no source management required.

**Key changes:**
- **Backend:** Modify `_resolve_source_id()` in `src/api/routes/upload.py` to auto-resolve: if `source_id` is null or absent, look up (or create) a per-user default source named `Uploads` (with a flag indicating it is system-managed, e.g. `is_system=True` column — or simply by name convention if a schema column is unwanted). Mark it hidden from the Connections page.
- **Frontend:** Remove the source dropdown and "Create new source" form from `UploadPage.tsx`. The component reverts to pure file-drop-and-go.
- **Data:** No migration. New sources created for users without an upload source are additive rows.

**Note on `is_system` column:** This can be avoided entirely by using a naming convention (`__uploads__`) and filtering by prefix on the Connections page list query. Avoids any schema migration while still hiding the row from users. Recommended over adding a column.

---

### WS-02: New "Add Media" page

| Field | Value |
|---|---|
| **ID** | WS-02 |
| **Name** | Add Media page |
| **Size** | Medium |
| **Dependencies** | WS-01 (upload section can reuse simplified UploadPage component) |

**Objective:** Create `/add-media` as the single entry point for all ingestion methods, replacing `/upload` in the nav.

**Key changes:**
- **Frontend — new page `AddMediaPage.tsx`:** Three panels:
  1. *Upload Files* — reuses the `DropZone` + `FileQueue` components from current UploadPage. 
  2. *Connect Google Drive* — shows connected status if a Drive connector exists, or a "Connect Google Drive" CTA. Calls the new `POST /api/v1/connectors/google-drive/quick-connect` endpoint (WS-03).
  3. *Connect S3* — collapsible form reusing the current S3 connector config UI from SourcesPage. Source naming is retained for S3 since users typically have meaningful bucket names.
- **Frontend — routing:** Add route `/add-media` → `AddMediaPage`. Add redirect from `/upload` → `/add-media`.
- **Frontend — nav:** Replace "Upload" nav link with "Add Media". Point to `/add-media`.
- **Frontend:** Post-OAuth callback from Google Drive redirects here (WS-04 handles the callback redirect change).

---

### WS-03: Google Drive quick-connect API endpoint

| Field | Value |
|---|---|
| **ID** | WS-03 |
| **Name** | Google Drive quick-connect endpoint |
| **Size** | Small–Medium |
| **Dependencies** | None |

**Objective:** Allow Google Drive OAuth to be initiated without a pre-existing Source. This removes the fundamental dependency that forces users to create a Source before connecting.

**Key changes:**
- **Backend — new endpoint:** `POST /api/v1/connectors/google-drive/quick-connect`
  - Auth: bearer token required
  - Body: `{ "source_name": string (optional) }` — defaults to `"Google Drive"` if not provided; will be updated to `"Google Drive — {email}"` after OAuth completes and account snapshot is fetched
  - Logic: creates a new `Source` row (owned by the calling user), then runs the same OAuth initiation logic as the existing `google_drive_start` endpoint
  - Returns: `ConnectorDriveStartResponse` (same shape as existing start endpoint — just the OAuth URL)
- **Backend — no schema changes.** Source creation is the same `POST /api/v1/sources/` logic, just called internally.
- **Frontend client (`client.ts`):** Add `startGoogleDriveQuickConnect(sourceName?: string)` method calling the new endpoint.
- **Existing `google_drive_start` endpoint:** Unchanged. S3 and power users who manage sources explicitly can still use the old path.

---

### WS-04: Post-OAuth configuration on Add Media page

| Field | Value |
|---|---|
| **ID** | WS-04 |
| **Name** | Post-OAuth Drive configuration inline |
| **Size** | Small–Medium |
| **Dependencies** | WS-02, WS-03 |

**Objective:** After Google Drive OAuth completes, land the user back on the Add Media page with a folder-selection step inline — eliminating the need to navigate to the Connections page to finish setup.

**Key changes:**
- **Backend:** Change the OAuth callback success redirect URL from `{frontend_url}/sources` to `{frontend_url}/add-media`. This is a one-line change in `_error_redirect` / the success redirect in `google_drive_connector.py`. The query params (`?connector=google_drive&source_id=...&connector_result=connected`) are preserved.
- **Frontend — `AddMediaPage.tsx`:** On mount, read the `?connector=google_drive&connector_result=connected&source_id=...` params (same logic currently in `SourcesPage.tsx`). When detected, expand the Google Drive panel and show the folder-configuration step inline (Drive folder picker + optional target collection). On save, trigger sync.
- **Frontend — `SourcesPage.tsx`:** Remove the post-OAuth callback handling logic (or retain as a fallback for users who bookmarked `/sources` directly — show a banner: "Google Drive connected. Configure it here or on the Add Media page").

---

### WS-05: Rename Sources → Connections

| Field | Value |
|---|---|
| **ID** | WS-05 |
| **Name** | Rename Sources to Connections |
| **Size** | Small |
| **Dependencies** | None |

**Objective:** Replace developer vocabulary with user vocabulary throughout the UI.

**Key changes:**
- **Frontend nav (`Layout.tsx`):** Change `Sources` label to `Connections`.
- **Frontend page heading (`SourcesPage.tsx`):** Change `<h1>Sources</h1>` to `<h1>Connections</h1>`.
- **Frontend copy:** All user-visible strings referencing "source" → "connection" (e.g. "No active sources" → "No active connections", "Create one on the Upload page" → "Add a connection from the Add Media page").
- **Backend API:** Route paths (`/api/v1/sources/...`) remain unchanged — this rename is UI-only. No API contract changes, no test impact.
- **Note:** The word "source" may remain in internal developer-facing contexts (API docs, log messages, test fixtures) without issue.

---

### WS-06: Connections page cleanup

| Field | Value |
|---|---|
| **ID** | WS-06 |
| **Name** | Connections page as management view |
| **Size** | Small |
| **Dependencies** | WS-05 (naming), WS-02 (Add Media exists as the link target) |

**Objective:** Reposition the Connections page as a management/status view, not an entry point for adding connections.

**Key changes:**
- **Frontend — `SourcesPage.tsx`:**
  - Add an "+ Add connection" button (or banner for empty state) that links to `/add-media`.
  - Filter out system-managed upload sources (identified by `__uploads__` name convention per WS-01) from the Connections list — users should not see the auto-created upload source here.
  - Improve the sync status display: show last sync time, item count delta from last run, and a "Sync now" button inline per row without requiring the connector panel to expand.
- **No backend changes.**

---

## 6. ADR-001: Implicit Source Creation for Ingestion Flows

**Status:** Proposed  
**Deciders:** Architect, Operator

### Context

The `Source` data model serves as a provenance record tying `MediaItem` rows to their ingestion origin. It is a sound model for the backend. However, the current UX requires users to explicitly create and name a `Source` before any ingestion can begin — whether uploading files or connecting Google Drive.

This is architecturally muddled because:
1. The Source concept has no user value until a connector is attached. For file uploads it has no user value at all.
2. The Google Drive OAuth endpoint (`POST /api/v1/sources/{source_id}/connector/google-drive/start`) requires a `source_id` in the URL, forcing Source creation as a prerequisite for OAuth. This inverts the natural user workflow.

### Decision

**Sources will be created implicitly by the backend for all user-facing ingestion flows.** Specifically:

1. **File uploads:** If no `source_id` is supplied to the upload endpoint, the backend auto-resolves a per-user default upload source (named `__uploads__`, created on demand). Users never see or interact with this source.

2. **Google Drive:** A new `POST /api/v1/connectors/google-drive/quick-connect` endpoint creates the Source internally as part of initiating OAuth. The user never names a source before connecting Drive.

3. **S3:** Source naming is **retained** for S3. S3 users typically manage multiple named buckets and the source name carries semantic meaning. S3 remains an explicit, named-source workflow.

The existing `POST /api/v1/sources/` endpoint and all source management APIs remain unchanged. Power users who interact with the Sources/Connections page directly are unaffected.

### Consequences

**Positive:**
- Google Drive connect flow reduces from 6 steps to 2.
- File upload flow has zero source management friction.
- No schema migration required — Sources continue to be created as rows; only the creation trigger changes from user-initiated to system-initiated.
- The existing API surface is preserved. The 254-test suite is unaffected.
- The `Source` → `SourceConnector` → `SyncRun` → `SourceObject` chain is unchanged; provenance tracking continues to work.

**Negative / risks:**
- Users connecting Google Drive via the new quick-connect path will have a Source named `Google Drive` (or similar) that they never explicitly created. If they visit the Connections page they will see it. The name should be updated to something meaningful post-OAuth (e.g., `Google Drive — alice@gmail.com`) using the account snapshot already fetched during OAuth. This is handled in the existing callback logic.
- The OAuth callback redirect URL changes from `/sources` to `/add-media`. Any existing bookmarks to the post-OAuth flow will redirect to a slightly different landing page. Risk: minimal (this URL is generated server-side and not user-bookmarkable in practice).
- Auto-created upload sources accumulate over time in the database. Mitigation: they are hidden from the UI and are low-cost rows.

---

## Approval Checklist

Before engineering begins, the operator should confirm:

- [ ] Option B is approved as the recommended approach
- [ ] The `__uploads__` naming convention for system upload sources is acceptable (vs. adding an `is_system` DB column)
- [ ] "Connections" is the right user-facing label (vs. alternatives: "Integrations", "Sources", "My Drive")
- [ ] Post-OAuth redirect changing from `/sources` to `/add-media` is acceptable
- [ ] WS-01 and WS-05 should proceed first as low-risk independent workstreams
- [ ] S3 naming workflow should be preserved (not simplified) in WS-02

---

*End of ARCH-001*
