import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";

type Props = {
  children: React.ReactNode;
  /** When false, guests may pass (legacy demo without free tier). */
  requireAuth?: boolean;
};

export function ProtectedRoute({ children, requireAuth = true }: Props) {
  const { loading, profile, session, usingSupabase } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <p className="muted">Checking session…</p>
        </div>
      </div>
    );
  }

  const authed = Boolean(profile || session);
  if (requireAuth && !authed) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  // Soft hint: supabase mode without session still blocked above
  void usingSupabase;
  return <>{children}</>;
}
