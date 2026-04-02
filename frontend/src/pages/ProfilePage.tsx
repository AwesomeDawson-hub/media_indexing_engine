import { useState, useEffect } from 'react';
import * as api from '../api/client';
import type { UserProfile } from '../types/api';

export default function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saveMsg, setSaveMsg] = useState('');
  const [saveError, setSaveError] = useState('');

  // Profile fields
  const [displayName, setDisplayName] = useState('');
  const [phone, setPhone] = useState('');
  const [company, setCompany] = useState('');
  const [iconUrl, setIconUrl] = useState('');

  // Email change
  const [showEmailChange, setShowEmailChange] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [emailToken, setEmailToken] = useState('');
  const [emailChangeMsg, setEmailChangeMsg] = useState('');
  const [emailChangeError, setEmailChangeError] = useState('');
  const [pendingEmailToken, setPendingEmailToken] = useState<string | null>(null);

  // Password reset
  const [showPasswordReset, setShowPasswordReset] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordMsg, setPasswordMsg] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [pendingResetToken, setPendingResetToken] = useState<string | null>(null);

  useEffect(() => {
    api.getProfile().then((p) => {
      setProfile(p);
      setDisplayName(p.display_name);
      setPhone(p.phone ?? '');
      setCompany(p.company ?? '');
      setIconUrl(p.icon_url ?? '');
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveMsg('');
    setSaveError('');
    try {
      const updated = await api.updateProfile({
        display_name: displayName || undefined,
        phone: phone || null,
        company: company || null,
        icon_url: iconUrl || null,
      });
      setProfile(updated);
      setSaveMsg('Profile updated.');
    } catch {
      setSaveError('Failed to save profile.');
    }
  }

  async function handleEmailChangeRequest(e: React.FormEvent) {
    e.preventDefault();
    setEmailChangeMsg('');
    setEmailChangeError('');
    try {
      const res = await api.requestEmailChange(newEmail);
      setEmailChangeMsg(res.message);
      if (res.token) {
        setPendingEmailToken(res.token);
      }
    } catch (err: unknown) {
      setEmailChangeError(err instanceof Error ? err.message : 'Failed to request email change.');
    }
  }

  async function handleEmailChangeConfirm(e: React.FormEvent) {
    e.preventDefault();
    setEmailChangeMsg('');
    setEmailChangeError('');
    try {
      const updated = await api.confirmEmailChange(emailToken || pendingEmailToken || '');
      setProfile(updated);
      setEmailChangeMsg('Email updated successfully.');
      setShowEmailChange(false);
      setPendingEmailToken(null);
      setEmailToken('');
      setNewEmail('');
    } catch {
      setEmailChangeError('Invalid or expired token.');
    }
  }

  async function handlePasswordResetRequest(e: React.FormEvent) {
    e.preventDefault();
    setPasswordMsg('');
    setPasswordError('');
    if (!profile) return;
    try {
      const res = await api.requestPasswordReset(profile.email);
      setPasswordMsg(res.message);
      if (res.token) {
        setPendingResetToken(res.token);
      }
    } catch {
      setPasswordError('Failed to send reset request.');
    }
  }

  async function handlePasswordResetConfirm(e: React.FormEvent) {
    e.preventDefault();
    setPasswordMsg('');
    setPasswordError('');
    try {
      const res = await api.confirmPasswordReset(resetToken || pendingResetToken || '', newPassword);
      setPasswordMsg(res.message);
      setShowPasswordReset(false);
      setPendingResetToken(null);
      setResetToken('');
      setNewPassword('');
    } catch {
      setPasswordError('Invalid or expired token, or password too short.');
    }
  }

  if (loading) return <div className="page-loading">Loading…</div>;
  if (!profile) return <div className="page-error">Could not load profile.</div>;

  return (
    <div className="profile-page">
      <h1>Profile</h1>

      <section className="profile-section">
        <h2>Account Info</h2>
        <p className="profile-meta">
          <strong>Plan:</strong> {profile.plan_name} &nbsp;·&nbsp;
          <strong>Monthly limit:</strong> {profile.monthly_limit} images
          {profile.role === 'admin' && <span className="badge-admin"> · Admin</span>}
        </p>
      </section>

      <section className="profile-section">
        <h2>Edit Profile</h2>
        <form onSubmit={handleSave} className="profile-form">
          <label>
            Display Name
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={100}
              required
            />
          </label>
          <label>
            Phone
            <input
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              maxLength={50}
              placeholder="Optional"
            />
          </label>
          <label>
            Company
            <input
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              maxLength={200}
              placeholder="Optional"
            />
          </label>
          <label>
            Icon URL
            <input
              type="url"
              value={iconUrl}
              onChange={(e) => setIconUrl(e.target.value)}
              maxLength={500}
              placeholder="https://..."
            />
          </label>
          <button type="submit" className="btn btn-primary">Save Changes</button>
          {saveMsg && <p className="form-success">{saveMsg}</p>}
          {saveError && <p className="form-error">{saveError}</p>}
        </form>
      </section>

      <section className="profile-section">
        <h2>Email</h2>
        <p>Current: <strong>{profile.email}</strong></p>
        {!showEmailChange ? (
          <button className="btn btn-secondary" onClick={() => setShowEmailChange(true)}>
            Change Email
          </button>
        ) : (
          <div className="profile-subform">
            <form onSubmit={handleEmailChangeRequest}>
              <label>
                New Email
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                />
              </label>
              <button type="submit" className="btn btn-primary">Request Change</button>
            </form>
            {(emailChangeMsg || pendingEmailToken) && (
              <form onSubmit={handleEmailChangeConfirm} style={{ marginTop: '0.75rem' }}>
                <p className="form-success">{emailChangeMsg}</p>
                <label>
                  Confirmation Token
                  <input
                    type="text"
                    value={emailToken || pendingEmailToken || ''}
                    onChange={(e) => setEmailToken(e.target.value)}
                    placeholder="Paste token here"
                    required
                  />
                </label>
                <button type="submit" className="btn btn-primary">Confirm Change</button>
              </form>
            )}
            {emailChangeError && <p className="form-error">{emailChangeError}</p>}
            <button className="btn btn-ghost" onClick={() => { setShowEmailChange(false); setEmailChangeMsg(''); setEmailChangeError(''); setPendingEmailToken(null); }}>
              Cancel
            </button>
          </div>
        )}
      </section>

      <section className="profile-section">
        <h2>Password</h2>
        {!showPasswordReset ? (
          <button className="btn btn-secondary" onClick={() => setShowPasswordReset(true)}>
            Change Password
          </button>
        ) : (
          <div className="profile-subform">
            <form onSubmit={handlePasswordResetRequest}>
              <p>A reset token will be sent to <strong>{profile.email}</strong>.</p>
              <button type="submit" className="btn btn-primary">Send Reset Token</button>
            </form>
            {(passwordMsg || pendingResetToken) && (
              <form onSubmit={handlePasswordResetConfirm} style={{ marginTop: '0.75rem' }}>
                <p className="form-success">{passwordMsg}</p>
                <label>
                  Reset Token
                  <input
                    type="text"
                    value={resetToken || pendingResetToken || ''}
                    onChange={(e) => setResetToken(e.target.value)}
                    placeholder="Paste token here"
                    required
                  />
                </label>
                <label>
                  New Password
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    minLength={8}
                    required
                  />
                </label>
                <button type="submit" className="btn btn-primary">Set New Password</button>
              </form>
            )}
            {passwordError && <p className="form-error">{passwordError}</p>}
            <button className="btn btn-ghost" onClick={() => { setShowPasswordReset(false); setPasswordMsg(''); setPasswordError(''); setPendingResetToken(null); }}>
              Cancel
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
