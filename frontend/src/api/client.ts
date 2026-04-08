import type {
  AuthResponse,
  AuthConfig,
  UserProfile,
  UploadResponse,
  BatchUploadResponse,
  PaginatedResponse,
  MediaItemResponse,
  SimilarItemsResponse,
  ScoreGroupResponse,
  AnalysisResponse,
  ReanalyzeResponse,
  SearchResponse,
  QuotaStatus,
  SourceResponse,
  ApiError,
  AdminUserSummary,
  AdminUserDetail,
  AdminUsersListResponse,
  AuditLogListResponse,
  BillingStatus,
  CheckoutSessionResponse,
  PortalSessionResponse,
  ConnectorS3ConfigRequest,
  ConnectorS3UpdateRequest,
  ConnectorResponse,
  ConnectorDriveStartResponse,
  DriveFoldersResponse,
  ConnectorDriveConfigureRequest,
  SyncRunsResponse,
  TriggerSyncResponse,
  QuotaHistoryResponse,
  QuotaDailyUsageResponse,
  CollectionListResponse,
  CollectionDetailResponse,
  CollectionResponse,
  CollectionItemsModifiedResponse,
  MutationStateResponse,
  LocalMutationResultRequest,
} from '../types/api';

const BASE_URL = '';

// ---------------------------------------------------------------------------
// In-memory API cache — avoids redundant round-trips when navigating back to
// an already-fetched media item. Analysis is only cached once terminal so that
// in-flight polling continues to fetch fresh data.
// ---------------------------------------------------------------------------
const _apiCache = new Map<string, { data: unknown; ts: number }>();
const API_CACHE_TTL = 60_000; // 60 s

function fromCache<T>(key: string): T | null {
  const entry = _apiCache.get(key);
  if (entry && Date.now() - entry.ts < API_CACHE_TTL) return entry.data as T;
  return null;
}

function toCache(key: string, data: unknown): void {
  _apiCache.set(key, { data, ts: Date.now() });
}

export function invalidateMediaCache(id: string): void {
  _apiCache.delete(`media:${id}`);
  _apiCache.delete(`analysis:${id}`);
}

export function clearApiCache(): void {
  _apiCache.clear();
}

export class ApiRequestError extends Error {
  status: number;
  errorCode: string;
  error?: string;
  remaining?: number;
  limit?: number;
  archivedSourceId?: string;

  constructor(status: number, data: ApiError) {
    super(data.detail || 'Request failed');
    this.name = 'ApiRequestError';
    this.status = status;
    this.errorCode = data.error_code;
    this.error = data.error;
    this.remaining = data.remaining;
    this.limit = data.limit;
    this.archivedSourceId = data.archived_source_id;
  }
}

function getToken(): string | null {
  return localStorage.getItem('auth_token');
}

function setToken(token: string): void {
  localStorage.setItem('auth_token', token);
}

function clearToken(): void {
  localStorage.removeItem('auth_token');
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const isFormData = options.body instanceof FormData;

  const headers = new Headers();

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // Don't set Content-Type for FormData — browser sets it with boundary automatically
  if (!isFormData) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && token) {
    // Token was present but rejected (expired/invalid) — clear and redirect
    clearToken();
    window.location.href = '/login';
    throw new Error('Session expired');
  }

  if (!response.ok) {
    const error = await response.json().catch((): ApiError => ({
      detail: 'Request failed',
      error_code: 'unknown',
    }));
    throw new ApiRequestError(response.status, error);
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<AuthResponse> {
  const data = await request<AuthResponse>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  setToken(data.access_token);
  return data;
}

export async function login(
  email: string,
  password: string,
): Promise<AuthResponse> {
  const data = await request<AuthResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  return data;
}

export async function getProfile(): Promise<UserProfile> {
  return request<UserProfile>('/api/v1/auth/me');
}

export async function getAuthConfig(): Promise<AuthConfig> {
  return request<AuthConfig>('/api/v1/auth/config');
}

export async function exchangeGoogleAuth(flowId: string): Promise<AuthResponse> {
  const data = await fetch('/api/v1/auth/google/exchange', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include', // send HTTP-only completion cookie
    body: JSON.stringify({ flow_id: flowId }),
  });
  if (!data.ok) {
    const err = await data.json().catch((): ApiError => ({ detail: 'Exchange failed', error_code: 'unknown' }));
    throw new ApiRequestError(data.status, err);
  }
  const result = await data.json() as AuthResponse;
  setToken(result.access_token);
  return result;
}

export async function uploadFile(file: File, sourceId?: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (sourceId) formData.append('source_id', sourceId);
  return request<UploadResponse>('/api/v1/upload', {
    method: 'POST',
    body: formData,
  });
}

export async function uploadBatch(files: File[], sourceId?: string): Promise<BatchUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  if (sourceId) formData.append('source_id', sourceId);
  return request<BatchUploadResponse>('/api/v1/upload/batch', {
    method: 'POST',
    body: formData,
  });
}

export async function listMedia(
  page: number = 1,
  perPage: number = 20,
): Promise<PaginatedResponse> {
  return request<PaginatedResponse>(
    `/api/v1/media?page=${page}&per_page=${perPage}`,
  );
}

export async function listMediaFiltered(
  page: number = 1,
  perPage: number = 20,
  filters: SearchFilters = {},
): Promise<PaginatedResponse> {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('per_page', String(perPage));
  if (filters.has_people !== undefined && filters.has_people !== null) {
    params.set('has_people', String(filters.has_people));
  }
  if (filters.orientation) params.set('orientation', filters.orientation);
  if (filters.mood) params.set('mood', filters.mood);
  if (filters.mime_type) params.set('mime_type', filters.mime_type);
  if (filters.min_width) params.set('min_width', String(filters.min_width));
  if (filters.max_width) params.set('max_width', String(filters.max_width));
  if (filters.aspect_ratio) params.set('aspect_ratio', filters.aspect_ratio);
  if (filters.tags) params.set('tags', filters.tags);
  if (filters.source_id) params.set('source_id', filters.source_id);
  if (filters.sort_by && filters.sort_by !== 'newest') params.set('sort_by', filters.sort_by);
  return request<PaginatedResponse>(`/api/v1/media?${params.toString()}`);
}

export async function getMedia(id: string): Promise<MediaItemResponse> {
  const cached = fromCache<MediaItemResponse>(`media:${id}`);
  if (cached) return cached;
  const data = await request<MediaItemResponse>(`/api/v1/media/${id}`);
  // Only cache terminal states — processing/pending items are actively polled
  if (!['processing', 'pending', 'uploaded'].includes(data.status)) {
    toCache(`media:${id}`, data);
  }
  return data;
}

export function getMediaFileUrl(id: string): string {
  return `/api/v1/media/${id}/file`;
}

export async function getAnalysis(id: string): Promise<AnalysisResponse> {
  const cached = fromCache<AnalysisResponse>(`analysis:${id}`);
  if (cached) return cached;
  const data = await request<AnalysisResponse>(`/api/v1/media/${id}/analysis`);
  // Only cache terminal states — in-progress items are actively polled
  if (['completed', 'failed', 'error'].includes(data.status)) {
    toCache(`analysis:${id}`, data);
  }
  return data;
}

export async function reanalyze(id: string, hint?: string): Promise<ReanalyzeResponse> {
  invalidateMediaCache(id);
  return request<ReanalyzeResponse>(`/api/v1/media/${id}/reanalyze`, {
    method: 'POST',
    body: hint ? JSON.stringify({ hint }) : undefined,
  });
}

export async function updateMetadata(id: string, data: Partial<import('../types/api').MetadataFields>): Promise<AnalysisResponse> {
  invalidateMediaCache(id);
  return request<AnalysisResponse>(`/api/v1/media/${id}/analysis`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export interface BatchReanalyzeResponse {
  queued: number;
  message: string;
}

export interface BatchDeleteResponse {
  deleted: number;
  message: string;
}

export async function reanalyzeBatch(ids: string[]): Promise<BatchReanalyzeResponse> {
  return request<BatchReanalyzeResponse>('/api/v1/media/reanalyze-batch', {
    method: 'POST',
    body: JSON.stringify({ media_ids: ids }),
  });
}

export async function deleteBatch(ids: string[]): Promise<BatchDeleteResponse> {
  ids.forEach(invalidateMediaCache);
  return request<BatchDeleteResponse>('/api/v1/media/batch', {
    method: 'DELETE',
    body: JSON.stringify({ media_ids: ids }),
  });
}

export interface BatchTagResponse {
  updated: number;
  message: string;
}

export async function tagBatch(ids: string[], tags: string[]): Promise<BatchTagResponse> {
  return request<BatchTagResponse>('/api/v1/media/tag-batch', {
    method: 'POST',
    body: JSON.stringify({ media_ids: ids, tags }),
  });
}

// Download functions

export async function downloadFile(id: string): Promise<void> {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`/api/v1/media/${id}/download`, { headers });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Download failed' }));
    throw new Error(err.detail || 'Download failed');
  }

  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?(.+?)"?$/);
  const filename = match ? match[1] : 'download';

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadBatch(ids: string[]): Promise<void> {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch('/api/v1/media/download-batch', {
    method: 'POST',
    headers,
    body: JSON.stringify({ media_ids: ids }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Batch download failed' }));
    throw new Error(err.detail || 'Batch download failed');
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'media_export.zip';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export interface ConvertResponse {
  id: string;
  original_filename: string;
  mime_type: string;
  status: string;
  message: string;
}

export async function convertToPng(id: string): Promise<ConvertResponse> {
  return request<ConvertResponse>(`/api/v1/media/${id}/convert-png`, {
    method: 'POST',
  });
}

export interface SearchFilters {
  has_people?: boolean | null;
  orientation?: string | null;
  mood?: string | null;
  mime_type?: string | null;
  min_width?: number | null;
  max_width?: number | null;
  min_height?: number | null;
  max_height?: number | null;
  aspect_ratio?: string | null;
  tags?: string | null;
  source_id?: string | null;
  sort_by?: string;
}

export async function search(
  query: string,
  page: number = 1,
  perPage: number = 20,
  filters: SearchFilters = {},
): Promise<SearchResponse> {
  const params = new URLSearchParams();
  params.set('q', query);
  params.set('page', String(page));
  params.set('per_page', String(perPage));

  if (filters.has_people !== undefined && filters.has_people !== null) {
    params.set('has_people', String(filters.has_people));
  }
  if (filters.orientation) params.set('orientation', filters.orientation);
  if (filters.mood) params.set('mood', filters.mood);
  if (filters.mime_type) params.set('mime_type', filters.mime_type);
  if (filters.min_width) params.set('min_width', String(filters.min_width));
  if (filters.max_width) params.set('max_width', String(filters.max_width));
  if (filters.min_height) params.set('min_height', String(filters.min_height));
  if (filters.max_height) params.set('max_height', String(filters.max_height));
  if (filters.aspect_ratio) params.set('aspect_ratio', filters.aspect_ratio);
  if (filters.tags) params.set('tags', filters.tags);
  if (filters.sort_by && filters.sort_by !== 'relevance') params.set('sort_by', filters.sort_by);

  return request<SearchResponse>(`/api/v1/search?${params.toString()}`);
}

export async function listSources(includeArchived = false): Promise<SourceResponse[]> {
  const params = includeArchived ? '?include_archived=true' : '';
  return request<SourceResponse[]>(`/api/v1/sources${params}`);
}

export async function createSource(name: string, sourceType = 'manual'): Promise<SourceResponse> {
  return request<SourceResponse>('/api/v1/sources', {
    method: 'POST',
    body: JSON.stringify({ name, source_type: sourceType }),
  });
}

export async function archiveSource(id: string): Promise<SourceResponse> {
  return request<SourceResponse>(`/api/v1/sources/${id}/archive`, { method: 'POST' });
}

export async function restoreSource(id: string): Promise<SourceResponse> {
  return request<SourceResponse>(`/api/v1/sources/${id}/restore`, { method: 'POST' });
}

export async function configureS3Connector(
  sourceId: string,
  config: ConnectorS3ConfigRequest,
): Promise<ConnectorResponse> {
  return request<ConnectorResponse>(`/api/v1/sources/${sourceId}/connector/s3`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function updateS3Connector(
  sourceId: string,
  update: ConnectorS3UpdateRequest,
): Promise<ConnectorResponse> {
  return request<ConnectorResponse>(`/api/v1/sources/${sourceId}/connector/s3`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  });
}

export async function getConnector(sourceId: string): Promise<ConnectorResponse> {
  return request<ConnectorResponse>(`/api/v1/sources/${sourceId}/connector`);
}

export async function startGoogleDriveConnector(
  sourceId: string,
): Promise<ConnectorDriveStartResponse> {
  return request<ConnectorDriveStartResponse>(
    `/api/v1/sources/${sourceId}/connector/google-drive/start`,
    { method: 'POST' },
  );
}

export async function quickConnectGoogleDrive(
  sourceName?: string,
): Promise<ConnectorDriveStartResponse> {
  return request<ConnectorDriveStartResponse>(
    '/api/v1/connectors/google-drive/quick-connect',
    {
      method: 'POST',
      body: JSON.stringify({ source_name: sourceName ?? null }),
    },
  );
}

export async function disconnectGoogleDriveConnector(sourceId: string): Promise<void> {
  await request<void>(`/api/v1/sources/${sourceId}/connector/google-drive`, { method: 'DELETE' });
}

export async function upgradeGoogleDriveScope(
  sourceId: string,
): Promise<ConnectorDriveStartResponse> {
  return request<ConnectorDriveStartResponse>(
    `/api/v1/sources/${sourceId}/connector/google-drive/upgrade-scope/start`,
    { method: 'POST' },
  );
}

export async function listDriveFolders(
  sourceId: string,
  parentId: string = 'root',
): Promise<DriveFoldersResponse> {
  return request<DriveFoldersResponse>(
    `/api/v1/sources/${sourceId}/connector/google-drive/folders?parent_id=${encodeURIComponent(parentId)}`,
  );
}

export async function configureDriveConnector(
  sourceId: string,
  body: ConnectorDriveConfigureRequest,
): Promise<ConnectorResponse> {
  return request<ConnectorResponse>(
    `/api/v1/sources/${sourceId}/connector/google-drive/configure`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export async function triggerSync(sourceId: string): Promise<TriggerSyncResponse> {
  return request<TriggerSyncResponse>(`/api/v1/sources/${sourceId}/sync`, { method: 'POST' });
}

export async function updateConnectorAutoSync(
  sourceId: string,
  enabled: boolean,
  intervalMinutes: number,
): Promise<ConnectorResponse> {
  return request<ConnectorResponse>(`/api/v1/sources/${sourceId}/connector/auto-sync`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled, interval_minutes: intervalMinutes }),
  });
}

export async function listSyncRuns(
  sourceId: string,
  page = 1,
  perPage = 20,
): Promise<SyncRunsResponse> {
  return request<SyncRunsResponse>(
    `/api/v1/sources/${sourceId}/sync-runs?page=${page}&per_page=${perPage}`,
  );
}

export async function listAllSyncRuns(
  page = 1,
  perPage = 50,
): Promise<SyncRunsResponse> {
  return request<SyncRunsResponse>(
    `/api/v1/sync-runs?page=${page}&per_page=${perPage}`,
  );
}

export async function getQuotaStatus(): Promise<QuotaStatus> {
  return request<QuotaStatus>('/api/v1/quota/status');
}

export async function getQuotaHistory(
  period?: string,
  page = 1,
  perPage = 25,
): Promise<QuotaHistoryResponse> {
  const params = new URLSearchParams();
  if (period) params.set('period', period);
  params.set('page', String(page));
  params.set('per_page', String(perPage));
  return request<QuotaHistoryResponse>(`/api/v1/quota/history?${params}`);
}

export async function getQuotaDailyUsage(
  period?: string,
): Promise<QuotaDailyUsageResponse> {
  const params = new URLSearchParams();
  if (period) params.set('period', period);
  return request<QuotaDailyUsageResponse>(`/api/v1/quota/daily?${params}`);
}

// Profile management

export async function updateProfile(data: {
  display_name?: string;
  phone?: string | null;
  company?: string | null;
  icon_url?: string | null;
}): Promise<UserProfile> {
  return request<UserProfile>('/api/v1/auth/me', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function requestEmailChange(newEmail: string): Promise<{ token?: string; message: string }> {
  return request<{ token?: string; message: string }>('/api/v1/auth/email-change/request', {
    method: 'POST',
    body: JSON.stringify({ new_email: newEmail }),
  });
}

export async function confirmEmailChange(token: string): Promise<UserProfile> {
  return request<UserProfile>('/api/v1/auth/email-change/confirm', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}

export async function requestPasswordReset(email: string): Promise<{ token?: string; message: string }> {
  return request<{ token?: string; message: string }>('/api/v1/auth/password-reset/request', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<{ message: string }> {
  return request<{ message: string }>('/api/v1/auth/password-reset/confirm', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export async function verifyEmail(token: string): Promise<{ message: string }> {
  return request<{ message: string }>('/api/v1/auth/verify-email', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}

export async function resendVerificationEmail(): Promise<{ message: string; token?: string }> {
  return request<{ message: string; token?: string }>('/api/v1/auth/verify-email/resend', {
    method: 'POST',
  });
}

export async function uploadAvatar(file: File): Promise<UserProfile> {
  const formData = new FormData();
  formData.append('file', file);
  const token = getToken();
  const resp = await fetch('/api/v1/auth/me/avatar', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed: ${resp.status}`);
  }
  return resp.json();
}

export async function deleteAvatar(): Promise<void> {
  await request<void>('/api/v1/auth/me/avatar', { method: 'DELETE' });
}

// Admin API

export async function adminListUsers(
  page = 1,
  perPage = 50,
  search?: string,
): Promise<AdminUsersListResponse> {
  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (search) params.set('search', search);
  return request<AdminUsersListResponse>(`/api/v1/admin/users?${params.toString()}`);
}

export async function adminGetUser(userId: string): Promise<AdminUserDetail> {
  return request<AdminUserDetail>(`/api/v1/admin/users/${userId}`);
}

export async function adminUpdateUser(
  userId: string,
  data: {
    email?: string;
    display_name?: string;
    phone?: string | null;
    company?: string | null;
    icon_url?: string | null;
    plan_name?: string;
    monthly_limit?: number;
    role?: string;
    disabled?: boolean;
    billing_status?: string;
  },
): Promise<AdminUserSummary> {
  return request<AdminUserSummary>(`/api/v1/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function adminGetAuditLog(
  page = 1,
  targetUserId?: string,
): Promise<AuditLogListResponse> {
  const params = new URLSearchParams({ page: String(page) });
  if (targetUserId) params.set('target_user_id', targetUserId);
  return request<AuditLogListResponse>(`/api/v1/admin/audit-log?${params.toString()}`);
}

// Billing API

export async function getBillingStatus(): Promise<BillingStatus> {
  return request<BillingStatus>('/api/v1/billing/status');
}

export async function createCheckoutSession(priceId: string): Promise<CheckoutSessionResponse> {
  return request<CheckoutSessionResponse>('/api/v1/billing/create-checkout-session', {
    method: 'POST',
    body: JSON.stringify({ price_id: priceId }),
  });
}

export async function createPortalSession(): Promise<PortalSessionResponse> {
  return request<PortalSessionResponse>('/api/v1/billing/create-portal-session', {
    method: 'POST',
  });
}

// Near-duplicate detection (P5-001) + AI scoring (P5-002)

export async function getSimilarMedia(id: string): Promise<SimilarItemsResponse> {
  return request<SimilarItemsResponse>(`/api/v1/media/${id}/similar`);
}

export async function scoreGroup(id: string): Promise<ScoreGroupResponse> {
  return request<ScoreGroupResponse>(`/api/v1/media/${id}/score-group`, {
    method: 'POST',
  });
}

// Collections (P7-001)

export async function listCollections(): Promise<CollectionListResponse> {
  return request<CollectionListResponse>('/api/v1/collections');
}

export async function createCollection(name: string, description?: string): Promise<CollectionResponse> {
  return request<CollectionResponse>('/api/v1/collections', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description: description || null }),
  });
}

export async function getCollection(id: string): Promise<CollectionDetailResponse> {
  return request<CollectionDetailResponse>(`/api/v1/collections/${id}`);
}

export async function updateCollection(
  id: string,
  data: { name?: string; description?: string | null }
): Promise<CollectionResponse> {
  return request<CollectionResponse>(`/api/v1/collections/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteCollection(id: string): Promise<void> {
  await request<void>(`/api/v1/collections/${id}`, { method: 'DELETE' });
}

export async function addItemsToCollection(
  collectionId: string,
  mediaItemIds: string[]
): Promise<CollectionItemsModifiedResponse> {
  return request<CollectionItemsModifiedResponse>(`/api/v1/collections/${collectionId}/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ media_item_ids: mediaItemIds }),
  });
}

export async function removeItemsFromCollection(
  collectionId: string,
  mediaItemIds: string[]
): Promise<CollectionItemsModifiedResponse> {
  return request<CollectionItemsModifiedResponse>(`/api/v1/collections/${collectionId}/items`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ media_item_ids: mediaItemIds }),
  });
}

// Source mutation completion states (P7-004)
export async function reportLocalMutationResult(
  mediaId: string,
  body: LocalMutationResultRequest,
): Promise<MutationStateResponse> {
  return request<MutationStateResponse>(`/api/v1/media/${mediaId}/mutation-result`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// Drive write-back retry (P7-005)
export async function retryWriteback(mediaId: string): Promise<MutationStateResponse> {
  return request<MutationStateResponse>(`/api/v1/media/${mediaId}/retry-writeback`, {
    method: 'POST',
  });
}
