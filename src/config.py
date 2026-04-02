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
    # S3 settings (used when provider == "s3")
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""  # Optional: for S3-compatible stores (MinIO, etc.)


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
class StripeConfig:
    secret_key: str = ""
    webhook_secret: str = ""
    test_mode: bool = True
    price_id_advanced: str = ""
    price_id_premium: str = ""


@dataclass
class EmailConfig:
    from_address: str = ""          # e.g. noreply@vyzindex.com — empty = sending disabled
    aws_region: str = "us-east-1"
    app_url: str = "https://vyzindex.com"


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
    stripe: StripeConfig = field(default_factory=StripeConfig)
    email: EmailConfig = field(default_factory=EmailConfig)


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
        stripe=StripeConfig(**raw.get("stripe", {})),
        email=EmailConfig(**raw.get("email", {})),
    )

    # Override secret key from env var if set (production override)
    import os
    env_secret = os.environ.get("AUTH_SECRET_KEY")
    if env_secret:
        s.auth.secret_key = env_secret

    # Override database URL from env var (production / Docker override)
    env_db_url = os.environ.get("DATABASE_URL")
    if env_db_url:
        s.database.url = env_db_url

    # Override storage provider from env var
    env_storage_provider = os.environ.get("STORAGE_PROVIDER")
    if env_storage_provider:
        s.storage.provider = env_storage_provider

    env_s3_bucket = os.environ.get("S3_BUCKET")
    if env_s3_bucket:
        s.storage.s3_bucket = env_s3_bucket

    env_s3_region = os.environ.get("S3_REGION")
    if env_s3_region:
        s.storage.s3_region = env_s3_region

    env_stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    if env_stripe_secret:
        s.stripe.secret_key = env_stripe_secret

    env_stripe_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if env_stripe_webhook:
        s.stripe.webhook_secret = env_stripe_webhook

    env_stripe_advanced = os.environ.get("STRIPE_PRICE_ID_ADVANCED")
    if env_stripe_advanced:
        s.stripe.price_id_advanced = env_stripe_advanced

    env_stripe_premium = os.environ.get("STRIPE_PRICE_ID_PREMIUM")
    if env_stripe_premium:
        s.stripe.price_id_premium = env_stripe_premium

    env_email_from = os.environ.get("EMAIL_FROM")
    if env_email_from:
        s.email.from_address = env_email_from

    env_email_region = os.environ.get("EMAIL_AWS_REGION")
    if env_email_region:
        s.email.aws_region = env_email_region

    return s


settings = load_settings()
