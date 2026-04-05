import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type {
  SourceResponse,
  ConnectorS3ConfigRequest,
  ConnectorResponse,
  SyncRunResponse,
  SyncRunsResponse,
} from '../types/api';

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [expandedConnector, setExpandedConnector] = useState<string | null>(null);
  const [callbackBanner, setCallbackBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

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

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connector = params.get('connector');
    const result = params.get('connector_result');
    if (connector === 'google_drive' && result) {
      if (result === 'connected') {
        setCallbackBanner({ type: 'success', message: 'Google Drive connected successfully.' });
        load(false);
      } else if (result === 'error') {
        const code = params.get('error_code') || 'unknown_error';
        setCallbackBanner({ type: 'error', message: `Google Drive connection failed: ${code.replace(/_/g, ' ')}` });
      }
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

      {callbackBanner && (
        <div className={`alert alert-${callbackBanner.type === 'success' ? 'info' : 'danger'}`}>
          {callbackBanner.message}
          <button className="btn btn-sm btn-outline" style={{ marginLeft: '1rem' }} onClick={() => setCallbackBanner(null)}>Dismiss</button>
        </div>
      )}

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
                  connectorExpanded={expandedConnector === s.id}
                  onToggleConnector={() =>
                    setExpandedConnector((prev) => (prev === s.id ? null : s.id))
                  }
                  onSourceUpdate={(updated) =>
                    setSources((prev) => prev.map((x) => (x.id === s.id ? updated : x)))
                  }
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
  connectorExpanded,
  onToggleConnector,
  onSourceUpdate,
}: {
  source: SourceResponse;
  pending: boolean;
  onArchive: () => void;
  onRestore: () => void;
  connectorExpanded?: boolean;
  onToggleConnector?: () => void;
  onSourceUpdate?: (updated: SourceResponse) => void;
}) {
  const isArchived = !!source.archived_at;
  const hasConnector = !!source.connector_status;
  return (
    <div className={`source-row card${isArchived ? ' source-row--archived' : ''}`}>
      <div className="source-row-info">
        <span className="source-row-name">{source.name}</span>
        <span className="source-row-meta">
          {source.media_count} {source.media_count === 1 ? 'item' : 'items'}
          {' · '}
          {source.source_type}
          {isArchived && <span className="badge badge-muted">Archived</span>}
          {hasConnector && (
            <span
              className={`badge badge-${
                source.connector_status === 'syncing' ? 'info' :
                source.connector_status === 'configured' ? 'success' :
                source.connector_status === 'error' ? 'danger' : 'muted'
              }`}
              title={source.last_synced_at ? `Last synced ${source.last_synced_at}` : undefined}
            >
              {source.connector_status}
            </span>
          )}
        </span>
      </div>
      <div className="source-row-actions">
        {!isArchived && (
          <button
            className="btn btn-sm btn-outline"
            onClick={onToggleConnector}
            title={hasConnector ? 'Connector settings' : 'Connect source'}
          >
            {connectorExpanded ? 'Close' : hasConnector ? 'Connector' : 'Connect'}
          </button>
        )}
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
      {connectorExpanded && !isArchived && (
        <ConnectorPanel
          source={source}
          onSourceUpdate={onSourceUpdate}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ConnectorPanel — S3 config form + sync trigger + run history
// ---------------------------------------------------------------------------

function ConnectorPanel({
  source,
  onSourceUpdate,
}: {
  source: SourceResponse;
  onSourceUpdate?: (updated: SourceResponse) => void;
}) {
  const [activeTab, setActiveTab] = useState<'config' | 'runs'>(source.connector_status ? 'runs' : 'config');
  const [formData, setFormData] = useState<ConnectorS3ConfigRequest>({
    bucket_name: '',
    access_key_id: '',
    secret_access_key: '',
    region: '',
    endpoint_url: '',
    prefix: '',
  });
  const [connector, setConnector] = useState<ConnectorResponse | null>(null);
  const [runs, setRuns] = useState<SyncRunResponse[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [syncPending, setSyncPending] = useState(false);
  const [savePending, setSavePending] = useState(false);
  const [drivePending, setDrivePending] = useState(false);
  const [showS3Form, setShowS3Form] = useState(false);
  const [panelError, setPanelError] = useState('');
  const [panelInfo, setPanelInfo] = useState('');

  useEffect(() => {
    if (source.connector_status) {
      api.getConnector(source.id).then(setConnector).catch(() => null);
      loadRuns();
    }
  }, [source.id]);

  async function loadRuns() {
    try {
      const result: SyncRunsResponse = await api.listSyncRuns(source.id);
      setRuns(result.runs);
      setRunsTotal(result.total);
    } catch {
      // silently fail
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setPanelError('');
    setPanelInfo('');
    setSavePending(true);
    try {
      const saved = await api.configureS3Connector(source.id, formData);
      setConnector(saved);
      if (onSourceUpdate) {
        onSourceUpdate({ ...source, connector_status: 'configured', source_type: 's3_compatible' });
      }
      setPanelInfo('Connector saved. Credentials are encrypted at rest and never shown again.');
      setFormData((prev) => ({ ...prev, access_key_id: '', secret_access_key: '' }));
      setActiveTab('runs');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPanelError(`Save failed: ${msg}`);
    } finally {
      setSavePending(false);
    }
  }

  async function handleSync() {
    setPanelError('');
    setPanelInfo('');
    setSyncPending(true);
    try {
      const result = await api.triggerSync(source.id);
      setPanelInfo(result.message);
      setTimeout(() => loadRuns(), 1500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPanelError(`Sync failed: ${msg}`);
    } finally {
      setSyncPending(false);
    }
  }

  async function handleDriveConnect() {
    setPanelError('');
    setDrivePending(true);
    try {
      const resp = await api.startGoogleDriveConnector(source.id);
      window.location.href = resp.authorization_url;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPanelError(`Could not start Google Drive connection: ${msg}`);
      setDrivePending(false);
    }
  }

  async function handleDriveDisconnect() {
    setPanelError('');
    setDrivePending(true);
    try {
      await api.disconnectGoogleDriveConnector(source.id);
      setConnector(null);
      if (onSourceUpdate) {
        onSourceUpdate({ ...source, connector_status: 'disconnected', source_type: 'google_drive' });
      }
      setPanelInfo('Google Drive disconnected.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPanelError(`Disconnect failed: ${msg}`);
    } finally {
      setDrivePending(false);
    }
  }

  return (
    <div className="connector-panel">
      <div className="connector-tabs">
        <button
          className={`connector-tab${activeTab === 'config' ? ' connector-tab--active' : ''}`}
          onClick={() => setActiveTab('config')}
        >
          Configure
        </button>
        <button
          className={`connector-tab${activeTab === 'runs' ? ' connector-tab--active' : ''}`}
          onClick={() => { setActiveTab('runs'); loadRuns(); }}
        >
          Sync runs {runsTotal > 0 ? `(${runsTotal})` : ''}
        </button>
        {source.connector_status && source.connector_status !== 'syncing' && (
          <button
            className="btn btn-sm btn-primary connector-sync-btn"
            onClick={handleSync}
            disabled={syncPending}
          >
            {syncPending ? 'Syncing…' : 'Sync now'}
          </button>
        )}
      </div>

      {panelError && <div className="alert alert-danger connector-alert">{panelError}</div>}
      {panelInfo && <div className="alert alert-info connector-alert">{panelInfo}</div>}

      {activeTab === 'config' && (
        <>
          {connector?.connector_type === 'google_drive' ? (
            // ── Google Drive connected ──────────────────────────────────────
            <div className="connector-drive-section">
              <p>
                <strong>Google Drive</strong> — My Drive
                {connector.authorized_account_email && (
                  <span className="text-muted"> ({connector.authorized_account_email})</span>
                )}
                {connector.authorized_account_display_name && (
                  <span className="text-muted"> · {connector.authorized_account_display_name}</span>
                )}
              </p>
              <button
                className="btn btn-sm btn-outline"
                onClick={handleDriveDisconnect}
                disabled={drivePending}
              >
                {drivePending ? '...' : 'Disconnect Google Drive'}
              </button>
            </div>
          ) : connector?.connector_type === 's3_compatible' ? (
            // ── S3 connected — show form to reconfigure ────────────────────
            <form onSubmit={handleSave} className="connector-form">
              <p className="text-muted connector-existing-note">
                Connected: <strong>{connector.remote_container_id}</strong>
                {connector.prefix ? `/${connector.prefix}` : ''}
                {connector.region ? ` (${connector.region})` : ''}
                . Enter new credentials to replace.
              </p>
              <label className="form-label">Bucket name *</label>
              <input
                className="form-input"
                required
                value={formData.bucket_name}
                onChange={(e) => setFormData((p) => ({ ...p, bucket_name: e.target.value }))}
              />
              <label className="form-label">Access key ID *</label>
              <input
                className="form-input"
                required
                autoComplete="off"
                value={formData.access_key_id}
                onChange={(e) => setFormData((p) => ({ ...p, access_key_id: e.target.value }))}
              />
              <label className="form-label">Secret access key *</label>
              <input
                className="form-input"
                type="password"
                required
                autoComplete="new-password"
                value={formData.secret_access_key}
                onChange={(e) => setFormData((p) => ({ ...p, secret_access_key: e.target.value }))}
              />
              <label className="form-label">Region</label>
              <input
                className="form-input"
                placeholder="us-east-1"
                value={formData.region ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, region: e.target.value }))}
              />
              <label className="form-label">Endpoint URL (S3-compatible)</label>
              <input
                className="form-input"
                placeholder="https://s3.example.com"
                value={formData.endpoint_url ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, endpoint_url: e.target.value }))}
              />
              <label className="form-label">Prefix (folder path)</label>
              <input
                className="form-input"
                placeholder="images/"
                value={formData.prefix ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, prefix: e.target.value }))}
              />
              <button className="btn btn-primary" type="submit" disabled={savePending}>
                {savePending ? 'Saving…' : 'Save connector'}
              </button>
            </form>
          ) : showS3Form ? (
            // ── S3 setup form ──────────────────────────────────────────────
            <form onSubmit={handleSave} className="connector-form">
              <button
                type="button"
                className="btn btn-sm btn-outline connector-back-btn"
                onClick={() => setShowS3Form(false)}
              >
                ← Back
              </button>
              <label className="form-label">Bucket name *</label>
              <input
                className="form-input"
                required
                value={formData.bucket_name}
                onChange={(e) => setFormData((p) => ({ ...p, bucket_name: e.target.value }))}
              />
              <label className="form-label">Access key ID *</label>
              <input
                className="form-input"
                required
                autoComplete="off"
                value={formData.access_key_id}
                onChange={(e) => setFormData((p) => ({ ...p, access_key_id: e.target.value }))}
              />
              <label className="form-label">Secret access key *</label>
              <input
                className="form-input"
                type="password"
                required
                autoComplete="new-password"
                value={formData.secret_access_key}
                onChange={(e) => setFormData((p) => ({ ...p, secret_access_key: e.target.value }))}
              />
              <label className="form-label">Region</label>
              <input
                className="form-input"
                placeholder="us-east-1"
                value={formData.region ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, region: e.target.value }))}
              />
              <label className="form-label">Endpoint URL (S3-compatible)</label>
              <input
                className="form-input"
                placeholder="https://s3.example.com"
                value={formData.endpoint_url ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, endpoint_url: e.target.value }))}
              />
              <label className="form-label">Prefix (folder path)</label>
              <input
                className="form-input"
                placeholder="images/"
                value={formData.prefix ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, prefix: e.target.value }))}
              />
              <button className="btn btn-primary" type="submit" disabled={savePending}>
                {savePending ? 'Saving…' : 'Save connector'}
              </button>
            </form>
          ) : (
            // ── No connector — pick one ────────────────────────────────────
            <div className="connector-picker">
              <p className="text-muted">Choose how to connect this source:</p>
              <div className="connector-picker-options">
                <button
                  className="btn btn-outline connector-picker-btn"
                  onClick={() => setShowS3Form(true)}
                >
                  <span className="connector-picker-icon">🪣</span>
                  <span className="connector-picker-label">S3 / S3-compatible</span>
                  <span className="connector-picker-sub">AWS S3, MinIO, Backblaze B2</span>
                </button>
                <button
                  className="btn btn-outline connector-picker-btn"
                  onClick={handleDriveConnect}
                  disabled={drivePending}
                >
                  <span className="connector-picker-icon">📁</span>
                  <span className="connector-picker-label">{drivePending ? 'Redirecting…' : 'Google Drive'}</span>
                  <span className="connector-picker-sub">Connect My Drive</span>
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {activeTab === 'runs' && (
        <div className="sync-runs">
          {runs.length === 0 ? (
            <p className="text-muted">No sync runs yet. Click &quot;Sync now&quot; to start the first sync.</p>
          ) : (
            <table className="sync-runs-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Discovered</th>
                  <th>Imported</th>
                  <th>Dupes</th>
                  <th>Skipped</th>
                  <th>Failed</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</td>
                    <td>
                      <span className={`badge badge-${
                        run.status === 'completed' ? 'success' :
                        run.status === 'running' ? 'info' :
                        run.status.startsWith('completed_with') ? 'warning' : 'danger'
                      }`}>{run.status}</span>
                    </td>
                    <td>{run.discovered_count}</td>
                    <td>{run.imported_count}</td>
                    <td>{run.duplicate_count}</td>
                    <td>{run.skipped_count}</td>
                    <td>{run.failed_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
