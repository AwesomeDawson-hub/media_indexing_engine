import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import * as api from '../api/client';
import type { AdminUserSummary, AdminUserDetail, AuditLogEntry } from '../types/api';

type Tab = 'users' | 'audit';

interface EditState {
  user: AdminUserDetail;
  role: string;
  planName: string;
  monthlyLimit: number;
  disabled: boolean;
  email: string;
}

export default function AdminPage() {
  const { user: currentUser } = useAuth();

  if (!currentUser || currentUser.role !== 'admin') {
    return <div className="page-error">Access denied. Admin only.</div>;
  }

  return <AdminContent />;
}

function AdminContent() {
  const [tab, setTab] = useState<Tab>('users');

  return (
    <div className="admin-page">
      <h1>Admin Console</h1>
      <div className="tab-bar">
        <button
          className={`tab-btn${tab === 'users' ? ' active' : ''}`}
          onClick={() => setTab('users')}
        >
          Users
        </button>
        <button
          className={`tab-btn${tab === 'audit' ? ' active' : ''}`}
          onClick={() => setTab('audit')}
        >
          Audit Log
        </button>
      </div>
      {tab === 'users' ? <UsersTab /> : <AuditTab />}
    </div>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [editError, setEditError] = useState('');
  const [editMsg, setEditMsg] = useState('');
  const perPage = 20;

  async function load(pg: number, q: string) {
    setLoading(true);
    try {
      const res = await api.adminListUsers(pg, perPage, q || undefined);
      setUsers(res.users);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(page, search); }, [page, search]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput);
  }

  async function openEdit(u: AdminUserSummary) {
    setEditError('');
    setEditMsg('');
    try {
      const detail = await api.adminGetUser(u.id);
      setEditState({
        user: detail,
        role: detail.role,
        planName: detail.plan_name,
        monthlyLimit: detail.monthly_limit,
        disabled: !!detail.disabled_at,
        email: detail.email,
      });
    } catch {
      // fall back to summary
      setEditState({
        user: { ...u, quota_this_month: 0 },
        role: u.role,
        planName: u.plan_name,
        monthlyLimit: u.monthly_limit,
        disabled: !!u.disabled_at,
        email: u.email,
      });
    }
  }

  async function handleEditSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editState) return;
    setEditError('');
    setEditMsg('');
    try {
      await api.adminUpdateUser(editState.user.id, {
        role: editState.role,
        plan_name: editState.planName,
        monthly_limit: editState.monthlyLimit,
        disabled: editState.disabled,
        email: editState.email !== editState.user.email ? editState.email : undefined,
      });
      setEditMsg('Saved.');
      load(page, search);
    } catch {
      setEditError('Failed to save changes.');
    }
  }

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="admin-tab">
      <form onSubmit={handleSearch} className="search-bar">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by email or name…"
        />
        <button type="submit" className="btn btn-primary">Search</button>
        {search && (
          <button type="button" className="btn btn-ghost" onClick={() => { setSearchInput(''); setSearch(''); setPage(1); }}>
            Clear
          </button>
        )}
      </form>

      {loading ? (
        <p className="page-loading">Loading…</p>
      ) : (
        <>
          <p className="result-count">{total} user{total !== 1 ? 's' : ''}</p>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Name</th>
                <th>Role</th>
                <th>Plan</th>
                <th>Limit</th>
                <th>Status</th>
                <th>Joined</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.disabled_at ? 'row-disabled' : ''}>
                  <td>{u.email}</td>
                  <td>{u.display_name}</td>
                  <td>{u.role}</td>
                  <td>{u.plan_name}</td>
                  <td>{u.monthly_limit}</td>
                  <td>{u.disabled_at ? <span className="badge-disabled">Disabled</span> : <span className="badge-active">Active</span>}</td>
                  <td>{new Date(u.created_at).toLocaleDateString()}</td>
                  <td><button className="btn btn-sm btn-secondary" onClick={() => openEdit(u)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="pagination">
              <button className="btn btn-sm btn-ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
              <span>Page {page} / {totalPages}</span>
              <button className="btn btn-sm btn-ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          )}
        </>
      )}

      {editState && (
        <div className="modal-overlay" onClick={() => setEditState(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h2>Edit User</h2>
            <p className="modal-sub">{editState.user.email}</p>
            {editState.user.quota_this_month > 0 && (
              <p className="modal-sub">Used this month: {editState.user.quota_this_month}</p>
            )}
            <form onSubmit={handleEditSave} className="profile-form">
              <label>
                Email
                <input
                  type="email"
                  value={editState.email}
                  onChange={(e) => setEditState(s => s ? { ...s, email: e.target.value } : s)}
                />
              </label>
              <label>
                Role
                <select
                  value={editState.role}
                  onChange={(e) => setEditState(s => s ? { ...s, role: e.target.value } : s)}
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </label>
              <label>
                Plan Name
                <input
                  type="text"
                  value={editState.planName}
                  onChange={(e) => setEditState(s => s ? { ...s, planName: e.target.value } : s)}
                  maxLength={50}
                />
              </label>
              <label>
                Monthly Limit
                <input
                  type="number"
                  value={editState.monthlyLimit}
                  min={0}
                  onChange={(e) => setEditState(s => s ? { ...s, monthlyLimit: Number(e.target.value) } : s)}
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={editState.disabled}
                  onChange={(e) => setEditState(s => s ? { ...s, disabled: e.target.checked } : s)}
                />
                Account Disabled
              </label>
              <div className="modal-actions">
                <button type="submit" className="btn btn-primary">Save</button>
                <button type="button" className="btn btn-ghost" onClick={() => setEditState(null)}>Cancel</button>
              </div>
              {editMsg && <p className="form-success">{editMsg}</p>}
              {editError && <p className="form-error">{editError}</p>}
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function AuditTab() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterUserId, setFilterUserId] = useState('');
  const [filterInput, setFilterInput] = useState('');
  const [loading, setLoading] = useState(true);
  const perPage = 20;

  async function load(pg: number, uid: string) {
    setLoading(true);
    try {
      const res = await api.adminGetAuditLog(pg, uid || undefined);
      setEntries(res.entries);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(page, filterUserId); }, [page, filterUserId]);

  function handleFilter(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setFilterUserId(filterInput.trim());
  }

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="admin-tab">
      <form onSubmit={handleFilter} className="search-bar">
        <input
          type="text"
          value={filterInput}
          onChange={(e) => setFilterInput(e.target.value)}
          placeholder="Filter by target user ID (optional)…"
        />
        <button type="submit" className="btn btn-primary">Filter</button>
        {filterUserId && (
          <button type="button" className="btn btn-ghost" onClick={() => { setFilterInput(''); setFilterUserId(''); setPage(1); }}>
            Clear
          </button>
        )}
      </form>

      {loading ? (
        <p className="page-loading">Loading…</p>
      ) : (
        <>
          <p className="result-count">{total} entr{total !== 1 ? 'ies' : 'y'}</p>
          <table className="admin-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Target User</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td><code>{e.action}</code></td>
                  <td>{e.target_user_id ?? '—'}</td>
                  <td className="audit-detail">{e.detail ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="pagination">
              <button className="btn btn-sm btn-ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</button>
              <span>Page {page} / {totalPages}</span>
              <button className="btn btn-sm btn-ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
