import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import * as api from '../api/client';

export default function RegisterPage() {
  const { register } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
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
      await register(email, password, displayName);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-form card" onSubmit={handleSubmit}>
        <h1>Register</h1>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="form-group">
          <label htmlFor="displayName">Display Name</label>
          <input
            id="displayName"
            type="text"
            required
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
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
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
          {loading ? 'Registering...' : 'Register'}
        </button>
        {googleEnabled && (
          <>
            <div className="auth-divider"><span>or</span></div>
            <a href="/api/v1/auth/google/start" className="btn btn-secondary btn-block">
              Sign up with Google
            </a>
          </>
        )}
        <p className="auth-link">
          Already have an account? <Link to="/login">Sign In</Link>
        </p>
      </form>
    </div>
  );
}
