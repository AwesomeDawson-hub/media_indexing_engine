import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type { SourceResponse } from '../types/api';

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [error, setError] = useState('');

  async function load(includeArchived: boolean) {
    setLoading(true);
    try {
      const data = await api.listSources(includeArchived);
      setSources(data);
    } catch {
      setError('Failed to load sources.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(showArchived);
  }, [showArchived]);

  async function handleArchive(id: string) {
    setActionPending(id);
    try {
      const updated = await api.archiveSource(id);
      setSources((prev) => prev.map((s) => (s.id === id ? { ...updated, media_count: s.media_count } : s)));
    } catch {
      setError('Failed to archive source.');
    } finally {
      setActionPending(null);
    }
  }

  async function handleRestore(id: string) {
    setActionPending(id);
    try {
      const updated = await api.restoreSource(id);
      setSources((prev) => prev.map((s) => (s.id === id ? { ...updated, media_count: s.media_count } : s)));
    } catch {
      setError('Failed to restore source.');
    } finally {
      setActionPending(null);
    }
  }

  const active = sources.filter((s) => !s.archived_at);
  const archived = sources.filter((s) => s.archived_at);

  return (
    <div>
      <div className="page-header">
        <h1>Sources</h1>
        <div className="upload-header-actions">
          <label className="sources-toggle-archived">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            Show archived
          </label>
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      {loading ? (
        <div className="page-loading"><div className="spinner" /></div>
      ) : (
        <>
          {active.length === 0 && !showArchived && (
            <p className="text-muted">No active sources. Create one on the <Link to="/upload">Upload page</Link>.</p>
          )}

          {active.length > 0 && (
            <div className="sources-list">
              {active.map((s) => (
                <SourceRow
                  key={s.id}
                  source={s}
                  pending={actionPending === s.id}
                  onArchive={() => handleArchive(s.id)}
                  onRestore={() => handleRestore(s.id)}
                />
              ))}
            </div>
          )}

          {showArchived && archived.length > 0 && (
            <>
              <h2 className="sources-section-heading">Archived</h2>
              <div className="sources-list">
                {archived.map((s) => (
                  <SourceRow
                    key={s.id}
                    source={s}
                    pending={actionPending === s.id}
                    onArchive={() => handleArchive(s.id)}
                    onRestore={() => handleRestore(s.id)}
                  />
                ))}
              </div>
            </>
          )}

          {showArchived && archived.length === 0 && (
            <p className="text-muted sources-no-archived">No archived sources.</p>
          )}
        </>
      )}
    </div>
  );
}

function SourceRow({
  source,
  pending,
  onArchive,
  onRestore,
}: {
  source: SourceResponse;
  pending: boolean;
  onArchive: () => void;
  onRestore: () => void;
}) {
  const isArchived = !!source.archived_at;
  return (
    <div className={`source-row card${isArchived ? ' source-row--archived' : ''}`}>
      <div className="source-row-info">
        <span className="source-row-name">{source.name}</span>
        <span className="source-row-meta">
          {source.media_count} {source.media_count === 1 ? 'item' : 'items'}
          {' · '}
          {source.source_type}
          {isArchived && <span className="badge badge-muted">Archived</span>}
        </span>
      </div>
      <div className="source-row-actions">
        {isArchived ? (
          <button
            className="btn btn-sm btn-outline"
            onClick={onRestore}
            disabled={pending}
          >
            {pending ? '...' : 'Restore'}
          </button>
        ) : (
          <button
            className="btn btn-sm btn-outline"
            onClick={onArchive}
            disabled={pending}
          >
            {pending ? '...' : 'Archive'}
          </button>
        )}
      </div>
    </div>
  );
}
