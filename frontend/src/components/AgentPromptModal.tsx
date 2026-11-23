import { FormEvent, useEffect, useMemo, useState } from "react";
import { useEscapeKey } from "../hooks/useEscapeKey";
import type {
  AgentPromptPreview,
  AgentPromptResult,
  CodingAgent,
  ReadinessResult,
} from "../types";

type Props = {
  readiness: ReadinessResult | null;
  busy: boolean;
  result: AgentPromptResult | null;
  preview: AgentPromptPreview | null;
  onClose: () => void;
  onPreview: (opts: {
    task: string;
    agent: CodingAgent;
    includeSkills: boolean;
  }) => void;
  onGenerate: (opts: {
    task: string;
    agent: CodingAgent;
    force: boolean;
    includeSkills: boolean;
    refineNotes: string;
  }) => void;
};

const AGENTS: { id: CodingAgent; label: string; blurb: string }[] = [
  {
    id: "cursor",
    label: "Cursor",
    blurb: "Repo inspection, module boundaries, scoped diffs",
  },
  {
    id: "antigravity",
    label: "Antigravity",
    blurb: "Plan → implement → verify agentic loop",
  },
  {
    id: "codex",
    label: "Codex",
    blurb: "Goal, constraints, done-when completion criteria",
  },
];

function sortChecklist(items: NonNullable<ReadinessResult["checklist"]>) {
  return [...items].sort((a, b) => {
    const aMissingMandatory = !a.present && a.category === "mandatory" ? 0 : 1;
    const bMissingMandatory = !b.present && b.category === "mandatory" ? 0 : 1;
    if (aMissingMandatory !== bMissingMandatory) {
      return aMissingMandatory - bMissingMandatory;
    }
    if (a.present !== b.present) return a.present ? 1 : -1;
    const aMand = a.category === "mandatory" ? 0 : 1;
    const bMand = b.category === "mandatory" ? 0 : 1;
    if (aMand !== bMand) return aMand - bMand;
    return a.label.localeCompare(b.label);
  });
}

export function AgentPromptModal({
  readiness,
  busy,
  result,
  preview,
  onClose,
  onPreview,
  onGenerate,
}: Props) {
  const [agent, setAgent] = useState<CodingAgent>("cursor");
  const [task, setTask] = useState("");
  const [refineNotes, setRefineNotes] = useState("");
  const [includeSkills, setIncludeSkills] = useState(true);
  const [force, setForce] = useState(false);
  useEscapeKey(onClose);

  useEffect(() => {
    onPreview({ task, agent, includeSkills });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- preview on open / agent change
  }, [agent, includeSkills]);

  function handleGenerate(e: FormEvent) {
    e.preventDefault();
    onGenerate({ task, agent, force, includeSkills, refineNotes });
  }

  const implReady = readiness?.implementation_ready === true;
  const score = readiness?.score_pct ?? 0;
  const gateLocked = !implReady && !force;
  const canGenerate = !busy && !gateLocked;

  const sortedChecklist = useMemo(
    () => (readiness?.checklist ? sortChecklist(readiness.checklist) : []),
    [readiness?.checklist],
  );

  const generateLabel = busy
    ? "Generating…"
    : !implReady && force
      ? "Force generate prompt"
      : "Generate prompt";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal spec-modal agent-prompt-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="spec-header agent-prompt-header">
          <h3>Export Agent Spec</h3>
          {readiness && (
            <span className={`readiness-badge ${readiness.status}`}>
              {implReady ? "implementation ready" : readiness.status.replace(/_/g, " ")}
              {typeof readiness.score_pct === "number" ? ` · ${score}%` : ""}
            </span>
          )}
        </div>

        <form onSubmit={handleGenerate} className="agent-prompt-form">
          <div className="agent-prompt-scroll">
            <p className="muted">
              Cursor · Antigravity · Codex tabs unlock when the Readiness Gate passes.
              Skills retrieval is optional; checklist and conflicts gate export.
            </p>

            {!implReady && (
              <div className="banner warn">
                Readiness Gate incomplete. Resolve blockers, or enable force after review.
              </div>
            )}

            {readiness?.conflicts && readiness.conflicts.length > 0 && (
              <>
                <p className="panel-label danger">Conflicts</p>
                <ul className="list-tight">
                  {readiness.conflicts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            )}

            {sortedChecklist.length > 0 && (
              <>
                <p className="panel-label">Readiness checklist</p>
                <ul className="list-tight checklist readiness-checklist-grid">
                  {sortedChecklist.map((item) => (
                    <li key={item.id} className={item.present ? "ok" : "missing"}>
                      <span className="checklist-mark" aria-hidden="true">
                        {item.present ? "✓" : "○"}
                      </span>
                      <span className="checklist-copy">
                        {item.label}
                        <span className="muted"> · {item.category}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            <label htmlFor="agent-family">Coding agent</label>
            <div
              className={`agent-picker ${gateLocked ? "gate-locked" : ""}`}
              role="radiogroup"
              aria-label="Coding agent"
            >
              {AGENTS.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={`agent-chip ${agent === a.id ? "active" : ""}`}
                  onClick={() => setAgent(a.id)}
                  aria-pressed={agent === a.id}
                  disabled={gateLocked}
                >
                  <strong>
                    {a.label}
                    {gateLocked ? <span className="agent-lock-badge">locked</span> : null}
                  </strong>
                  <span>{a.blurb}</span>
                </button>
              ))}
            </div>

            <label htmlFor="agent-task">Task (optional)</label>
            <textarea
              id="agent-task"
              rows={2}
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="e.g. Implement EVTX ingest endpoint with SQLite storage"
            />

            <label htmlFor="agent-refine">Refine notes (optional)</label>
            <textarea
              id="agent-refine"
              rows={2}
              value={refineNotes}
              onChange={(e) => setRefineNotes(e.target.value)}
              placeholder="Extra constraints for regeneration…"
            />

            <div className="toggle-stack">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={includeSkills}
                  onChange={(e) => setIncludeSkills(e.target.checked)}
                />
                <span className="toggle-copy">
                  <span className="toggle-title">Include Books-to-Skill retrieval</span>
                  <span className="toggle-desc">
                    Inject retrieved principles from the 6 active knowledge skills into the
                    exported spec.
                  </span>
                </span>
              </label>

              <label className={`toggle-row ${force ? "force-on" : ""}`}>
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                />
                <span className="toggle-copy">
                  <span className="toggle-title">
                    Force generate despite incomplete Readiness Gate
                  </span>
                  <span className="toggle-desc">
                    Override blockers and export an unverified draft prompt.
                  </span>
                </span>
              </label>
            </div>

            {preview && includeSkills && (
              <section className="skill-preview">
                <p className="panel-label">
                  Skills for {preview.task_class.replace(/_/g, " ")}
                </p>
                {preview.selected_slugs.length === 0 ? (
                  <p className="muted">No skills selected (builtins unavailable or empty).</p>
                ) : (
                  <div className="skill-pill-row">
                    {preview.selected_slugs.map((slug) => (
                      <span
                        key={slug}
                        className="skill-pill"
                        title={preview.reasons[slug] || undefined}
                      >
                        {slug}
                      </span>
                    ))}
                  </div>
                )}
                {preview.principles.length > 0 && (
                  <>
                    <p className="panel-label">Retrieved principles</p>
                    <div className="skill-pill-row">
                      {preview.principles.slice(0, 6).map((p, idx) => (
                        <span
                          key={`${p.title}-${idx}`}
                          className="skill-pill principle"
                          title={
                            p.source_book_id
                              ? `src:${p.source_book_id}${p.chapter_ref ? `/${p.chapter_ref}` : ""}`
                              : undefined
                          }
                        >
                          {p.title}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </section>
            )}

            {result && (
              <div className="agent-prompt-result">
                <div className="spec-header">
                  <h3>
                    {result.agent || agent} prompt
                    {result.blocked ? " (blocked)" : ""}
                  </h3>
                  {result.quality && (
                    <span
                      className={`readiness-badge ${
                        result.quality.passed ? "ready" : "not_ready"
                      }`}
                    >
                      quality {result.quality.score_pct}%
                    </span>
                  )}
                </div>
                {result.warnings && result.warnings.length > 0 && (
                  <div className="banner warn">{result.warnings.slice(0, 4).join(" · ")}</div>
                )}
                {result.skill_reasons && Object.keys(result.skill_reasons).length > 0 && (
                  <p className="muted">
                    Skills:{" "}
                    {Object.entries(result.skill_reasons)
                      .map(([s, r]) => `${s} (${r})`)
                      .join(", ")}
                  </p>
                )}
                <pre>{result.prompt}</pre>
                <div className="modal-actions result-actions">
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(result.prompt)}
                  >
                    Copy prompt
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onGenerate({
                        task,
                        agent,
                        force: true,
                        includeSkills,
                        refineNotes,
                      })
                    }
                  >
                    Regenerate
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="modal-actions agent-prompt-footer">
            {gateLocked && (
              <p className="gate-hint">
                Resolve readiness blockers or enable Force generate to unlock export.
              </p>
            )}
            <div className="modal-actions-row">
              <button className="btn btn-ghost" type="button" onClick={onClose}>
                Close
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                disabled={busy}
                onClick={() => onPreview({ task, agent, includeSkills })}
              >
                Refresh skills
              </button>
              <button
                className={`btn ${!implReady && force ? "btn-force" : ""}`}
                type="submit"
                disabled={!canGenerate}
              >
                {generateLabel}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
