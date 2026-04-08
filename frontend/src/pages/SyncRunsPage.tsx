import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type { SyncRunResponse } from '../types/api';

const PER_PAGE = 50;

const STATUS_CLASS: Record<string, string> = {
  completed: 'success',
  running: 'info',
  failed: 'danger',
  pending: 'muted',
};

function statusBadge(status: string) {
  const cls = STATUS_CLASS[status] ?? 'muted';
  return <span className={`badge badge-${cls}`}>{status}</span>;
}

function triggerBadge(triggerType: string) {
  return (
    <span className={`badge badge-${triggerType === 'auto' ? 'muted' : 'outline'}`}>
      {triggerType}
    </span>
  );
}

function formatDuration(run: SyncRunResponse): string {
  if (!run.started_at || !run.completed_at) return '—';
  const ms = new Date(run.completed_at).getTime() - new Date(run.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r > 0 ? `${m}m ${r}s` : `${m}m`;
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function SyncRunsPage() {
  const [runs, setRuns] = useState<SyncRunResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError('');
    try {
      const data = await api.listAllSyncRuns(p, PER_PAGE);
      setRuns(data.runs);
      setTotal(data.total);
    } catch {
      setError('Failed to load sync history.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(page);
  }, [page, load]);

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <div>
      <div className="page-header">
        <h1>Sync History</h1>
        <div className="upload-header-actions">
          <Link to="/sources" className="btn btn-sm btn-outline">← Connections</Link>
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      {loading ? (
        <div className="page-loading"><div className="spinner" /></div>
      ) : runs.length === 0 ? (
        <p className="text-muted">
          No sync runs yet.{' '}
          <Link to="/sources">Connect a source</Link> and trigger a sync to get started.
        </p>
      ) : (
        <>
          <p className="text-muted" style={{ marginBottom: '1rem' }}>
            {total} run{total !== 1 ? 's' : ''} across all connections
          </p>

          <div className="sync-runs-table-wrap">
            <table className="sync-runs-table">
              <thead>
                <tr>
                  <th>Connection</th>
                  <th>Type</th>
                  <th>Trigger</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th className="sync-runs-th-num">Found</th>
                  <th className="sync-runs-th-num">Imported</th>
                  <th className="sync-runs-th-num">Dupes</th>
                  <th className="sync-runs-th-num">Failed</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className={run.status === 'failed' ? 'sync-runs-row--failed' : ''}>
                    <td className="sync-runs-td-source">
                      <Link to="/sources" className="sync-runs-source-link">
                        {run.source_name ?? run.source_id}
                      </Link>
                    </td>
                    <td>{run.connector_type === 'google_drive' ? 'Drive' : run.connector_type}</td>
                    <td>{triggerBadge(run.trigger_type)}</td>
                    <td>{statusBadge(run.status)}</td>
                    <td className="sync-runs-td-ts">{formatTimestamp(run.started_at)}</td>
                    <td>{formatDuration(run)}</td>
                    <td className="sync-runs-td-num">{run.discovered_count}</td>
                    <td className="sync-runs-td-num">{run.imported_count}</td>
                    <td className="sync-runs-td-num">{run.duplicate_count}</td>
                    <td className="sync-runs-td-num sync-runs-td-failed">
                      {run.failed_count > 0 ? run.failed_count : '—'}
                    </td>
                    <td className="sync-runs-td-error">
                      {run.error_summary ? (
                        <span title={run.error_summary} className="sync-runs-error-text">
                          {run.error_summary.length > 60
                            ? run.error_summary.slice(0, 60) + '…'
                            : run.error_summary}
                        </span>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="pagination" style={{ marginTop: '1.5rem' }}>
              <button
                className="btn btn-sm btn-outline"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                ← Prev
              </button>
              <span className="pagination-info">
                Page {page} of {totalPages}
              </span>
              <button
                className="btn btn-sm btn-outline"
                disabled={page === totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
