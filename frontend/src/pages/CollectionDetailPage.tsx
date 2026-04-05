import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import * as api from '../api/client';
import MediaCard from '../components/MediaCard';
import type { CollectionDetailResponse } from '../types/api';

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [collection, setCollection] = useState<CollectionDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Edit state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editError, setEditError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    load(id);
  }, [id]);

  async function load(collectionId: string) {
    setLoading(true);
    try {
      const res = await api.getCollection(collectionId);
      setCollection(res);
      setEditName(res.name);
      setEditDesc(res.description ?? '');
    } catch {
      setError('Collection not found.');
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!id || !collection) return;
    setSaving(true);
    setEditError('');
    try {
      const updated = await api.updateCollection(id, {
        name: editName.trim(),
        description: editDesc.trim() || null,
      });
      setCollection({ ...collection, name: updated.name, description: updated.description });
      setEditing(false);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Failed to save.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!id || !collection) return;
    if (!window.confirm(`Delete "${collection.name}"? The media items will not be deleted.`)) return;
    try {
      await api.deleteCollection(id);
      navigate('/collections');
    } catch {
      alert('Failed to delete collection.');
    }
  }

  async function handleRemoveItem(mediaItemId: string) {
    if (!id || !collection) return;
    try {
      await api.removeItemsFromCollection(id, [mediaItemId]);
      setCollection({
        ...collection,
        items: collection.items.filter((item) => item.id !== mediaItemId),
        item_count: collection.item_count - 1,
      });
    } catch {
      alert('Failed to remove item.');
    }
  }

  if (loading) return <div className="page-loading">Loading…</div>;
  if (error || !collection) return (
    <div className="page-error">
      {error || 'Collection not found.'} <Link to="/collections">Back to Collections</Link>
    </div>
  );

  const itemIds = collection.items.map((i) => i.id);

  return (
    <div className="collection-detail-page">
      <div className="collection-detail-header">
        <Link to="/collections" className="collection-back-link">← Collections</Link>

        {editing ? (
          <form className="collection-edit-form" onSubmit={handleSaveEdit}>
            <div className="form-group">
              <label htmlFor="editName">Name</label>
              <input
                id="editName"
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                maxLength={200}
                required
                autoFocus
              />
            </div>
            <div className="form-group">
              <label htmlFor="editDesc">Description <span className="profile-optional">optional</span></label>
              <input
                id="editDesc"
                type="text"
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                maxLength={1000}
              />
            </div>
            {editError && <div className="alert alert-error">{editError}</div>}
            <div className="collection-edit-actions">
              <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className="collection-title-row">
            <div>
              <h1 className="collection-title">{collection.name}</h1>
              {collection.description && (
                <p className="collection-description">{collection.description}</p>
              )}
              <span className="collection-count">{collection.item_count} item{collection.item_count !== 1 ? 's' : ''}</span>
            </div>
            <div className="collection-header-actions">
              <button className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
                Edit
              </button>
              <button className="btn btn-danger btn-sm" onClick={handleDelete}>
                Delete
              </button>
            </div>
          </div>
        )}
      </div>

      {collection.items.length === 0 ? (
        <div className="collections-empty">
          <p>This collection is empty.</p>
          <p>Add items from the <Link to="/gallery">gallery</Link>.</p>
        </div>
      ) : (
        <div className="gallery-grid">
          {collection.items.map((item) => (
            <div key={item.id} className="collection-item-wrapper">
              <MediaCard
                id={item.id}
                filename={item.original_filename}
                status={item.status}
                mimeType={item.mime_type}
                fromPath={`/collections/${id}`}
                ids={itemIds}
              />
              <button
                className="collection-item-remove"
                title="Remove from collection"
                onClick={() => handleRemoveItem(item.id)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
