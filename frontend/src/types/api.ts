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
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
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
