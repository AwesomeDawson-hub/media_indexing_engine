interface StatusBadgeProps {
  status: string;
}

const statusClasses: Record<string, string> = {
  uploaded: 'badge-warning',
  processing: 'badge-info',
  completed: 'badge-success',
  error: 'badge-danger',
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const cls = statusClasses[status] || 'badge-info';
  return <span className={`badge ${cls}`}>{status}</span>;
}
