export interface UserProfile {
  id: string;
  email: string;
  display_name: string;
  role: string;
  phone?: string | null;
  company?: string | null;
  icon_url?: string | null;
  disabled_at?: string | null;
  plan_name: string;
  monthly_limit: number;
  billing_status: string;
  stripe_customer_id?: string | null;
  email_verified: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
  verification_token?: string | null;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthConfig {
  google_sso_enabled: boolean;
}

export interface GoogleExchangeRequest {
  flow_id: string;
}

export interface UploadResponse {
  id: string;
  content_hash: string;
  original_filename: string;
  file_size: number;
  mime_type: string;
  status: string;
  is_duplicate: boolean;
  message?: string;
  created_at: string;
}

export interface BatchFileResult {
  filename: string;
  status: string;
  id?: string;
  content_hash?: string;
  error?: string;
}

export interface BatchUploadResponse {
  total: number;
  successful: number;
  duplicates: number;
  failed: number;
  results: BatchFileResult[];
}

export interface MediaItemResponse {
  id: string;
  content_hash: string;
  original_filename: string;
  display_name?: string;
  file_size: number;
  mime_type: string;
  status: string;
  width?: number;
  height?: number;
  source_id?: string;
  source_name?: string;
  created_at: string;
  has_similar?: boolean;
  similar_count?: number;
}

export interface SimilarItemResponse {
  id: string;
  hamming_distance: number;
  media_item: MediaItemResponse;
  quality_score?: number | null;
  rationale?: string | null;
  is_best_pick?: boolean;
}

export interface SimilarItemsResponse {
  anchor_id: string;
  similar: SimilarItemResponse[];
  anchor_quality_score?: number | null;
  anchor_rationale?: string | null;
  anchor_is_best_pick?: boolean;
}

export interface ScoreGroupResponse {
  anchor_id: string;
  scored_count: number;
  failed_count: number;
  best_pick_id?: string | null;
  message: string;
}

export interface PaginatedResponse {
  items: MediaItemResponse[];
  total: number;
  page: number;
  per_page: number;
}

export interface MetadataFields {
  title: string;
  description: string;
  tags: string[];
  objects: string[];
  scenes: string[];
  context: string;
  mood: string;
  people: string[];
  people_count: number;
  orientation: string;
  colors: string[];
  location_hint?: string;
  quality_notes?: string;
  ocr_text?: string | null;
}

export interface JobInfo {
  id: string;
  status: string;
  attempts: number;
  error_message?: string;
  created_at: string;
}

export interface AnalysisResponse {
  media_item_id: string;
  status: string;
  metadata?: MetadataFields;
  ai_provider?: string;
  ai_model?: string;
  analyzed_at?: string;
  job?: JobInfo;
}

export interface ReanalyzeResponse {
  media_item_id: string;
  job_id: string;
  message: string;
}

export interface SearchResultItem {
  media_item: {
    id: string;
    original_filename: string;
    mime_type: string;
    status: string;
    width?: number;
    height?: number;
    created_at: string;
  };
  metadata: {
    title: string;
    description: string;
    tags: string[];
    mood: string;
  };
  score: number;
}

export interface QuotaStatus {
  plan_name: string;
  monthly_limit: number;
  consumed: number;
  reserved: number;
  remaining: number;
  period_month: string; // "YYYY-MM"
}

export interface QuotaHistoryItem {
  id: string;
  event_type: 'reserved' | 'consumed' | 'released';
  media_item_id: string | null;
  original_filename: string | null;
  created_at: string;
  period_month: string;
}

export interface QuotaHistoryResponse {
  items: QuotaHistoryItem[];
  total: number;
  page: number;
  per_page: number;
  period_month: string;
}

export interface QuotaDayItem {
  date: string; // "YYYY-MM-DD"
  count: number;
}

export interface QuotaDailyUsageResponse {
  days: QuotaDayItem[];
  period_month: string; // "YYYY-MM"
}

export interface SearchResponse {
  query: string;
  total: number;
  page: number;
  per_page: number;
  results: SearchResultItem[];
}

export interface SourceResponse {
  id: string;
  name: string;
  source_type: string;
  archived_at?: string | null;
  created_at: string;
  media_count: number;
  connector_status?: string | null;
  last_synced_at?: string | null;
}

// P5-003 Connector / sync types

export interface ConnectorS3ConfigRequest {
  bucket_name: string;
  access_key_id: string;
  secret_access_key: string;
  region?: string;
  endpoint_url?: string;
  prefix?: string;
}

export interface ConnectorResponse {
  id: string;
  source_id: string;
  connector_type: string;
  remote_container_id: string;
  remote_container_label: string | null;
  authorized_account_email: string | null;
  authorized_account_display_name: string | null;
  prefix?: string | null;
  region?: string | null;
  endpoint_url?: string | null;
  config_validated_at?: string | null;
  last_validation_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorDriveStartResponse {
  authorization_url: string;
}

export interface SyncRunResponse {
  id: string;
  source_id: string;
  connector_type: string;
  trigger_type: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  discovered_count: number;
  imported_count: number;
  duplicate_count: number;
  skipped_count: number;
  failed_count: number;
  error_summary?: string | null;
  created_at: string;
}

export interface SyncRunsResponse {
  runs: SyncRunResponse[];
  total: number;
}

export interface TriggerSyncResponse {
  sync_run_id: string;
  status: string;
  message: string;
}

export interface ApiError {
  detail: string;
  error_code: string;
  error?: string;
  remaining?: number;
  limit?: number;
  archived_source_id?: string;
}

export interface AdminUserSummary {
  id: string;
  email: string;
  display_name: string;
  role: string;
  phone?: string | null;
  company?: string | null;
  icon_url?: string | null;
  plan_name: string;
  monthly_limit: number;
  billing_status: string;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  disabled_at?: string | null;
  created_at: string;
}

export interface AdminUserDetail extends AdminUserSummary {
  quota_this_month: number;
}

export interface AdminUsersListResponse {
  users: AdminUserSummary[];
  total: number;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  detail?: string | null;
  target_user_id?: string | null;
  acting_admin_id: string;
  created_at: string;
}

export interface AuditLogListResponse {
  entries: AuditLogEntry[];
  total: number;
}

export interface BillingStatus {
  billing_status: string;
  plan_name: string;
  monthly_limit: number;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
}

export interface PortalSessionResponse {
  portal_url: string;
}

// Collections (P7-001)
export interface CollectionResponse {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  cover_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectionListResponse {
  collections: CollectionResponse[];
  total: number;
}

export interface CollectionDetailResponse {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string;
  updated_at: string;
  items: MediaItemResponse[];
}

export interface CollectionItemsModifiedResponse {
  added: number;
  removed: number;
  skipped: number;
}
