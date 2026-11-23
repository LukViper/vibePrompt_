import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { useAuth } from "./auth/AuthContext";
import { Composer } from "./components/Composer";
import { ContextPanel } from "./components/ContextPanel";
import { MessageBubble } from "./components/MessageBubble";
import { AgentPromptModal } from "./components/AgentPromptModal";
import { ByokModal, CreateProjectModal, SpecModal } from "./components/Modals";
import { KnowledgeLibrary } from "./components/KnowledgeLibrary";
import { RoiStrip, type RoiDashboard } from "./components/RoiStrip";
import { Sidebar } from "./components/Sidebar";
import { Welcome } from "./components/Welcome";
import { useByok } from "./hooks/useByok";
import { followUpsFrom, useChat } from "./hooks/useChat";
import { useFreeTier } from "./hooks/useFreeTier";
import { useProjects } from "./hooks/useProjects";

type ThemeMode = "dark" | "light";

function readTheme(): ThemeMode {
  const stored = localStorage.getItem("vibeprompt_theme");
  if (stored === "light" || stored === "dark") return stored;
  return "dark";
}

function App() {
  const navigate = useNavigate();
  const { profile: user, logout: authLogout, loading: authLoading } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState<"none" | "left" | "right">("none");
  const [theme, setTheme] = useState<ThemeMode>(readTheme);
  const [roi, setRoi] = useState<RoiDashboard | null>(null);

  const {
    freeTier,
    setFreeTier,
    refreshFreeTier,
    freeTierEnabled,
    needsByok,
    modePillLabel,
    modePillClass,
  } = useFreeTier();

  const byok = useByok({ refreshFreeTier, setBusy, setError });

  const projectsApi = useProjects({
    refreshFreeTier,
    setBusy,
    setError,
    setMobileNav,
  });

  const chat = useChat({
    project: projectsApi.project,
    setProject: projectsApi.setProject,
    setReadiness: projectsApi.setReadiness,
    setLimitations: projectsApi.setLimitations,
    setProviderStatus: projectsApi.setProviderStatus,
    setFundingSource: projectsApi.setFundingSource,
    setOfflineReview: projectsApi.setOfflineReview,
    setFreeTier,
    refreshFreeTier,
    refreshList: projectsApi.refreshList,
    loadProject: projectsApi.loadProject,
    setShowByok: byok.setShowByok,
    busy,
    setBusy,
    setError,
  });

  const needsAuth = freeTierEnabled && !user;
  const followUps = followUpsFrom(projectsApi.readiness, projectsApi.project);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("vibeprompt_theme", theme);
  }, [theme]);

  useEffect(() => {
    if (authLoading) return;
    const boot = async () => {
      await refreshFreeTier();
      await projectsApi.refreshSkills(Boolean(user));
      try {
        await projectsApi.refreshList();
      } catch (e) {
        setError(String(e));
      }
      if (user) {
        try {
          const me = await api.orgMe();
          const dash = await api.orgRoi(me.org_id);
          setRoi(dash);
        } catch {
          setRoi(null);
        }
      } else {
        setRoi(null);
      }
    };
    void boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot on auth identity change
  }, [authLoading, user?.id]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "k") return;
      e.preventDefault();
      if (!projectsApi.project) {
        projectsApi.setShowCreate(true);
        return;
      }
      document
        .querySelector<HTMLTextAreaElement>(".composer-box textarea")
        ?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [projectsApi.project, projectsApi.setShowCreate]);

  async function logout() {
    projectsApi.clearProjects();
    await authLogout();
    void refreshFreeTier();
    navigate("/login");
  }

  const project = projectsApi.project;

  return (
    <div
      className={`app ${sidebarCollapsed ? "sidebar-is-collapsed" : ""} ${
        panelOpen && project ? "panel-open" : "panel-closed"
      }`}
    >
      {projectsApi.offlineReview && (
        <div className="offline-banner" role="status">
          Offline heuristic mode — not live adversarial review.
        </div>
      )}

      {user && roi && <RoiStrip roi={roi} />}

      <header className="top-bar">
        <div className="top-bar-crumb">
          <span className="brand-mark-sm">VP</span>
          <span className="sep">/</span>
          <span className="title">{project?.name ?? "VibePrompt"}</span>
          {project?.behavioural_mode && (
            <>
              <span className="sep">·</span>
              <span
                className="mono"
                style={{ color: "var(--ink-faint)", fontSize: "0.6875rem" }}
              >
                {(project.behavioural_mode === "grill_review"
                  ? "review"
                  : project.behavioural_mode
                ).toUpperCase()}
              </span>
            </>
          )}
        </div>
        <div className="top-bar-actions">
          <button
            type="button"
            className={modePillClass}
            onClick={() => byok.setShowByok(true)}
            title="Bring your own API key / inference settings"
          >
            {modePillLabel}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            title="Toggle theme"
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          {project && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => void chat.exportSpec()}
              disabled={busy}
            >
              Spec
            </button>
          )}
        </div>
      </header>

      {(mobileNav === "left" || mobileNav === "right") && (
        <button
          type="button"
          className="drawer-scrim"
          aria-label="Close drawer"
          onClick={() => setMobileNav("none")}
        />
      )}

      <div className={`sidebar-shell ${mobileNav === "left" ? "drawer-open" : ""}`}>
        <Sidebar
          projects={projectsApi.projects}
          activeId={project?.id ?? null}
          activeMode={project?.behavioural_mode}
          user={user}
          freeTier={freeTier}
          fundingSource={projectsApi.fundingSource}
          projectQuery={projectsApi.projectQuery}
          needsAuth={needsAuth}
          needsByok={needsByok}
          skillsActive={projectsApi.skillsActive}
          skillsTotal={projectsApi.skillsTotal}
          onQueryChange={projectsApi.setProjectQuery}
          onSelectProject={(id) => void projectsApi.loadProject(id)}
          onNewProject={() => projectsApi.setShowCreate(true)}
          onOpenByok={() => byok.setShowByok(true)}
          onLogin={() => navigate("/login")}
          onRegister={() => navigate("/signup")}
          onLogout={() => void logout()}
          onOpenKnowledge={() => setShowKnowledge(true)}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        />
      </div>

      <main className="main">
        <div className="mobile-bar">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setMobileNav("left")}
          >
            Projects
          </button>
          <span className="mobile-title">{project?.name ?? "VibePrompt"}</span>
          {project && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setMobileNav("right")}
            >
              State
            </button>
          )}
        </div>

        {needsAuth || !project ? (
          <Welcome
            allocated={freeTier?.allocated ?? 20}
            needsAuth={needsAuth}
            onStart={(brief) => void projectsApi.createFromBrief(brief)}
            onRegister={() => navigate("/signup")}
            onPickExample={projectsApi.openCreateWithExample}
          />
        ) : (
          <>
            <header className="main-header">
              <div>
                <h2>{project.name}</h2>
                <p className="muted header-sub">
                  {project.objective ||
                    "No objective yet — assert the problem and stack."}
                </p>
              </div>
              <div className="header-actions">
                <button
                  className="btn btn-ghost btn-sm"
                  type="button"
                  onClick={() => {
                    if (window.matchMedia("(max-width: 1100px)").matches) {
                      setMobileNav("right");
                    } else {
                      setPanelOpen((v) => !v);
                    }
                  }}
                >
                  {panelOpen ? "Hide inspector" : "Show inspector"}
                </button>
                <button
                  className={
                    projectsApi.readiness?.implementation_ready
                      ? "btn btn-sm"
                      : "btn btn-ghost btn-sm"
                  }
                  type="button"
                  onClick={() => chat.openAgentPrompt()}
                  disabled={busy}
                  title={
                    projectsApi.readiness?.implementation_ready
                      ? "Export Agent Spec"
                      : "Locked until Readiness Gate passes"
                  }
                >
                  Export Agent Spec
                </button>
              </div>
            </header>

            {projectsApi.providerStatus && (
              <div
                className="provider-status"
                title={projectsApi.providerStatus}
              >
                {projectsApi.providerStatus}
                {projectsApi.fundingSource
                  ? ` · Funding: ${projectsApi.fundingSource}`
                  : ""}
              </div>
            )}
            {projectsApi.limitations.length > 0 && (
              <div className="banner warn">
                {projectsApi.limitations.join(" · ")}
              </div>
            )}
            {error && <div className="banner danger">{error}</div>}
            {needsByok && (
              <div className="banner warn">
                Free generations exhausted.{" "}
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => byok.setShowByok(true)}
                >
                  Configure BYOK
                </button>
              </div>
            )}

            <div className="chat" aria-label="Conversation">
              {project.messages.length === 0 && !busy ? (
                <div className="chat-empty">
                  <p className="chat-empty-title">Conversation</p>
                  <p className="muted">
                    Mentor briefs and your replies appear here. Start below —
                    state the product problem, constraints, and stack.
                  </p>
                  <ul className="chat-empty-hints">
                    <li>What problem are you solving, and for whom?</li>
                    <li>Which stack or architecture are you committing to?</li>
                    <li>What evidence supports that choice?</li>
                  </ul>
                </div>
              ) : null}
              {project.messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  techStack={project.tech_stack}
                  rejectedApproaches={project.rejected_approaches ?? []}
                  onCopy={(content) =>
                    void navigator.clipboard.writeText(content)
                  }
                />
              ))}
              {busy && (
                <div className="msg msg-assistant thinking" aria-live="polite">
                  <div className="msg-meta">
                    <span className="msg-role">Mentor brief</span>
                  </div>
                  <div className="thinking-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}
              {!busy && followUps.length > 0 && project.messages.length > 0 && (
                <div className="follow-ups">
                  {followUps.map((tip) => (
                    <button
                      key={tip}
                      type="button"
                      className="follow-chip"
                      disabled={needsByok}
                      onClick={() => chat.setDraft(tip)}
                    >
                      {tip}
                    </button>
                  ))}
                </div>
              )}
              <div ref={chat.chatEnd} />
            </div>

            <Composer
              draft={chat.draft}
              busy={busy}
              disabled={needsByok}
              onDraftChange={chat.setDraft}
              onSubmit={(e) => void chat.sendMessage(e)}
            />
          </>
        )}
      </main>

      {project && (
        <div
          className={`context-shell ${panelOpen ? "visible" : ""} ${
            mobileNav === "right" ? "drawer-open" : ""
          }`}
          aria-hidden={!panelOpen && mobileNav !== "right"}
          hidden={!panelOpen && mobileNav !== "right"}
        >
          <ContextPanel
            readiness={projectsApi.readiness}
            findings={chat.openFindings}
            decisions={project.decisions}
            techStack={project.tech_stack}
            rejectedApproaches={project.rejected_approaches ?? []}
            busy={busy}
            onUpdateFinding={(id, status, note) =>
              void chat.updateFinding(id, status, note)
            }
            onExportAgent={chat.openAgentPrompt}
            onClose={() => {
              setPanelOpen(false);
              setMobileNav("none");
            }}
          />
        </div>
      )}

      {projectsApi.showCreate && (
        <CreateProjectModal
          name={projectsApi.newName}
          objective={projectsApi.newObjective}
          message={projectsApi.newMessage}
          busy={busy}
          onName={projectsApi.setNewName}
          onObjective={projectsApi.setNewObjective}
          onMessage={projectsApi.setNewMessage}
          onClose={() => projectsApi.setShowCreate(false)}
          onSubmit={(e) => void projectsApi.handleCreate(e)}
        />
      )}

      {byok.showByok && (
        <ByokModal
          provider={byok.byokProvider}
          model={byok.byokModel}
          apiKey={byok.byokKey}
          baseUrl={byok.byokBaseUrl}
          remaining={freeTier?.remaining ?? null}
          allocated={freeTier?.allocated ?? null}
          connected={Boolean(freeTier?.byok_configured)}
          busy={busy}
          onProvider={(p, model) => {
            byok.setByokProvider(p);
            byok.setByokModel(model);
          }}
          onModel={byok.setByokModel}
          onKey={byok.setByokKey}
          onBaseUrl={byok.setByokBaseUrl}
          onClose={() => byok.setShowByok(false)}
          onSubmit={(e) => void byok.handleByok(e)}
        />
      )}

      {chat.spec && (
        <SpecModal spec={chat.spec} onClose={() => chat.setSpec(null)} />
      )}

      {chat.showAgentPrompt && project && (
        <AgentPromptModal
          readiness={projectsApi.readiness}
          busy={busy}
          result={chat.agentPromptResult}
          preview={chat.agentPromptPreview}
          onClose={() => {
            chat.setShowAgentPrompt(false);
            chat.setAgentPromptResult(null);
          }}
          onPreview={(opts) => void chat.previewAgentSkills(opts)}
          onGenerate={(opts) => void chat.generateAgentPrompt(opts)}
        />
      )}

      {showKnowledge && user && (
        <KnowledgeLibrary
          onClose={() => setShowKnowledge(false)}
          onError={(msg) => setError(msg)}
        />
      )}
    </div>
  );
}

export default App;
