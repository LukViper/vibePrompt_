import { FormEvent, useEffect, useState } from "react";
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

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal spec-modal agent-prompt-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="spec-header">
          <h3>Generate agent prompt</h3>
          {readiness && (
            <span className={`readiness-badge ${readiness.status}`}>
              {implReady ? "implementation ready" : readiness.status.replace(/_/g, " ")}
              {typeof readiness.score_pct === "number" ? ` · ${score}%` : ""}
            </span>
          )}
        </div>

        <form onSubmit={handleGenerate} className="agent-prompt-form">
          <p className="muted">
            Book-informed prompts use project context, readiness checks, and retrieved
            skills. Score alone never unlocks generation — checklist and conflicts do.
          </p>

          {!implReady && (
            <div className="banner warn">
              Not implementation-ready yet. Resolve checklist gaps, or enable force after
              review.
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

          {readiness?.checklist && readiness.checklist.length > 0 && (
            <>
              <p className="panel-label">Readiness checklist</p>
              <ul className="list-tight checklist">
                {readiness.checklist.map((item) => (
                  <li key={item.id} className={item.present ? "ok" : "missing"}>
                    {item.present ? "✓" : "○"} {item.label}
                    <span className="muted"> · {item.category}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <label htmlFor="agent-family">Coding agent</label>
          <div className="agent-picker" role="radiogroup" aria-label="Coding agent">
            {AGENTS.map((a) => (
              <button
                key={a.id}
                type="button"
                className={`agent-chip ${agent === a.id ? "active" : ""}`}
                onClick={() => setAgent(a.id)}
                aria-pressed={agent === a.id}
              >
                <strong>{a.label}</strong>
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

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeSkills}
              onChange={(e) => setIncludeSkills(e.target.checked)}
            />
            Include Books-to-Skill retrieval
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            Force generate despite readiness/quality gates
          </label>

          {preview && includeSkills && (
            <section className="skill-preview">
              <p className="panel-label">
                Skills for {preview.task_class.replace(/_/g, " ")}
              </p>
              {preview.selected_slugs.length === 0 ? (
                <p className="muted">No skills selected (builtins unavailable or empty).</p>
              ) : (
                <ul className="list-tight">
                  {preview.selected_slugs.map((slug) => (
                    <li key={slug}>
                      <strong>{slug}</strong>
                      {preview.reasons[slug] ? (
                        <span className="muted"> — {preview.reasons[slug]}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              {preview.principles.length > 0 && (
                <>
                  <p className="panel-label">Retrieved principles</p>
                  <ul className="list-tight">
                    {preview.principles.slice(0, 6).map((p, idx) => (
                      <li key={`${p.title}-${idx}`}>
                        {p.title}
                        {p.source_book_id ? (
                          <span className="muted">
                            {" "}
                            [src:{p.source_book_id}
                            {p.chapter_ref ? `/${p.chapter_ref}` : ""}]
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )}

          <div className="modal-actions">
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
            <button className="btn" type="submit" disabled={busy}>
              {busy ? "Generating…" : "Generate prompt"}
            </button>
          </div>
        </form>

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
            <div className="modal-actions">
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
                  onGenerate({ task, agent, force: true, includeSkills, refineNotes })
                }
              >
                Regenerate
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
