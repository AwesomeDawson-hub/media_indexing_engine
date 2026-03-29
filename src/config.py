"""Application configuration loaded from settings.yaml."""

from pathlib import Path
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

# Load .env from project root (before anything reads os.environ)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

CONFIG_DIR = _PROJECT_ROOT / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"


@dataclass
class AppConfig:
    name: str = "Media Indexing Engine"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])


@dataclass
class StorageConfig:
    provider: str = "local"
    local_path: str = "./uploads"


@dataclass
class DatabaseConfig:
    url: str = "sqlite+aiosqlite:///./media_index.db"


@dataclass
class UploadConfig:
    max_file_size_mb: int = 50
    max_batch_size: int = 20
    allowed_mime_types: list[str] = field(default_factory=lambda: [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "image/gif",
        "image/avif",
    ])

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@dataclass
class ProcessingConfig:
    max_attempts: int = 3


@dataclass
class AnalysisConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_image_dimension: int = 1568
    max_concurrent: int = 5
    timeout_seconds: int = 60


@dataclass
class SearchConfig:
    provider: str = "chromadb"
    collection_name: str = "media_embeddings"
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = 20
    persist_directory: str = "./chromadb_data"


@dataclass
class AuthConfig:
    secret_key: str = "dev-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    dev_mode: bool = True


@dataclass
class DownloadConfig:
    max_batch_size: int = 50


@dataclass
class Settings:
    app: AppConfig = field(default_factory=AppConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    """Load settings from a YAML file. Falls back to defaults if file is missing."""
    if not path.exists():
        return Settings()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    s = Settings(
        app=AppConfig(**raw.get("app", {})),
        storage=StorageConfig(**raw.get("storage", {})),
        database=DatabaseConfig(**raw.get("database", {})),
        upload=UploadConfig(**raw.get("upload", {})),
        processing=ProcessingConfig(**raw.get("processing", {})),
        analysis=AnalysisConfig(**raw.get("analysis", {})),
        search=SearchConfig(**raw.get("search", {})),
        auth=AuthConfig(**raw.get("auth", {})),
        download=DownloadConfig(**raw.get("download", {})),
    )

    # Override secret key from env var if set (production override)
    import os
    env_secret = os.environ.get("AUTH_SECRET_KEY")
    if env_secret:
        s.auth.secret_key = env_secret

    return s


settings = load_settings()
