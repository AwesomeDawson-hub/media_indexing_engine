import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import PublicRoute from './components/PublicRoute';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import GalleryPage from './pages/GalleryPage';
import UploadPage from './pages/UploadPage';
import AddMediaPage from './pages/AddMediaPage';
import MediaDetailPage from './pages/MediaDetailPage';
import SourcesPage from './pages/SourcesPage';
import ProfilePage from './pages/ProfilePage';
import AdminPage from './pages/AdminPage';
import BillingPage from './pages/BillingPage';
import GoogleAuthCallbackPage from './pages/GoogleAuthCallbackPage';
import CollectionsPage from './pages/CollectionsPage';
import CollectionDetailPage from './pages/CollectionDetailPage';
import VerifyEmailPage from './pages/VerifyEmailPage';

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Standalone OAuth callback — must not be behind Public or Protected guards */}
        <Route path="/auth/google/callback" element={<GoogleAuthCallbackPage />} />

        {/* Standalone email verification — accessible with or without auth */}
        <Route path="/verify-email" element={<VerifyEmailPage />} />

        {/* Public routes - redirect to / if authenticated */}
        <Route element={<PublicRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </Route>

        {/* Protected routes - redirect to /login if not authenticated */}
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<GalleryPage />} />
            <Route path="/add-media" element={<AddMediaPage />} />
            <Route path="/upload" element={<Navigate to="/add-media" replace />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/media/:id" element={<MediaDetailPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/collections" element={<CollectionsPage />} />
            <Route path="/collections/:id" element={<CollectionDetailPage />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
