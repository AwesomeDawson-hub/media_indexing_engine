import { useEffect, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import * as api from '../api/client';

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const { refreshUser } = useAuth();
  const token = searchParams.get('token');

  const [status, setStatus] = useState<'pending' | 'success' | 'error'>('pending');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No verification token found. Please use the link from your email.');
      return;
    }

    api.verifyEmail(token)
      .then(async () => {
        await refreshUser();
        setStatus('success');
      })
      .catch((err) => {
        setStatus('error');
        setMessage(
          err?.message || 'This link is invalid or has expired. Request a new one from the banner inside the app.',
        );
      });
  // Run once on mount only
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="verify-email-page">
      <div className="verify-email-card">
        {status === 'pending' && (
          <>
            <div className="verify-email-spinner" />
            <p>Verifying your email address…</p>
          </>
        )}
        {status === 'success' && (
          <>
            <div className="verify-email-icon verify-email-icon--success">✓</div>
            <h2>Email verified!</h2>
            <p>Your email address has been confirmed. You're all set.</p>
            <Link to="/" className="btn btn-primary">Go to gallery</Link>
          </>
        )}
        {status === 'error' && (
          <>
            <div className="verify-email-icon verify-email-icon--error">✕</div>
            <h2>Verification failed</h2>
            <p>{message}</p>
            <Link to="/" className="btn btn-primary">Back to app</Link>
          </>
        )}
      </div>
    </div>
  );
}
