import type {
  AuthResponse,
  UserProfile,
  UploadResponse,
  BatchUploadResponse,
  PaginatedResponse,
  MediaItemResponse,
  AnalysisResponse,
  ReanalyzeResponse,
  SearchResponse,
  QuotaStatus,
  ApiError,
} from '../types/api';

const BASE_URL = '';

export class ApiRequestError extends Error {
  status: number;
  errorCode: string;
  error?: string;
  remaining?: number;
  limit?: number;

  constructor(status: number, data: ApiError) {
    super(data.detail || 'Request failed');
    this.name = 'ApiRequestError';
    this.status = status;
    this.errorCode = data.error_code;
    this.error = data.error;
    this.remaining = data.remaining;
    this.limit = data.limit;
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

export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return request<UploadResponse>('/api/v1/upload', {
    method: 'POST',
    body: formData,
  });
}

export async function uploadBatch(files: File[]): Promise<BatchUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
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
  if (filters.sort_by && filters.sort_by !== 'newest') params.set('sort_by', filters.sort_by);
  return request<PaginatedResponse>(`/api/v1/media?${params.toString()}`);
}

export async function getMedia(id: string): Promise<MediaItemResponse> {
  return request<MediaItemResponse>(`/api/v1/media/${id}`);
}

export function getMediaFileUrl(id: string): string {
  return `/api/v1/media/${id}/file`;
}

export async function getAnalysis(id: string): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(`/api/v1/media/${id}/analysis`);
}

export async function reanalyze(id: string): Promise<ReanalyzeResponse> {
  return request<ReanalyzeResponse>(`/api/v1/media/${id}/reanalyze`, {
    method: 'POST',
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
  return request<BatchDeleteResponse>('/api/v1/media/batch', {
    method: 'DELETE',
    body: JSON.stringify({ media_ids: ids }),
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

export async function getQuotaStatus(): Promise<QuotaStatus> {
  return request<QuotaStatus>('/api/v1/quota/status');
}
