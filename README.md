# Media Indexing Engine

An AI-powered system that analyzes photos and videos, enriches their metadata, and enables fast semantic search across large media libraries.

## Overview

Media Indexing Engine automates the organization and retrieval of media files. Users upload or connect a media source, and the system automatically analyzes each file using vision AI models, extracts meaningful metadata (objects, scenes, context), and indexes it for fast natural language search.

## Target Users

- **Photographers** managing large volumes of photos who need automated organization, tagging, and retrieval
- **Marketing teams** who need to quickly find relevant, high-quality images for campaigns and content
- **Content teams and small businesses** managing growing media libraries

## Key Capabilities (V1)

- Upload media via local folder upload or drag-and-drop
- Automatic AI-powered analysis and metadata enrichment (objects, scenes, context)
- Natural language semantic search (e.g., "team meeting in office," "sunset beach portrait")
- Hash-based deduplication to avoid redundant processing
- Simple, non-technical user interface
- Authenticated web-based access

## Architecture (High-Level)

```
frontend/          → Web UI (upload, search, browse)
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

## Constraints (V1)

- **Platform:** Web-based, browser-accessible
- **Auth:** Login required
- **Input:** Local folder upload and drag-and-drop (cloud integrations deferred)
- **Media:** Images first; video support deferred
- **AI:** Existing vision models only (no custom training)
- **Storage:** Cloud-based storage and metadata indexing
- **Scale:** Batch uploads supported; extreme scale optimization deferred
- **Deduplication:** Hash-based, no reprocessing of identical files

## Getting Started

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
python -m pytest tests/ -q
```

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

Important caveats:

- some browsers will cache a failed HTTPS attempt or force HTTPS automatically; use an Incognito/InPrivate window if the normal browser keeps refusing the connection
- this is a temporary beta-only workaround
- once a real domain is attached, switch `DOMAIN` back to that domain and restore the default HTTPS Caddyfile

---

## Known Configuration Notes

- **Upload size limit:** The nginx frontend is configured to accept files up to **50 MB** (`client_max_body_size 50M`). Adjust `frontend/nginx.conf` if you need a different limit.
- **File storage:** Local disk by default (`storage.provider: local`). Set `STORAGE_PROVIDER=s3` and the S3 env vars to enable S3-backed storage.
- **AI analysis:** Requires a valid `ANTHROPIC_API_KEY`. Without it, uploads will succeed but AI analysis jobs will fail silently in the background.

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

