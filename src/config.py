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
class CurationConfig:
    # When True: Gallery responses include has_similar / similar_count fields
    # and the Media Detail page shows the similar photos panel.
    # New uploads always receive a perceptual hash regardless of this flag.
    enable_duplicate_detection: bool = False
    # When True: AI quality scoring endpoints are active. Requires
    # enable_duplicate_detection to also be True. Default OFF.
    enable_ai_scoring: bool = False


@dataclass
class ConnectorConfig:
    # Base64-url-safe Fernet key for encrypting connector credentials at rest.
    # Must be set via CONNECTOR_CREDENTIALS_KEY env var in production.
    # If absent, all connector create/update/sync paths refuse to run.
    credentials_key: str = ""
    # Maximum number of objects to enumerate from a remote source per sync run.
    # Protects against runaway enumeration on large buckets.
    max_objects_per_sync: int = 1000


@dataclass
class GoogleAuthConfig:
    """Google OAuth2 / OpenID Connect configuration (P6-001).

    All traffic to Google SSO routes is blocked when ``is_ready`` is False.
    """
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    # Full backend callback URL (e.g. https://vyzindex.com/api/v1/auth/google/callback).
    # Computed from request.base_url when empty (works for local dev).
    # Must be set explicitly in production behind a reverse proxy.
    redirect_uri: str = ""
    # Frontend base URL for redirecting the browser after the backend callback.
    # Falls back to email.app_url when empty.
    frontend_url: str = ""

    @property
    def is_ready(self) -> bool:
        """True only when the gate is ON and both Google credentials are present."""
        return self.enabled and bool(self.client_id) and bool(self.client_secret)


@dataclass
class GoogleDriveConfig:
    """Google Drive connector OAuth2 configuration (P7-002).

    Uses a dedicated OAuth client separate from Google SSO (P6-001).
    All connector routes are blocked when ``is_ready`` is False.
    """
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    # Full backend callback URL. Must be set in production behind a reverse proxy.
    redirect_uri: str = ""
    # Frontend base URL for redirecting after callback. Falls back to email.app_url.
    frontend_url: str = ""

    @property
    def is_ready(self) -> bool:
        """True only when the gate is ON and both credentials are present."""
        return self.enabled and bool(self.client_id) and bool(self.client_secret)


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
    curation: CurationConfig = field(default_factory=CurationConfig)
    connector: ConnectorConfig = field(default_factory=ConnectorConfig)
    google: GoogleAuthConfig = field(default_factory=GoogleAuthConfig)
    google_drive: GoogleDriveConfig = field(default_factory=GoogleDriveConfig)


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
        curation=CurationConfig(**raw.get("curation", {})),
        connector=ConnectorConfig(**raw.get("connector", {})),
        google=GoogleAuthConfig(**{k: v for k, v in raw.get("google", {}).items()
                                   if k in ("enabled", "client_id", "client_secret",
                                            "redirect_uri", "frontend_url")}),
    )

    # Override secret key from env var if set (production override)
    import os
    env_secret = os.environ.get("AUTH_SECRET_KEY")
    if env_secret:
        s.auth.secret_key = env_secret

    # Override dev_mode from env var — set AUTH_DEV_MODE=false in production
    env_dev_mode = os.environ.get("AUTH_DEV_MODE")
    if env_dev_mode is not None:
        s.auth.dev_mode = env_dev_mode.lower() not in ("false", "0", "no")

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

    env_dup_detection = os.environ.get("ENABLE_DUPLICATE_DETECTION")
    if env_dup_detection is not None:
        s.curation.enable_duplicate_detection = env_dup_detection.lower() in ("1", "true", "yes")

    env_ai_scoring = os.environ.get("ENABLE_AI_SCORING")
    if env_ai_scoring is not None:
        s.curation.enable_ai_scoring = env_ai_scoring.lower() in ("1", "true", "yes")

    env_connector_key = os.environ.get("CONNECTOR_CREDENTIALS_KEY")
    if env_connector_key:
        s.connector.credentials_key = env_connector_key

    env_google_sso = os.environ.get("ENABLE_GOOGLE_SSO")
    if env_google_sso is not None:
        s.google.enabled = env_google_sso.lower() in ("1", "true", "yes")

    env_google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if env_google_client_id:
        s.google.client_id = env_google_client_id

    env_google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if env_google_client_secret:
        s.google.client_secret = env_google_client_secret

    env_google_redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if env_google_redirect_uri:
        s.google.redirect_uri = env_google_redirect_uri

    env_google_frontend_url = os.environ.get("GOOGLE_FRONTEND_URL")
    if env_google_frontend_url:
        s.google.frontend_url = env_google_frontend_url

    env_gdrive_enabled = os.environ.get("ENABLE_GOOGLE_DRIVE_CONNECTOR")
    if env_gdrive_enabled is not None:
        s.google_drive.enabled = env_gdrive_enabled.lower() in ("1", "true", "yes")

    env_gdrive_client_id = os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
    if env_gdrive_client_id:
        s.google_drive.client_id = env_gdrive_client_id

    env_gdrive_client_secret = os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET")
    if env_gdrive_client_secret:
        s.google_drive.client_secret = env_gdrive_client_secret

    env_gdrive_redirect_uri = os.environ.get("GOOGLE_DRIVE_REDIRECT_URI")
    if env_gdrive_redirect_uri:
        s.google_drive.redirect_uri = env_gdrive_redirect_uri

    env_gdrive_frontend_url = os.environ.get("GOOGLE_DRIVE_FRONTEND_URL")
    if env_gdrive_frontend_url:
        s.google_drive.frontend_url = env_gdrive_frontend_url

    return s


settings = load_settings()
