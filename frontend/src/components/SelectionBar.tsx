import { useState, useEffect } from 'react';
import * as api from '../api/client';
import type { CollectionResponse } from '../types/api';

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
  const [tagging, setTagging] = useState(false);
  const [showTagInput, setShowTagInput] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [lastMessage, setLastMessage] = useState<string | null>(null);

  // Add to collection
  const [showCollectionPicker, setShowCollectionPicker] = useState(false);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [addingToCollection, setAddingToCollection] = useState(false);

  useEffect(() => {
    if (showCollectionPicker && collections.length === 0) {
      setCollectionsLoading(true);
      api.listCollections().then((res) => {
        setCollections(res.collections);
      }).catch(() => {}).finally(() => setCollectionsLoading(false));
    }
  }, [showCollectionPicker]);

  const busy = downloading || reanalyzing || deleting || tagging;

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

  async function handleTagSubmit() {
    const tags = tagInput.split(',').map((t) => t.trim()).filter(Boolean);
    if (tags.length === 0) return;
    setTagging(true);
    setLastMessage(null);
    try {
      const res = await api.tagBatch(selectedIds, tags);
      setLastMessage(res.message);
      setTagInput('');
      setShowTagInput(false);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Tag update failed');
    } finally {
      setTagging(false);
    }
  }

  async function handleAddToCollection(collectionId: string, collectionName: string) {
    setAddingToCollection(true);
    setLastMessage(null);
    try {
      const res = await api.addItemsToCollection(collectionId, selectedIds);
      setLastMessage(`Added ${res.added} item${res.added !== 1 ? 's' : ''} to "${collectionName}".`);
      setShowCollectionPicker(false);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to add to collection');
    } finally {
      setAddingToCollection(false);
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
        disabled={busy}
      >
        {downloading ? 'Downloading...' : 'Download'}
      </button>
      <button
        className="btn btn-secondary btn-sm"
        onClick={handleReanalyze}
        disabled={busy}
      >
        {reanalyzing ? 'Queuing...' : 'Re-analyze'}
      </button>
      <button
        className="btn btn-secondary btn-sm"
        onClick={() => { setShowTagInput((v) => !v); setLastMessage(null); }}
        disabled={busy}
      >
        Add Tags
      </button>
      <div className="selection-collection-wrapper">
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => { setShowCollectionPicker((v) => !v); setLastMessage(null); }}
          disabled={busy || addingToCollection}
        >
          Add to Collection
        </button>
        {showCollectionPicker && (
          <div className="selection-collection-dropdown">
            {collectionsLoading ? (
              <div className="selection-collection-item selection-collection-loading">Loading…</div>
            ) : collections.length === 0 ? (
              <div className="selection-collection-item selection-collection-empty">No collections yet</div>
            ) : (
              collections.map((c) => (
                <button
                  key={c.id}
                  className="selection-collection-item"
                  onClick={() => handleAddToCollection(c.id, c.name)}
                  disabled={addingToCollection}
                >
                  {c.name}
                  <span className="selection-collection-count">{c.item_count}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
      <button
        className="btn btn-danger btn-sm"
        onClick={handleDelete}
        disabled={busy}
      >
        {deleting ? 'Deleting...' : 'Delete'}
      </button>
      <button className="btn btn-outline btn-sm" onClick={onClear} disabled={busy}>
        Clear
      </button>
      {showTagInput && (
        <div className="selection-tag-row">
          <input
            className="selection-tag-input"
            type="text"
            placeholder="tag1, tag2, tag3"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleTagSubmit(); if (e.key === 'Escape') setShowTagInput(false); }}
            autoFocus
          />
          <button
            className="btn btn-primary btn-sm"
            onClick={handleTagSubmit}
            disabled={tagging || !tagInput.trim()}
          >
            {tagging ? 'Saving...' : 'Apply'}
          </button>
          <button
            className="btn btn-outline btn-sm"
            onClick={() => { setShowTagInput(false); setTagInput(''); }}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
