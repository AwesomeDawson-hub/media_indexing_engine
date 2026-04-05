import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type {
  SourceResponse,
  ConnectorS3ConfigRequest,
  ConnectorResponse,
  SyncRunResponse,
  SyncRunsResponse,
  DriveFolderItem,
  CollectionResponse,
  ConnectorDriveConfigureRequest,
} from '../types/api';

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [expandedConnector, setExpandedConnector] = useState<string | null>(null);
  const [callbackBanner, setCallbackBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [autoConfigureSourceId, setAutoConfigureSourceId] = useState<string | null>(null);

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
        const sid = params.get('source_id');
        setCallbackBanner({ type: 'success', message: 'Google Drive connected. Choose a folder to sync.' });
        if (sid) {
          setAutoConfigureSourceId(sid);
          setExpandedConnector(sid);
        }
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
                  autoOpenConfigure={autoConfigureSourceId === s.id}
                  onAutoConfigureHandled={() => setAutoConfigureSourceId(null)}
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
  autoOpenConfigure,
  onAutoConfigureHandled,
}: {
  source: SourceResponse;
  pending: boolean;
  onArchive: () => void;
  onRestore: () => void;
  connectorExpanded?: boolean;
  onToggleConnector?: () => void;
  onSourceUpdate?: (updated: SourceResponse) => void;
  autoOpenConfigure?: boolean;
  onAutoConfigureHandled?: () => void;
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
          autoOpenConfigure={autoOpenConfigure}
          onAutoConfigureHandled={onAutoConfigureHandled}
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
  autoOpenConfigure,
  onAutoConfigureHandled,
}: {
  source: SourceResponse;
  onSourceUpdate?: (updated: SourceResponse) => void;
  autoOpenConfigure?: boolean;
  onAutoConfigureHandled?: () => void;
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

  // Drive folder + collection configure state
  const [showDriveConfigure, setShowDriveConfigure] = useState(false);
  const [driveNavStack, setDriveNavStack] = useState<{ id: string; name: string }[]>([]);
  const [driveFolders, setDriveFolders] = useState<DriveFolderItem[]>([]);
  const [folderLoading, setFolderLoading] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<{ id: string; name: string } | null>(null);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [configurePending, setConfigurePending] = useState(false);

  useEffect(() => {
    if (source.connector_status) {
      api.getConnector(source.id).then((c) => {
        setConnector(c);
        // If auto-open was requested (just OAuth'd), open the configure panel now
        if (autoOpenConfigure && c.connector_type === 'google_drive') {
          if (onAutoConfigureHandled) onAutoConfigureHandled();
          setShowDriveConfigure(true);
          setDriveNavStack([]);
          setSelectedFolder(c.target_folder_id ? { id: c.target_folder_id, name: c.target_folder_label ?? c.target_folder_id } : null);
          setSelectedCollectionId(c.target_collection_id ?? null);
          setFolderLoading(true);
          api.listDriveFolders(source.id, 'root')
            .then((r) => setDriveFolders(r.folders))
            .catch(() => null)
            .finally(() => setFolderLoading(false));
          api.listCollections().then((data) => setCollections(data.collections)).catch(() => null);
        }
      }).catch(() => null);
      loadRuns();
    }
  }, [source.id]); // eslint-disable-line react-hooks/exhaustive-deps

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
      setShowDriveConfigure(false);
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

  async function loadDriveFolders(parentId: string) {
    setFolderLoading(true);
    try {
      const resp = await api.listDriveFolders(source.id, parentId);
      setDriveFolders(resp.folders);
    } catch {
      setPanelError('Failed to load Drive folders.');
    } finally {
      setFolderLoading(false);
    }
  }

  async function handleDriveConfigOpen() {
    setPanelError('');
    setShowDriveConfigure(true);
    setDriveNavStack([]);
    setSelectedFolder(connector?.target_folder_id
      ? { id: connector.target_folder_id, name: connector.target_folder_label ?? connector.target_folder_id }
      : null);
    setSelectedCollectionId(connector?.target_collection_id ?? null);
    loadDriveFolders('root');
    try {
      const data = await api.listCollections();
      setCollections(data.collections);
    } catch {
      // collections unavailable, not fatal
    }
  }

  async function handleDriveNavInto(folder: { id: string; name: string }) {
    setDriveNavStack((prev) => [...prev, folder]);
    setSelectedFolder(folder); // navigation = selection
    await loadDriveFolders(folder.id);
  }

  async function handleDriveNavTo(idx: number) {
    const newStack = driveNavStack.slice(0, idx + 1);
    setDriveNavStack(newStack);
    setSelectedFolder({ id: newStack[newStack.length - 1].id, name: newStack[newStack.length - 1].name });
    await loadDriveFolders(newStack[newStack.length - 1].id);
  }

  async function handleDriveNavRoot() {
    setDriveNavStack([]);
    setSelectedFolder(null); // root
    await loadDriveFolders('root');
  }

  async function handleDriveConfigureSave() {
    setPanelError('');
    setConfigurePending(true);
    try {
      const body: ConnectorDriveConfigureRequest = {
        target_folder_id: selectedFolder?.id ?? null,
        target_folder_label: selectedFolder?.name ?? null,
        target_collection_id: selectedCollectionId,
      };
      const updated = await api.configureDriveConnector(source.id, body);
      setConnector(updated);
      setShowDriveConfigure(false);
      setPanelInfo(
        `Sync scope saved: ${selectedFolder ? selectedFolder.name : 'My Drive (root)'}` +
        (selectedCollectionId ? ` → collection assigned` : ''),
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPanelError(`Save failed: ${msg}`);
    } finally {
      setConfigurePending(false);
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

      {panelError && <div className="connector-status connector-status--error">{panelError}</div>}
      {panelInfo && <div className="connector-status connector-status--info">{panelInfo}</div>}

      {activeTab === 'config' && (
        <>
          {connector?.connector_type === 'google_drive' ? (
            // ── Google Drive connected ──────────────────────────────────────
            <div className="connector-drive-section">
              {!showDriveConfigure ? (
                // ── Summary view ─────────────────────────────────────────
                <>
                  <div className="connector-drive-header">
                    <div>
                      <strong>Google Drive</strong>
                      {connector.authorized_account_email && (
                        <span className="connector-drive-account"> · {connector.authorized_account_email}</span>
                      )}
                    </div>
                    <button className="btn btn-sm btn-outline" onClick={handleDriveDisconnect} disabled={drivePending}>
                      {drivePending ? '...' : 'Disconnect'}
                    </button>
                  </div>
                  <div className="connector-drive-meta">
                    <div className="connector-drive-meta-row">
                      <span className="connector-drive-meta-label">Sync folder</span>
                      <span className="connector-drive-meta-value">
                        {connector.target_folder_label ?? 'My Drive (root)'}
                      </span>
                      <button className="btn btn-sm btn-outline connector-drive-change-btn" onClick={handleDriveConfigOpen}>
                        Change
                      </button>
                    </div>
                    {connector.target_collection_id && (
                      <div className="connector-drive-meta-row">
                        <span className="connector-drive-meta-label">Collection</span>
                        <span className="connector-drive-meta-value">
                          {collections.find((c) => c.id === connector.target_collection_id)?.name ?? connector.target_collection_id}
                        </span>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                // ── Folder + collection configure ─────────────────────────
                <div className="drive-configure-panel">
                  <p className="drive-configure-title">Choose sync folder</p>

                  {/* Breadcrumb — clicking any level navigates + selects it */}
                  <div className="drive-breadcrumb">
                    <button
                      type="button"
                      className={`drive-breadcrumb-item${driveNavStack.length === 0 ? ' drive-breadcrumb-item--current' : ''}`}
                      onClick={handleDriveNavRoot}
                    >
                      My Drive
                    </button>
                    {driveNavStack.map((seg, idx) => (
                      <span key={seg.id}>
                        <span className="drive-breadcrumb-sep">›</span>
                        <button
                          type="button"
                          className={`drive-breadcrumb-item${idx === driveNavStack.length - 1 ? ' drive-breadcrumb-item--current' : ''}`}
                          onClick={() => handleDriveNavTo(idx)}
                        >
                          {seg.name}
                        </button>
                      </span>
                    ))}
                  </div>

                  {/* Sub-folder list — clicking a row navigates into it */}
                  {folderLoading ? (
                    <div className="drive-folder-loading"><div className="spinner spinner-sm" /></div>
                  ) : driveFolders.length === 0 ? (
                    <p className="drive-folder-empty">No sub-folders — will sync this folder's files</p>
                  ) : (
                    <div className="drive-folder-list">
                      {driveFolders.map((f) => (
                        <button
                          key={f.id}
                          type="button"
                          className="drive-folder-item"
                          onClick={() => handleDriveNavInto(f)}
                        >
                          <span>📁</span>
                          <span className="drive-folder-item-name">{f.name}</span>
                          <span className="drive-folder-item-chevron">›</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Collection picker */}
                  {collections.length > 0 && (
                    <div className="drive-collection-picker">
                      <label className="form-label">
                        Auto-add to collection <span className="text-muted">(optional)</span>
                      </label>
                      <select
                        className="form-input"
                        value={selectedCollectionId ?? ''}
                        onChange={(e) => setSelectedCollectionId(e.target.value || null)}
                      >
                        <option value="">— None —</option>
                        {collections.map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="drive-configure-actions">
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleDriveConfigureSave}
                      disabled={configurePending}
                    >
                      {configurePending ? 'Saving…' : 'Save'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-outline"
                      onClick={() => setShowDriveConfigure(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
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
            <p className="text-muted sync-runs-empty">No sync runs yet. Click "Sync now" to start.</p>
          ) : (
            <div className="sync-run-list">
              {runs.map((run) => (
                <div key={run.id} className="sync-run-row">
                  <div className="sync-run-left">
                    <span className={`badge badge-${
                      run.status === 'completed' ? 'success' :
                      run.status === 'running' ? 'info' :
                      run.status.startsWith('completed_with') ? 'warning' : 'danger'
                    } sync-run-status`}>{run.status}</span>
                    <span className="sync-run-date">
                      {run.started_at ? new Date(run.started_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </span>
                  </div>
                  <div className="sync-run-stats">
                    <span className="sync-run-stat" title="Discovered">{run.discovered_count} <span className="sync-run-stat-label">found</span></span>
                    <span className="sync-run-stat" title="Imported">{run.imported_count} <span className="sync-run-stat-label">imported</span></span>
                    {run.duplicate_count > 0 && <span className="sync-run-stat sync-run-stat--muted" title="Duplicates">{run.duplicate_count} <span className="sync-run-stat-label">dupes</span></span>}
                    {run.skipped_count > 0 && <span className="sync-run-stat sync-run-stat--muted" title="Skipped">{run.skipped_count} <span className="sync-run-stat-label">skipped</span></span>}
                    {run.failed_count > 0 && <span className="sync-run-stat sync-run-stat--danger" title="Failed">{run.failed_count} <span className="sync-run-stat-label">failed</span></span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
