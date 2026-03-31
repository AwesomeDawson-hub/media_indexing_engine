import { Link, Outlet, useLocation } from 'react-router-dom';
import UserMenu from './UserMenu';

function GalleryNavLink() {
  const location = useLocation();
  const isOnGallery = location.pathname === '/';
  // When already on the gallery, stay on current URL; otherwise restore last gallery URL
  const href = isOnGallery
    ? location.pathname + location.search
    : (sessionStorage.getItem('gallery_last_url') || '/');
  return <Link to={href} className="nav-link">Gallery</Link>;
}

export default function Layout() {
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <Link to="/" className="app-logo">
            Media Indexer
          </Link>
          <nav className="app-nav">
            <GalleryNavLink />
            <Link to="/upload" className="nav-link">Source</Link>
          </nav>
          <UserMenu />
        </div>
      </header>
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}
