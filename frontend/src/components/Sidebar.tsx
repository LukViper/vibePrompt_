import { UserProfile } from "./auth/UserProfile";
import type { FreeTierStatus, ProjectSummary, UserPublic } from "../types";

type Props = {
  projects: ProjectSummary[];
  activeId: string | null;
  user: UserPublic | null;
  freeTier: FreeTierStatus | null;
  fundingSource: string | null;
  projectQuery: string;
  needsAuth: boolean;
  needsByok: boolean;
  onQueryChange: (q: string) => void;
  onSelectProject: (id: string) => void;
  onNewProject: () => void;
  onOpenByok: () => void;
  onLogin: () => void;
  onRegister: () => void;
  onLogout: () => void;
  onOpenKnowledge?: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
};

export function Sidebar({
  projects,
  activeId,
  user,
  freeTier,
  fundingSource,
  projectQuery,
  needsAuth,
  needsByok,
  onQueryChange,
  onSelectProject,
  onNewProject,
  onOpenByok,
  onLogin,
  onRegister,
  onLogout: _onLogout,
  onOpenKnowledge,
  collapsed,
  onToggleCollapse,
}: Props) {
  const freeTierEnabled = freeTier?.enabled === true;
  const q = projectQuery.trim().toLowerCase();
  const filtered = q
    ? projects.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.objective.toLowerCase().includes(q)
      )
    : projects;

  const allocated = freeTier?.allocated ?? 0;
  const remaining = freeTier?.remaining ?? 0;
  const pct = allocated > 0 ? Math.round((remaining / allocated) * 100) : 0;

  if (collapsed) {
    return (
      <aside className="sidebar sidebar-collapsed">
        <button
          type="button"
          className="brand-mark"
          onClick={onToggleCollapse}
          title="Expand sidebar"
        >
          VP
        </button>
        <button
          type="button"
          className="icon-btn accent"
          onClick={onNewProject}
          disabled={needsAuth}
          title="New project"
        >
          +
        </button>
        <div className="sidebar-collapsed-spacer" />
        <button
          type="button"
          className="avatar-sm"
          onClick={onOpenByok}
          title="API settings"
        >
          {(user?.email?.[0] ?? "V").toUpperCase()}
        </button>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="brand-row">
          <div>
            <p className="brand">VibePrompt</p>
            <p className="brand-sub">Shape ideas · craft prompts</p>
          </div>
          {onToggleCollapse && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onToggleCollapse}
              title="Collapse sidebar"
            >
              «
            </button>
          )}
        </div>

        <button
          className="btn btn-block"
          type="button"
          onClick={onNewProject}
          disabled={needsAuth}
        >
          New project
        </button>
        {onOpenKnowledge && user && (
          <button
            className="btn btn-block btn-ghost"
            type="button"
            onClick={onOpenKnowledge}
          >
            Knowledge Library
          </button>
        )}

        <label className="search-field">
          <span className="sr-only">Search projects</span>
          <input
            type="search"
            placeholder="Search projects…"
            value={projectQuery}
            onChange={(e) => onQueryChange(e.target.value)}
          />
        </label>
      </div>

      <div className="sidebar-scroll">
        <p className="section-label">Recent</p>
        <ul className="project-list">
          {filtered.length === 0 && (
            <li className="muted empty-list">No projects yet</li>
          )}
          {filtered.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className={`project-item ${activeId === p.id ? "active" : ""}`}
                onClick={() => onSelectProject(p.id)}
              >
                <span className="name">{p.name}</span>
                <span className="meta">
                  {p.open_finding_count} open · {p.message_count} msgs
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="sidebar-footer">
        {freeTierEnabled && (
          <div className={`quota-card ${needsByok ? "exhausted" : ""}`}>
            <div className="quota-head">
              <span>AI generations</span>
              <strong>
                {remaining} / {allocated}
              </strong>
            </div>
            <div className="progress-track" aria-hidden>
              <div className="progress-fill" style={{ width: `${pct}%` }} />
            </div>
            {needsByok ? (
              <p className="quota-msg">Free tier exhausted — connect BYOK.</p>
            ) : (
              <p className="quota-msg">
                {freeTier?.funding === "BYOK"
                  ? `${freeTier.byok_provider ?? "BYOK"} · your key`
                  : `${freeTier?.provider ?? "Qwen"} · platform`}
                {fundingSource ? ` · last: ${fundingSource}` : ""}
              </p>
            )}
            <button
              className="btn btn-sm btn-ghost btn-block"
              type="button"
              onClick={onOpenByok}
            >
              {needsByok ? "Configure BYOK" : "API settings"}
            </button>
          </div>
        )}

        {user ? (
          <UserProfile />
        ) : (
          <div className="auth-bar">
            <button className="btn btn-sm" type="button" onClick={onLogin}>
              Sign in
            </button>
            <button className="btn btn-sm btn-ghost" type="button" onClick={onRegister}>
              Register
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
