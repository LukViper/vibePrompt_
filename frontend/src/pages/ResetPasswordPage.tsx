import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function ResetPasswordPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setLocalError(null);
    if (password.length < 6) {
      setLocalError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setLocalError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await auth.updatePassword(password);
      setDone(true);
      window.setTimeout(() => navigate("/", { replace: true }), 1200);
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <p className="brand">VibePrompt</p>
        <h1>Choose a new password</h1>
        {done ? (
          <p className="muted">Password updated. Redirecting…</p>
        ) : (
          <form className="auth-form" onSubmit={(e) => void onSubmit(e)}>
            <label htmlFor="new-password">New password</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              disabled={busy}
            />
            <label htmlFor="new-password-confirm">Confirm password</label>
            <input
              id="new-password-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              disabled={busy}
            />
            {(localError || auth.error) && (
              <div className="banner danger">{localError || auth.error}</div>
            )}
            <button className="btn btn-block" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Update password"}
            </button>
            <div className="auth-links">
              <Link to="/login">Back to sign in</Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
