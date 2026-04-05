"""SQLAlchemy ORM models for users, media_items, and processing_jobs."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_name: Mapped[str] = mapped_column(String(50), nullable=False, default="basic")
    monthly_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    media_items: Mapped[list["MediaItem"]] = relationship(back_populates="user")
    sources: Mapped[list["Source"]] = relationship(back_populates="user")
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_audit_log_acting_admin_id", "acting_admin_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    acting_admin_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    target_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PendingToken(Base):
    __tablename__ = "pending_tokens"
    __table_args__ = (
        Index("ix_pending_tokens_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_type: Mapped[str] = mapped_column(String(30), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    new_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Connector summary fields (P5-003) — populated for connected sources only
    connector_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="sources")
    media_items: Mapped[list["MediaItem"]] = relationship(back_populates="source")
    connector: Mapped["SourceConnector | None"] = relationship(back_populates="source", uselist=False)


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_user_content_hash"),
        Index("ix_user_content_hash", "user_id", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"), nullable=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    phash_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phash_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="media_items")
    source: Mapped["Source | None"] = relationship(back_populates="media_items")
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="media_item")
    analysis_metadata: Mapped["MediaMetadata | None"] = relationship(back_populates="media_item", uselist=False)
    curation_score: Mapped["CurationScore | None"] = relationship(back_populates="media_item", uselist=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    media_item: Mapped["MediaItem"] = relationship(back_populates="processing_jobs")


class MediaMetadata(Base):
    __tablename__ = "media_metadata"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    objects: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    scenes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    context: Mapped[str] = mapped_column(Text, nullable=False)
    mood: Mapped[str] = mapped_column(String(100), nullable=False)
    people: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    people_count: Mapped[int] = mapped_column(Integer, nullable=False)
    orientation: Mapped[str] = mapped_column(String(20), nullable=False)
    colors: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    location_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quality_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    media_item: Mapped["MediaItem"] = relationship(back_populates="analysis_metadata")


class QuotaEvent(Base):
    __tablename__ = "quota_events"
    __table_args__ = (
        Index("ix_quota_events_user_period", "user_id", "period_month"),
        Index("ix_quota_events_user_period_type", "user_id", "period_month", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)  # reserved / consumed / released
    media_item_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=True)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class StripeEvent(Base):
    """Idempotency log for processed Stripe webhook events."""
    __tablename__ = "stripe_events"
    __table_args__ = (
        Index("ix_stripe_events_stripe_event_id", "stripe_event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    stripe_event_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CurationScore(Base):
    """AI quality score for a media item within a near-duplicate group (P5-002)."""
    __tablename__ = "curation_scores"
    __table_args__ = (
        Index("ix_curation_scores_media_item_id", "media_item_id", unique=True),
        Index("ix_curation_scores_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_model: Mapped[str] = mapped_column(String(100), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    media_item: Mapped["MediaItem"] = relationship(back_populates="curation_score")


class SourceConnector(Base):
    """One-to-one connector configuration for connected sources (P5-003)."""
    __tablename__ = "source_connectors"
    __table_args__ = (
        Index("ix_source_connectors_source_id", "source_id", unique=True),
        Index("ix_source_connectors_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bucket_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    source: Mapped["Source"] = relationship(back_populates="connector")


class SyncRun(Base):
    """One execution record per manual sync trigger (P5-003)."""
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_source_id", "source_id"),
        Index("ix_sync_runs_user_id", "user_id"),
        Index("ix_sync_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class SourceObject(Base):
    """Per-object sync memory — enables idempotent re-sync (P5-003)."""
    __tablename__ = "source_objects"
    __table_args__ = (
        Index("ix_source_objects_source_key", "source_id", "external_object_key", unique=True),
        Index("ix_source_objects_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    external_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    external_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_sync_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sync_runs.id"), nullable=True)
    last_imported_media_item_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class OAuthAccount(Base):
    """Provider-neutral external identity link for application users (P6-001).

    Enforces:
      - UNIQUE (provider, provider_user_id) — one local user per external identity
      - UNIQUE (user_id, provider) — at most one Google identity per local user in Phase 6
    """
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
        Index("ix_oauth_accounts_user_id", "user_id"),
        Index("ix_oauth_accounts_provider_email", "provider", "provider_email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_email_verified: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="oauth_accounts")


class GoogleCompletionRecord(Base):
    """Short-lived one-time record for backend-to-frontend SSO token handoff (P6-001).

    The ``flow_id`` is public (embedded in the frontend redirect URL).
    The ``completion_id_hash`` is derived from the secret completion ID that
    is delivered only via an HTTP-only browser cookie — the exchange endpoint
    validates both to prove browser ownership before issuing a JWT.
    """
    __tablename__ = "google_completion_records"
    __table_args__ = (
        Index("ix_completion_expires", "expires_at"),
        Index("ix_completion_user_id", "user_id"),
    )

    flow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    completion_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Collection(Base):
    """User-owned named group of media items (P7-001)."""
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_collection_user_name"),
        Index("ix_collections_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    items: Mapped[list["CollectionItem"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class CollectionItem(Base):
    """Join record linking a media item to a collection (P7-001)."""
    __tablename__ = "collection_items"
    __table_args__ = (
        UniqueConstraint("collection_id", "media_item_id", name="uq_collection_item"),
        Index("ix_collection_items_collection_id", "collection_id"),
        Index("ix_collection_items_media_item_id", "media_item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    collection_id: Mapped[str] = mapped_column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="items")
    media_item: Mapped["MediaItem"] = relationship()
