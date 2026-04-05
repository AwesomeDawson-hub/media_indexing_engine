import { Link } from 'react-router-dom';
import { getMediaFileUrl } from '../api/client';
import { useAuthImage } from '../api/useAuthImage';
import StatusBadge from './StatusBadge';

interface MediaCardProps {
  id: string;
  filename: string;
  status: string;
  mimeType: string;
  fromPath?: string;
  ids?: string[];
  hasSimilar?: boolean;
  similarCount?: number;
  selected?: boolean;
  onSelect?: (id: string, checked: boolean) => void;
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max - 3) + '...' : str;
}

export default function MediaCard({ id, filename, status, mimeType, fromPath, ids, hasSimilar, similarCount, selected, onSelect }: MediaCardProps) {
  const isImage = mimeType.startsWith('image/');
  const imgSrc = useAuthImage(getMediaFileUrl(id));

  return (
    <div className={`media-card-wrapper${selected ? ' media-card-wrapper--selected' : ''}`}>
      {onSelect && (
        <label
          className="media-card-checkbox"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={!!selected}
            onChange={(e) => onSelect(id, e.target.checked)}
          />
        </label>
      )}
      <Link to={`/media/${id}`} state={{ from: fromPath, ids }} className="media-card">
        <div className="media-card-thumb">
          {isImage && imgSrc ? (
            <img src={imgSrc} alt={filename} loading="lazy" />
          ) : (
            <div className="media-card-placeholder">{isImage ? '...' : (mimeType.split('/')[1] || 'file')}</div>
          )}
          {hasSimilar && (
            <span className="similar-badge" title={`${similarCount ?? 0} similar photo${(similarCount ?? 0) === 1 ? '' : 's'}`}>
              {similarCount ?? 0} similar
            </span>
          )}
        </div>
        <div className="media-card-info">
          <span className="media-card-name" title={filename}>
            {truncate(filename, 30)}
          </span>
          <StatusBadge status={status} />
        </div>
      </Link>
    </div>
  );
}
