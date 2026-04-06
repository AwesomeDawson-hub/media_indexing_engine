"""Pydantic response models for the API."""

from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class MediaItemResponse(BaseModel):
    id: str
    content_hash: str
    original_filename: str
    display_name: str | None = None
    file_size: int
    mime_type: str
    status: str
    width: int | None = None
    height: int | None = None
    source_id: str | None = None
    source_name: str | None = None
    created_at: datetime
    # Duplicate-detection summary (populated when feature gate is ON)
    has_similar: bool = False
    similar_count: int = 0

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    id: str
    content_hash: str
    original_filename: str
    file_size: int
    mime_type: str
    status: str
    is_duplicate: bool
    message: str | None = None
    created_at: datetime


class BatchFileResult(BaseModel):
    filename: str
    status: str  # "created" | "duplicate" | "error"
    id: str | None = None
    content_hash: str | None = None
    error: str | None = None


class BatchUploadResponse(BaseModel):
    total: int
    successful: int
    duplicates: int
    failed: int
    results: list[BatchFileResult]


class PaginatedResponse(BaseModel):
    items: list[MediaItemResponse]
    total: int
    page: int
    per_page: int


class MetadataFields(BaseModel):
    title: str
    description: str
    tags: list[str]
    objects: list[str]
    scenes: list[str]
    context: str
    mood: str
    people: list[str]
    people_count: int
    orientation: str
    colors: list[str]
    location_hint: str | None = None
    quality_notes: str | None = None
    ocr_text: str | None = None


class JobInfo(BaseModel):
    id: str
    status: str
    attempts: int
    error_message: str | None = None
    created_at: datetime


class AnalysisResponse(BaseModel):
    media_item_id: str
    status: str
    metadata: MetadataFields | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    analyzed_at: datetime | None = None
    job: JobInfo | None = None


class ReanalyzeRequest(BaseModel):
    hint: str | None = Field(default=None, max_length=500)


class ReanalyzeResponse(BaseModel):
    media_item_id: str
    job_id: str
    message: str


class MetadataUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tags: list[str] | None = None
    objects: list[str] | None = None
    scenes: list[str] | None = None
    context: str | None = None
    mood: str | None = Field(default=None, max_length=100)
    people: list[str] | None = None
    people_count: int | None = Field(default=None, ge=0)
    orientation: str | None = Field(default=None, max_length=20)
    colors: list[str] | None = None
    location_hint: str | None = Field(default=None, max_length=200)
    quality_notes: str | None = None


class SearchMediaItem(BaseModel):
    id: str
    original_filename: str
    mime_type: str
    status: str
    width: int | None = None
    height: int | None = None
    created_at: datetime


class SearchMetadataSubset(BaseModel):
    title: str
    description: str
    tags: list[str]
    mood: str


class SearchResultItemResponse(BaseModel):
    media_item: SearchMediaItem
    metadata: SearchMetadataSubset
    score: float


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    per_page: int
    results: list[SearchResultItemResponse]


# Source schemas are defined in the P5-003 connector section below.

# Auth schemas

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    role: str = "user"
    phone: str | None = None
    company: str | None = None
    icon_url: str | None = None
    disabled_at: datetime | None = None
    plan_name: str = "basic"
    monthly_limit: int = 500
    billing_status: str = "none"
    stripe_customer_id: str | None = None
    email_verified: bool = False

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile
    verification_token: str | None = None  # Only present in dev_mode on registration


class VerifyEmailRequest(BaseModel):
    token: str


# Download schemas

class BatchDownloadRequest(BaseModel):
    media_ids: list[str]


class ConvertResponse(BaseModel):
    id: str
    original_filename: str
    mime_type: str
    status: str
    message: str


class GoogleExchangeRequest(BaseModel):
    flow_id: str


class BatchOperationRequest(BaseModel):
    media_ids: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("media_ids")
    @classmethod
    def no_empty_ids(cls, v: list[str]) -> list[str]:
        if any(not item.strip() for item in v):
            raise ValueError("media_ids must not contain empty strings")
        return v


class BatchReanalyzeResponse(BaseModel):
    queued: int
    message: str


class BatchDeleteResponse(BaseModel):
    deleted: int
    message: str


class BatchTagRequest(BaseModel):
    media_ids: list[str] = Field(..., min_length=1, max_length=50)
    tags: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("media_ids")
    @classmethod
    def no_empty_ids(cls, v: list[str]) -> list[str]:
        if any(not item.strip() for item in v):
            raise ValueError("media_ids must not contain empty strings")
        return v

    @field_validator("tags")
    @classmethod
    def no_empty_tags(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v if t.strip()]
        if not cleaned:
            raise ValueError("tags must not be all empty strings")
        return cleaned


class BatchTagResponse(BaseModel):
    updated: int
    message: str


class QuotaStatusResponse(BaseModel):
    plan_name: str
    monthly_limit: int
    consumed: int
    reserved: int
    remaining: int
    period_month: str  # "YYYY-MM"


class QuotaHistoryItem(BaseModel):
    id: str
    event_type: str  # "reserved" | "consumed" | "released"
    media_item_id: str | None
    original_filename: str | None
    created_at: datetime
    period_month: str  # "YYYY-MM"


class QuotaHistoryResponse(BaseModel):
    items: list[QuotaHistoryItem]
    total: int
    page: int
    per_page: int
    period_month: str  # "YYYY-MM"


class QuotaDayItem(BaseModel):
    date: str   # "YYYY-MM-DD"
    count: int


class QuotaDailyUsageResponse(BaseModel):
    days: list[QuotaDayItem]
    period_month: str  # "YYYY-MM"


# Admin + profile schemas

class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    icon_url: str | None = Field(default=None, max_length=500)


class AdminUserSummary(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    phone: str | None = None
    company: str | None = None
    icon_url: str | None = None
    plan_name: str
    monthly_limit: int
    billing_status: str = "none"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    disabled_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserDetailResponse(AdminUserSummary):
    quota_this_month: int = 0


class AdminUpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    icon_url: str | None = Field(default=None, max_length=500)
    plan_name: str | None = None
    monthly_limit: int | None = Field(default=None, ge=0)
    role: str | None = None
    disabled: bool | None = None
    billing_status: str | None = None


class AuditLogEntry(BaseModel):
    id: str
    action: str
    detail: str | None = None
    target_user_id: str | None = None
    acting_admin_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUsersListResponse(BaseModel):
    users: list[AdminUserSummary]
    total: int


class AuditLogListResponse(BaseModel):
    entries: list[AuditLogEntry]
    total: int


# Token-based flows

class EmailChangeRequest(BaseModel):
    new_email: str


class EmailChangeConfirmRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


# Billing schemas

class BillingStatusResponse(BaseModel):
    billing_status: str
    plan_name: str
    monthly_limit: int
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    model_config = {"from_attributes": True}


class CheckoutSessionRequest(BaseModel):
    price_id: str


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


# Near-duplicate detection schemas (P5-001) + AI scoring (P5-002)

class SimilarItemResponse(BaseModel):
    id: str
    hamming_distance: int
    media_item: MediaItemResponse
    # AI quality scoring — populated when enable_ai_scoring gate is ON and item
    # has been scored. Null values mean "not yet scored"; they are not an error.
    quality_score: float | None = None
    rationale: str | None = None
    is_best_pick: bool = False


class SimilarItemsResponse(BaseModel):
    anchor_id: str
    similar: list[SimilarItemResponse]
    # Anchor's own AI quality score (P5-002) — null when not yet scored
    anchor_quality_score: float | None = None
    anchor_rationale: str | None = None
    anchor_is_best_pick: bool = False


class ScoreGroupResponse(BaseModel):
    """Response from POST /media/{id}/score-group (P5-002)."""
    anchor_id: str
    scored_count: int
    failed_count: int
    best_pick_id: str | None = None
    message: str


# ---------------------------------------------------------------------------
# Source connector schemas (P5-003)
# ---------------------------------------------------------------------------

class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    archived_at: datetime | None = None
    created_at: datetime
    media_count: int = 0
    # Connector summary (only meaningful for connected sources)
    connector_status: str | None = None
    last_synced_at: datetime | None = None

    model_config = {"from_attributes": True}


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_type: str = Field(default="manual")


class ConnectorS3ConfigRequest(BaseModel):
    """Request body for POST /sources/{id}/connector/s3."""
    # bucket_name is the S3-specific UI label; stored as remote_container_id in DB
    bucket_name: str = Field(..., min_length=1, max_length=255)
    access_key_id: str = Field(..., min_length=1, max_length=256)
    secret_access_key: str = Field(..., min_length=1, max_length=512)
    region: str | None = Field(default=None, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=500)
    prefix: str | None = Field(default=None, max_length=500)


class ConnectorResponse(BaseModel):
    """Connector configuration response — never exposes secrets."""
    id: str
    source_id: str
    connector_type: str
    # Provider-neutral container fields (P7-002)
    remote_container_id: str
    remote_container_label: str | None = None
    authorized_account_provider_id: str | None = None
    authorized_account_email: str | None = None
    authorized_account_display_name: str | None = None
    # Drive folder scoping (P7-002b)
    target_folder_id: str | None = None
    target_folder_label: str | None = None
    target_collection_id: str | None = None
    prefix: str | None = None
    region: str | None = None
    endpoint_url: str | None = None
    config_validated_at: datetime | None = None
    last_validation_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorDriveStartResponse(BaseModel):
    """Response from POST /sources/{id}/connector/google-drive/start."""
    authorization_url: str


class ConnectorDriveQuickConnectRequest(BaseModel):
    """Body for POST /api/v1/connectors/google-drive/quick-connect."""
    source_name: str | None = None  # Defaults to "Google Drive" if omitted


class DriveFolderItem(BaseModel):
    """One folder entry returned by the Drive folder browser."""
    id: str
    name: str
    has_children: bool = False


class DriveFoldersResponse(BaseModel):
    """Response from GET /sources/{id}/connector/google-drive/folders."""
    parent_id: str
    folders: list[DriveFolderItem]


class ConnectorDriveConfigureRequest(BaseModel):
    """Body for POST /sources/{id}/connector/google-drive/configure."""
    target_folder_id: str | None = None   # None or omitted = root (My Drive)
    target_folder_label: str | None = None
    target_collection_id: str | None = None


class SyncRunResponse(BaseModel):
    """One sync run record."""
    id: str
    source_id: str
    connector_type: str
    trigger_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    discovered_count: int = 0
    imported_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_summary: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncRunsResponse(BaseModel):
    """Paginated list of sync runs."""
    runs: list[SyncRunResponse]
    total: int


class TriggerSyncResponse(BaseModel):
    """Immediate response from POST /sources/{id}/sync."""
    sync_run_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Collections (P7-001)
# ---------------------------------------------------------------------------

class CollectionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class CollectionUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str | None
    item_count: int
    cover_url: str | None  # thumbnail URL of the first item, or None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CollectionListResponse(BaseModel):
    collections: list[CollectionResponse]
    total: int


class CollectionItemsRequest(BaseModel):
    """Batch add or remove media item IDs."""
    media_item_ids: list[str] = Field(..., min_length=1, max_length=500)


class CollectionDetailResponse(BaseModel):
    id: str
    name: str
    description: str | None
    item_count: int
    created_at: str
    updated_at: str
    items: list["MediaItemResponse"]

    class Config:
        from_attributes = True


class CollectionItemsModifiedResponse(BaseModel):
    added: int = 0
    removed: int = 0
    skipped: int = 0
