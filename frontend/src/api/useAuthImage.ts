import { useState, useEffect } from 'react';

/**
 * Fetch an image via the API with the auth token and return a blob URL.
 * This is needed because <img src> doesn't send Authorization headers.
 */
export function useAuthImage(url: string): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    fetch(url, { headers })
      .then((res) => {
        if (!res.ok) return null;
        return res.blob();
      })
      .then((blob) => {
        if (blob && !revoked) {
          setBlobUrl(URL.createObjectURL(blob));
        }
      })
      .catch(() => {});

    return () => {
      revoked = true;
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
    // Only re-fetch when URL changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  return blobUrl;
}
