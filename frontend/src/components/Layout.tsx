import { Link, Outlet, useLocation } from 'react-router-dom';
import UserMenu from './UserMenu';
import { useAuth } from '../context/AuthContext';

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
  const { user } = useAuth();
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <Link to="/" className="app-logo">
            Media Indexer
          </Link>
          <nav className="app-nav">
            <GalleryNavLink />
            <Link to="/upload" className="nav-link">Upload</Link>
            <Link to="/sources" className="nav-link">Sources</Link>
            <Link to="/profile" className="nav-link">Profile</Link>
            {user?.role === 'admin' && (
              <Link to="/admin" className="nav-link">Admin</Link>
            )}
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
