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
    email_verified: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    media_items: Mapped[list["MediaItem"]] = relationship(back_populates="user")
    sources: Mapped[list["Source"]] = relationship(back_populates="user")
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user")
    source_capability_snapshots: Mapped[list["SourceCapabilitySnapshot"]] = relationship(back_populates="user")
    writeback_operations: Mapped[list["WriteBackOperation"]] = relationship(back_populates="user")


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
    capability_snapshot: Mapped["SourceCapabilitySnapshot | None"] = relationship(back_populates="source", uselist=False)
    writeback_operations: Mapped[list["WriteBackOperation"]] = relationship(back_populates="source")


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
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="full", server_default="full")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"), nullable=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    phash_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phash_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Source mutation completion state (P7-004)
    # Values: fully_applied | pending_writeback | blocked_writeback | NULL (not yet determined)
    mutation_state: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    first_seen_source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prior_source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_filename_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_writeback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_mutation_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_mutation_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_mutation_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="media_items")
    source: Mapped["Source | None"] = relationship(back_populates="media_items")
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="media_item")
    analysis_metadata: Mapped["MediaMetadata | None"] = relationship(back_populates="media_item", uselist=False)
    curation_score: Mapped["CurationScore | None"] = relationship(back_populates="media_item", uselist=False)
    mutation_history: Mapped[list["SourceMutationHistory"]] = relationship(back_populates="media_item")
    # P9-003 origin/preview domain split
    origin_asset_ref: Mapped["OriginAssetRef | None"] = relationship(back_populates="media_item", uselist=False)
    preview_assets: Mapped[list["PreviewAsset"]] = relationship(back_populates="media_item")
    writeback_operations: Mapped[list["WriteBackOperation"]] = relationship(back_populates="media_item")


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
    # Provider-neutral remote container identity (P7-002: renamed from bucket_name)
    remote_container_id: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_container_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prefix: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Authorized-account snapshot (non-secret, informational — P7-002)
    authorized_account_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorized_account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorized_account_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Drive folder scoping (P7-002b): NULL = root of My Drive
    target_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_folder_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional collection to auto-add synced items to (P7-002b)
    target_collection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # OAuth scopes actually granted at authorization time (P7-004)
    # Stored as space-separated scope string (matches OAuth standard format).
    # NULL means pre-P7-004 connector authorized before this field was added.
    granted_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Auto-sync scheduler (P7-006)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    auto_sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    source: Mapped["Source"] = relationship(back_populates="connector")
    capability_snapshot: Mapped["SourceCapabilitySnapshot | None"] = relationship(back_populates="source_connector", uselist=False)
    writeback_operations: Mapped[list["WriteBackOperation"]] = relationship(back_populates="source_connector")


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


class OriginAssetRef(Base):
    """Item-owned canonical origin locator (P9-003 / ARCH-002).

    One row per MediaItem.  This is the authoritative origin reference used by
    application-layer consumers (source-aware reads, write-back, availability
    checks).  It does NOT replace SourceObject, which remains the source-scoped
    connector sync-memory record.

    Canonical ``provider_type`` values in this slice:
      google_drive | s3_compatible | local_folder | app_upload
    """
    __tablename__ = "origin_asset_refs"
    __table_args__ = (
        UniqueConstraint("media_item_id", name="uq_origin_asset_refs_media_item_id"),
        Index("ix_origin_asset_refs_user_id", "user_id"),
        Index("ix_origin_asset_refs_source_id", "source_id"),
        Index("ix_origin_asset_refs_source_object_id", "source_object_id"),
        Index("ix_origin_asset_refs_provider_type_provider_object_id",
              "provider_type", "provider_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    # Denormalized source join helper — mirrors MediaItem.source_id
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sources.id"), nullable=True
    )
    # FK to SourceObject; NULL for non-connector items and reference items whose
    # SourceObject has not yet been committed when OriginAssetRef was created.
    source_object_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_objects.id"), nullable=True
    )
    # Identifies the origin system.  Locked values for P9-003: see class docstring.
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Stable provider object identifier (e.g. Drive file ID, S3 key).
    provider_object_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Display-oriented path/key snapshot; for initial connector items same as provider_object_id.
    locator_snapshot: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Version / revision / etag marker from the source.
    revision_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # App-retained original path — authoritative for app_upload items.
    # Mirrors MediaItem.storage_path during rollout.
    app_storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Canonical local-folder fingerprint — authoritative for local_folder items.
    # Mirrors MediaItem.source_file_fingerprint during rollout.
    local_file_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    media_item: Mapped["MediaItem"] = relationship(back_populates="origin_asset_ref")
    writeback_operations: Mapped[list["WriteBackOperation"]] = relationship(back_populates="origin_asset_ref")


class PreviewAsset(Base):
    """Application-retained visual derivative used for gallery and detail preview (P9-003 / ARCH-002).

    One row per retained preview variant per MediaItem.
    Initial variant_type is 'thumbnail'.

    The authoritative preview path for a MediaItem is the PreviewAsset with
    variant_type='thumbnail'.  MediaItem.thumbnail_path is kept as a compatibility
    mirror during rollout.
    """
    __tablename__ = "preview_assets"
    __table_args__ = (
        UniqueConstraint("media_item_id", "variant_type", name="uq_preview_assets_item_variant"),
        Index("ix_preview_assets_user_id", "user_id"),
        Index("ix_preview_assets_storage_path", "storage_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_items.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    # Locked initial value: 'thumbnail'.  Future-safe for 'preview'.
    variant_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    media_item: Mapped["MediaItem"] = relationship(back_populates="preview_assets")


class SourceMutationHistory(Base):
    """Durable audit record of each source-mutation attempt for a media item (P7-004).

    One row per mutation attempt (rename or metadata write-back).
    The current mutation state lives on MediaItem; this table is the full history.
    """
    __tablename__ = "source_mutation_history"
    __table_args__ = (
        Index("ix_mutation_history_media_item_id", "media_item_id"),
        Index("ix_mutation_history_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # Operation type: rename | metadata_write
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prior_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Provider-specific snapshot: Drive file ID + version, path hint, etc. (JSON)
    source_locator_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hash of the metadata payload written back (for dedup / revision tracking)
    metadata_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    succeeded: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    media_item: Mapped["MediaItem"] = relationship(back_populates="mutation_history")


class SourceCapabilitySnapshot(Base):
    """Current connector-level capability record (P9-004 / ARCH-002)."""
    __tablename__ = "source_capability_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_source_capability_snapshots_source_id"),
        UniqueConstraint("source_connector_id", name="uq_source_capability_snapshots_connector_id"),
        Index("ix_source_capability_snapshots_user_id", "user_id"),
        Index("ix_source_capability_snapshots_provider_verification", "provider_type", "verification_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    source_connector_id: Mapped[str] = mapped_column(String(36), ForeignKey("source_connectors.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    can_read: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    can_write: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    can_refetch: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    scope_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    verification_state: Mapped[str] = mapped_column(String(20), nullable=False, default="current")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="source_capability_snapshots")
    source: Mapped["Source"] = relationship(back_populates="capability_snapshot")
    source_connector: Mapped["SourceConnector"] = relationship(back_populates="capability_snapshot")


class WriteBackOperation(Base):
    """Durable current write-back intent row (P9-004 / ARCH-002)."""
    __tablename__ = "writeback_operations"
    __table_args__ = (
        UniqueConstraint("media_item_id", "operation_type", name="uq_writeback_operations_item_operation"),
        Index("ix_writeback_operations_origin_asset_ref_id", "origin_asset_ref_id"),
        Index("ix_writeback_operations_user_id", "user_id"),
        Index("ix_writeback_operations_source_id", "source_id"),
        Index("ix_writeback_operations_source_connector_id", "source_connector_id"),
        Index("ix_writeback_operations_state_operation", "state", "operation_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    media_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("media_items.id"), nullable=False)
    origin_asset_ref_id: Mapped[str] = mapped_column(String(36), ForeignKey("origin_asset_refs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"), nullable=True)
    source_connector_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("source_connectors.id"), nullable=True)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_metadata_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_metadata_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="writeback_operations")
    media_item: Mapped["MediaItem"] = relationship(back_populates="writeback_operations")
    origin_asset_ref: Mapped["OriginAssetRef"] = relationship(back_populates="writeback_operations")
    source: Mapped["Source | None"] = relationship(back_populates="writeback_operations")
    source_connector: Mapped["SourceConnector | None"] = relationship(back_populates="writeback_operations")
