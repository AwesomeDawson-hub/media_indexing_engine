# Workstream Plan: WS-005 — Frontend MVP

## Metadata

| Field | Value |
|---|---|
| **Workstream** | WS-005 |
| **Phase** | Phase 1 — MVP |
| **Project** | Media Indexing Engine |
| **Dependencies** | WS-003 (Search & Retrieval) — Completed, WS-004 (Auth & API Hardening) — Completed |
| **Estimated Size** | Medium |
| **Created** | 2026-03-28 |
| **Status** | Draft — awaiting operator review |

## Objective

Build the frontend MVP: a React + TypeScript single-page application that consumes all 10 backend API endpoints. Users can register/login, upload images (drag-and-drop + file picker, single and batch), browse their library in a paginated grid, view image details with AI-extracted metadata, search using natural language, and trigger re-analysis. The interface must be simple enough for a non-technical user per the project success criteria.

## Scope

### In Scope

- React 18 + TypeScript project scaffold (Vite)
- Auth pages: login and registration forms, JWT token management (localStorage)
- Protected routes: redirect to login when unauthenticated
- Upload page: drag-and-drop zone + file picker, batch support, per-file progress/status feedback
- Library page: paginated thumbnail grid with status indicators (uploaded / processing / completed / error)
- Media detail view: image preview + full AI metadata display (all 13 fields)
- Search page: search bar with natural language query, ranked results with scores
- Re-analysis trigger from media detail view
- API client module wrapping all 10 backend endpoints
- CORS middleware on the backend (FastAPI)
- Responsive layout (works on desktop; mobile not optimized but usable)
- Minimal styling (functional over polished — per project philosophy)

### Out of Scope

- Advanced responsive/mobile-native design (Phase 2)
- Dark mode or theme customization
- Drag-to-reorder, bulk actions on library items
- Real-time progress via WebSocket (polling for status instead)
- Image editing or cropping
- Infinite scroll (use pagination buttons)
- End-to-end (Playwright/Cypress) tests (manual testing for MVP; E2E is Phase 2)
- SSR / server-side rendering
- PWA / offline support

## Constraints

- **Stack:** React 18, TypeScript, Vite (fast build tooling)
- **Styling:** CSS Modules or a lightweight utility library (e.g., Tailwind CSS) — avoid heavy component frameworks (Material UI, Ant Design) for MVP simplicity
- **HTTP client:** `fetch` API (native, no axios dependency needed)
- **Routing:** React Router v6
- **State management:** React Context + `useState`/`useReducer` for auth state. No Redux — the app is too small.
- **Image serving:** Thumbnails served via a new backend endpoint (`GET /api/v1/media/{id}/file`) that reads from the file store. This avoids exposing raw storage paths.
- **Dev server:** Vite dev server on port 5173 proxying API requests to FastAPI on port 8000.
- **No unit tests for MVP frontend.** The frontend is a thin UI over validated backend APIs. Manual verification against the running backend is the test plan. E2E tests are a Phase 2 concern.

## Backend API Surface (10 Endpoints)

The frontend consumes all 10 existing endpoints:

| # | Method | Endpoint | Auth | Used By |
|---|---|---|---|---|
| 1 | POST | `/api/v1/auth/register` | Public | Registration form |
| 2 | POST | `/api/v1/auth/login` | Public | Login form |
| 3 | GET | `/api/v1/auth/me` | JWT | Auth context init |
| 4 | POST | `/api/v1/upload` | JWT | Single file upload |
| 5 | POST | `/api/v1/upload/batch` | JWT | Batch file upload |
| 6 | GET | `/api/v1/media` | JWT | Library grid |
| 7 | GET | `/api/v1/media/{id}` | JWT | Media detail |
| 8 | GET | `/api/v1/media/{id}/analysis` | JWT | Metadata display |
| 9 | POST | `/api/v1/media/{id}/reanalyze` | JWT | Re-analyze button |
| 10 | GET | `/api/v1/search?q=...` | JWT | Search results |

### New Backend Endpoint Required: File Serving

**`GET /api/v1/media/{id}/file`** — Serve the raw image file for display.

The frontend needs to display images. Files are stored at content-addressed paths that the frontend should not know about. This endpoint reads the file via the `FileStore` interface and returns it with the correct `Content-Type`.

**Response:** Raw file bytes with `Content-Type: image/jpeg` (or appropriate MIME type).
**Auth:** JWT required (users can only access their own files).
**Implementation:** Added to `src/api/routes/media.py` — 15 lines of code. Reads `media_item.storage_path` via `FileStore.read()`, returns `Response(content=bytes, media_type=mime_type)`.

This is the only backend change in WS-005.

## Page Structure

```
/login              → Login form (public)
/register           → Registration form (public)
/                   → Library grid (protected, default page)
/upload             → Upload page (protected)
/media/:id          → Media detail + metadata (protected)
/search             → Search page (protected)
```

### Layout

```
┌──────────────────────────────────────────────────┐
│  Header: Logo / Title  |  Search bar  |  User ▼  │
├──────────────────────────────────────────────────┤
│                                                    │
│                  Page Content                      │
│                                                    │
└──────────────────────────────────────────────────┘
```

- **Header** is persistent across all protected pages.
- **Search bar** in the header for quick access from any page. Pressing Enter navigates to `/search?q=...`.
- **User dropdown** shows display name, logout action.

## Component Architecture

```
App
├── AuthProvider (context: user, token, login, logout, register)
├── Router
│   ├── PublicRoute (redirect to / if logged in)
│   │   ├── LoginPage
│   │   └── RegisterPage
│   └── ProtectedRoute (redirect to /login if not logged in)
│       ├── Layout (header + search bar + user menu)
│       │   ├── LibraryPage (/)
│       │   ├── UploadPage (/upload)
│       │   ├── MediaDetailPage (/media/:id)
│       │   └── SearchPage (/search)
```

### Key Components

| Component | Responsibility |
|---|---|
| `AuthProvider` | JWT management, login/register/logout, persist token to localStorage, load profile on init |
| `ApiClient` | Centralized HTTP functions for all 10 endpoints + file serving. Attaches JWT header. Handles 401 → logout. |
| `LoginPage` | Email + password form, error display, link to register |
| `RegisterPage` | Email + password + display name form, error display, link to login |
| `Layout` | Shared header with nav links, search bar, user dropdown |
| `LibraryPage` | Fetch paginated media items, display as thumbnail grid, status badges, pagination controls |
| `UploadPage` | Drag-and-drop zone + file picker, file queue with per-file status, submit button |
| `MediaDetailPage` | Image preview (full size), all 13 metadata fields, processing status, re-analyze button |
| `SearchPage` | Search input, results grid with scores, "no results" state |
| `MediaCard` | Reusable thumbnail card (used in library and search results): image, filename, status badge |
| `StatusBadge` | Visual indicator for media status (uploaded=yellow, processing=blue, completed=green, error=red) |

## Auth Flow (Frontend)

```
App loads
    │
    ├── Token in localStorage?
    │   ├── Yes → Call GET /auth/me
    │   │   ├── 200 → Set user in context, render protected routes
    │   │   └── 401 → Clear token, redirect to /login
    │   └── No → Redirect to /login
    │
Login form submit
    │ POST /auth/login → { access_token, user }
    │ Store token in localStorage
    │ Set user in context
    │ Navigate to /
    │
Register form submit
    │ POST /auth/register → { access_token, user }
    │ Store token in localStorage
    │ Set user in context
    │ Navigate to /
    │
Logout
    │ Clear token from localStorage
    │ Clear user from context
    │ Navigate to /login
    │
API returns 401 on any request
    │ Auto-logout (token expired)
    │ Navigate to /login
```

## Upload Flow (Frontend)

```
User drops files or picks via file dialog
    │
    ▼
Files added to upload queue (displayed as list with status per file)
    │
    ▼
User clicks "Upload" (or auto-submit on drop — configurable)
    │
    ▼
For batch (≤ 20 files): POST /upload/batch → per-file results
For single file: POST /upload → single result
    │
    ▼
Update queue: mark each file as ✓ created / ⚠ duplicate / ✗ error
    │
    ▼
"View Library" link to see uploaded items
```

**UX details:**
- Drag-and-drop zone is a large area with dashed border and "Drop files here" text.
- File picker button as alternative ("or click to browse").
- File list shows: filename, size, status icon.
- Invalid files (wrong format, too large) rejected client-side before upload with error message.
- Progress: use simple states (queued → uploading → done/error), not byte-level progress bars.
- Batch limit: 20 files. If more selected, show warning and truncate.

## Library Page

```
┌──────────────────────────────────────────────────┐
│ My Library                          [Upload] btn  │
├──────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│ │  thumb  │ │  thumb  │ │  thumb  │ │  thumb  │ │
│ │ ●status │ │ ●status │ │ ●status │ │ ●status │ │
│ │filename │ │filename │ │filename │ │filename │ │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
│ ┌─────────┐ ┌─────────┐ ...                      │
│ │  thumb  │ │  thumb  │                          │
│ └─────────┘ └─────────┘                          │
│                                                    │
│           « Prev    Page 1 of 3    Next »         │
└──────────────────────────────────────────────────┘
```

- Fetches `GET /api/v1/media?page=N&per_page=20`.
- Thumbnail: `GET /api/v1/media/{id}/file` loaded as `<img src>`.
- Status badge on each card: colored dot + label.
- Click card → navigates to `/media/:id`.
- "Upload" button → navigates to `/upload`.
- Empty state: "No media yet. Upload your first images!"

## Media Detail Page

```
┌──────────────────────────────────────────────────┐
│ ← Back to Library                                 │
├──────────────────────────────────────────────────┤
│                                                    │
│   ┌──────────────────────┐   Title: Sunset Beach  │
│   │                      │   Description: A warm.. │
│   │    Image Preview     │                        │
│   │    (full width)      │   Tags: sunset, beach.. │
│   │                      │   Objects: sun, ocean.. │
│   └──────────────────────┘   Scenes: coastal...   │
│                              Context: Nature...    │
│   Status: ● Completed        Mood: Serene         │
│   Filename: sunset.jpg       People: None (0)     │
│   Size: 2.4 MB               Orientation: land..  │
│   Uploaded: 2026-03-28       Colors: orange, blue  │
│                              Location: Pacific..   │
│   [Re-analyze]               Quality: null         │
│                                                    │
│   AI Provider: Anthropic     Model: claude-son..   │
│   Analyzed: 2026-03-28 12:00                       │
└──────────────────────────────────────────────────┘
```

- Fetches `GET /api/v1/media/{id}` for file info.
- Fetches `GET /api/v1/media/{id}/analysis` for metadata.
- Image loaded via `GET /api/v1/media/{id}/file`.
- If analysis pending/running: show spinner + "Analysis in progress..." with poll every 5 seconds.
- If analysis failed: show error message + "Re-analyze" button.
- If analysis completed: show all 13 metadata fields.
- "Re-analyze" button: `POST /api/v1/media/{id}/reanalyze` → show polling state.

## Search Page

```
┌──────────────────────────────────────────────────┐
│ Search your library                               │
│ ┌──────────────────────────────────────┐ [Search] │
│ │ sunset beach portrait                │          │
│ └──────────────────────────────────────┘          │
├──────────────────────────────────────────────────┤
│ 3 results for "sunset beach portrait"             │
│                                                    │
│ ┌─────────┐ Sunset Beach Photo          87% match │
│ │  thumb  │ A warm sunset over the Pacific...     │
│ │         │ Tags: sunset, beach, ocean            │
│ └─────────┘ Mood: serene                          │
│                                                    │
│ ┌─────────┐ Beach Vacation              72% match │
│ │  thumb  │ Family enjoying a day at the...       │
│ │         │ Tags: beach, family, vacation         │
│ └─────────┘ Mood: cheerful                        │
└──────────────────────────────────────────────────┘
```

- Search input pre-filled from URL query param (`/search?q=...`).
- Header search bar and search page search bar are synced.
- Results fetched from `GET /api/v1/search?q=...&page=N&per_page=20`.
- Each result: thumbnail, title, description snippet, tags, mood, relevance score as percentage.
- Click result → navigates to `/media/:id`.
- Empty state: "No results found. Try a different query."
- Loading state: spinner while waiting for results.

## API Client Module

A single module (`src/api/client.ts`) that wraps all backend calls with TypeScript types:

```typescript
// Auth
register(email, password, displayName) → AuthResponse
login(email, password) → AuthResponse
getProfile() → UserProfile

// Upload
uploadFile(file: File) → UploadResponse
uploadBatch(files: File[]) → BatchUploadResponse

// Media
listMedia(page, perPage) → PaginatedResponse
getMedia(id) → MediaItemResponse
getMediaFile(id) → Blob  // for <img> display

// Analysis
getAnalysis(id) → AnalysisResponse
reanalyze(id) → ReanalyzeResponse

// Search
search(query, page, perPage) → SearchResponse
```

**Responsibilities:**
- Attach `Authorization: Bearer <token>` header to all protected calls.
- Parse JSON responses with TypeScript types matching backend schemas.
- On 401 response: trigger auto-logout (token expired).
- On error: return typed error with `detail` and `error_code` from the standardized format.
- Base URL configurable (defaults to `""` — same origin via Vite proxy in dev).

## CORS Configuration

Add CORS middleware to the FastAPI backend so the Vite dev server (port 5173) can call the API (port 8000).

```python
# In app.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.cors_origins,  # ["http://localhost:5173"] for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

New config:
```yaml
app:
  cors_origins:
    - "http://localhost:5173"
```

```python
@dataclass
class AppConfig:
    # ... existing fields
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
```

## Implementation Steps

Each step has a validation checkpoint. Do not proceed to the next step until the current step's validation passes.

### Step 1: Backend Changes — File Serving Endpoint + CORS

**What:** Add the `GET /api/v1/media/{id}/file` endpoint for serving image files. Add CORS middleware to FastAPI. Add `cors_origins` to `AppConfig`.

**Files to modify:**
- `src/api/routes/media.py` — add `GET /media/{id}/file` endpoint
- `src/api/app.py` — add `CORSMiddleware`
- `src/config.py` — add `cors_origins` to `AppConfig`
- `config/settings.yaml` — add `cors_origins`
- `config/settings.example.yaml` — add `cors_origins`

**Validation:**
- [ ] `GET /api/v1/media/{id}/file` returns image bytes with correct Content-Type
- [ ] 404 for non-existent media ID
- [ ] Auth required (401 without token when dev mode off)
- [ ] CORS headers present in response (`Access-Control-Allow-Origin`)
- [ ] All 38 existing tests still pass

### Step 2: React Project Scaffold

**What:** Initialize a React + TypeScript project with Vite in the `frontend/` directory. Set up project structure, dev proxy, and basic dependencies.

**Commands:**
```bash
cd frontend/
npm create vite@latest . -- --template react-ts
npm install react-router-dom
```

**Project structure:**
```
frontend/
├── src/
│   ├── api/           → API client module
│   ├── components/    → Reusable UI components
│   ├── pages/         → Page components
│   ├── context/       → React contexts (auth)
│   ├── types/         → TypeScript type definitions
│   ├── App.tsx        → Router setup
│   ├── main.tsx       → Entry point
│   └── index.css      → Global styles
├── vite.config.ts     → Dev server proxy config
├── package.json
└── tsconfig.json
```

**Vite proxy config** (`vite.config.ts`):
```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

**Validation:**
- [ ] `npm run dev` starts Vite dev server on port 5173
- [ ] TypeScript compiles without errors
- [ ] Proxy works: requests to `/api/v1/...` from the frontend reach the backend

### Step 3: TypeScript Types and API Client

**What:** Define TypeScript types matching all backend response schemas. Create the API client module with all 11 endpoint functions (10 existing + file serving).

**Files to create:**
- `frontend/src/types/api.ts` — TypeScript interfaces for all request/response types
- `frontend/src/api/client.ts` — API client with typed functions, auth header injection, 401 handling

**Validation:**
- [ ] All 11 endpoint functions exist with correct TypeScript signatures
- [ ] Types match backend Pydantic schemas exactly
- [ ] Auth header attached when token is present
- [ ] Error responses parsed into typed error objects

### Step 4: Auth Context and Protected Routes

**What:** Create the auth context provider (manages token + user state), login/register pages, and route guards.

**Files to create:**
- `frontend/src/context/AuthContext.tsx` — `AuthProvider`, `useAuth` hook
- `frontend/src/pages/LoginPage.tsx` — login form
- `frontend/src/pages/RegisterPage.tsx` — registration form
- `frontend/src/components/ProtectedRoute.tsx` — redirects to /login if not authenticated
- `frontend/src/components/PublicRoute.tsx` — redirects to / if already authenticated
- `frontend/src/App.tsx` — wire up router with auth provider and route guards

**Auth context behavior:**
- On mount: check localStorage for token → call `GET /auth/me` → set user or clear token
- `login(email, password)`: call API → store token → set user → navigate to /
- `register(email, password, displayName)`: call API → store token → set user → navigate to /
- `logout()`: clear token + user → navigate to /login
- Expose: `user`, `token`, `isLoading`, `login`, `register`, `logout`

**Validation:**
- [ ] Navigate to / without token → redirected to /login
- [ ] Register → token stored, redirected to /
- [ ] Login → token stored, redirected to /
- [ ] Logout → token cleared, redirected to /login
- [ ] Invalid credentials → error message displayed on form
- [ ] Duplicate email → error message displayed
- [ ] Page refresh with valid token → stays logged in (profile loaded)
- [ ] Page refresh with expired token → redirected to /login

### Step 5: Layout and Navigation

**What:** Create the shared layout component with header, search bar, navigation, and user menu.

**Files to create:**
- `frontend/src/components/Layout.tsx` — header + content area
- `frontend/src/components/SearchBar.tsx` — search input in header
- `frontend/src/components/UserMenu.tsx` — display name + logout
- `frontend/src/index.css` — global styles and CSS reset

**Validation:**
- [ ] Header visible on all protected pages
- [ ] Search bar in header → pressing Enter navigates to `/search?q=...`
- [ ] User menu shows display name
- [ ] Logout from user menu works
- [ ] Nav links: Library (/), Upload (/upload)
- [ ] Active page highlighted in nav

### Step 6: Upload Page

**What:** Create the upload page with drag-and-drop zone, file picker, file queue with per-file status, and upload execution.

**Files to create:**
- `frontend/src/pages/UploadPage.tsx` — main upload page
- `frontend/src/components/DropZone.tsx` — drag-and-drop area + file picker button
- `frontend/src/components/FileQueue.tsx` — list of queued files with status indicators

**Upload behavior:**
- Files added to queue on drop or pick
- Client-side validation: reject non-image MIME types, reject files > 50 MB
- Queue shows: filename, size, status (queued / uploading / ✓ created / ⚠ duplicate / ✗ error)
- "Upload" button sends batch request (or single if 1 file)
- After upload: show results, "View Library" link
- Batch limit: 20 files. Show warning if exceeded.

**Validation:**
- [ ] Drag files onto drop zone → added to queue
- [ ] Click "Browse" → file picker opens, selected files added to queue
- [ ] Invalid file type → rejected with message (client-side)
- [ ] File > 50 MB → rejected with message (client-side)
- [ ] Upload 1 file → POST /upload → result displayed
- [ ] Upload multiple → POST /upload/batch → per-file results displayed
- [ ] Duplicate file → shows "duplicate" status
- [ ] > 20 files → warning, extras trimmed

### Step 7: Library Page

**What:** Create the library page with paginated thumbnail grid and status indicators.

**Files to create:**
- `frontend/src/pages/LibraryPage.tsx` — main library page
- `frontend/src/components/MediaCard.tsx` — thumbnail card (image + filename + status)
- `frontend/src/components/StatusBadge.tsx` — colored status indicator
- `frontend/src/components/Pagination.tsx` — page controls (prev/next, current page)

**Behavior:**
- Fetches `GET /api/v1/media?page=N&per_page=20` on mount and page change.
- Thumbnails loaded via `GET /api/v1/media/{id}/file` as `<img>` src (using blob URL or data URL via API client).
- Each card shows: thumbnail, filename (truncated), status badge.
- Click card → navigate to `/media/:id`.
- Pagination: Prev/Next buttons, "Page X of Y" label.
- Empty state: "No media yet. Upload your first images!" with link to /upload.

**Validation:**
- [ ] Library loads and shows uploaded images as thumbnails
- [ ] Status badges: yellow (uploaded), blue (processing), green (completed), red (error)
- [ ] Click card → navigates to media detail
- [ ] Pagination: prev/next buttons change page, correct total
- [ ] Empty library → empty state message with upload link
- [ ] "Upload" button navigates to /upload

### Step 8: Media Detail Page

**What:** Create the media detail view with image preview, file info, and full AI metadata.

**Files to create:**
- `frontend/src/pages/MediaDetailPage.tsx` — main detail page
- `frontend/src/components/MetadataDisplay.tsx` — renders all 13 metadata fields

**Behavior:**
- Fetches `GET /api/v1/media/{id}` for file info.
- Fetches `GET /api/v1/media/{id}/analysis` for metadata.
- Image loaded via `GET /api/v1/media/{id}/file`.
- **Completed:** Show image + all metadata fields in a structured layout.
- **Pending/Running:** Show image + "Analysis in progress..." spinner. Poll every 5 seconds.
- **Failed:** Show image + error message + "Re-analyze" button.
- "Re-analyze" button: calls `POST /api/v1/media/{id}/reanalyze`, then polls for completion.
- "Back to Library" link.

**Metadata layout:** Two-column on desktop (image left, metadata right). Single column on narrow screens.

**Validation:**
- [ ] Completed item: image displayed, all 13 metadata fields shown
- [ ] Pending item: spinner + "Analysis in progress" + auto-poll
- [ ] Failed item: error message + "Re-analyze" button
- [ ] Re-analyze: button triggers re-analysis, status updates on poll
- [ ] Back link returns to library
- [ ] Tags, objects, scenes, colors displayed as tag pills/chips
- [ ] Null fields (location_hint, quality_notes) show "N/A" or are hidden

### Step 9: Search Page

**What:** Create the search page with query input and ranked results.

**Files to create:**
- `frontend/src/pages/SearchPage.tsx` — search interface

**Behavior:**
- Search input pre-filled from URL query param (`/search?q=...`).
- On submit: update URL → fetch `GET /api/v1/search?q=...&page=N&per_page=20`.
- Results: list/grid with thumbnail, title, description snippet, tags, mood, score as percentage.
- Click result → navigate to `/media/:id`.
- Header search bar navigates to this page with query.
- Pagination on results.
- States: loading spinner, results, empty ("No results found"), initial (no query yet).

**Validation:**
- [ ] Type query, submit → results displayed with scores
- [ ] Scores shown as percentage (e.g., "87% match")
- [ ] Results ordered by relevance (highest score first)
- [ ] Click result → navigates to media detail
- [ ] Header search bar → navigates to search page with query
- [ ] URL query param preserved (shareable search links)
- [ ] No results → "No results found" message
- [ ] Pagination works on search results

### Step 10: Styling and Polish

**What:** Apply consistent, minimal styling across all pages. Ensure functional UX without heavy frameworks.

**Approach:**
- Use CSS Modules (`.module.css` files per component) for scoped styles.
- Simple color palette: white background, dark text, brand accent color.
- Status colors: yellow (#f59e0b), blue (#3b82f6), green (#10b981), red (#ef4444).
- Tag pills: light background, rounded, small text.
- Card shadows: subtle box-shadow for media cards.
- Responsive: CSS grid with `auto-fill` for media grid, flexbox for layout.
- Consistent spacing: 8px grid system.

**Validation:**
- [ ] All pages have consistent look and feel
- [ ] No raw unstyled elements
- [ ] Responsive: grid reflows on narrow windows
- [ ] Status badges visually distinct
- [ ] Forms have clear labels, input focus states, error states
- [ ] Loading states have spinners (not blank screens)

### Step 11: Integration Testing (Manual)

**What:** End-to-end manual test of the complete flow against a running backend.

**Procedure:**
1. Start backend: `uvicorn src.api.app:app --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Register a new user
4. Upload a single image
5. Upload a batch of images (include one duplicate, one invalid format)
6. View library — see thumbnails and status badges
7. Wait for analysis to complete (or check detail page for polling)
8. View media detail — see all metadata fields
9. Search for content that matches uploaded images
10. Trigger re-analysis on one item
11. Logout and verify redirect to login
12. Login with created credentials

**Validation:**
- [ ] Registration → login → full flow works end-to-end
- [ ] Upload single → appears in library with correct status progression
- [ ] Upload batch → per-file results displayed correctly
- [ ] Library thumbnails load correctly
- [ ] Media detail shows full metadata after analysis
- [ ] Search finds relevant images with scores
- [ ] Re-analysis updates metadata
- [ ] Auth flow: logout → login → data persists

### Step 12: PROJECT_MAP and Documentation Update

**What:** Update `PROJECT_MAP.md` with the frontend module structure.

**Files to modify:**
- `docs/PROJECT_MAP.md` — document `frontend/` structure and module responsibilities

**Validation:**
- [ ] `frontend/` section lists key directories and files
- [ ] Component architecture documented
- [ ] API client module documented
- [ ] No stale references

## File/Directory Structure

```
frontend/
├── src/
│   ├── api/
│   │   └── client.ts              → API client (11 endpoint functions)
│   ├── components/
│   │   ├── DropZone.tsx           → Drag-and-drop upload area
│   │   ├── FileQueue.tsx          → Upload queue with status per file
│   │   ├── Layout.tsx             → Shared header + content wrapper
│   │   ├── MediaCard.tsx          → Thumbnail card for grid
│   │   ├── MetadataDisplay.tsx    → Full 13-field metadata view
│   │   ├── Pagination.tsx         → Page controls
│   │   ├── ProtectedRoute.tsx     → Auth guard
│   │   ├── PublicRoute.tsx        → Redirect if authenticated
│   │   ├── SearchBar.tsx          → Header search input
│   │   ├── StatusBadge.tsx        → Colored status indicator
│   │   └── UserMenu.tsx           → User dropdown + logout
│   ├── context/
│   │   └── AuthContext.tsx        → Auth state management
│   ├── pages/
│   │   ├── LibraryPage.tsx        → Paginated media grid
│   │   ├── LoginPage.tsx          → Login form
│   │   ├── MediaDetailPage.tsx    → Image + metadata view
│   │   ├── RegisterPage.tsx       → Registration form
│   │   ├── SearchPage.tsx         → Search input + results
│   │   └── UploadPage.tsx         → Upload interface
│   ├── types/
│   │   └── api.ts                 → TypeScript types for API
│   ├── App.tsx                    → Router + providers
│   ├── main.tsx                   → Entry point
│   └── index.css                  → Global styles
├── vite.config.ts                 → Dev proxy
├── package.json
└── tsconfig.json
```

## Exit Criteria

All of the following must be true to close WS-005:

- [ ] User can register, login, and logout via the web UI
- [ ] User can upload images via drag-and-drop or file picker (single + batch)
- [ ] Upload shows per-file status (created / duplicate / error)
- [ ] Library page shows paginated grid of uploaded media with thumbnails
- [ ] Status badges indicate processing state (uploaded / processing / completed / error)
- [ ] Media detail page shows full image and all 13 AI-extracted metadata fields
- [ ] Pending analysis shows polling spinner that updates on completion
- [ ] Re-analyze button triggers re-analysis and updates display
- [ ] Search page accepts natural language queries and shows ranked results with scores
- [ ] Search results show thumbnails, titles, descriptions, tags, and relevance percentages
- [ ] Auth protects all routes (redirect to login when unauthenticated)
- [ ] CORS configured on backend for frontend dev server
- [ ] File serving endpoint returns images with correct Content-Type
- [ ] All 38 existing backend tests still pass
- [ ] Manual integration test passes (registration → upload → analysis → search → re-analyze)
- [ ] `PROJECT_MAP.md` updated with frontend structure
- [ ] Closeout checklist completed
- [ ] **This completes Phase 1 — MVP.**

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Thumbnail loading slow for large libraries | Medium | Use browser lazy-loading (`loading="lazy"` on `<img>`). Thumbnail generation is a Phase 2 optimization. |
| CORS misconfiguration blocks API calls | Low | Test CORS in Step 1 before building any frontend. Dev proxy bypasses CORS entirely. |
| Analysis polling creates unnecessary load | Low | 5-second interval is light. Only polls on detail page when status is pending/running. |
| Token expiry disrupts active upload | Medium | 60-minute token should cover most sessions. Refresh tokens deferred to Phase 2. |
| Vite build differs from dev behavior | Low | Test production build (`npm run build`) before closeout. |
| Large batch upload times out | Low | Backend processes sequentially and returns results. Frontend shows "uploading..." state. |

## Notes

- **Functional over polished.** Per project philosophy, the frontend should work correctly but need not be beautiful. Consistent, clean UI is sufficient. Visual refinement is Phase 2.
- **No frontend tests in MVP.** The backend APIs are thoroughly tested (38 tests). The frontend is a thin UI layer. Manual integration testing against the running backend is the verification strategy. E2E tests (Playwright/Cypress) are a Phase 2 addition.
- **Vite dev proxy** means the frontend never constructs backend URLs — all API calls go to the same origin, and Vite forwards them. This simplifies deployment and avoids CORS issues during development.
- **CSS Modules over Tailwind.** Tailwind adds a build dependency and learning curve. CSS Modules are built into Vite, require zero config, and keep styles co-located with components. For an MVP with ~12 components, this is simpler.
- **Image serving via API** (not direct file path) is intentional. It respects auth (users can only access their own files), hides storage implementation, and works identically in dev and production.
- **This is the final workstream in Phase 1.** Closing WS-005 triggers the Phase 1 closeout checklist.
