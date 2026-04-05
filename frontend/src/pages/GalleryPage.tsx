import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, Link, useLocation } from 'react-router-dom';
import * as api from '../api/client';
import { getMediaFileUrl } from '../api/client';
import type { SearchFilters } from '../api/client';
import type { MediaItemResponse, SearchResultItem, SourceResponse } from '../types/api';
import MediaCard from '../components/MediaCard';
import MediaListRow from '../components/MediaListRow';
import ViewToggle from '../components/ViewToggle';
import SelectionBar from '../components/SelectionBar';
import Pagination from '../components/Pagination';
import AuthImage from '../components/AuthImage';
import StatusBadge from '../components/StatusBadge';
import { useAuthImage } from '../api/useAuthImage';

const PER_PAGE = 20;
const POLL_INTERVAL = 5000;
const VIEW_KEY = 'gallery_view';

// Search result row in list view
function SearchListRow({ item, selected, onSelect, fromPath, ids }: {
  item: SearchResultItem;
  selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
  fromPath: string;
  ids: string[];
}) {
  const imgSrc = useAuthImage(getMediaFileUrl(item.media_item.id));
  return (
    <div className="media-list-row">
      <label className="media-list-checkbox">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(item.media_item.id, e.target.checked)}
        />
      </label>
      <Link to={`/media/${item.media_item.id}`} state={{ from: fromPath, ids }} className="media-list-link">
        <div className="media-list-thumb">
          {imgSrc
            ? <img src={imgSrc} alt={item.metadata.title} />
            : <div className="media-card-placeholder">...</div>}
        </div>
        <span className="media-list-name">{item.metadata.title || item.media_item.original_filename}</span>
        <StatusBadge status={item.media_item.status} />
        <span className="search-score">{Math.round(item.score * 100)}%</span>
        <span className="media-list-type">{item.media_item.mime_type.split('/')[1]}</span>
      </Link>
    </div>
  );
}

function FilterPanel({
  hasPeople, setHasPeople,
  orientation, setOrientation,
  mood, setMood,
  mimeType, setMimeType,
  aspectRatio, setAspectRatio,
  sizeBucket, setSizeBucket,
  sortBy, setSortBy,
  isSearchMode,
  hasActiveFilters,
  onApply,
  onReset,
  onClearSearch,
  onSortChange,
  sources,
  sourceId,
  setSourceId,
}: {
  hasPeople: boolean | null;
  setHasPeople: (v: boolean | null) => void;
  orientation: string;
  setOrientation: (v: string) => void;
  mood: string;
  setMood: (v: string) => void;
  mimeType: string;
  setMimeType: (v: string) => void;
  aspectRatio: string;
  setAspectRatio: (v: string) => void;
  sizeBucket: string;
  setSizeBucket: (v: string) => void;
  sortBy: string;
  setSortBy: (v: string) => void;
  onSortChange: (v: string) => void;
  isSearchMode: boolean;
  hasActiveFilters: boolean;
  onApply: () => void;
  onReset: () => void;
  onClearSearch: () => void;
  sources: SourceResponse[];
  sourceId: string;
  setSourceId: (v: string) => void;
}) {
  return (
    <div className="filter-panel card">
      <div className="filter-grid">
        <div className="filter-group">
          <label>People</label>
          <div className="filter-toggle-group">
            <button className={`filter-toggle ${hasPeople === null ? 'active' : ''}`} onClick={() => setHasPeople(null)}>Any</button>
            <button className={`filter-toggle ${hasPeople === false ? 'active' : ''}`} onClick={() => setHasPeople(false)}>No People</button>
            <button className={`filter-toggle ${hasPeople === true ? 'active' : ''}`} onClick={() => setHasPeople(true)}>Has People</button>
          </div>
        </div>

        <div className="filter-group">
          <label>Orientation</label>
          <select value={orientation} onChange={(e) => setOrientation(e.target.value)}>
            <option value="">Any</option>
            <option value="landscape">Landscape</option>
            <option value="portrait">Portrait</option>
            <option value="square">Square</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Size</label>
          <select value={sizeBucket} onChange={(e) => setSizeBucket(e.target.value)}>
            <option value="">Any size</option>
            <option value="small">Small (&lt; 1000px wide)</option>
            <option value="medium">Medium (1000–2499px wide)</option>
            <option value="large">Large (2500px+ wide)</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Aspect Ratio</label>
          <select value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)}>
            <option value="">Any</option>
            <option value="16:9">16:9 (Widescreen)</option>
            <option value="3:2">3:2 (Classic Photo)</option>
            <option value="4:3">4:3 (Standard)</option>
            <option value="1:1">1:1 (Square)</option>
            <option value="4:5">4:5 (Instagram Portrait)</option>
            <option value="2:3">2:3 (Portrait Photo)</option>
            <option value="9:16">9:16 (Vertical Video)</option>
            <option value="other">Other</option>
          </select>
        </div>

        <div className="filter-group">
          <label>File Type</label>
          <select value={mimeType} onChange={(e) => setMimeType(e.target.value)}>
            <option value="">Any</option>
            <option value="image/jpeg">JPEG</option>
            <option value="image/png">PNG</option>
            <option value="image/webp">WebP</option>
            <option value="image/gif">GIF</option>
            <option value="image/avif">AVIF</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Mood</label>
          <select value={mood} onChange={(e) => setMood(e.target.value)}>
            <option value="">Any</option>
            <option value="serene">Serene / Calm</option>
            <option value="cheerful">Cheerful / Happy</option>
            <option value="dramatic">Dramatic</option>
            <option value="energetic">Energetic / Lively</option>
            <option value="warm">Warm</option>
            <option value="festive">Festive / Celebratory</option>
            <option value="mysterious">Mysterious</option>
            <option value="nostalgic">Nostalgic</option>
            <option value="professional">Professional</option>
            <option value="playful">Playful</option>
            <option value="solemn">Solemn / Serious</option>
            <option value="romantic">Romantic</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Source</label>
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">Any source</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Sort By</label>
          <select value={sortBy} onChange={(e) => onSortChange(e.target.value)}>
            {isSearchMode && <option value="relevance">Relevance</option>}
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="largest">Largest Dimensions</option>
            <option value="smallest">Smallest Dimensions</option>
          </select>
        </div>
      </div>

      <div className="filter-actions">
        <button className="btn btn-primary btn-sm" onClick={onApply}>Apply Filters</button>
        {hasActiveFilters && (
          <button className="btn btn-outline btn-sm" onClick={onReset}>Reset Filters</button>
        )}
        {isSearchMode && (
          <button className="btn btn-outline btn-sm" onClick={onClearSearch}>Clear Search</button>
        )}
      </div>
    </div>
  );
}

// Map size bucket label to min/max width params
function sizeBucketToWidthParams(bucket: string): { min_width?: number; max_width?: number } {
  if (bucket === 'small') return { max_width: 999 };
  if (bucket === 'medium') return { min_width: 1000, max_width: 2499 };
  if (bucket === 'large') return { min_width: 2500 };
  return {};
}

export default function GalleryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const queryParam = searchParams.get('q') || '';
  const pageParam = parseInt(searchParams.get('page') || '1', 10);

  const [query, setQuery] = useState(queryParam);
  // page is derived directly from URL — no separate state to avoid divergence on back-navigation

  // Browse mode state
  const [browseItems, setBrowseItems] = useState<MediaItemResponse[]>([]);
  const [browseTotal, setBrowseTotal] = useState(0);
  const [browseLoading, setBrowseLoading] = useState(false);

  // Search mode state
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const [error, setError] = useState('');
  const [view, setView] = useState<'grid' | 'list'>(
    () => (localStorage.getItem(VIEW_KEY) as 'grid' | 'list') || 'grid'
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // Filter state — initialized from URL so back-navigation restores filters
  const hasPeopleParam = searchParams.get('has_people');
  const [hasPeople, setHasPeople] = useState<boolean | null>(
    hasPeopleParam === 'true' ? true : hasPeopleParam === 'false' ? false : null
  );
  const [orientation, setOrientation] = useState(searchParams.get('orientation') || '');
  const [mood, setMood] = useState(searchParams.get('mood') || '');
  const [mimeType, setMimeType] = useState(searchParams.get('mime_type') || '');
  const [aspectRatio, setAspectRatio] = useState(searchParams.get('aspect_ratio') || '');
  const [sizeBucket, setSizeBucket] = useState(searchParams.get('size') || '');
  const [sortBy, setSortBy] = useState(() => {
    const s = searchParams.get('sort');
    if (s) return s;
    return queryParam ? 'relevance' : 'newest';
  });
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [sourceId, setSourceId] = useState(searchParams.get('source_id') || '');

  const isSearchMode = Boolean(queryParam);

  // Persist current gallery URL so the nav link can restore it when returning from other pages
  useEffect(() => {
    sessionStorage.setItem('gallery_last_url', location.pathname + location.search);
  });

  // Fetch sources once on mount for the source filter dropdown
  useEffect(() => {
    api.listSources().then(setSources).catch(() => {});
  }, []);

  // Track the last query submitted via the form so the URL-change effect
  // doesn't double-fire when handleSubmit already kicked off the search.
  const lastSubmittedQuery = useRef('');

  // Skip the initial mount so we don't redundantly re-write URL values that
  // were just read from it — only write on subsequent user-driven changes.
  const filtersWritten = useRef(false);

  // Mirror filter state to URL immediately on every change so that back-navigation
  // restores the exact filter combination the user had set, regardless of whether
  // they clicked "Apply Filters".
  useEffect(() => {
    if (!filtersWritten.current) {
      filtersWritten.current = true;
      return;
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (hasPeople !== null) next.set('has_people', String(hasPeople)); else next.delete('has_people');
      if (orientation) next.set('orientation', orientation); else next.delete('orientation');
      if (mood) next.set('mood', mood); else next.delete('mood');
      if (mimeType) next.set('mime_type', mimeType); else next.delete('mime_type');
      if (aspectRatio) next.set('aspect_ratio', aspectRatio); else next.delete('aspect_ratio');
      if (sizeBucket) next.set('size', sizeBucket); else next.delete('size');
      if (sourceId) next.set('source_id', sourceId); else next.delete('source_id');
      return next;
    }, { replace: true });
  }, [hasPeople, orientation, mood, mimeType, aspectRatio, sizeBucket, sourceId, setSearchParams]);

  function buildFilters(): SearchFilters {
    return {
      has_people: hasPeople,
      orientation: orientation || null,
      mood: mood || null,
      mime_type: mimeType || null,
      aspect_ratio: aspectRatio || null,
      source_id: sourceId || null,
      sort_by: sortBy,
      ...sizeBucketToWidthParams(sizeBucket),
    };
  }

  const fetchBrowse = useCallback(async (p: number, showLoading = false) => {
    if (showLoading) setBrowseLoading(true);
    try {
      const res = await api.listMediaFiltered(p, PER_PAGE, buildFilters());
      setBrowseItems(res.items);
      setBrowseTotal(res.total);
      setError('');
    } catch (err: unknown) {
      if (showLoading) setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      if (showLoading) setBrowseLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPeople, orientation, mood, mimeType, aspectRatio, sizeBucket, sortBy, sourceId]);

  async function doSearch(q: string, p: number, sortOverride?: string) {
    setSearchLoading(true);
    setError('');
    try {
      const filters = sortOverride ? { ...buildFilters(), sort_by: sortOverride } : buildFilters();
      const res = await api.search(q, p, PER_PAGE, filters);
      setSearchResults(res.results);
      setSearchTotal(res.total);
      setSearched(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setSearchLoading(false);
    }
  }

  // Browse mode — load on mount and page/filter changes
  useEffect(() => {
    if (!isSearchMode) {
      fetchBrowse(pageParam, true);
      setSelected(new Set());
    }
  }, [pageParam, isSearchMode, fetchBrowse]);

  // Search mode — trigger search when URL query changes (back/fwd nav, direct URL, refresh)
  useEffect(() => {
    if (isSearchMode && queryParam !== lastSubmittedQuery.current) {
      setQuery(queryParam);
      doSearch(queryParam, pageParam);
      setSelected(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryParam]);

  // Auto-poll while items are processing (browse mode only)
  useEffect(() => {
    if (isSearchMode) return;
    const hasProcessing = browseItems.some(
      (i) => i.status === 'uploaded' || i.status === 'processing'
    );
    if (hasProcessing) {
      pollRef.current = setInterval(() => fetchBrowse(pageParam), POLL_INTERVAL);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [browseItems, pageParam, isSearchMode, fetchBrowse]);

  function handleViewChange(v: 'grid' | 'list') {
    setView(v);
    localStorage.setItem(VIEW_KEY, v);
    setSelected(new Set());
  }

  function handleSelect(id: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function handleSelectAllBrowse(checked: boolean) {
    setSelected(checked ? new Set(browseItems.map((i) => i.id)) : new Set());
  }

  function handleSelectAllSearch(checked: boolean) {
    setSelected(checked ? new Set(searchResults.map((r) => r.media_item.id)) : new Set());
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    // When switching from browse to search mode, reset sort to relevance.
    // Can't rely on setSortBy here (async), so pass it as an override directly.
    const effectiveSort = isSearchMode ? sortBy : 'relevance';
    if (!isSearchMode) setSortBy('relevance');
    lastSubmittedQuery.current = q;
    const submitParams: Record<string, string> = { q };
    if (hasPeople !== null) submitParams.has_people = String(hasPeople);
    if (orientation) submitParams.orientation = orientation;
    if (mood) submitParams.mood = mood;
    if (mimeType) submitParams.mime_type = mimeType;
    if (aspectRatio) submitParams.aspect_ratio = aspectRatio;
    if (sizeBucket) submitParams.size = sizeBucket;
    if (sourceId) submitParams.source_id = sourceId;
    if (effectiveSort !== 'relevance') submitParams.sort = effectiveSort;
    setSearchParams(submitParams);
    doSearch(q, 1, effectiveSort);
    setSelected(new Set());
  }

  function handleSortChange(value: string) {
    setSortBy(value);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      const defaultSort = isSearchMode ? 'relevance' : 'newest';
      if (value !== defaultSort) next.set('sort', value);
      else next.delete('sort');
      return next;
    }, { replace: true });
  }

  function handleApplyFilters() {
    // Write active filters to URL so back-navigation can restore them
    const params: Record<string, string> = {};
    if (queryParam) params.q = queryParam;
    if (hasPeople !== null) params.has_people = String(hasPeople);
    if (orientation) params.orientation = orientation;
    if (mood) params.mood = mood;
    if (mimeType) params.mime_type = mimeType;
    if (aspectRatio) params.aspect_ratio = aspectRatio;
    if (sizeBucket) params.size = sizeBucket;
    if (sourceId) params.source_id = sourceId;
    const defaultSort = isSearchMode ? 'relevance' : 'newest';
    if (sortBy !== defaultSort) params.sort = sortBy;
    // page intentionally omitted — Apply always resets to page 1
    setSearchParams(params, { replace: true });

    if (isSearchMode) {
      doSearch(queryParam, 1);
    } else {
      fetchBrowse(1, true);
    }
  }

  function handlePageChange(newPage: number) {
    // Update URL — pageParam re-derives on next render, browse useEffect handles refetch
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (newPage > 1) {
        next.set('page', String(newPage));
      } else {
        next.delete('page');
      }
      return next;
    }, { replace: true });
    if (isSearchMode) {
      doSearch(queryParam, newPage);
    }
  }

  function resetFilters() {
    setHasPeople(null);
    setOrientation('');
    setMood('');
    setMimeType('');
    setAspectRatio('');
    setSizeBucket('');
    setSourceId('');
    setSortBy(isSearchMode ? 'relevance' : 'newest');
    // Strip filter params from URL, keeping only q
    const params: Record<string, string> = {};
    if (queryParam) params.q = queryParam;
    // page intentionally omitted — reset returns to page 1
    setSearchParams(params, { replace: true });
    setTimeout(() => {
      if (isSearchMode) doSearch(queryParam, 1);
      else fetchBrowse(1, true);
    }, 0);
  }

  function clearSearch() {
    setSearchParams({});
    setQuery('');
    setSortBy('newest');
  }

  const hasActiveFilters =
    hasPeople !== null || orientation || mood || mimeType || aspectRatio || sizeBucket || sourceId ||
    (isSearchMode ? sortBy !== 'relevance' : sortBy !== 'newest');

  const totalPages = isSearchMode
    ? Math.ceil(searchTotal / PER_PAGE)
    : Math.ceil(browseTotal / PER_PAGE);

  const loading = isSearchMode ? searchLoading : browseLoading;

  // Determine selected IDs for the current mode
  const currentIds = isSearchMode
    ? searchResults.map((r) => r.media_item.id)
    : browseItems.map((i) => i.id);
  const allOnPageSelected = currentIds.length > 0 && currentIds.every((id) => selected.has(id));

  return (
    <div>
      {/* Search bar */}
      <form className="search-form" onSubmit={handleSubmit}>
        <input
          type="search"
          className="search-input-large"
          placeholder="Search your media library..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {isSearchMode ? 'Re-search' : 'Search'}
        </button>
        {isSearchMode && (
          <button type="button" className="btn btn-outline" onClick={clearSearch}>
            Browse All
          </button>
        )}
      </form>

      <FilterPanel
        hasPeople={hasPeople} setHasPeople={setHasPeople}
        orientation={orientation} setOrientation={setOrientation}
        mood={mood} setMood={setMood}
        mimeType={mimeType} setMimeType={setMimeType}
        aspectRatio={aspectRatio} setAspectRatio={setAspectRatio}
        sizeBucket={sizeBucket} setSizeBucket={setSizeBucket}
        sortBy={sortBy} setSortBy={setSortBy}
        sources={sources} sourceId={sourceId} setSourceId={setSourceId}
        isSearchMode={isSearchMode}
        hasActiveFilters={Boolean(hasActiveFilters)}
        onApply={handleApplyFilters}
        onReset={resetFilters}
        onClearSearch={clearSearch}
        onSortChange={handleSortChange}
      />

      {error && <div className="alert alert-danger">{error}</div>}

      {loading && <div className="page-loading"><div className="spinner" /></div>}

      {/* Browse mode */}
      {!isSearchMode && !loading && (
        <>
          {browseItems.length === 0 ? (
            <div className="empty-state">
              <h2>No media yet</h2>
              <p>Upload some files to get started.</p>
              <Link to="/upload" className="btn btn-primary">Source</Link>
            </div>
          ) : (
            <>
              <div className="page-header">
                <p className="search-count">{browseTotal} item{browseTotal !== 1 ? 's' : ''}</p>
                <div className="page-header-actions">
                  <ViewToggle view={view} onChange={handleViewChange} />
                </div>
              </div>

              <SelectionBar
                count={selected.size}
                selectedIds={Array.from(selected)}
                onClear={() => setSelected(new Set())}
                onDeleteSuccess={(ids) => {
                  const remaining = browseItems.filter((i) => !ids.includes(i.id));
                  const newTotal = browseTotal - ids.length;
                  setSelected(new Set());
                  if (remaining.length === 0 && newTotal > 0) {
                    // Page is now empty but more items exist — go to page 1 and re-fetch
                    const newPage = pageParam > 1 ? 1 : pageParam;
                    if (newPage !== pageParam) {
                      setSearchParams((prev) => { const p = new URLSearchParams(prev); p.set('page', '1'); return p; });
                    } else {
                      fetchBrowse(1, true);
                    }
                  } else {
                    setBrowseItems(remaining);
                    setBrowseTotal(newTotal);
                  }
                }}
              />

              {view === 'grid' ? (
                <div className="media-grid">
                  {browseItems.map((item) => (
                    <MediaCard
                      key={item.id}
                      id={item.id}
                      filename={item.display_name || item.original_filename}
                      status={item.status}
                      mimeType={item.mime_type}
                      fromPath={location.pathname + location.search}
                      ids={currentIds}
                      hasSimilar={item.has_similar}
                      similarCount={item.similar_count}
                      selected={selected.has(item.id)}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              ) : (
                <div className="media-list">
                  <div className="media-list-header">
                    <label className="media-list-checkbox">
                      <input
                        type="checkbox"
                        checked={allOnPageSelected}
                        onChange={(e) => handleSelectAllBrowse(e.target.checked)}
                      />
                    </label>
                    <span className="media-list-header-label">Select all</span>
                  </div>
                  {browseItems.map((item) => (
                    <MediaListRow
                      key={item.id}
                      id={item.id}
                      filename={item.display_name || item.original_filename}
                      status={item.status}
                      mimeType={item.mime_type}
                      fileSize={item.file_size}
                      createdAt={item.created_at}
                      selected={selected.has(item.id)}
                      onSelect={handleSelect}
                      fromPath={location.pathname + location.search}
                      ids={currentIds}
                    />
                  ))}
                </div>
              )}

              <Pagination page={pageParam} totalPages={totalPages} onPageChange={handlePageChange} />
            </>
          )}
        </>
      )}

      {/* Search mode */}
      {isSearchMode && !loading && (
        <>
          {searched && searchResults.length === 0 && (
            <div className="empty-state">
              <h2>No results found</h2>
              <p>Try a different search term{hasActiveFilters ? ' or adjust your filters' : ''}.</p>
            </div>
          )}

          {searchResults.length > 0 && (
            <>
              <div className="search-results-header">
                <p className="search-count">{searchTotal} result{searchTotal !== 1 ? 's' : ''} found</p>
                <ViewToggle view={view} onChange={handleViewChange} />
              </div>

              <SelectionBar
                count={selected.size}
                selectedIds={Array.from(selected)}
                onClear={() => setSelected(new Set())}
                onDeleteSuccess={(ids) => {
                  const remaining = searchResults.filter((r) => !ids.includes(r.media_item.id));
                  const newTotal = searchTotal - ids.length;
                  setSelected(new Set());
                  if (remaining.length === 0 && newTotal > 0) {
                    doSearch(lastSubmittedQuery.current, 1);
                    setSearchParams((prev) => { const p = new URLSearchParams(prev); p.set('page', '1'); return p; });
                  } else {
                    setSearchResults(remaining);
                    setSearchTotal(newTotal);
                  }
                }}
              />

              {view === 'grid' ? (
                <div className="search-results">
                  {searchResults.map((r) => (
                    <div
                      key={r.media_item.id}
                      className={`search-result-card-wrapper${selected.has(r.media_item.id) ? ' media-card-wrapper--selected' : ''}`}
                    >
                      <label
                        className="media-card-checkbox"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(r.media_item.id)}
                          onChange={(e) => handleSelect(r.media_item.id, e.target.checked)}
                        />
                      </label>
                      <Link
                        to={`/media/${r.media_item.id}`}
                        state={{ from: location.pathname + location.search, ids: currentIds }}
                        className="search-result-card card"
                      >
                      <div className="search-result-thumb">
                        {r.media_item.mime_type.startsWith('image/') ? (
                          <AuthImage
                            src={getMediaFileUrl(r.media_item.id)}
                            alt={r.metadata.title}
                            loading="lazy"
                          />
                        ) : (
                          <div className="media-card-placeholder">
                            {r.media_item.mime_type.split('/')[1] || 'file'}
                          </div>
                        )}
                      </div>
                      <div className="search-result-info">
                        <h3>{r.metadata.title || r.media_item.original_filename}</h3>
                        <p className="search-result-desc">{r.metadata.description}</p>
                        <div className="search-result-meta">
                          <StatusBadge status={r.media_item.status} />
                          <span className="search-score">{Math.round(r.score * 100)}% match</span>
                          {r.metadata.mood && <span className="pill">{r.metadata.mood}</span>}
                        </div>
                        {r.metadata.tags && r.metadata.tags.length > 0 && (
                          <div className="pill-list">
                            {r.metadata.tags.slice(0, 5).map((tag, i) => (
                              <span key={i} className="pill">{tag}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </Link>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="media-list">
                  <div className="media-list-header">
                    <label className="media-list-checkbox">
                      <input
                        type="checkbox"
                        checked={allOnPageSelected}
                        onChange={(e) => handleSelectAllSearch(e.target.checked)}
                      />
                    </label>
                    <span className="media-list-header-label">Select all</span>
                  </div>
                  {searchResults.map((r) => (
                    <SearchListRow
                      key={r.media_item.id}
                      item={r}
                      selected={selected.has(r.media_item.id)}
                      onSelect={handleSelect}
                      fromPath={location.pathname + location.search}
                      ids={currentIds}
                    />
                  ))}
                </div>
              )}

              <Pagination page={pageParam} totalPages={totalPages} onPageChange={handlePageChange} />
            </>
          )}
        </>
      )}
    </div>
  );
}
