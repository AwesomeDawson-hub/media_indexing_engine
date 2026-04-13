import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type {
  DriveFolderItem,
  CollectionResponse,
  ConnectorDriveConfigureRequest,
  ConnectorResponse,
} from '../types/api';


// ---------------------------------------------------------------------------
// Drive configure panel — shown inline after OAuth success
// ---------------------------------------------------------------------------
function DriveConfigurePanel({
  sourceId,
  onDone,
}: {
  sourceId: string;
  onDone: (connector: ConnectorResponse) => void;
}) {
  const [driveNavStack, setDriveNavStack] = useState<{ id: string; name: string }[]>([]);
  const [driveFolders, setDriveFolders] = useState<DriveFolderItem[]>([]);
  const [folderLoading, setFolderLoading] = useState(true);
  const [selectedFolder, setSelectedFolder] = useState<{ id: string; name: string } | null>(null);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [configurePending, setConfigurePending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.listDriveFolders(sourceId, 'root')
      .then((r) => setDriveFolders(r.folders))
      .catch(() => setError('Failed to load Drive folders.'))
      .finally(() => setFolderLoading(false));
    api.listCollections().then((d) => setCollections(d.collections)).catch(() => null);
  }, [sourceId]);

  async function loadFolders(parentId: string) {
    setFolderLoading(true);
    try {
      const resp = await api.listDriveFolders(sourceId, parentId);
      setDriveFolders(resp.folders);
    } catch {
      setError('Failed to load Drive folders.');
    } finally {
      setFolderLoading(false);
    }
  }

  async function handleNavInto(folder: { id: string; name: string }) {
    setDriveNavStack((prev) => [...prev, folder]);
    setSelectedFolder(folder);
    await loadFolders(folder.id);
  }

  async function handleNavTo(idx: number) {
    const newStack = driveNavStack.slice(0, idx + 1);
    setDriveNavStack(newStack);
    setSelectedFolder({ id: newStack[newStack.length - 1].id, name: newStack[newStack.length - 1].name });
    await loadFolders(newStack[newStack.length - 1].id);
  }

  async function handleNavRoot() {
    setDriveNavStack([]);
    setSelectedFolder(null);
    await loadFolders('root');
  }

  async function handleSave() {
    setError('');
    setConfigurePending(true);
    try {
      const body: ConnectorDriveConfigureRequest = {
        target_folder_id: selectedFolder?.id ?? null,
        target_folder_label: selectedFolder?.name ?? null,
        target_collection_id: selectedCollectionId,
      };
      const updated = await api.configureDriveConnector(sourceId, body);
      onDone(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Save failed: ${msg}`);
    } finally {
      setConfigurePending(false);
    }
  }

  return (
    <div className="drive-configure-panel">
      <p className="drive-configure-title">Choose sync folder</p>

      <div className="drive-breadcrumb">
        <button
          type="button"
          className={`drive-breadcrumb-item${driveNavStack.length === 0 ? ' drive-breadcrumb-item--current' : ''}`}
          onClick={handleNavRoot}
        >
          My Drive
        </button>
        {driveNavStack.map((seg, idx) => (
          <span key={seg.id}>
            <span className="drive-breadcrumb-sep">›</span>
            <button
              type="button"
              className={`drive-breadcrumb-item${idx === driveNavStack.length - 1 ? ' drive-breadcrumb-item--current' : ''}`}
              onClick={() => handleNavTo(idx)}
            >
              {seg.name}
            </button>
          </span>
        ))}
      </div>

      {folderLoading ? (
        <p className="connector-status connector-status--info">Loading folders…</p>
      ) : driveFolders.length === 0 ? (
        <p className="connector-status connector-status--info">No sub-folders here.</p>
      ) : (
        <div className="drive-folder-list">
          {driveFolders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="drive-folder-item"
              onClick={() => handleNavInto({ id: f.id, name: f.name })}
            >
              <span>📁 {f.name}</span>
              {f.has_children && <span className="drive-folder-item-chevron">›</span>}
            </button>
          ))}
        </div>
      )}

      <div className="drive-configure-selected">
        Sync from: <strong>{selectedFolder ? selectedFolder.name : 'My Drive (root)'}</strong>
      </div>

      {collections.length > 0 && (
        <div className="drive-configure-collection">
          <label>Add to collection:</label>
          <select
            value={selectedCollectionId ?? ''}
            onChange={(e) => setSelectedCollectionId(e.target.value || null)}
          >
            <option value="">No collection</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      )}

      {error && <div className="connector-status connector-status--error">{error}</div>}

      <button
        className="btn btn-primary"
        onClick={handleSave}
        disabled={configurePending}
      >
        {configurePending ? 'Saving…' : 'Save and start syncing'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddMediaPage
// ---------------------------------------------------------------------------

export default function AddMediaPage() {
  // Drive section state
  const [drivePending, setDrivePending] = useState(false);
  const [driveError, setDriveError] = useState('');
  const [callbackSourceId, setCallbackSourceId] = useState<string | null>(null);
  const [callbackResult, setCallbackResult] = useState<'connected' | 'error' | null>(null);
  const [callbackErrorCode, setCallbackErrorCode] = useState('');
  const [driveConfigured, setDriveConfigured] = useState<ConnectorResponse | null>(null);

  // Read callback query params on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connector = params.get('connector');
    const result = params.get('connector_result');
    if (connector === 'google_drive' && result) {
      if (result === 'connected') {
        const sid = params.get('source_id');
        setCallbackSourceId(sid);
        setCallbackResult('connected');
      } else if (result === 'error') {
        const code = params.get('error_code') || 'unknown_error';
        setCallbackResult('error');
        setCallbackErrorCode(code);
      }
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  // Drive handler
  async function handleDriveConnect() {
    setDriveError('');
    setDrivePending(true);
    try {
      const resp = await api.quickConnectGoogleDrive();
      window.location.href = resp.authorization_url;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setDriveError(`Could not start Google Drive connection: ${msg}`);
      setDrivePending(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>Add Media</h1>
      </div>

      {/* ── Connect Google Drive ──────────────────────────────────────────── */}
      <section className="add-media-section">
        <h2 className="add-media-section-title">Connect Google Drive</h2>

        {callbackResult === 'error' && (
          <div className="connector-status connector-status--error">
            Google Drive connection failed: {callbackErrorCode.replace(/_/g, ' ')}
          </div>
        )}

        {callbackResult === 'connected' && callbackSourceId && !driveConfigured && (
          <>
            <div className="connector-status connector-status--info">
              Google Drive connected. Choose a folder to sync below.
            </div>
            <DriveConfigurePanel
              sourceId={callbackSourceId}
              onDone={(connector) => setDriveConfigured(connector)}
            />
          </>
        )}

        {driveConfigured && (
          <div className="connector-status connector-status--info">
            Drive sync configured: <strong>{driveConfigured.target_folder_label ?? 'My Drive (root)'}</strong>.{' '}
            <Link to="/sources">Manage in Connections →</Link>
          </div>
        )}

        {!callbackResult && (
          <>
            <p className="add-media-hint">
              Connect your Google Drive to automatically sync images from a folder.
            </p>
            {driveError && <div className="connector-status connector-status--error">{driveError}</div>}
            <button
              className="btn btn-outline"
              onClick={handleDriveConnect}
              disabled={drivePending}
            >
              {drivePending ? 'Connecting…' : 'Connect Google Drive'}
            </button>
          </>
        )}
      </section>

      {/* ── Advanced Settings ─────────────────────────────────────────── */}
      <details className="advanced-settings">
        <summary className="advanced-settings-toggle">Advanced Settings</summary>

        <section className="add-media-section">
          <h2 className="add-media-section-title">Connect S3 Bucket</h2>
          <p className="add-media-hint">
            For teams storing originals in AWS S3 or an S3-compatible store (Backblaze B2, MinIO, etc.).
            Requires an IAM access key with <code>s3:ListBucket</code> and <code>s3:GetObject</code> permissions.{' '}
            <Link to="/sources">Set it up from the Connections page</Link>.
          </p>
        </section>
      </details>
    </div>
  );
}
