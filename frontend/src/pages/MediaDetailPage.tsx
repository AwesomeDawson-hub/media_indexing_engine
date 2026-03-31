import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import * as api from '../api/client';
import { getMediaFileUrl } from '../api/client';
import { useAuthImage } from '../api/useAuthImage';
import type { MediaItemResponse, AnalysisResponse } from '../types/api';
import StatusBadge from '../components/StatusBadge';
import MetadataDisplay from '../components/MetadataDisplay';

const NO_EMBED_TYPES = ['image/bmp', 'image/gif'];

export default function MediaDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const backHref = (location.state as { from?: string } | null)?.from || '/';
  const [media, setMedia] = useState<MediaItemResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reanalyzing, setReanalyzing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [converting, setConverting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();
  const imgSrc = useAuthImage(id ? getMediaFileUrl(id) : '');

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
    if (analysis.status !== 'pending' && analysis.status !== 'processing') return;

    pollRef.current = setInterval(async () => {
      try {
        const a = await api.getAnalysis(id);
        setAnalysis(a);
        if (a.status !== 'pending' && a.status !== 'processing') {
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
    <div>
      <Link to={backHref} className="back-link">&larr; Back to Gallery</Link>

      <div className="media-detail">
        <div className="media-detail-preview">
          {isImage && imgSrc ? (
            <img src={imgSrc} alt={media.original_filename} />
          ) : (
            <div className="media-card-placeholder large">
              {media.mime_type.split('/')[1] || 'file'}
            </div>
          )}

          {/* Download buttons below the image */}
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
                </>
              ) : (
                <button
                  className="btn btn-primary"
                  onClick={handleDownload}
                  disabled={downloading}
                >
                  {downloading ? 'Downloading...' : 'Download (with metadata)'}
                </button>
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
    </div>
  );
}
