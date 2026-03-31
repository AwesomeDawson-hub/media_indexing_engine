interface StatusBadgeProps {
  status: string;
}

const statusClasses: Record<string, string> = {
  uploaded: 'badge-warning',
  processing: 'badge-info',
  error: 'badge-danger',
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const cls = statusClasses[status];
  if (!cls) return null; // don't show badge for 'completed' or unknown states
  return <span className={`badge ${cls}`}>{status}</span>;
}
