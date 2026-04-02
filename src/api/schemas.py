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


class ReanalyzeResponse(BaseModel):
    media_item_id: str
    job_id: str
    message: str


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


# Source schemas

class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    archived_at: datetime | None = None
    created_at: datetime
    media_count: int = 0

    model_config = {"from_attributes": True}


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_type: str = Field(default="manual")


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

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


# Download schemas

class BatchDownloadRequest(BaseModel):
    media_ids: list[str]


class ConvertResponse(BaseModel):
    id: str
    original_filename: str
    mime_type: str
    status: str
    message: str


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


class QuotaStatusResponse(BaseModel):
    plan_name: str
    monthly_limit: int
    consumed: int
    reserved: int
    remaining: int
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
