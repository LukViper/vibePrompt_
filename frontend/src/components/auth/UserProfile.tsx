import { useAuth } from "../../auth/AuthContext";
import { LogoutButton } from "./LogoutButton";

export function UserProfile() {
  const { profile, supabaseUser, loading } = useAuth();
  if (loading) return null;
  if (!profile && !supabaseUser) return null;

  const email = profile?.email || supabaseUser?.email || "";
  const name =
    profile?.display_name ||
    (typeof supabaseUser?.user_metadata?.full_name === "string"
      ? supabaseUser.user_metadata.full_name
      : null) ||
    email;
  const avatar = profile?.avatar_url || null;
  const initial = (name || email || "V")[0]?.toUpperCase() ?? "V";

  return (
    <div className="user-row">
      {avatar ? (
        <img className="avatar-sm avatar-img" src={avatar} alt="" referrerPolicy="no-referrer" />
      ) : (
        <div className="avatar-sm">{initial}</div>
      )}
      <div className="user-meta">
        <span className="email" title={email}>
          {name}
        </span>
        <LogoutButton />
      </div>
    </div>
  );
}
