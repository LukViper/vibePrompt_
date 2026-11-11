import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { safeRedirectPath } from "../lib/supabase";

export function SignupPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeRedirectPath(params.get("next"), "/");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [verifyNotice, setVerifyNotice] = useState(false);

  const err = localError || auth.error;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setLocalError(null);
    auth.clearError();
    if (!email.trim()) {
      setLocalError("Email is required.");
      return;
    }
    if (password.length < (auth.usingSupabase ? 6 : 8)) {
      setLocalError("Password is too short.");
      return;
    }
    if (password !== confirm) {
      setLocalError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      if (auth.usingSupabase) {
        const result = await auth.signUpWithPassword(email.trim(), password);
        if (result.needsEmailConfirm) {
          setVerifyNotice(true);
        } else {
          navigate(next, { replace: true });
        }
      } else {
        await auth.registerLegacy(email.trim(), password);
        navigate(next, { replace: true });
      }
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function oauth(provider: "google" | "github") {
    if (busy) return;
    setBusy(true);
    try {
      sessionStorage.setItem("vp_auth_next", next);
      await auth.signInWithOAuth(provider);
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "OAuth failed");
      setBusy(false);
    }
  }

  if (verifyNotice) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <p className="brand">VibePrompt</p>
          <h1>Check your email</h1>
          <p>
            We sent a verification link to <strong>{email}</strong>. Open it to activate your
            account, then sign in.
          </p>
          <Link className="btn btn-block" to="/login">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <p className="brand">VibePrompt</p>
        <h1>Create account</h1>
        <p className="muted">Save projects and resume discovery anytime.</p>

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
          <label htmlFor="signup-email">Email</label>
          <input
            id="signup-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={busy}
          />
          <label htmlFor="signup-password">Password</label>
          <input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={auth.usingSupabase ? 6 : 8}
            disabled={busy}
          />
          <label htmlFor="signup-confirm">Confirm password</label>
          <input
            id="signup-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            disabled={busy}
          />
          {err && <div className="banner danger">{err}</div>}
          <button className="btn btn-block" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>

        <div className="auth-links">
          <Link to={`/login?next=${encodeURIComponent(next)}`}>Already have an account?</Link>
        </div>
      </div>
    </div>
  );
}
