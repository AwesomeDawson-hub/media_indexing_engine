import { Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import PublicRoute from './components/PublicRoute';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import GalleryPage from './pages/GalleryPage';
import UploadPage from './pages/UploadPage';
import MediaDetailPage from './pages/MediaDetailPage';
import SourcesPage from './pages/SourcesPage';
import ProfilePage from './pages/ProfilePage';
import AdminPage from './pages/AdminPage';
import BillingPage from './pages/BillingPage';

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public routes - redirect to / if authenticated */}
        <Route element={<PublicRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>

        {/* Protected routes - redirect to /login if not authenticated */}
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<GalleryPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/media/:id" element={<MediaDetailPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
