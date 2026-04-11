import { useState, useCallback } from 'react';
import DropZone from '../components/DropZone';
import FileQueue, { type QueuedFile } from '../components/FileQueue';
import * as api from '../api/client';
import type { QuotaStatus } from '../types/api';

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/tiff', 'image/bmp', 'image/avif'];
const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.tiff', '.tif', '.bmp', '.avif'];
const MAX_SIZE = 50 * 1024 * 1024; // 50 MB

const HAS_FOLDER_PICKER = typeof window !== 'undefined' && 'showDirectoryPicker' in window;

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
  const [workingFolder, setWorkingFolder] = useState<FileSystemDirectoryHandle | null>(null);
  const [folderPickerError, setFolderPickerError] = useState<string | null>(null);

  const queuedCount = queue.filter((q) => q.status === 'queued').length;
  const exceedsQuota = quotaStatus !== null && queuedCount > quotaStatus.remaining;
  const quotaDepleted = quotaStatus !== null && quotaStatus.remaining === 0;
  const canProcess = HAS_FOLDER_PICKER && workingFolder !== null;

  async function handleSelectFolder() {
    setFolderPickerError(null);
    try {
      // showDirectoryPicker is a standard File System Access API method
      const handle = await (window as unknown as { showDirectoryPicker: () => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker();
      setWorkingFolder(handle);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled the picker — do not show error
        return;
      }
      setFolderPickerError('Could not open folder. Please try again.');
    }
  }

  const handleFiles = useCallback((files: File[]) => {
    if (!canProcess) return; // Gate: require working folder
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
  }, [canProcess]);

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
        // P9-005: write original into the working folder first so the user's device
        // is the source of truth, then send bytes transiently to the backend.
        const fileHandle = await workingFolder!.getFileHandle(qf.file.name, { create: true });
        const writable = await fileHandle.createWritable();
        await writable.write(qf.file);
        await writable.close();

        const localPath = (qf.file as File & { webkitRelativePath?: string }).webkitRelativePath || qf.file.name;
        const res = await api.uploadLocalFolderFile(qf.file, undefined, localPath);
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

  // Unsupported browser: File System Access API unavailable
  if (!HAS_FOLDER_PICKER) {
    return (
      <div>
        <div className="page-header">
          <h1>Local Working-Folder Intake</h1>
        </div>
        <div className="alert alert-warning">
          <strong>Browser not supported for local working-folder intake.</strong>
          <p>
            This feature requires the File System Access API, which is available in Chromium-based
            browsers (Chrome, Edge) on desktop. Firefox and Safari do not currently support it.
          </p>
          <p>
            To add media from a local folder, please use a supported browser, or connect a cloud
            source (Google Drive or S3-compatible) from the Add Media page.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Local Working-Folder Intake</h1>
        <div className="upload-header-actions">
          {queuedCount > 0 && (
            <button
              className="btn btn-primary"
              onClick={handleClickProcess}
              disabled={uploading || quotaLoading || !canProcess}
            >
              {quotaLoading ? 'Checking quota...' : uploading ? 'Processing...' : `Process ${queuedCount} file${queuedCount > 1 ? 's' : ''}`}
            </button>
          )}
        </div>
      </div>

      <div className="working-folder-section">
        {workingFolder ? (
          <div className="working-folder-status">
            <span className="folder-indicator">&#x1F4C2;</span>
            <span>Working folder: <strong>{workingFolder.name}</strong></span>
            <button className="btn btn-outline btn-sm" onClick={handleSelectFolder}>
              Change folder
            </button>
          </div>
        ) : (
          <div className="working-folder-prompt">
            <p>
              Select a local working folder before adding files. Originals are kept on your device
              &mdash; the app retains only a preview thumbnail and AI-generated metadata.
            </p>
            <button className="btn btn-primary" onClick={handleSelectFolder}>
              Select Working Folder
            </button>
            {folderPickerError && (
              <p className="text-danger">{folderPickerError}</p>
            )}
          </div>
        )}
      </div>

      {canProcess && (
        <>
          <DropZone
            onFiles={handleFiles}
            accept={[...ALLOWED_TYPES, ...ALLOWED_EXTENSIONS].join(',')}
          />
          <div className="file-queue-scroll">
            <FileQueue files={queue} />
          </div>
        </>
      )}

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
