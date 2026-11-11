import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { useAuth } from "./auth/AuthContext";
import { Composer } from "./components/Composer";
import { ContextPanel } from "./components/ContextPanel";
import { MessageBubble } from "./components/MessageBubble";
import { AgentPromptModal } from "./components/AgentPromptModal";
import { ByokModal, CreateProjectModal, SpecModal } from "./components/Modals";
import { KnowledgeLibrary } from "./components/KnowledgeLibrary";
import { Sidebar } from "./components/Sidebar";
import { Welcome } from "./components/Welcome";
import type {
  AgentPromptPreview,
  AgentPromptResult,
  ByokProvider,
  CodingAgent,
  FindingStatus,
  FreeTierStatus,
  ProjectState,
  ProjectSummary,
  ReadinessResult,
  SpecificationResult,
} from "./types";

function App() {
  const navigate = useNavigate();
  const { profile: user, logout: authLogout, loading: authLoading } = useAuth();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectState | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResult | null>(null);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [providerStatus, setProviderStatus] = useState<string | null>(null);
  const [fundingSource, setFundingSource] = useState<string | null>(null);
  const [freeTier, setFreeTier] = useState<FreeTierStatus | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showByok, setShowByok] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [spec, setSpec] = useState<SpecificationResult | null>(null);
  const [showAgentPrompt, setShowAgentPrompt] = useState(false);
  const [agentPromptResult, setAgentPromptResult] =
    useState<AgentPromptResult | null>(null);
  const [agentPromptPreview, setAgentPromptPreview] =
    useState<AgentPromptPreview | null>(null);
  const [newName, setNewName] = useState("");
  const [newObjective, setNewObjective] = useState("");
  const [newMessage, setNewMessage] = useState("");
  const [byokProvider, setByokProvider] = useState<ByokProvider>("qwen");
  const [byokModel, setByokModel] = useState("qwen3.5-flash");
  const [byokKey, setByokKey] = useState("");
  const [byokBaseUrl, setByokBaseUrl] = useState("");
  const [projectQuery, setProjectQuery] = useState("");
  const [panelOpen, setPanelOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState<"none" | "left" | "right">("none");
  const chatEnd = useRef<HTMLDivElement>(null);

  const refreshFreeTier = useCallback(async () => {
    try {
      const status = await api.freeTierStatus();
      setFreeTier(status);
    } catch {
      setFreeTier(null);
    }
  }, []);

  const refreshList = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
  }, []);

  const loadProject = useCallback(async (id: string) => {
    const p = await api.getProject(id);
    setProject(p);
    const r = await api.getReadiness(id);
    setReadiness(r);
    setLimitations([]);
    setProviderStatus(null);
    setFundingSource(null);
    setMobileNav("none");
  }, []);

  useEffect(() => {
    if (authLoading) return;
    const boot = async () => {
      await refreshFreeTier();
      try {
        await refreshList();
      } catch (e) {
        setError(String(e));
      }
    };
    void boot();
  }, [authLoading, user?.id, refreshFreeTier, refreshList]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [project?.messages]);

  async function logout() {
    setProject(null);
    setProjects([]);
    await authLogout();
    void refreshFreeTier();
    navigate("/login");
  }

  async function handleByok(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.upsertByok({
        provider: byokProvider,
        api_key: byokKey.trim(),
        model: byokModel.trim(),
        base_url: byokBaseUrl.trim() || undefined,
        set_active: true,
      });
      setByokKey("");
      setShowByok(false);
      await refreshFreeTier();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createProject({
        name: newName.trim(),
        objective: newObjective.trim() || undefined,
        initial_message: newMessage.trim() || undefined,
      });
      setShowCreate(false);
      setNewName("");
      setNewObjective("");
      setNewMessage("");
      await refreshList();
      await loadProject(p.id);
      await refreshFreeTier();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    if (!project || !draft.trim() || busy) return;
    setBusy(true);
    setError(null);
    const content = draft.trim();
    setDraft("");
    try {
      // Mode is resolved internally — do not send an explicit activation mode
      const res = await api.sendMessage(project.id, content);
      setProject(res.project);
      setReadiness(res.readiness);
      setLimitations(res.review_limitations);
      setProviderStatus(res.provider_status);
      setFundingSource(res.funding_source);
      if (res.free_tier) setFreeTier(res.free_tier);
      else await refreshFreeTier();
      await refreshList();
    } catch (err) {
      setError(String(err));
      setDraft(content);
      await refreshFreeTier();
    } finally {
      setBusy(false);
    }
  }

  async function updateFinding(findingId: string, status: FindingStatus) {
    if (!project) return;
    setBusy(true);
    try {
      await api.updateFinding(project.id, findingId, status);
      await loadProject(project.id);
      await refreshList();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function exportSpec() {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.generateSpec(project.id);
      setSpec(result);
      setReadiness(result.readiness);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function openAgentPrompt() {
    setAgentPromptResult(null);
    setAgentPromptPreview(null);
    setShowAgentPrompt(true);
  }

  async function previewAgentSkills(opts: {
    task: string;
    agent: CodingAgent;
    includeSkills: boolean;
  }) {
    if (!project) return;
    try {
      const preview = await api.previewAgentPromptSkills(project.id, {
        task: opts.task || undefined,
      });
      setAgentPromptPreview(preview);
      setReadiness(preview.readiness);
    } catch (err) {
      setError(String(err));
    }
  }

  async function generateAgentPrompt(opts: {
    task: string;
    agent: CodingAgent;
    force: boolean;
    includeSkills: boolean;
    refineNotes: string;
  }) {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.generateAgentPrompt(project.id, {
        task: opts.task || undefined,
        agent: opts.agent,
        force: opts.force,
        include_skills: opts.includeSkills,
        refine_notes: opts.refineNotes || undefined,
      });
      setAgentPromptResult(result);
      setReadiness(result.readiness);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function openCreateWithExample(name: string, idea: string) {
    setNewName(name);
    setNewMessage(idea);
    setNewObjective("");
    setShowCreate(true);
  }

  const openFindings = project?.findings.filter((f) => f.status === "open") ?? [];
  const freeTierEnabled = freeTier?.enabled === true;
  const needsAuth = freeTierEnabled && !user;
  const needsByok = freeTier?.requires_byok === true && !freeTier.byok_configured;
  const followUps =
    readiness?.unblock_actions?.slice(0, 3) ??
    (project
      ? ["Clarify target users", "List must-have features", "Confirm the tech stack"]
      : []);

  return (
    <div
      className={`app ${sidebarCollapsed ? "sidebar-is-collapsed" : ""} ${
        panelOpen && project ? "panel-open" : "panel-closed"
      }`}
    >
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
          projects={projects}
          activeId={project?.id ?? null}
          user={user}
          freeTier={freeTier}
          fundingSource={fundingSource}
          projectQuery={projectQuery}
          needsAuth={needsAuth}
          needsByok={needsByok}
          onQueryChange={setProjectQuery}
          onSelectProject={(id) => void loadProject(id)}
          onNewProject={() => setShowCreate(true)}
          onOpenByok={() => setShowByok(true)}
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
              Readiness
            </button>
          )}
        </div>

        {needsAuth || !project ? (
          <Welcome
            allocated={freeTier?.allocated ?? 20}
            needsAuth={needsAuth}
            onStart={() => setShowCreate(true)}
            onRegister={() => navigate("/signup")}
            onPickExample={openCreateWithExample}
          />
        ) : (
          <>
            <header className="main-header">
              <div>
                <h2>{project.name}</h2>
                <p className="muted header-sub">
                  {project.objective || "No objective yet — describe the product."}
                </p>
              </div>
              <div className="header-actions">
                <button
                  className="btn btn-ghost btn-sm"
                  type="button"
                  onClick={() => setPanelOpen((v) => !v)}
                >
                  {panelOpen ? "Hide readiness" : "Show readiness"}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => void exportSpec()}
                  disabled={busy}
                >
                  Export spec
                </button>
                <button
                  className={
                    readiness?.implementation_ready ? "btn btn-sm" : "btn btn-ghost"
                  }
                  type="button"
                  onClick={() => openAgentPrompt()}
                  disabled={busy}
                  title={
                    readiness?.implementation_ready
                      ? "Project is implementation-ready — generate an agent prompt"
                      : "Generate prompt (blocked until checklist is complete, unless forced)"
                  }
                >
                  Agent prompt
                  {readiness?.implementation_ready ? " · ready" : ""}
                </button>
              </div>
            </header>

            {providerStatus && (
              <div className="provider-status" title={providerStatus}>
                {providerStatus}
                {fundingSource ? ` · Funding: ${fundingSource}` : ""}
              </div>
            )}
            {limitations.length > 0 && (
              <div className="banner warn">{limitations.join(" · ")}</div>
            )}
            {error && <div className="banner danger">{error}</div>}
            {needsByok && (
              <div className="banner warn">
                Free generations exhausted.{" "}
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => setShowByok(true)}
                >
                  Configure BYOK
                </button>
              </div>
            )}

            <div className="chat">
              {project.messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  onCopy={(content) => void navigator.clipboard.writeText(content)}
                />
              ))}
              {busy && (
                <div className="msg msg-assistant thinking" aria-live="polite">
                  <div className="msg-meta">
                    <span className="msg-role">VibePrompt</span>
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
                      onClick={() => setDraft(tip)}
                    >
                      {tip}
                    </button>
                  ))}
                </div>
              )}
              <div ref={chatEnd} />
            </div>

            <Composer
              draft={draft}
              busy={busy}
              disabled={needsByok}
              onDraftChange={setDraft}
              onSubmit={(e) => void sendMessage(e)}
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
            readiness={readiness}
            findings={openFindings}
            decisions={project.decisions}
            busy={busy}
            onUpdateFinding={(id, status) => void updateFinding(id, status)}
            onClose={() => {
              setPanelOpen(false);
              setMobileNav("none");
            }}
          />
        </div>
      )}

      {showCreate && (
        <CreateProjectModal
          name={newName}
          objective={newObjective}
          message={newMessage}
          busy={busy}
          onName={setNewName}
          onObjective={setNewObjective}
          onMessage={setNewMessage}
          onClose={() => setShowCreate(false)}
          onSubmit={(e) => void handleCreate(e)}
        />
      )}

      {showByok && (
        <ByokModal
          provider={byokProvider}
          model={byokModel}
          apiKey={byokKey}
          baseUrl={byokBaseUrl}
          remaining={freeTier?.remaining ?? null}
          allocated={freeTier?.allocated ?? null}
          connected={Boolean(freeTier?.byok_configured)}
          busy={busy}
          onProvider={(p, model) => {
            setByokProvider(p);
            setByokModel(model);
          }}
          onModel={setByokModel}
          onKey={setByokKey}
          onBaseUrl={setByokBaseUrl}
          onClose={() => setShowByok(false)}
          onSubmit={(e) => void handleByok(e)}
        />
      )}

      {spec && <SpecModal spec={spec} onClose={() => setSpec(null)} />}

      {showAgentPrompt && project && (
        <AgentPromptModal
          readiness={readiness}
          busy={busy}
          result={agentPromptResult}
          preview={agentPromptPreview}
          onClose={() => {
            setShowAgentPrompt(false);
            setAgentPromptResult(null);
          }}
          onPreview={(opts) => void previewAgentSkills(opts)}
          onGenerate={(opts) => void generateAgentPrompt(opts)}
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
