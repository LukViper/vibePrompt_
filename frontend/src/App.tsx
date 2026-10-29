import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type {
  FindingStatus,
  ProjectState,
  ProjectSummary,
  ReadinessResult,
  SpecificationResult,
} from "./types";

function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectState | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResult | null>(null);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [providerStatus, setProviderStatus] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [spec, setSpec] = useState<SpecificationResult | null>(null);
  const [newName, setNewName] = useState("");
  const [newObjective, setNewObjective] = useState("");
  const [newMessage, setNewMessage] = useState("");
  const chatEnd = useRef<HTMLDivElement>(null);

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
  }, []);

  useEffect(() => {
    refreshList().catch((e) => setError(String(e)));
  }, [refreshList]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [project?.messages]);

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
      const res = await api.sendMessage(project.id, content);
      setProject(res.project);
      setReadiness(res.readiness);
      setLimitations(res.review_limitations);
      setProviderStatus(res.provider_status);
      await refreshList();
    } catch (err) {
      setError(String(err));
      setDraft(content);
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

  const openFindings = project?.findings.filter((f) => f.status === "open") ?? [];

  return (
    <div className="app">
      <aside className="sidebar">
        <p className="brand">VibePrompt</p>
        <p className="brand-sub">Invisible Grill — challenge before you build</p>
        <button className="btn" type="button" onClick={() => setShowCreate(true)}>
          New project
        </button>
        <ul className="project-list">
          {projects.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className={`project-item ${project?.id === p.id ? "active" : ""}`}
                onClick={() => loadProject(p.id)}
              >
                <span className="name">{p.name}</span>
                <span className="meta">
                  {p.open_finding_count} open · {p.message_count} msgs
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="main">
        {!project ? (
          <div className="empty-state">
            <h2>Grill your idea before the agents do</h2>
            <p className="muted">
              Create a project and describe what you want to build. Grill challenges weak
              assumptions with evidence — not noise.
            </p>
            <button className="btn" type="button" onClick={() => setShowCreate(true)}>
              Start a review
            </button>
          </div>
        ) : (
          <>
            <header className="main-header">
              <div>
                <h2>{project.name}</h2>
                <p className="muted" style={{ margin: "0.2rem 0 0", fontSize: "0.85rem" }}>
                  {project.objective || "No objective yet — describe the product."}
                </p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={exportSpec} disabled={busy}>
                Export spec
              </button>
            </header>
            {providerStatus && (
              <div className="provider-status" title={providerStatus}>
                {providerStatus}
              </div>
            )}
            {limitations.length > 0 && (
              <div className="limitations">{limitations.join(" · ")}</div>
            )}
            {error && <div className="limitations">{error}</div>}
            <div className="chat">
              {project.messages.map((m) => (
                <div key={m.id} className={`bubble ${m.role}`}>
                  <div className="role">{m.role === "user" ? "You" : "Grill"}</div>
                  <div className="content">{m.content}</div>
                  {m.role === "assistant" && m.provenance === "two_model" && (
                    <div className="provenance">Reviewed with an independent critic model</div>
                  )}
                  {m.role === "assistant" && m.provenance === "primary_only" && (
                    <div className="provenance">Primary review only</div>
                  )}
                </div>
              ))}
              <div ref={chatEnd} />
            </div>
            <form className="composer" onSubmit={sendMessage}>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Describe a decision, constraint, or new evidence…"
                rows={2}
                disabled={busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendMessage(e);
                  }
                }}
              />
              <button className="btn" type="submit" disabled={busy || !draft.trim()}>
                {busy ? "…" : "Send"}
              </button>
            </form>
          </>
        )}
      </main>

      <aside className="right-panel">
        <section className="panel-section">
          <h3>Readiness</h3>
          {readiness ? (
            <>
              <span className={`readiness-badge ${readiness.status}`}>
                {readiness.status.replace(/_/g, " ")}
              </span>
              {readiness.blockers.length > 0 && (
                <>
                  <p className="muted" style={{ marginBottom: "0.35rem" }}>
                    Blockers
                  </p>
                  <ul className="list-tight">
                    {readiness.blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </>
              )}
              {readiness.missing_essentials.length > 0 && (
                <>
                  <p className="muted" style={{ margin: "0.75rem 0 0.35rem" }}>
                    Missing
                  </p>
                  <ul className="list-tight">
                    {readiness.missing_essentials.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </>
              )}
              {readiness.unblock_actions.length > 0 && (
                <>
                  <p className="muted" style={{ margin: "0.75rem 0 0.35rem" }}>
                    To unblock
                  </p>
                  <ul className="list-tight">
                    {readiness.unblock_actions.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <p className="muted">Select a project</p>
          )}
        </section>

        <section className="panel-section">
          <h3>Open findings</h3>
          {openFindings.length === 0 && <p className="muted">No open findings</p>}
          {openFindings.map((f) => (
            <div key={f.id} className="finding-card">
              <p className="title">
                <span className={`sev ${f.severity}`}>{f.severity}</span>
                {f.title}
              </p>
              <p className="claim">{f.challenged_claim}</p>
              <p className="muted" style={{ fontSize: "0.75rem", margin: 0 }}>
                {f.recommended_next_step}
              </p>
              <div className="finding-actions">
                <button
                  className="btn btn-sm btn-ghost"
                  type="button"
                  onClick={() => updateFinding(f.id, "resolved")}
                >
                  Resolve
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  type="button"
                  onClick={() => updateFinding(f.id, "accepted_risk")}
                >
                  Accept risk
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  type="button"
                  onClick={() => updateFinding(f.id, "rejected")}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </section>

        {project && project.decisions.length > 0 && (
          <section className="panel-section">
            <h3>Decisions</h3>
            <ul className="list-tight">
              {project.decisions.map((d) => (
                <li key={d.id}>
                  <strong>{d.title}:</strong> {d.choice}
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>

      {showCreate && (
        <div className="modal-backdrop" onClick={() => setShowCreate(false)}>
          <form
            className="modal"
            onClick={(e) => e.stopPropagation()}
            onSubmit={handleCreate}
          >
            <h3>New project</h3>
            <label htmlFor="name">Name</label>
            <input
              id="name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
              autoFocus
            />
            <label htmlFor="objective">Objective (optional)</label>
            <textarea
              id="objective"
              rows={2}
              value={newObjective}
              onChange={(e) => setNewObjective(e.target.value)}
            />
            <label htmlFor="initial">Initial idea (optional)</label>
            <textarea
              id="initial"
              rows={3}
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              placeholder="Describe what you want to build…"
            />
            <div className="modal-actions">
              <button className="btn btn-ghost" type="button" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button className="btn" type="submit" disabled={busy}>
                Create
              </button>
            </div>
          </form>
        </div>
      )}

      {spec && (
        <div className="modal-backdrop" onClick={() => setSpec(null)}>
          <div className="modal spec-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Specification</h3>
            <span className={`readiness-badge ${spec.readiness.status}`}>
              {spec.readiness.status.replace(/_/g, " ")}
            </span>
            <pre>{spec.markdown}</pre>
            <div className="modal-actions">
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(spec.markdown);
                }}
              >
                Copy markdown
              </button>
              <button className="btn" type="button" onClick={() => setSpec(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
