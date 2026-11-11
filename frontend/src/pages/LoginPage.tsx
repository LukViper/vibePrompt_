import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { safeRedirectPath } from "../lib/supabase";

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeRedirectPath(params.get("next"), "/");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const err = localError || auth.error;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setLocalError(null);
    auth.clearError();
    if (!email.trim() || !password) {
      setLocalError("Email and password are required.");
      return;
    }
    setBusy(true);
    try {
      if (auth.usingSupabase) {
        await auth.signInWithPassword(email.trim(), password);
      } else {
        await auth.signInLegacy(email.trim(), password);
      }
      navigate(next, { replace: true });
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  async function oauth(provider: "google" | "github") {
    if (busy) return;
    setLocalError(null);
    auth.clearError();
    setBusy(true);
    try {
      sessionStorage.setItem("vp_auth_next", next);
      await auth.signInWithOAuth(provider);
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "OAuth failed");
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <p className="brand">VibePrompt</p>
        <h1>Sign in</h1>
        <p className="muted">Continue building your project plan.</p>

        {auth.usingSupabase && (
          <div className="oauth-stack">
            <button
              type="button"
              className="btn btn-block oauth-btn"
              disabled={busy}
              onClick={() => void oauth("google")}
            >
              Continue with Google
            </button>
            <button
              type="button"
              className="btn btn-block oauth-btn ghost"
              disabled={busy}
              onClick={() => void oauth("github")}
            >
              Continue with GitHub
            </button>
            <div className="auth-divider">
              <span>or email</span>
            </div>
          </div>
        )}

        <form onSubmit={(e) => void onSubmit(e)} className="auth-form">
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={busy}
          />
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={auth.usingSupabase ? 6 : 8}
            disabled={busy}
          />
          {err && <div className="banner danger">{err}</div>}
          <button className="btn btn-block" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="auth-links">
          {auth.usingSupabase && (
            <Link to="/forgot-password">Forgot password?</Link>
          )}
          <Link to={`/signup?next=${encodeURIComponent(next)}`}>Create an account</Link>
          <Link to="/">Back to app</Link>
        </div>

        {auth.usingSupabase && (
          <p className="muted small">
            Google/GitHub work only after providers are enabled in Supabase and credentials are
            configured — see AUTH_SETUP.md.
          </p>
        )}
      </div>
    </div>
  );
}
