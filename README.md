# Media Indexing Engine

An AI-powered media library that ingests images from supported connected sources, enriches them with structured AI metadata, and makes them searchable through a web app.

## Overview

Media Indexing Engine helps people organize image libraries without manual tagging. You connect supported sources, the app analyzes the media with AI, and you can search it in plain language.

In the current beta, the product already supports Google sign-in, Google Drive ingestion, source-aware library management, batch reanalysis, and async batch export for eligible items.

## For Beta Users

### What this app does

- brings images into one searchable library
- analyzes images automatically with AI
- extracts structured metadata to improve search and organization
- lets you search using plain English instead of manual folders and tags
- supports exporting batches of eligible items when you need a packaged download

### Typical beta flow

1. Sign in with email/password or Google.
2. Connect a supported source.
3. Wait for analysis to complete.
4. Search, browse, reanalyze, or export eligible results.

### What works in beta today

- email/password login
- Google SSO
- Google Drive connector ingestion
- automatic AI metadata extraction
- natural-language search
- batch reanalysis
- async batch export for supported items

### Important beta limitations

- images are the primary supported media type
- not every source type supports every action
- Google sign-in or Google Drive connection can be blocked by Google’s own testing, publishing, or verification settings even when the app itself is working correctly
- some export/download behavior depends on where the original file lives
- local working-folder intake is currently hidden and deprecated rather than a supported beta path

### Batch export in plain language

Batch export is supported, but not for every kind of item.

- full items stored by the app are eligible
- Google Drive-backed reference items are eligible through the async export flow
- local-folder reference items are not currently eligible for server-side bulk export
- unsupported future providers do not automatically inherit Google Drive behavior

### What to expect from the product model

This app is designed to be source-aware:

- if an item is reference-backed, the original often stays in its original source system
- the app keeps metadata, search state, and preview assets
- the app is a searchable media intelligence layer, not a permanent hosted vault for every original file
- deprecated local working-folder intake code may still exist in the repo, but it is not part of the supported beta experience

## Target Users

- **Photographers** managing large volumes of photos who need automated organization, tagging, and retrieval
- **Marketing teams** who need to quickly find relevant, high-quality images for campaigns and content
- **Content teams and small businesses** managing growing media libraries

## What Works Today

- Email/password auth plus Google SSO
- Google Drive connector ingestion
- Automatic AI-powered metadata extraction and enrichment
- Natural-language semantic search
- Source-aware reference-mode storage for supported source-backed items
- Drive-backed single-item refetch for approved reanalysis and download flows
- Capability-aware batch reanalysis with explicit per-item outcomes
- Async batch export with export-job status and temporary artifacts for eligible selections
- Durable source capability and write-back state tracking
- Hash-based deduplication and user-scoped access control

## Current Product Boundaries

- Images are the primary supported media type
- Full/app-retained items are exportable and reanalyzable
- Drive-backed reference items are supported only where explicitly approved by the current contracts
- Local working-folder intake is deprecated and not part of the supported beta path; any legacy local-folder reference items remain blocked for server-side bulk export
- Non-Drive reference providers do not inherit Drive behavior automatically
- The legacy synchronous batch ZIP route still exists for compatibility, but the main mixed-selection export path is the async export-job model

## Current Beta Caveats

- Google SSO and Google Drive exist technically, but external beta users can still be blocked by Google Auth Platform testing, publishing, or verification state even when app code is correct.
- Some connected-source actions depend on source capability, auth state, and provider scope.
- The product is actively being hardened for beta reliability and clearer recovery UX.

## For Developers

The sections below are primarily for developers and operators.

Current internal status at a glance:

- **Current phase:** Post-Phase 9 incremental workstreams
- **Current governance step:** P12-001 is the current approval gate; P11-002 is completed and formally closed
- **Core storage architecture:** Phase 9 ARCH-002 remediation completed
- **Latest delivered backend capability:** async connector-aware bulk export (P11-002), completed and closed
- **Current live operational pressure:** Google OAuth publishing/testing readiness for external beta access

For the authoritative live state, read these first:

1. `docs/PROJECT_HANDOFF.md`
2. `docs/CURRENT_STATE.md`
3. `docs/WORKSTREAMS.md`
4. `docs/DECISION_LOG.md`

## Architecture (High-Level)

```
frontend/          → Web UI (connectors, search, browse)
src/
  ingestion/       → File intake, validation, deduplication
  analysis/        → AI vision model integration, metadata extraction
  search/          → Semantic search and query processing
  storage/         → Cloud storage and metadata persistence
  api/             → REST API layer
  utils/           → Shared utilities
tests/             → Test suite
config/            → Configuration files
docs/              → Project-specific documentation
scripts/           → Automation and utility scripts
```

## Architecture Notes That Matter

- **Reference-mode is real:** connector-backed originals are not meant to become hidden app-retained originals.
- **Source-aware behavior is intentional:** Drive-backed fetch/reanalysis/export behavior exists only where explicitly approved.
- **Previews are app-owned; originals are often not:** the app is a metadata/search/workflow system, not a permanent original vault.
- **Connector capability state matters:** read/write/refetch readiness, scope state, and retry/recovery behavior are part of the product contract.
- **Governance matters:** before changing storage, connector, export, or refetch behavior, read the relevant plan and ADRs in `docs/`.

Recommended architecture reading order for later developers:

1. `docs/planning/ARCH-002-reference-mode-storage.md`
2. `docs/planning/PHASE_9_arch002_gap_remediation_plan.md`
3. `docs/planning/P11-001_plan.md`
4. `docs/planning/P11-002_plan.md`
5. `docs/DECISION_LOG.md`

## Developer Beta Caveats

- The full backend suite is not currently fully green because of an unrelated failure in `tests/test_google_drive_connector.py`.
- That unrelated connector-suite failure should not be confused with P11-002 export scope or closeout status.
- Local working-folder intake is currently hidden/deprecated because it has not been reliable enough for the supported beta experience.

## Cleanup And Hardening Priorities

If the next focus is cleanup and hardening rather than new feature expansion, the most pragmatic targets are:

1. **Google OAuth production-readiness**
  - clarify publishing/testing requirements
  - document beta tester onboarding
  - improve user-facing messaging when Google blocks access for policy reasons
2. **Connector health and recovery UX**
  - make scope/auth/connectivity state easier to understand
  - surface clearer reconnect, retry, and blocked-action guidance
3. **Release-confidence hardening**
  - isolate and fix unrelated connector test failures
  - document what counts as a workstream blocker versus unrelated suite drift
  - tighten smoke-test expectations for auth, Drive, sync, and export
4. **Async export polish**
  - improve status visibility, expiry messaging, and job lifecycle clarity
  - keep this as polish on top of ADR-036, not an architecture rewrite
5. **Developer-document cleanup**
  - keep top-level docs synchronized with current governance
  - avoid stale references to pre-connector or pre-reference-mode assumptions

## Developer Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend)
- An Anthropic API key (for AI analysis)

### Backend setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -e .
```

Copy `config/settings.yaml` and set your values, or export `DATABASE_URL` for production.

### Database migration

**Fresh installation** — create the schema by running Alembic:

```bash
python -m alembic upgrade head
```

**Existing database** (created before Alembic was introduced, i.e. before P3-002) — stamp the current state so Alembic knows the schema is already up to date:

```bash
python -m alembic stamp head
```

After that, all future schema changes are applied with `alembic upgrade head`.

### Creating new migrations (after schema changes)

1. Edit the ORM models in `src/models.py`
2. Generate a migration:

```bash
python -m alembic revision --autogenerate -m "describe_change"
```

3. Review the generated file in `alembic/versions/`, clean up any autogenerate noise
4. Apply: `python -m alembic upgrade head`

### Running the backend

```bash
# Dev mode (create_all, no Alembic required):
python -m uvicorn src.api.app:app --reload

# Production (requires alembic upgrade head first, debug:false in settings.yaml):
python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### Running the tests

```bash
python -m pytest tests/ -q --tb=short
```

Authoritative recent validation context:

- P11-002 focused suite: 19/19 pass
- directly affected suites around P11-002: 71 pass
- current full-suite status includes a separate unrelated failure in `tests/test_google_drive_connector.py`

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

---

## Production Deployment

The full system runs as four Docker services: **backend** (FastAPI), **frontend** (nginx), **chromadb**, and **postgres**.

### Prerequisites

- Docker 24+ and Docker Compose v2 (`docker compose` command)
- An Anthropic API key

### 1. Prepare environment

```bash
cp .env.example .env
```

Edit `.env` and fill in real values for every variable:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (see `.env.example` for format) |
| `AUTH_SECRET_KEY` | Random secret for JWT signing — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude vision model |
| `POSTGRES_PASSWORD` | PostgreSQL superuser password |

For S3 file storage (optional — local disk is the default):

| Variable | Description |
|---|---|
| `STORAGE_PROVIDER` | Set to `s3` to enable S3 storage |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `S3_BUCKET` | Target S3 bucket name |
| `S3_REGION` | AWS region (default: `us-east-1`) |

### 2. Start all services

```bash
docker compose up -d
```

The backend automatically runs `alembic upgrade head` before starting uvicorn. On first run this creates the full database schema.

### 3. Verify the stack

```bash
curl http://localhost/api/v1/health
# → {"status": "ok", "version": "0.1.0"}
```

The web UI is available at `http://localhost`.

### 4. Run database migrations (after upgrade)

When updating to a new version that includes schema changes:

```bash
docker compose exec backend alembic upgrade head
```

### Stopping and restarting

```bash
docker compose down       # stop (data volumes are preserved)
docker compose down -v    # stop AND delete all data volumes
```

### Updating the image

```bash
docker compose build --no-cache
docker compose up -d
```

### Public beta deployment on a VPS

The simplest path for beta testers is a single Linux VPS running Docker with HTTPS in front of the existing stack.

Recommended baseline:

- Ubuntu 24.04 LTS VPS
- 4 vCPU / 8 GB RAM to start
- A domain or subdomain pointed at the server (`beta.yourdomain.com`)

Steps:

1. Copy the repo to the VPS.
2. Copy `.env.example` to `.env` and fill in real values.
3. Set these public-beta values in `.env`:
  - `DOMAIN=beta.yourdomain.com`
4. Start the stack with the beta override:

```bash
docker compose -f docker-compose.yml -f docker-compose.beta.yml up -d --build
```

What the beta override does:

- hides `backend`, `postgres`, and `chromadb` from the public internet
- removes direct public exposure of the frontend container
- adds a `caddy` service that terminates HTTPS automatically and proxies traffic to the frontend

After the containers are up:

```bash
docker compose -f docker-compose.yml -f docker-compose.beta.yml ps
curl https://beta.yourdomain.com/api/v1/health
```

Expected result:

```json
{"status": "ok", "version": "0.1.0"}
```

Operational recommendation for beta:

- keep `STORAGE_PROVIDER=local` initially unless you specifically need S3 now
- use daily database backups before inviting testers
- rotate `AUTH_SECRET_KEY` and set a real `POSTGRES_PASSWORD`
- do not expose ports `8000`, `8001`, or `5432` publicly on the VPS

### AWS EC2 temporary-hostname note

If you deploy the beta on AWS EC2 and use the default AWS hostname (for example `ec2-xx-xx-xx-xx.compute-1.amazonaws.com`) instead of a real domain you control, automatic HTTPS will fail because ACME/Let's Encrypt will not issue certificates for that hostname.

In that case, use a temporary HTTP-only Caddyfile until you attach a real domain:

```caddy
http://ec2-xx-xx-xx-xx.compute-1.amazonaws.com {
  encode gzip
  reverse_proxy frontend:80
}
```

Then access the site with the full `http://...` URL, not `https://...`.

## Developer Notes

- Do not assume old README language about "cloud integrations deferred" or "upload-only V1" is still true; the governance docs are the source of truth.
- Before planning new connector or storage work, verify whether the behavior is already locked by ADR or by a completed workstream.
- Do not reopen completed Phase 9 architecture casually. Most near-term value is in cleanup, hardening, UX clarity, and beta operational readiness.

Important caveats:

- some browsers will cache a failed HTTPS attempt or force HTTPS automatically; use an Incognito/InPrivate window if the normal browser keeps refusing the connection
- this is a temporary beta-only workaround
- once a real domain is attached, switch `DOMAIN` back to that domain and restore the default HTTPS Caddyfile

---

## Known Configuration Notes

- **Upload size limit:** The nginx frontend is configured to accept files up to **50 MB** (`client_max_body_size 50M`). Adjust `frontend/nginx.conf` if you need a different limit.
- **File storage:** Local disk by default (`storage.provider: local`). Set `STORAGE_PROVIDER=s3` and the S3 env vars to enable S3-backed storage.
- **AI analysis:** Requires a valid `ANTHROPIC_API_KEY`. Without it, intake requests may succeed but AI analysis jobs will fail silently in the background.

---

## Changelog

### 2026-03-29 — Post-Phase-3 Bug Fixes (commit `fd5013e`)
- **Upload limit raised to 50 MB** — nginx default of 1 MB was causing HTTP 413 errors for typical photo files. `frontend/nginx.conf` now sets `client_max_body_size 50M`.
- **Search user isolation hardened** — `src/search/search_service.py` now enforces `user_id` scoping at the database layer (defense-in-depth; ChromaDB already filtered by user, DB now independently enforces it).
- **Search relevance sort fixed** — First search after login now correctly returns results sorted by semantic relevance. Previously, the browse mode `sort_by=newest` state leaked into the first search query.

### 2026-03-28 — Phase 3: Polish & Production Readiness (complete)
- Production Docker stack (`docker-compose.yml`) with backend, frontend (nginx), ChromaDB, and PostgreSQL
- S3-compatible file storage backend (`S3FileStore`)
- Health endpoint (`GET /api/v1/health`) — no auth required
- Alembic database migrations
- Bulk re-analyze and delete operations (up to 50 items per request)
- UI polish: metadata prefix cleanup, dimensions displayed, unified Gallery page, "Source" rename

### 2026-03-28 — Phase 2: Download & Enrichment
- Metadata embedding into downloaded files (EXIF/IPTC/XMP for JPEG, WebP, AVIF, PNG, TIFF)
- Download endpoints: single file, batch ZIP, convert-to-PNG
- Grid/list view toggle with multi-select and batch download

### 2026-03-27–28 — Phase 1: MVP
- Full upload → AI analysis → semantic search pipeline
- React + TypeScript frontend with dark mode
- JWT authentication, rate limiting, standardized error responses
- Hash-based deduplication, content-addressed storage
- ChromaDB vector search with sentence-transformers (`all-MiniLM-L6-v2`)

