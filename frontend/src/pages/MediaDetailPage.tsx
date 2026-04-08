import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import * as api from '../api/client';
import { getMediaThumbnailUrl } from '../api/client';
import { useAuthImage, prefetchAuthImage } from '../api/useAuthImage';
import type { MediaItemResponse, AnalysisResponse, SimilarItemsResponse, CollectionResponse } from '../types/api';
import StatusBadge from '../components/StatusBadge';
import MetadataDisplay from '../components/MetadataDisplay';
import AuthImage from '../components/AuthImage';

const NO_EMBED_TYPES = ['image/bmp', 'image/gif'];
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
  const [similar, setSimilar] = useState<SimilarItemsResponse | null>(null);
  const [scoring, setScoring] = useState(false);
  const [scoreError, setScoreError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeHint, setReanalyzeHint] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [converting, setConverting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();
  const imgSrc = useAuthImage(id ? getMediaThumbnailUrl(id) : '');

  // Add to Collection
  const [showCollectionPicker, setShowCollectionPicker] = useState(false);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [collectionsLoaded, setCollectionsLoaded] = useState(false);
  const [addingToCollection, setAddingToCollection] = useState(false);
  const [collectionMsg, setCollectionMsg] = useState('');

  // Drive write-back retry (P7-005)
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState('');

  // Swipe / gesture state
  const swipeWrapRef = useRef<HTMLDivElement>(null);
  const gestureStateRef = useRef({ startX: 0, startY: 0, axis: null as 'h' | null, active: false, tx: 0 });
  const [swipeTx, setSwipeTx] = useState(0);
  const [isSwiping, setIsSwiping] = useState(false);

  // Neighbor navigation (ordered IDs list supplied via router state from the gallery)
  const currentIdx = ids.indexOf(id ?? '');
  const prevId = currentIdx > 0 ? ids[currentIdx - 1] : null;
  const nextId = currentIdx < ids.length - 1 ? ids[currentIdx + 1] : null;

  // Warm the image cache for neighbours so arrow/swipe navigation feels instant
  useEffect(() => {
    if (prevId) prefetchAuthImage(getMediaThumbnailUrl(prevId));
    if (nextId) prefetchAuthImage(getMediaThumbnailUrl(nextId));
  }, [prevId, nextId]);

  function goToId(targetId: string) {
    navigate(`/media/${targetId}`, { state: { from: backHref, ids } });
  }

  // Always-fresh refs for gesture / keyboard closures (avoids stale captures in effects)
  const actionsRef = useRef({
    goToId: (_id: string) => { /* updated each render */ },
    prevId: null as string | null,
    nextId: null as string | null,
  });

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    Promise.all([api.getMedia(id), api.getAnalysis(id).catch(() => null)])
      .then(([m, a]) => {
        setMedia(m);
        setAnalysis(a);
        // Fetch similar photos — feature gate enforced server-side; 404 = gate OFF
        if (m.has_similar) {
          api.getSimilarMedia(id).then(setSimilar).catch(() => null);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id]);

  const isTerminal = (s: string) => ['completed', 'failed', 'error'].includes(s);

  useEffect(() => {
    if (!id) return;
    // reanalyzing=true forces poll even if analysis.status hasn't changed yet (race condition fix)
    const analysisSettled = !reanalyzing && analysis !== null && isTerminal(analysis.status);
    const mediaSettled = media !== null && media.status !== 'processing' && media.status !== 'pending';
    if (analysisSettled && mediaSettled) return;

    pollRef.current = setInterval(async () => {
      try {
        const [m, a] = await Promise.all([
          api.getMedia(id),
          api.getAnalysis(id).catch(() => null),
        ]);
        setMedia(m);
        setAnalysis(a);
        if (a && isTerminal(a.status)) {
          clearInterval(pollRef.current);
          setReanalyzing(false);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id, analysis?.status, media?.status, reanalyzing]);

  async function handleReanalyze(hint?: string) {
    if (!id) return;
    setReanalyzing(true);
    // Don't fetch analysis here — backend may still return old 'completed' status
    // (race condition). The poll effect starts because reanalyzing=true.
    try {
      await api.reanalyze(id, hint || undefined);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Re-analyze failed');
      setReanalyzing(false);
    }
  }

  async function handleRetryWriteback() {
    if (!id) return;
    setRetrying(true);
    setRetryError('');
    try {
      const result = await api.retryWriteback(id);
      setMedia((prev) => prev ? { ...prev, mutation_state: result.mutation_state } : prev);
    } catch (err: unknown) {
      setRetryError(err instanceof Error ? err.message : 'Retry failed');
    } finally {
      setRetrying(false);
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

  async function handleOpenCollectionPicker() {
    setShowCollectionPicker((v) => !v);
    setCollectionMsg('');
    if (!collectionsLoaded) {
      try {
        const res = await api.listCollections();
        setCollections(res.collections);
        setCollectionsLoaded(true);
      } catch { /* silent */ }
    }
  }

  async function handleAddToCollection(collectionId: string, collectionName: string) {
    if (!id) return;
    setAddingToCollection(true);
    try {
      const res = await api.addItemsToCollection(collectionId, [id]);
      setCollectionMsg(`Added to "${collectionName}".`);
      if (res.skipped > 0) setCollectionMsg(`Already in "${collectionName}".`);
      setShowCollectionPicker(false);
    } catch { /* silent */ } finally {
      setAddingToCollection(false);
    }
  }

  async function handleDownload() {    if (!id) return;
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
  actionsRef.current = { goToId, prevId, nextId };

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
      g.active = true;
    }

    function onMove(e: TouchEvent) {
      if (!g.active || e.touches.length !== 1) return;
      const t = e.touches[0];
      const dx = t.clientX - g.startX;
      const dy = t.clientY - g.startY;
      if (!g.axis && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
        if (Math.abs(dx) > Math.abs(dy)) {
          g.axis = 'h';
        } else {
          g.active = false; // vertical — let browser scroll
          return;
        }
      }
      if (g.axis === 'h') {
        e.preventDefault();
        g.tx = dx;
        setSwipeTx(dx);
        setIsSwiping(true);
      }
    }

    function onEnd() {
      if (!g.active) return;
      g.active = false;
      const tx = g.tx;
      g.axis = null;
      g.tx = 0;

      const { prevId: pId, nextId: nId, goToId: go } = actionsRef.current;

      if (tx < -HORIZ_THRESHOLD && nId) { setSwipeTx(0); setIsSwiping(false); go(nId); return; }
      if (tx > HORIZ_THRESHOLD && pId) { setSwipeTx(0); setIsSwiping(false); go(pId); return; }

      // Snap back with CSS transition
      setIsSwiping(false);
      setSwipeTx(0);
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
  }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

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

  return (
    <div ref={swipeWrapRef} className="swipe-zone">
      {/* Fixed prev/next arrows — visible on both sides of the full page */}
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

      <div
        className="swipe-content-wrap"
        style={{
          transform: `translateX(${swipeTx}px)`,
          transition: isSwiping ? 'none' : 'transform 0.25s ease',
        }}
      >
      <Link to={backHref} className="back-link">&larr; Back to Gallery</Link>

      <div className="media-detail">
        <div className="media-detail-preview">
          <div className="swipe-image-wrap">
            {isImage && imgSrc ? (
              <img src={imgSrc} alt={media.original_filename} />
            ) : (
              <div className="media-card-placeholder large">
                {media.mime_type.split('/')[1] || 'file'}
              </div>
            )}
          </div>

          {/* Action buttons below the swipe zone */}
          {isAnalyzed && (
            <div className="media-detail-actions">
              {collectionMsg && <span className="collection-feedback-msg">{collectionMsg}</span>}
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
                  <div className="detail-collection-wrapper">
                    <button
                      className="btn btn-secondary"
                      onClick={handleOpenCollectionPicker}
                      disabled={addingToCollection}
                    >
                      + Collection
                    </button>
                    {showCollectionPicker && (
                      <div className="selection-collection-dropdown">
                        {collections.length === 0 ? (
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
                  <div className="detail-collection-wrapper">
                    <button
                      className="btn btn-secondary"
                      onClick={handleOpenCollectionPicker}
                      disabled={addingToCollection}
                    >
                      + Collection
                    </button>
                    {showCollectionPicker && (
                      <div className="selection-collection-dropdown">
                        {collections.length === 0 ? (
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

          {/* Source mutation state (P7-004) */}
          {media.status === 'completed' && media.mutation_state && (
            <div className={`mutation-state-banner mutation-state--${media.mutation_state}`}>
              {media.mutation_state === 'fully_applied' && (
                <span>✓ Source file updated — filename and metadata applied at source</span>
              )}
              {media.mutation_state === 'pending_writeback' && (
                <>
                  <span>⏳ Write-back pending — source file update in progress</span>
                  <button
                    className="btn btn-sm btn-secondary mutation-retry-btn"
                    onClick={handleRetryWriteback}
                    disabled={retrying}
                  >
                    {retrying ? 'Retrying…' : 'Retry now'}
                  </button>
                  {retryError && (
                    <span className="mutation-action-hint mutation-retry-error"> {retryError}</span>
                  )}
                </>
              )}
              {media.mutation_state === 'blocked_writeback' && (
                <>
                  <span>⚠ Write-back blocked — source file has not been updated</span>
                  {analysis?.last_mutation_error_code === 'no_write_scope' && (
                    <span className="mutation-action-hint">
                      {' '}Reconnect Google Drive with write permission to enable rename and metadata write-back.
                    </span>
                  )}
                  {analysis?.last_mutation_error_code === 'local_access_lost' && (
                    <span className="mutation-action-hint">
                      {' '}Folder access was lost. Reselect the folder to retry.
                    </span>
                  )}
                </>
              )}
            </div>
          )}

          <div className="media-detail-analysis">
            <div className="section-header">
              <h2>Analysis</h2>
              {reanalyzing && (
                <span className="reanalyze-confirm-label">Analyzing...</span>
              )}
            </div>
            {!reanalyzing && (
              <div className="reanalyze-confirm">
                <label className="reanalyze-hint-label">Optional guidance for the AI</label>
                <textarea
                  className="reanalyze-hint-input"
                  placeholder="e.g. 'focus on the background details', 'this is a wedding photo', 'identify the car model'"
                  value={reanalyzeHint}
                  onChange={(e) => setReanalyzeHint(e.target.value)}
                  maxLength={500}
                />
                <div className="reanalyze-confirm-row">
                  <span className="reanalyze-confirm-label">Uses 1 credit —</span>
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => { handleReanalyze(reanalyzeHint); }}
                    disabled={analysis?.status === 'processing' || analysis?.status === 'pending'}
                  >
                    Re-analyze
                  </button>
                </div>
              </div>
            )}

            {!reanalyzing && !analysis && <p className="text-muted">No analysis available yet.</p>}

            {(reanalyzing || (analysis && (analysis.status === 'pending' || analysis.status === 'processing'))) && (
              <div className="analysis-pending">
                <div className="spinner" />
                <p>Analysis in progress...</p>
              </div>
            )}

            {!reanalyzing && analysis && analysis.status === 'completed' && analysis.metadata && (
              <MetadataDisplay
                metadata={analysis.metadata}
                onSave={async (updated) => {
                  if (!id) return;
                  const result = await api.updateMetadata(id, updated);
                  setAnalysis(result);
                }}
              />
            )}

            {analysis && analysis.status === 'error' && (
              <div className="alert alert-danger">
                Analysis failed.{' '}
                {analysis.job?.error_message && <span>{analysis.job.error_message}</span>}
              </div>
            )}
          </div>

          {similar && similar.similar.length > 0 && (
            <div className="media-detail-similar">
              <div className="similar-header">
                <h2>Similar Photos ({similar.similar.length})</h2>
                {/* Show Score button when AI scoring gate is on but group not yet scored */}
                {similar.similar.every((s) => s.quality_score == null) && (
                  <button
                    className="btn btn-secondary btn-sm"
                    disabled={scoring}
                    onClick={async () => {
                      if (!id) return;
                      setScoring(true);
                      setScoreError('');
                      try {
                        await api.scoreGroup(id);
                        // Refresh similar data to pick up new scores
                        const refreshed = await api.getSimilarMedia(id);
                        setSimilar(refreshed);
                      } catch {
                        setScoreError('Scoring failed. Check API key and try again.');
                      } finally {
                        setScoring(false);
                      }
                    }}
                  >
                    {scoring ? 'Scoring…' : 'Find best pick'}
                  </button>
                )}
              </div>
              {scoreError && <p className="score-error">{scoreError}</p>}
              <div className="similar-strip">
                {/* Anchor item (current page) */}
                <div
                  className={`similar-item similar-item--anchor${similar.anchor_is_best_pick ? ' similar-item--best-pick' : ''}`}
                  title="Current photo"
                >
                  {similar.anchor_is_best_pick && <span className="best-pick-crown" title="Best pick">👑</span>}
                  <AuthImage
                    src={getMediaThumbnailUrl(id!)}
                    alt="Current photo"
                    className="similar-item-thumb"
                  />
                  {similar.anchor_quality_score != null && (
                    <span
                      className="similar-item-score"
                      title={similar.anchor_rationale ?? undefined}
                    >
                      {Math.round(similar.anchor_quality_score * 100)}%
                    </span>
                  )}
                  <span className="similar-item-dist">this</span>
                </div>
                {similar.similar.map((s) => (
                  <Link
                    key={s.id}
                    to={`/media/${s.id}`}
                    state={{ from: backHref, ids }}
                    className={`similar-item${s.is_best_pick ? ' similar-item--best-pick' : ''}`}
                    title={`${s.hamming_distance} bit${s.hamming_distance === 1 ? '' : 's'} apart${
                      s.rationale ? ` • ${s.rationale}` : ''
                    }`}
                  >
                    {s.is_best_pick && <span className="best-pick-crown" title="Best pick">👑</span>}
                    <AuthImage
                      src={getMediaThumbnailUrl(s.id)}
                      alt={s.media_item.display_name || s.media_item.original_filename}
                      className="similar-item-thumb"
                    />
                    {s.quality_score != null && (
                      <span
                        className="similar-item-score"
                        title={s.rationale ?? undefined}
                      >
                        {Math.round(s.quality_score * 100)}%
                      </span>
                    )}
                    <span className="similar-item-dist">{s.hamming_distance}b</span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      </div>{/* end swipe-content-wrap */}
    </div>
  );
}
