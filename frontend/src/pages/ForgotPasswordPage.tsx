import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function ForgotPasswordPage() {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setLocalError(null);
    if (!auth.usingSupabase) {
      setLocalError("Password recovery requires Supabase Auth.");
      return;
    }
    setBusy(true);
    try {
      await auth.resetPasswordForEmail(email.trim());
      setSent(true);
    } catch (ex) {
      setLocalError(ex instanceof Error ? ex.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <p className="brand">VibePrompt</p>
        <h1>Reset password</h1>
        {sent ? (
          <>
            <p>
              If an account exists for <strong>{email}</strong>, a reset link is on its way.
              Check your inbox and spam folder.
            </p>
            <Link className="btn btn-block" to="/login">
              Back to sign in
            </Link>
          </>
        ) : (
          <form className="auth-form" onSubmit={(e) => void onSubmit(e)}>
            <p className="muted">Enter your email and we will send a recovery link.</p>
            <label htmlFor="forgot-email">Email</label>
            <input
              id="forgot-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={busy}
            />
            {(localError || auth.error) && (
              <div className="banner danger">{localError || auth.error}</div>
            )}
            <button className="btn btn-block" type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send reset link"}
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
