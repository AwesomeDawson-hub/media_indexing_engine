import { useState, useEffect } from 'react';
import * as api from '../api/client';
import type { UserProfile } from '../types/api';

function Avatar({ name, imageUrl }: { name: string; imageUrl?: string | null }) {
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  if (imageUrl) {
    return <img className="profile-avatar" src={imageUrl} alt={name} />;
  }
  return <div className="profile-avatar profile-avatar--initials">{initials}</div>;
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saveMsg, setSaveMsg] = useState('');
  const [saveError, setSaveError] = useState('');

  // Profile fields
  const [displayName, setDisplayName] = useState('');
  const [phone, setPhone] = useState('');
  const [company, setCompany] = useState('');

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
      if (res.token) setPendingEmailToken(res.token);
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
      if (res.token) setPendingResetToken(res.token);
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
      {/* Header */}
      <div className="profile-header">
        <Avatar name={profile.display_name} imageUrl={profile.icon_url} />
        <div className="profile-header-info">
          <h1 className="profile-header-name">{profile.display_name}</h1>
          <p className="profile-header-email">{profile.email}</p>
          <div className="profile-header-badges">
            <span className="profile-badge">{profile.plan_name}</span>
            {profile.role === 'admin' && <span className="profile-badge profile-badge--admin">Admin</span>}
          </div>
        </div>
      </div>

      {/* Account info card */}
      <div className="profile-card">
        <h2 className="profile-card-title">Account</h2>
        <div className="profile-info-grid">
          <div className="profile-info-item">
            <span className="profile-info-label">Plan</span>
            <span className="profile-info-value" style={{ textTransform: 'capitalize' }}>{profile.plan_name}</span>
          </div>
          <div className="profile-info-item">
            <span className="profile-info-label">Monthly Limit</span>
            <span className="profile-info-value">{profile.monthly_limit.toLocaleString()} analyses</span>
          </div>
          <div className="profile-info-item">
            <span className="profile-info-label">Billing Status</span>
            <span className="profile-info-value" style={{ textTransform: 'capitalize' }}>{profile.billing_status}</span>
          </div>
          <div className="profile-info-item">
            <span className="profile-info-label">Role</span>
            <span className="profile-info-value" style={{ textTransform: 'capitalize' }}>{profile.role}</span>
          </div>
        </div>
      </div>

      {/* Edit profile card */}
      <div className="profile-card">
        <h2 className="profile-card-title">Edit Profile</h2>
        <form onSubmit={handleSave}>
          <div className="form-group">
            <label htmlFor="displayName">Display Name</label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={100}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="phone">Phone <span className="profile-optional">optional</span></label>
            <input
              id="phone"
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              maxLength={50}
              placeholder="e.g. +1 555 000 0000"
            />
          </div>
          <div className="form-group">
            <label htmlFor="company">Company <span className="profile-optional">optional</span></label>
            <input
              id="company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              maxLength={200}
              placeholder="e.g. Acme Corp"
            />
          </div>
          {saveMsg && <div className="alert alert-success">{saveMsg}</div>}
          {saveError && <div className="alert alert-error">{saveError}</div>}
          <div className="profile-form-actions">
            <button type="submit" className="btn btn-primary">Save Changes</button>
          </div>
        </form>
      </div>

      {/* Email card */}
      <div className="profile-card">
        <h2 className="profile-card-title">Email Address</h2>
        <p className="profile-current-value">{profile.email}</p>
        {!showEmailChange ? (
          <button className="btn btn-secondary btn-sm" onClick={() => setShowEmailChange(true)}>
            Change Email
          </button>
        ) : (
          <div className="profile-subcard">
            <form onSubmit={handleEmailChangeRequest}>
              <div className="form-group">
                <label htmlFor="newEmail">New Email Address</label>
                <input
                  id="newEmail"
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary btn-sm">Send Confirmation</button>
            </form>

            {(emailChangeMsg || pendingEmailToken) && (
              <form onSubmit={handleEmailChangeConfirm} className="profile-token-form">
                {emailChangeMsg && <div className="alert alert-success">{emailChangeMsg}</div>}
                <div className="form-group">
                  <label htmlFor="emailToken">Confirmation Token</label>
                  <input
                    id="emailToken"
                    type="text"
                    value={emailToken || pendingEmailToken || ''}
                    onChange={(e) => setEmailToken(e.target.value)}
                    placeholder="Paste token from email"
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary btn-sm">Confirm Change</button>
              </form>
            )}

            {emailChangeError && <div className="alert alert-error">{emailChangeError}</div>}
            <button
              className="btn btn-outline btn-sm"
              style={{ marginTop: '12px' }}
              onClick={() => { setShowEmailChange(false); setEmailChangeMsg(''); setEmailChangeError(''); setPendingEmailToken(null); }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Password card */}
      <div className="profile-card">
        <h2 className="profile-card-title">Password</h2>
        {!showPasswordReset ? (
          <button className="btn btn-secondary btn-sm" onClick={() => setShowPasswordReset(true)}>
            Change Password
          </button>
        ) : (
          <div className="profile-subcard">
            <form onSubmit={handlePasswordResetRequest}>
              <p className="profile-subcard-hint">
                A reset token will be sent to <strong>{profile.email}</strong>.
              </p>
              <button type="submit" className="btn btn-primary btn-sm">Send Reset Token</button>
            </form>

            {(passwordMsg || pendingResetToken) && (
              <form onSubmit={handlePasswordResetConfirm} className="profile-token-form">
                {passwordMsg && <div className="alert alert-success">{passwordMsg}</div>}
                <div className="form-group">
                  <label htmlFor="resetToken">Reset Token</label>
                  <input
                    id="resetToken"
                    type="text"
                    value={resetToken || pendingResetToken || ''}
                    onChange={(e) => setResetToken(e.target.value)}
                    placeholder="Paste token from email"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="newPassword">New Password</label>
                  <input
                    id="newPassword"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    minLength={8}
                    placeholder="Minimum 8 characters"
                    required
                  />
                </div>
                <button type="submit" className="btn btn-primary btn-sm">Set New Password</button>
              </form>
            )}

            {passwordError && <div className="alert alert-error">{passwordError}</div>}
            <button
              className="btn btn-outline btn-sm"
              style={{ marginTop: '12px' }}
              onClick={() => { setShowPasswordReset(false); setPasswordMsg(''); setPasswordError(''); setPendingResetToken(null); }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
