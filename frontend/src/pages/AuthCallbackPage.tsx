import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getSupabase, safeRedirectPath } from "../lib/supabase";

export function AuthCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sb = getSupabase();
    if (!sb) {
      setError("Supabase is not configured in this environment.");
      return;
    }

    let cancelled = false;
    const run = async () => {
      // PKCE / hash fragments are handled by detectSessionInUrl
      const { data, error: err } = await sb.auth.getSession();
      if (cancelled) return;
      if (err) {
        setError(err.message);
        return;
      }
      if (!data.session) {
        // Exchange may still be in progress — listen once
        const { data: sub } = sb.auth.onAuthStateChange((event, session) => {
          if (event === "SIGNED_IN" && session) {
            const next = safeRedirectPath(sessionStorage.getItem("vp_auth_next"), "/");
            sessionStorage.removeItem("vp_auth_next");
            navigate(next, { replace: true });
          }
          if (event === "SIGNED_OUT") {
            setError("Sign-in was cancelled.");
          }
        });
        window.setTimeout(() => {
          if (!cancelled) {
            setError("No session returned. You may have cancelled OAuth or the link expired.");
          }
          sub.subscription.unsubscribe();
        }, 8000);
        return;
      }
      const next = safeRedirectPath(sessionStorage.getItem("vp_auth_next"), "/");
      sessionStorage.removeItem("vp_auth_next");
      navigate(next, { replace: true });
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <p className="brand">VibePrompt</p>
        <h1>Completing sign-in…</h1>
        {error ? (
          <>
            <div className="banner danger">{error}</div>
            <Link className="btn btn-block" to="/login">
              Back to sign in
            </Link>
          </>
        ) : (
          <p className="muted">Finishing OAuth / email verification.</p>
        )}
      </div>
    </div>
  );
}
