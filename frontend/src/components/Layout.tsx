import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import UserMenu from './UserMenu';
import { useAuth } from '../context/AuthContext';
import { useState } from 'react';
import * as api from '../api/client';

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

function VerificationBanner() {
  const { user } = useAuth();
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  if (!user || user.email_verified) return null;

  async function handleResend() {
    setSending(true);
    try {
      await api.resendVerificationEmail();
      setSent(true);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="verification-banner">
      <span>
        Please verify your email address. Check your inbox for a confirmation link.
      </span>
      {sent ? (
        <span className="verification-banner-sent">Email sent!</span>
      ) : (
        <button
          className="verification-banner-resend"
          onClick={handleResend}
          disabled={sending}
        >
          {sending ? 'Sending…' : 'Resend email'}
        </button>
      )}
    </div>
  );
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
            <NavLink to="/sources" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Connections</NavLink>
            <NavLink to="/sync-runs" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Sync History</NavLink>
            <NavLink to="/billing" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Billing</NavLink>
            <NavLink to="/profile" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Profile</NavLink>
            {user?.role === 'admin' && (
              <NavLink to="/admin" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Admin</NavLink>
            )}
          </nav>
          <UserMenu />
        </div>
      </header>
      <VerificationBanner />
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}
