import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import UserMenu from './UserMenu';
import { useAuth } from '../context/AuthContext';

function GalleryNavLink() {
  const location = useLocation();
  const isOnGallery = location.pathname === '/';
  // When already on the gallery, stay on current URL; otherwise restore last gallery URL
  const href = isOnGallery
    ? location.pathname + location.search
    : (sessionStorage.getItem('gallery_last_url') || '/');
  const isActive = location.pathname === '/' || location.pathname.startsWith('/media/');
  return <Link to={href} className={`nav-link${isActive ? ' active' : ''}`}>Gallery</Link>;
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
            <NavLink to="/upload" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Upload</NavLink>
            <NavLink to="/sources" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Sources</NavLink>
            <NavLink to="/collections" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Collections</NavLink>
            <NavLink to="/billing" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Billing</NavLink>
            <NavLink to="/profile" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Profile</NavLink>
            {user?.role === 'admin' && (
              <NavLink to="/admin" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Admin</NavLink>
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
