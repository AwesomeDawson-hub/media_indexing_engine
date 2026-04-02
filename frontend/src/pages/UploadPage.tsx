import { useState, useCallback, useEffect } from 'react';
import DropZone from '../components/DropZone';
import FileQueue, { type QueuedFile } from '../components/FileQueue';
import * as api from '../api/client';
import type { QuotaStatus, SourceResponse } from '../types/api';

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/tiff', 'image/bmp', 'image/avif'];
const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.tiff', '.tif', '.bmp', '.avif'];
const MAX_SIZE = 50 * 1024 * 1024; // 50 MB

function isAllowedFile(file: File): boolean {
  // Check MIME type first
  if (ALLOWED_TYPES.includes(file.type)) return true;
  // Fallback: check extension (browsers may not know AVIF/TIFF MIME types)
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  return ALLOWED_EXTENSIONS.includes(ext);
}

export default function UploadPage() {
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [quotaStatus, setQuotaStatus] = useState<QuotaStatus | null>(null);
  const [showQuotaModal, setShowQuotaModal] = useState(false);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [showNewSourceForm, setShowNewSourceForm] = useState(false);
  const [newSourceName, setNewSourceName] = useState('');
  const [creatingSource, setCreatingSource] = useState(false);
  const [createError, setCreateError] = useState<{ message: string; archivedSourceId?: string } | null>(null);
  const queuedCount = queue.filter((q) => q.status === 'queued').length;
  const hasCompleted = queue.some((q) => q.status !== 'queued' && q.status !== 'uploading');
  const exceedsQuota = quotaStatus !== null && queuedCount > quotaStatus.remaining;
  const quotaDepleted = quotaStatus !== null && quotaStatus.remaining === 0;

  useEffect(() => {
    api.listSources().then(setSources).catch(() => {});
  }, []);

  async function handleCreateSource() {
    const name = newSourceName.trim();
    if (!name) return;
    setCreatingSource(true);
    setCreateError(null);
    try {
      const created = await api.createSource(name);
      setSources((prev) => [...prev, created]);
      setSelectedSourceId(created.id);
      setShowNewSourceForm(false);
      setNewSourceName('');
    } catch (err: unknown) {
      if (err instanceof api.ApiRequestError && err.status === 409) {
        setCreateError({ message: err.message, archivedSourceId: err.archivedSourceId });
      } else {
        setCreateError({ message: 'Failed to create source.' });
      }
    } finally {
      setCreatingSource(false);
    }
  }

  async function handleRestoreFromConflict(archivedSourceId: string) {
    setCreatingSource(true);
    try {
      const restored = await api.restoreSource(archivedSourceId);
      setSources((prev) => {
        const exists = prev.find((s) => s.id === restored.id);
        if (exists) return prev.map((s) => (s.id === restored.id ? { ...restored, media_count: s.media_count } : s));
        return [...prev, { ...restored, media_count: 0 }];
      });
      setSelectedSourceId(restored.id);
      setShowNewSourceForm(false);
      setNewSourceName('');
      setCreateError(null);
    } catch {
      setCreateError({ message: 'Failed to restore source.' });
    } finally {
      setCreatingSource(false);
    }
  }

  const handleFiles = useCallback((files: File[]) => {
    const newEntries: QueuedFile[] = files.map((file) => {
      if (!isAllowedFile(file)) {
        return { file, status: 'error' as const, error: 'Unsupported file type' };
      }
      if (file.size > MAX_SIZE) {
        return { file, status: 'error' as const, error: 'File too large (max 50 MB)' };
      }
      return { file, status: 'queued' as const };
    });
    setQueue((prev) => [...prev, ...newEntries]);
  }, []);

  async function handleUpload() {
    const toUpload = queue.filter((q) => q.status === 'queued');
    if (toUpload.length === 0) return;

    setUploading(true);

    // Mark all queued files as uploading in one state update
    setQueue((prev) =>
      prev.map((q) => (q.status === 'queued' ? { ...q, status: 'uploading' as const } : q)),
    );

    const CONCURRENCY = 4;
    let quotaExceeded = false;

    // Process files in parallel with a concurrency limit
    const results: { filename: string; status: QueuedFile['status']; error?: string }[] = [];

    async function uploadOne(qf: QueuedFile) {
      if (quotaExceeded) {
        results.push({ filename: qf.file.name, status: 'error', error: 'Monthly quota exceeded' });
        return;
      }
      try {
        const res = await api.uploadFile(qf.file, selectedSourceId || undefined);
        results.push({ filename: qf.file.name, status: res.is_duplicate ? 'duplicate' : 'created' });
      } catch (err: unknown) {
        if (err instanceof api.ApiRequestError && err.error === 'quota_exceeded') {
          quotaExceeded = true;
          results.push({ filename: qf.file.name, status: 'error', error: 'Monthly quota exceeded' });
        } else {
          const message = err instanceof Error ? err.message : 'Upload failed';
          results.push({ filename: qf.file.name, status: 'error', error: message });
        }
      }
    }

    // Run with concurrency cap
    const chunks: QueuedFile[][] = [];
    for (let i = 0; i < toUpload.length; i += CONCURRENCY) {
      chunks.push(toUpload.slice(i, i + CONCURRENCY));
    }
    for (const chunk of chunks) {
      await Promise.all(chunk.map(uploadOne));
    }

    // Apply all status updates in a single state write
    const resultMap = new Map(results.map((r) => [r.filename, r]));
    setQueue((prev) =>
      prev.map((q) => {
        const r = resultMap.get(q.file.name);
        if (!r) return q;
        return { ...q, status: r.status, error: r.error };
      }),
    );

    setUploading(false);
  }

  async function handleClickProcess() {
    const toUpload = queue.filter((q) => q.status === 'queued');
    if (toUpload.length === 0) return;

    setQuotaLoading(true);
    try {
      const status = await api.getQuotaStatus();
      setQuotaStatus(status);
      setShowQuotaModal(true);
    } catch {
      // Quota check unavailable — proceed without modal
      await handleUpload();
    } finally {
      setQuotaLoading(false);
    }
  }

  async function handleConfirmUpload() {
    setShowQuotaModal(false);
    await handleUpload();
  }

  function clearCompleted() {
    setQueue((prev) => prev.filter((q) => q.status === 'queued' || q.status === 'uploading'));
  }

  return (
    <div>
      <div className="page-header">
        <h1>Upload</h1>
        <div className="upload-header-actions">
          {queuedCount > 0 && (
            <button
              className="btn btn-primary"
              onClick={handleClickProcess}
              disabled={uploading || quotaLoading}
            >
              {quotaLoading ? 'Checking quota...' : uploading ? 'Processing...' : `Process ${queuedCount} file${queuedCount > 1 ? 's' : ''}`}
            </button>
          )}
          {hasCompleted && (
            <button className="btn btn-outline" onClick={clearCompleted}>
              Clear Completed
            </button>
          )}
        </div>
      </div>
      <div className="upload-source-section card">
        <div className="filter-group">
          <label>Tag uploads with a source</label>
          <div className="upload-source-row">
            <select
              value={selectedSourceId}
              onChange={(e) => setSelectedSourceId(e.target.value)}
            >
              <option value="">No source</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            {!showNewSourceForm && (
              <button
                className="btn btn-outline btn-sm"
                onClick={() => setShowNewSourceForm(true)}
              >
                + New Source
              </button>
            )}
          </div>
          {showNewSourceForm && (
            <div className="upload-new-source-form">
              <input
                type="text"
                placeholder="Source name"
                value={newSourceName}
                onChange={(e) => { setNewSourceName(e.target.value); setCreateError(null); }}
                maxLength={200}
              />
              <button
                className="btn btn-primary btn-sm"
                onClick={handleCreateSource}
                disabled={creatingSource || !newSourceName.trim()}
              >
                {creatingSource ? 'Creating...' : 'Create'}
              </button>
              <button
                className="btn btn-outline btn-sm"
                onClick={() => { setShowNewSourceForm(false); setNewSourceName(''); setCreateError(null); }}
              >
                Cancel
              </button>
              {createError && (
                <div className="upload-new-source-error">
                  {createError.message}
                  {createError.archivedSourceId && (
                    <button
                      className="btn btn-sm btn-outline"
                      onClick={() => handleRestoreFromConflict(createError.archivedSourceId!)}
                      disabled={creatingSource}
                    >
                      Restore it
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {selectedSourceId && (
        <p className="upload-source-active-hint">
          Uploads will be tagged: <strong>{sources.find((s) => s.id === selectedSourceId)?.name}</strong>
        </p>
      )}
      <DropZone
        onFiles={handleFiles}
        accept={[...ALLOWED_TYPES, ...ALLOWED_EXTENSIONS].join(',')}
      />
      <div className="file-queue-scroll">
        <FileQueue files={queue} />
      </div>

      {showQuotaModal && quotaStatus && (
        <div className="modal-overlay">
          <div className="modal">
            <h2>Confirm Processing</h2>
            <p>
              Plan: <strong>{quotaStatus.plan_name}</strong> &mdash; {quotaStatus.period_month}
            </p>
            <p>
              Selected now: <strong>{queuedCount}</strong>
            </p>
            <p>
              Used this month:{' '}
              <strong>{quotaStatus.consumed + quotaStatus.reserved}</strong> /{' '}
              {quotaStatus.monthly_limit}
            </p>
            <p>
              Available: <strong>{quotaStatus.remaining}</strong>
            </p>
            <p>
              Re-analysis overwrites existing AI metadata, but original capture date and geo-location
              are preserved.
            </p>
            {exceedsQuota && quotaStatus.remaining > 0 && (
              <p className="text-warning">
                Selected files exceed your remaining monthly quota. Reduce the selection before
                processing.
              </p>
            )}
            {quotaDepleted && (
              <p className="text-danger">
                Monthly quota exhausted. Wait until next month or change the selection.
              </p>
            )}
            <div className="modal-actions">
              <button className="btn btn-outline" onClick={() => setShowQuotaModal(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleConfirmUpload}
                disabled={exceedsQuota || quotaDepleted}
              >
                Confirm and Process
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
