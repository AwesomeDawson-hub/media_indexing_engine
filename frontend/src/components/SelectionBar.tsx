import { useState } from 'react';
import * as api from '../api/client';

interface SelectionBarProps {
  count: number;
  selectedIds: string[];
  onClear: () => void;
}

export default function SelectionBar({ count, selectedIds, onClear }: SelectionBarProps) {
  const [downloading, setDownloading] = useState(false);

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

  if (count === 0) return null;

  return (
    <div className="selection-bar">
      <span className="selection-count">{count} selected</span>
      <button
        className="btn btn-primary btn-sm"
        onClick={handleDownload}
        disabled={downloading}
      >
        {downloading ? 'Downloading...' : 'Download Selected'}
      </button>
      <button className="btn btn-outline btn-sm" onClick={onClear}>
        Clear Selection
      </button>
    </div>
  );
}
