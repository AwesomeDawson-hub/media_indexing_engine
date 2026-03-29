import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import * as api from '../api/client';
import { getMediaFileUrl } from '../api/client';
import type { SearchFilters } from '../api/client';
import type { MediaItemResponse, SearchResultItem } from '../types/api';
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
function SearchListRow({ item, selected, onSelect }: {
  item: SearchResultItem;
  selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
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
      <Link to={`/media/${item.media_item.id}`} className="media-list-link">
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
  sortBy, setSortBy,
  isSearchMode,
  hasActiveFilters,
  onApply,
  onReset,
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
  sortBy: string;
  setSortBy: (v: string) => void;
  isSearchMode: boolean;
  hasActiveFilters: boolean;
  onApply: () => void;
  onReset: () => void;
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
          <label>Sort By</label>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
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
          <button className="btn btn-outline btn-sm" onClick={onReset}>Reset</button>
        )}
      </div>
    </div>
  );
}

export default function GalleryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryParam = searchParams.get('q') || '';
  const pageParam = parseInt(searchParams.get('page') || '1', 10);

  const [query, setQuery] = useState(queryParam);
  const [page, setPage] = useState(pageParam);

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
  const [showFilters, setShowFilters] = useState(false);

  // Filter state
  const [hasPeople, setHasPeople] = useState<boolean | null>(null);
  const [orientation, setOrientation] = useState('');
  const [mood, setMood] = useState('');
  const [mimeType, setMimeType] = useState('');
  const [aspectRatio, setAspectRatio] = useState('');
  const [sortBy, setSortBy] = useState(() => queryParam ? 'relevance' : 'newest');

  const isSearchMode = Boolean(queryParam);

  function buildFilters(): SearchFilters {
    return {
      has_people: hasPeople,
      orientation: orientation || null,
      mood: mood || null,
      mime_type: mimeType || null,
      aspect_ratio: aspectRatio || null,
      sort_by: sortBy,
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
  }, [hasPeople, orientation, mood, mimeType, aspectRatio, sortBy]);

  async function doSearch(q: string, p: number) {
    setSearchLoading(true);
    setError('');
    try {
      const res = await api.search(q, p, PER_PAGE, buildFilters());
      setSearchResults(res.results);
      setSearchTotal(res.total);
      setPage(res.page);
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
      fetchBrowse(page, true);
      setSelected(new Set());
    }
  }, [page, isSearchMode, fetchBrowse]);

  // Search mode — trigger search when URL query changes
  useEffect(() => {
    if (isSearchMode) {
      setQuery(queryParam);
      doSearch(queryParam, 1);
      setPage(1);
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
      pollRef.current = setInterval(() => fetchBrowse(page), POLL_INTERVAL);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [browseItems, page, isSearchMode, fetchBrowse]);

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
    if (!query.trim()) return;
    setSearchParams({ q: query.trim() });
  }

  function handleApplyFilters() {
    if (isSearchMode) {
      doSearch(queryParam, 1);
    } else {
      setPage(1);
      fetchBrowse(1, true);
    }
  }

  function handlePageChange(newPage: number) {
    setPage(newPage);
    if (isSearchMode) {
      doSearch(queryParam, newPage);
    }
    // browse: useEffect handles it via page dependency
  }

  function resetFilters() {
    setHasPeople(null);
    setOrientation('');
    setMood('');
    setMimeType('');
    setAspectRatio('');
    setSortBy(isSearchMode ? 'relevance' : 'newest');
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
    hasPeople !== null || orientation || mood || mimeType || aspectRatio ||
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
      {/* Search bar + filter toggle */}
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
        <button
          type="button"
          className={`btn ${showFilters ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => setShowFilters(!showFilters)}
        >
          Filters {hasActiveFilters ? '●' : ''}
        </button>
      </form>

      {showFilters && (
        <FilterPanel
          hasPeople={hasPeople} setHasPeople={setHasPeople}
          orientation={orientation} setOrientation={setOrientation}
          mood={mood} setMood={setMood}
          mimeType={mimeType} setMimeType={setMimeType}
          aspectRatio={aspectRatio} setAspectRatio={setAspectRatio}
          sortBy={sortBy} setSortBy={setSortBy}
          isSearchMode={isSearchMode}
          hasActiveFilters={Boolean(hasActiveFilters)}
          onApply={handleApplyFilters}
          onReset={resetFilters}
        />
      )}

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
                  <Link to="/upload" className="btn btn-primary">Source</Link>
                </div>
              </div>

              <SelectionBar
                count={selected.size}
                selectedIds={Array.from(selected)}
                onClear={() => setSelected(new Set())}
              />

              {view === 'grid' ? (
                <div className="media-grid">
                  {browseItems.map((item) => (
                    <MediaCard
                      key={item.id}
                      id={item.id}
                      filename={item.original_filename}
                      status={item.status}
                      mimeType={item.mime_type}
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
                      filename={item.original_filename}
                      status={item.status}
                      mimeType={item.mime_type}
                      fileSize={item.file_size}
                      createdAt={item.created_at}
                      selected={selected.has(item.id)}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              )}

              <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
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
              />

              {view === 'grid' ? (
                <div className="search-results">
                  {searchResults.map((r) => (
                    <Link
                      key={r.media_item.id}
                      to={`/media/${r.media_item.id}`}
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
                    />
                  ))}
                </div>
              )}

              <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
            </>
          )}
        </>
      )}
    </div>
  );
}
