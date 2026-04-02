import { useState, useEffect } from 'react';

// Module-level cache: API URL → blob object URL.
// Survives component unmounts so navigating back to an already-loaded image is instant.
const blobCache = new Map<string, string>();

export function clearAuthImageCache(): void {
  blobCache.forEach((objUrl) => URL.revokeObjectURL(objUrl));
  blobCache.clear();
}

// Fire-and-forget: fetch an image into cache without needing a hook.
// Call this to warm the cache for images the user hasn't navigated to yet.
export function prefetchAuthImage(url: string): void {
  if (!url || blobCache.has(url)) return;
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  fetch(url, { headers })
    .then((res) => (res.ok ? res.blob() : null))
    .then((blob) => {
      if (blob && !blobCache.has(url)) {
        blobCache.set(url, URL.createObjectURL(blob));
      }
    })
    .catch(() => {});
}

export function useAuthImage(url: string): string | null {
  // Initialise directly from cache — zero-flash on revisit
  const [blobUrl, setBlobUrl] = useState<string | null>(() => blobCache.get(url) ?? null);

  useEffect(() => {
    if (!url) return;

    // Serve from cache immediately; no fetch needed
    if (blobCache.has(url)) {
      setBlobUrl(blobCache.get(url)!);
      return;
    }

    let cancelled = false;
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    fetch(url, { headers })
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (blob && !cancelled) {
          const objUrl = URL.createObjectURL(blob);
          blobCache.set(url, objUrl);
          setBlobUrl(objUrl);
        }
      })
      .catch(() => {});

    // Don't revoke on unmount — the cache is the owner of the blob URL
    return () => { cancelled = true; };
  }, [url]);

  return blobUrl;
}
