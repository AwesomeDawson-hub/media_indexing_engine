import { useAuthImage } from '../api/useAuthImage';

interface AuthImageProps {
  src: string;
  alt: string;
  loading?: 'lazy' | 'eager';
  className?: string;
}

export default function AuthImage({ src, alt, loading, className }: AuthImageProps) {
  const blobUrl = useAuthImage(src);

  if (!blobUrl) {
    return <div className={className || 'media-card-placeholder'}>...</div>;
  }

  return <img src={blobUrl} alt={alt} loading={loading} className={className} />;
}
