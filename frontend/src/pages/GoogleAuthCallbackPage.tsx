import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ERROR_MESSAGES: Record<string, string> = {
  sso_disabled: 'Google Sign-In is not currently available.',
  oauth_error: 'Google sign-in was cancelled or denied.',
  invalid_request: 'The sign-in request was invalid. Please try again.',
  missing_cookies: 'Your browser blocked required cookies. Please allow cookies and try again.',
  invalid_state: 'The sign-in session has expired or is invalid. Please try again.',
  invalid_nonce: 'The sign-in session is invalid. Please try again.',
  unverified_email: 'Your Google account email is not verified.',
  identity_error: 'Could not verify your Google identity. Please try again.',
  exchange_failed: 'Could not retrieve account information from Google. Please try again.',
  account_disabled: 'Your account has been disabled. Please contact support.',
  link_conflict: 'This email is already linked to a different Google account.',
};

export default function GoogleAuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { loginWithGoogle } = useAuth();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const error = searchParams.get('error');
    const flowId = searchParams.get('flow_id');

    if (error) {
      setErrorMessage(ERROR_MESSAGES[error] ?? 'An unexpected error occurred. Please try again.');
      return;
    }

    if (!flowId) {
      setErrorMessage('Missing sign-in state. Please try again.');
      return;
    }

    loginWithGoogle(flowId)
      .then(() => navigate('/', { replace: true }))
      .catch(() => {
        setErrorMessage('Could not complete sign-in. Please try again.');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (errorMessage) {
    return (
      <div className="auth-page">
        <div className="auth-form card">
          <h1>Sign-In Failed</h1>
          <div className="alert alert-danger">{errorMessage}</div>
          <p className="auth-link">
            <Link to="/login">Back to Sign In</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-form card">
        <p>Completing sign-in…</p>
      </div>
    </div>
  );
}
