import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import { useAuthImage } from '../api/useAuthImage';
import type { CollectionResponse } from '../types/api';

function CollectionCard({ collection, onDelete }: { collection: CollectionResponse; onDelete: (id: string) => void }) {
  const coverSrc = useAuthImage(collection.cover_url ?? '');

  return (
    <div className="collection-card">
      <Link to={`/collections/${collection.id}`} className="collection-card-link">
        <div className="collection-card-cover">
          {coverSrc ? (
            <img src={coverSrc} alt={collection.name} />
          ) : (
            <div className="collection-card-empty-cover">
              <span>No items</span>
            </div>
          )}
          <span className="collection-card-count">{collection.item_count}</span>
        </div>
        <div className="collection-card-info">
          <span className="collection-card-name" title={collection.name}>{collection.name}</span>
          {collection.description && (
            <span className="collection-card-desc">{collection.description}</span>
          )}
        </div>
      </Link>
      <button
        className="collection-card-delete"
        title="Delete collection"
        onClick={() => onDelete(collection.id)}
      >
        ×
      </button>
    </div>
  );
}

export default function CollectionsPage() {
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    try {
      const res = await api.listCollections();
      setCollections(res.collections);
    } catch {
      setError('Failed to load collections.');
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      const created = await api.createCollection(newName.trim(), newDesc.trim() || undefined);
      setCollections((prev) => [created, ...prev]);
      setNewName('');
      setNewDesc('');
      setShowCreate(false);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create collection.');
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    const coll = collections.find((c) => c.id === id);
    if (!coll) return;
    if (!window.confirm(`Delete "${coll.name}"? The media items will not be deleted.`)) return;
    try {
      await api.deleteCollection(id);
      setCollections((prev) => prev.filter((c) => c.id !== id));
    } catch {
      alert('Failed to delete collection.');
    }
  }

  if (loading) return <div className="page-loading">Loading…</div>;

  return (
    <div className="collections-page">
      <div className="collections-header">
        <h1>Collections</h1>
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? 'Cancel' : '+ New Collection'}
        </button>
      </div>

      {showCreate && (
        <form className="collection-create-form" onSubmit={handleCreate}>
          <div className="form-group">
            <label htmlFor="collectionName">Name</label>
            <input
              id="collectionName"
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              maxLength={200}
              placeholder="e.g. Summer 2025"
              required
              autoFocus
            />
          </div>
          <div className="form-group">
            <label htmlFor="collectionDesc">
              Description <span className="profile-optional">optional</span>
            </label>
            <input
              id="collectionDesc"
              type="text"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              maxLength={1000}
              placeholder="A short description"
            />
          </div>
          {createError && <div className="alert alert-error">{createError}</div>}
          <button type="submit" className="btn btn-primary btn-sm" disabled={creating}>
            {creating ? 'Creating…' : 'Create'}
          </button>
        </form>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {collections.length === 0 ? (
        <div className="collections-empty">
          <p>No collections yet.</p>
          <p>Create a collection to organise your media into named groups.</p>
        </div>
      ) : (
        <div className="collections-grid">
          {collections.map((c) => (
            <CollectionCard key={c.id} collection={c} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  );
}
