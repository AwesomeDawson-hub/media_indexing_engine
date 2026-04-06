import { useState, useCallback, useEffect } from 'react';
import { Link } from 'react-router-dom';
import DropZone from '../components/DropZone';
import FileQueue, { type QueuedFile } from '../components/FileQueue';
import * as api from '../api/client';
import type {
  QuotaStatus,
  DriveFolderItem,
  CollectionResponse,
  ConnectorDriveConfigureRequest,
  ConnectorResponse,
} from '../types/api';

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/tiff', 'image/bmp', 'image/avif'];
const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.tiff', '.tif', '.bmp', '.avif'];
const MAX_SIZE = 50 * 1024 * 1024; // 50 MB

function isAllowedFile(file: File): boolean {
  if (ALLOWED_TYPES.includes(file.type)) return true;
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  return ALLOWED_EXTENSIONS.includes(ext);
}

// ---------------------------------------------------------------------------
// Drive configure panel — shown inline after OAuth success
// ---------------------------------------------------------------------------
function DriveConfigurePanel({
  sourceId,
  onDone,
}: {
  sourceId: string;
  onDone: (connector: ConnectorResponse) => void;
}) {
  const [driveNavStack, setDriveNavStack] = useState<{ id: string; name: string }[]>([]);
  const [driveFolders, setDriveFolders] = useState<DriveFolderItem[]>([]);
  const [folderLoading, setFolderLoading] = useState(true);
  const [selectedFolder, setSelectedFolder] = useState<{ id: string; name: string } | null>(null);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [configurePending, setConfigurePending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.listDriveFolders(sourceId, 'root')
      .then((r) => setDriveFolders(r.folders))
      .catch(() => setError('Failed to load Drive folders.'))
      .finally(() => setFolderLoading(false));
    api.listCollections().then((d) => setCollections(d.collections)).catch(() => null);
  }, [sourceId]);

  async function loadFolders(parentId: string) {
    setFolderLoading(true);
    try {
      const resp = await api.listDriveFolders(sourceId, parentId);
      setDriveFolders(resp.folders);
    } catch {
      setError('Failed to load Drive folders.');
    } finally {
      setFolderLoading(false);
    }
  }

  async function handleNavInto(folder: { id: string; name: string }) {
    setDriveNavStack((prev) => [...prev, folder]);
    setSelectedFolder(folder);
    await loadFolders(folder.id);
  }

  async function handleNavTo(idx: number) {
    const newStack = driveNavStack.slice(0, idx + 1);
    setDriveNavStack(newStack);
    setSelectedFolder({ id: newStack[newStack.length - 1].id, name: newStack[newStack.length - 1].name });
    await loadFolders(newStack[newStack.length - 1].id);
  }

  async function handleNavRoot() {
    setDriveNavStack([]);
    setSelectedFolder(null);
    await loadFolders('root');
  }

  async function handleSave() {
    setError('');
    setConfigurePending(true);
    try {
      const body: ConnectorDriveConfigureRequest = {
        target_folder_id: selectedFolder?.id ?? null,
        target_folder_label: selectedFolder?.name ?? null,
        target_collection_id: selectedCollectionId,
      };
      const updated = await api.configureDriveConnector(sourceId, body);
      onDone(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Save failed: ${msg}`);
    } finally {
      setConfigurePending(false);
    }
  }

  return (
    <div className="drive-configure-panel">
      <p className="drive-configure-title">Choose sync folder</p>

      <div className="drive-breadcrumb">
        <button
          type="button"
          className={`drive-breadcrumb-item${driveNavStack.length === 0 ? ' drive-breadcrumb-item--current' : ''}`}
          onClick={handleNavRoot}
        >
          My Drive
        </button>
        {driveNavStack.map((seg, idx) => (
          <span key={seg.id}>
            <span className="drive-breadcrumb-sep">›</span>
            <button
              type="button"
              className={`drive-breadcrumb-item${idx === driveNavStack.length - 1 ? ' drive-breadcrumb-item--current' : ''}`}
              onClick={() => handleNavTo(idx)}
            >
              {seg.name}
            </button>
          </span>
        ))}
      </div>

      {folderLoading ? (
        <p className="connector-status connector-status--info">Loading folders…</p>
      ) : driveFolders.length === 0 ? (
        <p className="connector-status connector-status--info">No sub-folders here.</p>
      ) : (
        <div className="drive-folder-list">
          {driveFolders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="drive-folder-item"
              onClick={() => handleNavInto({ id: f.id, name: f.name })}
            >
              <span>📁 {f.name}</span>
              {f.has_children && <span className="drive-folder-item-chevron">›</span>}
            </button>
          ))}
        </div>
      )}

      <div className="drive-configure-selected">
        Sync from: <strong>{selectedFolder ? selectedFolder.name : 'My Drive (root)'}</strong>
      </div>

      {collections.length > 0 && (
        <div className="drive-configure-collection">
          <label>Add to collection:</label>
          <select
            value={selectedCollectionId ?? ''}
            onChange={(e) => setSelectedCollectionId(e.target.value || null)}
          >
            <option value="">No collection</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      )}

      {error && <div className="connector-status connector-status--error">{error}</div>}

      <button
        className="btn btn-primary"
        onClick={handleSave}
        disabled={configurePending}
      >
        {configurePending ? 'Saving…' : 'Save and start syncing'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddMediaPage
// ---------------------------------------------------------------------------

export default function AddMediaPage() {
  // Upload state
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [quotaStatus, setQuotaStatus] = useState<QuotaStatus | null>(null);
  const [showQuotaModal, setShowQuotaModal] = useState(false);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const queuedCount = queue.filter((q) => q.status === 'queued').length;
  const exceedsQuota = quotaStatus !== null && queuedCount > quotaStatus.remaining;
  const quotaDepleted = quotaStatus !== null && quotaStatus.remaining === 0;

  // Drive section state
  const [drivePending, setDrivePending] = useState(false);
  const [driveError, setDriveError] = useState('');
  const [callbackSourceId, setCallbackSourceId] = useState<string | null>(null);
  const [callbackResult, setCallbackResult] = useState<'connected' | 'error' | null>(null);
  const [callbackErrorCode, setCallbackErrorCode] = useState('');
  const [driveConfigured, setDriveConfigured] = useState<ConnectorResponse | null>(null);

  // Read callback query params on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connector = params.get('connector');
    const result = params.get('connector_result');
    if (connector === 'google_drive' && result) {
      if (result === 'connected') {
        const sid = params.get('source_id');
        setCallbackSourceId(sid);
        setCallbackResult('connected');
      } else if (result === 'error') {
        const code = params.get('error_code') || 'unknown_error';
        setCallbackResult('error');
        setCallbackErrorCode(code);
      }
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  // Upload handlers
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
    setQueue((prev) =>
      prev.map((q) => (q.status === 'queued' ? { ...q, status: 'uploading' as const } : q)),
    );
    const CONCURRENCY = 4;
    let quotaExceeded = false;
    const results: { filename: string; status: QueuedFile['status']; error?: string }[] = [];

    async function uploadOne(qf: QueuedFile) {
      if (quotaExceeded) {
        results.push({ filename: qf.file.name, status: 'error', error: 'Monthly quota exceeded' });
        return;
      }
      try {
        const res = await api.uploadFile(qf.file);
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

    const chunks: QueuedFile[][] = [];
    for (let i = 0; i < toUpload.length; i += CONCURRENCY) {
      chunks.push(toUpload.slice(i, i + CONCURRENCY));
    }
    for (const chunk of chunks) {
      await Promise.all(chunk.map(uploadOne));
    }

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
      await handleUpload();
    } finally {
      setQuotaLoading(false);
    }
  }

  async function handleConfirmUpload() {
    setShowQuotaModal(false);
    await handleUpload();
  }

  // Drive handler
  async function handleDriveConnect() {
    setDriveError('');
    setDrivePending(true);
    try {
      const resp = await api.quickConnectGoogleDrive();
      window.location.href = resp.authorization_url;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setDriveError(`Could not start Google Drive connection: ${msg}`);
      setDrivePending(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>Add Media</h1>
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
        </div>
      </div>

      {/* ── Upload Files ─────────────────────────────────────────────────── */}
      <section className="add-media-section">
        <h2 className="add-media-section-title">Upload Files</h2>
        <DropZone
          onFiles={handleFiles}
          accept={[...ALLOWED_TYPES, ...ALLOWED_EXTENSIONS].join(',')}
        />
        <div className="file-queue-scroll">
          <FileQueue files={queue} />
        </div>
      </section>

      {/* ── Connect Google Drive ──────────────────────────────────────────── */}
      <section className="add-media-section">
        <h2 className="add-media-section-title">Connect Google Drive</h2>

        {callbackResult === 'error' && (
          <div className="connector-status connector-status--error">
            Google Drive connection failed: {callbackErrorCode.replace(/_/g, ' ')}
          </div>
        )}

        {callbackResult === 'connected' && callbackSourceId && !driveConfigured && (
          <>
            <div className="connector-status connector-status--info">
              Google Drive connected. Choose a folder to sync below.
            </div>
            <DriveConfigurePanel
              sourceId={callbackSourceId}
              onDone={(connector) => setDriveConfigured(connector)}
            />
          </>
        )}

        {driveConfigured && (
          <div className="connector-status connector-status--info">
            Drive sync configured: <strong>{driveConfigured.target_folder_label ?? 'My Drive (root)'}</strong>.{' '}
            <Link to="/sources">Manage in Connections →</Link>
          </div>
        )}

        {!callbackResult && (
          <>
            <p className="add-media-hint">
              Connect your Google Drive to automatically sync images from a folder.
            </p>
            {driveError && <div className="connector-status connector-status--error">{driveError}</div>}
            <button
              className="btn btn-outline"
              onClick={handleDriveConnect}
              disabled={drivePending}
            >
              {drivePending ? 'Connecting…' : 'Connect Google Drive'}
            </button>
          </>
        )}
      </section>

      {/* ── S3 ───────────────────────────────────────────────────────────── */}
      <section className="add-media-section">
        <h2 className="add-media-section-title">Connect S3 Bucket</h2>
        <p className="add-media-hint">
          To connect an AWS S3 or S3-compatible bucket,{' '}
          <Link to="/sources">manage it from the Connections page</Link>.
        </p>
      </section>

      {/* ── Quota modal ──────────────────────────────────────────────────── */}
      {showQuotaModal && quotaStatus && (
        <div className="modal-overlay">
          <div className="modal">
            <h2>Confirm Processing</h2>
            <p>Plan: <strong>{quotaStatus.plan_name}</strong> &mdash; {quotaStatus.period_month}</p>
            <p>Selected now: <strong>{queuedCount}</strong></p>
            <p>
              Used this month:{' '}
              <strong>{quotaStatus.consumed + quotaStatus.reserved}</strong> / {quotaStatus.monthly_limit}
            </p>
            <p>Available: <strong>{quotaStatus.remaining}</strong></p>
            <p>Re-analysis overwrites existing AI metadata, but original capture date and geo-location are preserved.</p>
            {exceedsQuota && quotaStatus.remaining > 0 && (
              <p className="text-warning">
                Selected files exceed your remaining monthly quota. Reduce the selection before uploading.
              </p>
            )}
            {quotaDepleted && (
              <p className="text-warning">
                You have used your full monthly quota. <Link to="/billing">Upgrade your plan</Link> to continue.
              </p>
            )}
            <div className="modal-actions">
              <button
                className="btn btn-primary"
                onClick={handleConfirmUpload}
                disabled={quotaDepleted}
              >
                Confirm
              </button>
              <button className="btn btn-outline" onClick={() => setShowQuotaModal(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
