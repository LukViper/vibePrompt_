import { UserProfile } from "./auth/UserProfile";
import type {
  BehaviouralMode,
  FreeTierStatus,
  ProjectSummary,
  UserPublic,
} from "../types";

const STAGES: { id: BehaviouralMode; label: string }[] = [
  { id: "explore", label: "EXPLORE" },
  { id: "plan", label: "PLAN" },
  { id: "build", label: "BUILD" },
  { id: "review", label: "REVIEW" },
  { id: "debug", label: "DEBUG" },
];

const STAGE_ORDER = STAGES.map((s) => s.id);

function normalizeStage(mode?: BehaviouralMode | null): BehaviouralMode {
  if (!mode) return "explore";
  if (mode === "grill_review") return "review";
  if (mode === "brainstorming" || mode === "conversational") return "explore";
  if (STAGE_ORDER.includes(mode)) return mode;
  return "explore";
}

type Props = {
  projects: ProjectSummary[];
  activeId: string | null;
  activeMode?: BehaviouralMode | null;
  user: UserPublic | null;
  freeTier: FreeTierStatus | null;
  fundingSource: string | null;
  projectQuery: string;
  needsAuth: boolean;
  needsByok: boolean;
  skillsActive: number;
  skillsTotal: number;
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
  activeMode,
  user,
  freeTier,
  fundingSource,
  projectQuery,
  needsAuth,
  needsByok,
  skillsActive,
  skillsTotal,
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
  const current = normalizeStage(activeMode);
  const currentIdx = STAGE_ORDER.indexOf(current);

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
          <p className="brand">VibePrompt</p>
          {onToggleCollapse && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onToggleCollapse}
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
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
        <p className="section-label">Projects</p>
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

        {activeId && (
          <>
            <p className="section-label" style={{ marginTop: "1rem" }}>
              Stage
            </p>
            <ul className="stage-stepper" aria-label="Project stage">
              {STAGES.map((s, i) => {
                const done = i < currentIdx;
                const active = i === currentIdx;
                return (
                  <li
                    key={s.id}
                    className={`stage-step ${done ? "done" : ""} ${active ? "active" : ""}`}
                  >
                    <span className="stage-check" aria-hidden>
                      {done ? "✓" : active ? "›" : ""}
                    </span>
                    {s.label}
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {(user || skillsTotal > 0) && (
          <>
            <p className="section-label" style={{ marginTop: "1rem" }}>
              Knowledge Library
            </p>
            <button
              type="button"
              className="skills-status"
              onClick={onOpenKnowledge}
              disabled={!user || !onOpenKnowledge}
              title={user ? "Open Knowledge Library" : "Sign in to manage skills"}
              style={{ width: "100%", cursor: user ? "pointer" : "default" }}
            >
              <span className="count">
                {skillsActive}/{skillsTotal || 6}
              </span>
              <span className="label">Active Skills</span>
            </button>
          </>
        )}
      </div>

      <div className="sidebar-footer">
        {freeTierEnabled ? (
          <div className={`quota-card ${needsByok ? "exhausted" : ""}`}>
            <div className="quota-head">
              <span>Generations</span>
              <strong>
                {remaining}/{allocated}
              </strong>
            </div>
            <div className="progress-track" aria-hidden>
              <div
                className={`progress-fill ${needsByok ? "blocking" : ""}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="quota-msg">
              {needsByok
                ? "Free tier exhausted — connect BYOK."
                : freeTier?.funding === "BYOK"
                  ? `${freeTier.byok_provider ?? "BYOK"} · your key`
                  : `${freeTier?.provider ?? "Qwen"} · platform`}
              {fundingSource ? ` · last: ${fundingSource}` : ""}
            </p>
            <button
              className="btn btn-sm btn-ghost btn-block"
              type="button"
              onClick={onOpenByok}
            >
              {needsByok ? "Configure BYOK" : "API settings"}
            </button>
          </div>
        ) : (
          <div className="quota-card">
            <div className="quota-head">
              <span>Inference</span>
              <strong>
                {freeTier?.byok_configured ? "BYOK" : "Keys"}
              </strong>
            </div>
            <p className="quota-msg">
              {freeTier?.byok_configured
                ? `${freeTier.byok_provider ?? "BYOK"} · your key`
                : "Server providers on · BYOK optional if you prefer your own key."}
            </p>
            <button
              className="btn btn-sm btn-ghost btn-block"
              type="button"
              onClick={onOpenByok}
            >
              {freeTier?.byok_configured ? "API settings" : "Optional BYOK"}
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
