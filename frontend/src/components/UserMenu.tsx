import { useAuth } from '../context/AuthContext';

export default function UserMenu() {
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <div className="user-menu">
      <span className="user-name">{user.display_name}</span>
      <button className="btn btn-sm btn-outline" onClick={logout}>
        Logout
      </button>
    </div>
  );
}
