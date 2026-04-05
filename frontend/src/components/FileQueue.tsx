export interface QueuedFile {
  file: File;
  status: 'queued' | 'uploading' | 'created' | 'duplicate' | 'error';
  error?: string;
}

interface FileQueueProps {
  files: QueuedFile[];
}

const statusLabels: Record<string, string> = {
  queued: 'Queued',
  uploading: 'Processing...',
  created: 'Completed',
  duplicate: 'Duplicate',
  error: 'Error',
};

const statusClasses: Record<string, string> = {
  queued: '',
  uploading: 'badge-info',
  created: 'badge-success',
  duplicate: 'badge-warning',
  error: 'badge-danger',
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export default function FileQueue({ files }: FileQueueProps) {
  if (files.length === 0) return null;

  return (
    <div className="file-queue">
      <h3>Files ({files.length})</h3>
      <ul className="file-queue-list">
        {files.map((qf, i) => (
          <li key={i} className="file-queue-item">
            <span className="file-queue-name">{qf.file.name}</span>
            <span className="file-queue-size">{formatSize(qf.file.size)}</span>
            <span className={`badge ${statusClasses[qf.status]}`}>
              {statusLabels[qf.status]}
            </span>
            {qf.error && <span className="file-queue-error">{qf.error}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
