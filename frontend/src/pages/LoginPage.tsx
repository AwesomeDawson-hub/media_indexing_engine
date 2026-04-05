import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import * as api from '../api/client';

export default function LoginPage() {
  const { login } = useAuth();
  const location = useLocation();
  const successMessage = (location.state as { message?: string } | null)?.message ?? '';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    api.getAuthConfig().then((cfg) => setGoogleEnabled(cfg.google_sso_enabled)).catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-form card" onSubmit={handleSubmit}>
        <h1>Sign In</h1>
        {successMessage && <div className="alert alert-success">{successMessage}</div>}
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="form-group">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
          {loading ? 'Signing in...' : 'Sign In'}
        </button>
        {googleEnabled && (
          <>
            <div className="auth-divider"><span>or</span></div>
            <a href="/api/v1/auth/google/start" className="btn btn-secondary btn-block">
              Sign in with Google
            </a>
          </>
        )}
        <p className="auth-link">
          Don't have an account? <Link to="/register">Register</Link>
        </p>
        <p className="auth-link">
          <Link to="/forgot-password">Forgot your password?</Link>
        </p>
      </form>
    </div>
  );
}
