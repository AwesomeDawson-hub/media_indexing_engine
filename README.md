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

---

