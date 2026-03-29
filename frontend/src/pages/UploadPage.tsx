import { useState, useCallback } from 'react';
import DropZone from '../components/DropZone';
import FileQueue, { type QueuedFile } from '../components/FileQueue';
import * as api from '../api/client';

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

    // Upload files one at a time for reliable per-file status
    for (const qf of toUpload) {
      updateStatus(qf.file.name, 'uploading');
      try {
        const res = await api.uploadFile(qf.file);
        updateStatus(qf.file.name, res.is_duplicate ? 'duplicate' : 'created');
      } catch (err: unknown) {
        updateStatus(qf.file.name, 'error', err instanceof Error ? err.message : 'Upload failed');
      }
    }

    setUploading(false);
  }

  function updateStatus(filename: string, status: QueuedFile['status'], error?: string) {
    setQueue((prev) =>
      prev.map((q) =>
        q.file.name === filename ? { ...q, status, error } : q,
      ),
    );
  }

  function clearCompleted() {
    setQueue((prev) => prev.filter((q) => q.status === 'queued' || q.status === 'uploading'));
  }

  const queuedCount = queue.filter((q) => q.status === 'queued').length;
  const hasCompleted = queue.some((q) => q.status !== 'queued' && q.status !== 'uploading');

  return (
    <div>
      <div className="page-header">
        <h1>Source</h1>
        <div className="upload-header-actions">
          {queuedCount > 0 && (
            <button
              className="btn btn-primary"
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? 'Processing...' : `Process ${queuedCount} file${queuedCount > 1 ? 's' : ''}`}
            </button>
          )}
          {hasCompleted && (
            <button className="btn btn-outline" onClick={clearCompleted}>
              Clear Completed
            </button>
          )}
        </div>
      </div>
      <DropZone
        onFiles={handleFiles}
        accept={[...ALLOWED_TYPES, ...ALLOWED_EXTENSIONS].join(',')}
      />
      <div className="file-queue-scroll">
        <FileQueue files={queue} />
      </div>
    </div>
  );
}
