import { useState } from 'react';
import * as api from '../api/client';

interface SelectionBarProps {
  count: number;
  selectedIds: string[];
  onClear: () => void;
  onDeleteSuccess?: (deletedIds: string[]) => void;
}

export default function SelectionBar({ count, selectedIds, onClear, onDeleteSuccess }: SelectionBarProps) {
  const [downloading, setDownloading] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [lastMessage, setLastMessage] = useState<string | null>(null);

  async function handleDownload() {
    setDownloading(true);
    try {
      await api.downloadBatch(selectedIds);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setDownloading(false);
    }
  }

  async function handleReanalyze() {
    setReanalyzing(true);
    setLastMessage(null);
    try {
      const res = await api.reanalyzeBatch(selectedIds);
      setLastMessage(res.message);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Re-analyze failed');
    } finally {
      setReanalyzing(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete ${count} selected item${count !== 1 ? 's' : ''}? This cannot be undone.`)) {
      return;
    }
    setDeleting(true);
    setLastMessage(null);
    try {
      const res = await api.deleteBatch(selectedIds);
      if (onDeleteSuccess) onDeleteSuccess(selectedIds);
      onClear();
      setLastMessage(res.message);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
    }
  }

  if (count === 0) return null;

  return (
    <div className="selection-bar">
      <span className="selection-count">{count} selected</span>
      {lastMessage && <span className="selection-message">{lastMessage}</span>}
      <button
        className="btn btn-primary btn-sm"
        onClick={handleDownload}
        disabled={downloading || reanalyzing || deleting}
      >
        {downloading ? 'Downloading...' : 'Download Selected'}
      </button>
      <button
        className="btn btn-secondary btn-sm"
        onClick={handleReanalyze}
        disabled={downloading || reanalyzing || deleting}
      >
        {reanalyzing ? 'Queuing...' : 'Re-analyze'}
      </button>
      <button
        className="btn btn-danger btn-sm"
        onClick={handleDelete}
        disabled={downloading || reanalyzing || deleting}
      >
        {deleting ? 'Deleting...' : 'Delete'}
      </button>
      <button className="btn btn-outline btn-sm" onClick={onClear}>
        Clear Selection
      </button>
    </div>
  );
}
