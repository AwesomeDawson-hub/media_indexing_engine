import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import * as api from '../api/client';
import { getMediaFileUrl } from '../api/client';
import { useAuthImage } from '../api/useAuthImage';
import type { MediaItemResponse, AnalysisResponse } from '../types/api';
import StatusBadge from '../components/StatusBadge';
import MetadataDisplay from '../components/MetadataDisplay';

const NO_EMBED_TYPES = ['image/bmp', 'image/gif'];
const SKIP_DELETE_CONFIRM = 'vyz_swipe_delete_confirmed';
const VERT_THRESHOLD = 80;
const HORIZ_THRESHOLD = 80;

export default function MediaDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = location.state as { from?: string; ids?: string[] } | null;
  const backHref = locationState?.from || '/';
  const ids = locationState?.ids ?? [];
  const [media, setMedia] = useState<MediaItemResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reanalyzing, setReanalyzing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [converting, setConverting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();
  const imgSrc = useAuthImage(id ? getMediaFileUrl(id) : '');

  // Swipe / gesture state
  const swipeWrapRef = useRef<HTMLDivElement>(null);
  const gestureStateRef = useRef({ startX: 0, startY: 0, axis: null as 'h' | 'v' | null, active: false, tx: 0, ty: 0 });
  const [swipeTx, setSwipeTx] = useState(0);
  const [swipeTy, setSwipeTy] = useState(0);
  const [isSwiping, setIsSwiping] = useState(false);

  // Delete confirmation modal
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [dontShowAgain, setDontShowAgain] = useState(false);

  // Neighbor navigation (ordered IDs list supplied via router state from the gallery)
  const currentIdx = ids.indexOf(id ?? '');
  const prevId = currentIdx > 0 ? ids[currentIdx - 1] : null;
  const nextId = currentIdx < ids.length - 1 ? ids[currentIdx + 1] : null;

  function goToId(targetId: string) {
    navigate(`/media/${targetId}`, { state: { from: backHref, ids } });
  }

  // Always-fresh refs for gesture / keyboard closures (avoids stale captures in effects)
  const actionsRef = useRef({
    goToId: (_id: string) => { /* updated each render */ },
    prevId: null as string | null,
    nextId: null as string | null,
    handleDownload: async () => { /* updated each render */ },
    handleSwipeDelete: () => { /* updated each render */ },
  });

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    Promise.all([api.getMedia(id), api.getAnalysis(id).catch(() => null)])
      .then(([m, a]) => {
        setMedia(m);
        setAnalysis(a);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id]);

  useEffect(() => {
    if (!id || !analysis) return;
    const isTerminal = (s: string) => ['completed', 'failed', 'error'].includes(s);
    if (isTerminal(analysis.status)) return;

    pollRef.current = setInterval(async () => {
      try {
        const a = await api.getAnalysis(id);
        setAnalysis(a);
        if (isTerminal(a.status)) {
          clearInterval(pollRef.current);
          // Re-fetch media so status badge reflects the completed state
          const m = await api.getMedia(id);
          setMedia(m);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id, analysis?.status]);

  async function handleReanalyze() {
    if (!id) return;
    setReanalyzing(true);
    try {
      await api.reanalyze(id);
      const a = await api.getAnalysis(id);
      setAnalysis(a);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Re-analyze failed');
    } finally {
      setReanalyzing(false);
    }
  }

  async function executeDelete() {
    if (!id) return;
    setDeleting(true);
    try {
      await api.deleteBatch([id]);
      navigate(backHref, { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed');
      setDeleting(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm('Delete this item? This cannot be undone.')) return;
    await executeDelete();
  }

  function handleSwipeDelete() {
    if (localStorage.getItem(SKIP_DELETE_CONFIRM)) {
      executeDelete();
    } else {
      setShowDeleteModal(true);
    }
  }

  async function handleDownload() {
    if (!id) return;
    setDownloading(true);
    try {
      await api.downloadFile(id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setDownloading(false);
    }
  }

  async function handleConvertToPng() {
    if (!id) return;
    setConverting(true);
    try {
      const result = await api.convertToPng(id);
      navigate(`/media/${result.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Conversion failed');
    } finally {
      setConverting(false);
    }
  }

  // Keep actionsRef current on every render so gesture / keyboard closures see the latest values
  actionsRef.current = { goToId, prevId, nextId, handleDownload, handleSwipeDelete };

  // Touch gesture handler — attached imperatively so touchmove can call e.preventDefault()
  useEffect(() => {
    const el = swipeWrapRef.current;
    if (!el) return;
    const g = gestureStateRef.current;

    function onStart(e: TouchEvent) {
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      g.startX = t.clientX;
      g.startY = t.clientY;
      g.axis = null;
      g.tx = 0;
      g.ty = 0;
      g.active = true;
      setIsSwiping(true);
    }

    function onMove(e: TouchEvent) {
      if (!g.active || e.touches.length !== 1) return;
      const t = e.touches[0];
      const dx = t.clientX - g.startX;
      const dy = t.clientY - g.startY;
      if (!g.axis && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
        g.axis = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      }
      if (g.axis) {
        e.preventDefault();
        const tx = g.axis === 'h' ? dx : 0;
        const ty = g.axis === 'v' ? dy : 0;
        g.tx = tx;
        g.ty = ty;
        setSwipeTx(tx);
        setSwipeTy(ty);
      }
    }

    function onEnd() {
      if (!g.active) return;
      g.active = false;
      const axis = g.axis;
      const tx = g.tx;
      const ty = g.ty;
      g.axis = null;
      g.tx = 0;
      g.ty = 0;

      const { prevId: pId, nextId: nId, goToId: go, handleDownload: dl, handleSwipeDelete: del } = actionsRef.current;

      if (axis === 'h') {
        if (tx < -HORIZ_THRESHOLD && nId) { setSwipeTx(0); setSwipeTy(0); go(nId); return; }
        if (tx > HORIZ_THRESHOLD && pId) { setSwipeTx(0); setSwipeTy(0); go(pId); return; }
      } else if (axis === 'v') {
        if (ty < -VERT_THRESHOLD) { setIsSwiping(false); setSwipeTx(0); setSwipeTy(0); del(); return; }
        if (ty > VERT_THRESHOLD) { setIsSwiping(false); setSwipeTx(0); setSwipeTy(0); dl(); return; }
      }

      // Snap back with CSS transition
      setIsSwiping(false);
      setSwipeTx(0);
      setSwipeTy(0);
    }

    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchmove', onMove, { passive: false });
    el.addEventListener('touchend', onEnd);
    el.addEventListener('touchcancel', onEnd);

    return () => {
      el.removeEventListener('touchstart', onStart);
      el.removeEventListener('touchmove', onMove);
      el.removeEventListener('touchend', onEnd);
      el.removeEventListener('touchcancel', onEnd);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard arrow navigation (desktop parity)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const { prevId: pId, nextId: nId, goToId: go } = actionsRef.current;
      if (e.key === 'ArrowLeft' && pId) go(pId);
      if (e.key === 'ArrowRight' && nId) go(nId);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return <div className="page-loading"><div className="spinner" /></div>;
  }

  if (error || !media) {
    return <div className="alert alert-danger">{error || 'Media not found'}</div>;
  }

  const isImage = media.mime_type.startsWith('image/');
  const isAnalyzed = analysis?.status === 'completed';
  const isNoEmbedFormat = NO_EMBED_TYPES.includes(media.mime_type);
  const upOpacity = swipeTy < 0 ? Math.min(1, Math.abs(swipeTy) / VERT_THRESHOLD) : 0;
  const downOpacity = swipeTy > 0 ? Math.min(1, swipeTy / VERT_THRESHOLD) : 0;

  return (
    <div>
      <Link to={backHref} className="back-link">&larr; Back to Gallery</Link>

      <div className="media-detail">
        <div className="media-detail-preview">
          <div className="swipe-zone" ref={swipeWrapRef}>
            {/* Vertical swipe action backings */}
            <div className="swipe-backing swipe-backing-up" style={{ opacity: upOpacity }}>
              <span className="swipe-backing-label">&#128465; Delete</span>
            </div>
            <div className="swipe-backing swipe-backing-down" style={{ opacity: downOpacity }}>
              <span className="swipe-backing-label">&#11015; Download</span>
            </div>

            {/* Image / placeholder — translates with the swipe gesture */}
            <div
              className="swipe-image-wrap"
              style={{
                transform: `translate(${swipeTx}px, ${swipeTy}px)`,
                transition: isSwiping ? 'none' : 'transform 0.25s ease',
              }}
            >
              {isImage && imgSrc ? (
                <img src={imgSrc} alt={media.original_filename} />
              ) : (
                <div className="media-card-placeholder large">
                  {media.mime_type.split('/')[1] || 'file'}
                </div>
              )}
            </div>

            {/* Desktop prev / next arrow buttons (also tappable on mobile) */}
            {prevId && (
              <button
                className="swipe-nav-arrow swipe-nav-arrow-left"
                onClick={() => goToId(prevId)}
                aria-label="Previous photo"
              >
                &#8249;
              </button>
            )}
            {nextId && (
              <button
                className="swipe-nav-arrow swipe-nav-arrow-right"
                onClick={() => goToId(nextId)}
                aria-label="Next photo"
              >
                &#8250;
              </button>
            )}
          </div>

          {/* Action buttons below the swipe zone */}
          {isAnalyzed && (
            <div className="media-detail-actions">
              {isNoEmbedFormat ? (
                <>
                  <button
                    className="btn btn-primary"
                    onClick={handleDownload}
                    disabled={downloading}
                  >
                    {downloading ? 'Downloading...' : 'Download'}
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={handleConvertToPng}
                    disabled={converting}
                  >
                    {converting ? 'Converting...' : 'Convert to PNG with metadata'}
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? 'Deleting...' : 'Delete'}
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="btn btn-primary"
                    onClick={handleDownload}
                    disabled={downloading}
                  >
                    {downloading ? 'Downloading...' : 'Download (with metadata)'}
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? 'Deleting...' : 'Delete'}
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="media-detail-info">
          <h1>{media.original_filename}</h1>
          <div className="media-detail-meta">
            <StatusBadge status={media.status} />
            <span>{(media.file_size / 1024).toFixed(1)} KB</span>
            <span>{media.mime_type}</span>
            {media.width && media.height && (
              <span>{media.width} × {media.height}</span>
            )}
            {media.source_name && (
              <span title="Source">📁 {media.source_name}</span>
            )}
            <span>{new Date(media.created_at).toLocaleDateString()}</span>
          </div>

          <div className="media-detail-analysis">
            <div className="section-header">
              <h2>Analysis</h2>
              <button
                className="btn btn-sm btn-outline"
                onClick={handleReanalyze}
                disabled={reanalyzing}
              >
                {reanalyzing ? 'Requesting...' : 'Re-analyze'}
              </button>
            </div>

            {!analysis && <p className="text-muted">No analysis available yet.</p>}

            {analysis && (analysis.status === 'pending' || analysis.status === 'processing') && (
              <div className="analysis-pending">
                <div className="spinner" />
                <p>Analysis in progress...</p>
              </div>
            )}

            {analysis && analysis.status === 'completed' && analysis.metadata && (
              <MetadataDisplay metadata={analysis.metadata} />
            )}

            {analysis && analysis.status === 'error' && (
              <div className="alert alert-danger">
                Analysis failed.{' '}
                {analysis.job?.error_message && <span>{analysis.job.error_message}</span>}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Swipe-delete confirmation modal (shown once unless "don't show again" is checked) */}
      {showDeleteModal && (
        <div className="modal-overlay" onClick={() => setShowDeleteModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Delete this photo?</h2>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
              This cannot be undone.
            </p>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={dontShowAgain}
                onChange={(e) => setDontShowAgain(e.target.checked)}
              />
              Don't ask again for gesture deletes
            </label>
            <div className="modal-actions">
              <button className="btn btn-outline" onClick={() => setShowDeleteModal(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  if (dontShowAgain) localStorage.setItem(SKIP_DELETE_CONFIRM, '1');
                  setShowDeleteModal(false);
                  executeDelete();
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
