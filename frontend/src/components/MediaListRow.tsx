import { Link } from 'react-router-dom';
import { getMediaFileUrl } from '../api/client';
import { useAuthImage } from '../api/useAuthImage';
import StatusBadge from './StatusBadge';

interface MediaListRowProps {
  id: string;
  filename: string;
  status: string;
  mimeType: string;
  fileSize: number;
  createdAt: string;
  selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
  fromPath?: string;
}

export default function MediaListRow({
  id, filename, status, mimeType, fileSize, createdAt, selected, onSelect, fromPath,
}: MediaListRowProps) {
  const imgSrc = useAuthImage(getMediaFileUrl(id));

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <div className="media-list-row">
      <label className="media-list-checkbox">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(id, e.target.checked)}
        />
      </label>
      <Link to={`/media/${id}`} state={{ from: fromPath }} className="media-list-link">
        <div className="media-list-thumb">
          {imgSrc ? (
            <img src={imgSrc} alt={filename} />
          ) : (
            <div className="media-card-placeholder">...</div>
          )}
        </div>
        <span className="media-list-name" title={filename}>{filename}</span>
        <StatusBadge status={status} />
        <span className="media-list-size">{formatSize(fileSize)}</span>
        <span className="media-list-type">{mimeType.split('/')[1]}</span>
        <span className="media-list-date">{new Date(createdAt).toLocaleDateString()}</span>
      </Link>
    </div>
  );
}
