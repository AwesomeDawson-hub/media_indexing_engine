# Backend Dockerfile — Media Indexing Engine
# Builds the FastAPI backend with all production dependencies.

FROM python:3.11-slim

WORKDIR /app

# System dependencies required by some Python packages (Pillow, piexif, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY pyproject.toml ./

# Install CPU-only PyTorch BEFORE the main install to prevent sentence-transformers
# from pulling in the full CUDA stack (~2 GB). The embedding model runs fine on CPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -e ".[prod]"

# Copy application source
COPY src/ ./src/
COPY config/ ./config/
COPY alembic/ ./alembic/
COPY alembic.ini ./

EXPOSE 8000

# Run Alembic migrations then start the server.
# DATABASE_URL, AUTH_SECRET_KEY, and ANTHROPIC_API_KEY must be provided via
# environment variables — never bake secrets into the image.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.api.app:app --host 0.0.0.0 --port 8000"]
