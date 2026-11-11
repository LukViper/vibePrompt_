import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";

type Props = {
  className?: string;
  confirm?: boolean;
};

export function LogoutButton({ className = "text-link", confirm = true }: Props) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function onClick() {
    if (confirm && !window.confirm("Sign out of VibePrompt?")) return;
    setBusy(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <button type="button" className={className} disabled={busy} onClick={() => void onClick()}>
      {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
