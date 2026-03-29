import { Link, Outlet } from 'react-router-dom';
import UserMenu from './UserMenu';

export default function Layout() {
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <Link to="/" className="app-logo">
            Media Indexer
          </Link>
          <nav className="app-nav">
            <Link to="/" className="nav-link">Gallery</Link>
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
