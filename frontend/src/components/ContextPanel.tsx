import { useState } from "react";
import type {
  Finding,
  FindingStatus,
  ReadinessResult,
  RejectedApproach,
} from "../types";

type Props = {
  readiness: ReadinessResult | null;
  findings: Finding[];
  decisions: { id: string; title: string; choice: string }[];
  techStack: string[];
  rejectedApproaches: RejectedApproach[];
  busy: boolean;
  onUpdateFinding: (id: string, status: FindingStatus, note?: string) => void;
  onExportAgent: () => void;
  onClose?: () => void;
};

function readinessLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function progressFromReadiness(r: ReadinessResult | null): number {
  if (!r) return 0;
  if (typeof r.score_pct === "number") return Math.max(0, Math.min(100, r.score_pct));
  if (r.implementation_ready) return 100;
  if (r.ready) return 85;
  const missing = r.missing_essentials.length + r.blockers.length;
  return Math.max(12, Math.min(85, 70 - missing * 12));
}

function isBlocking(f: Finding): boolean {
  return (f.kind || "").trim().toLowerCase() === "blocking_contradiction";
}

function FindingCard({
  finding,
  busy,
  onUpdateFinding,
}: {
  finding: Finding;
  busy: boolean;
  onUpdateFinding: (id: string, status: FindingStatus, note?: string) => void;
}) {
  const [note, setNote] = useState("");
  const [expanded, setExpanded] = useState(isBlocking(finding));
  const blocking = isBlocking(finding);
  const noteOk = note.trim().length >= 8;

  return (
    <div className={`finding-card ${blocking ? "blocking-kind" : ""}`}>
      <button
        type="button"
        className="title"
        style={{
          width: "100%",
          textAlign: "left",
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          color: "inherit",
        }}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className={`sev ${finding.severity}`}>{finding.severity}</span>
        {finding.title}
        {blocking && (
          <span className="state-badge blocking" style={{ marginLeft: 6 }}>
            BLOCKING
          </span>
        )}
      </button>

      {expanded && (
        <>
          <p className="claim">{finding.challenged_claim}</p>
          {finding.reasoning && (
            <p className="next-step">{finding.reasoning}</p>
          )}
          {finding.recommended_next_step && (
            <p className="next-step" style={{ marginTop: 6 }}>
              Next: {finding.recommended_next_step}
            </p>
          )}
          {finding.evidence.length > 0 && (
            <>
              <p className="panel-label">Evidence on file</p>
              <ul className="list-tight">
                {finding.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          )}
          <p className="evidence-hint">
            {blocking
              ? "Evidence required — counterevidence note (state / artifact)"
              : "Resolution note required"}
          </p>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={
              blocking
                ? "e.g. Migrated API to single-node FastAPI; Vercel rejected superseded…"
                : "Describe evidence or resolution…"
            }
            aria-label="Resolution evidence note"
          />
          <div className="finding-actions">
            <button
              className="btn btn-sm"
              type="button"
              disabled={busy || !noteOk}
              onClick={() => onUpdateFinding(finding.id, "resolved", note.trim())}
            >
              Resolve w/ evidence
            </button>
            <button
              className="btn btn-sm btn-ghost"
              type="button"
              disabled={busy || !noteOk}
              onClick={() =>
                onUpdateFinding(finding.id, "accepted_risk", note.trim())
              }
            >
              Accept risk
            </button>
            {!blocking && (
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                disabled={busy || !noteOk}
                onClick={() =>
                  onUpdateFinding(finding.id, "rejected", note.trim())
                }
              >
                Reject finding
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function ContextPanel({
  readiness,
  findings,
  decisions,
  techStack,
  rejectedApproaches,
  busy,
  onUpdateFinding,
  onExportAgent,
  onClose,
}: Props) {
  const pct = progressFromReadiness(readiness);
  const blockerCount =
    (readiness?.blockers.length ?? 0) +
    findings.filter(isBlocking).length;
  const implReady = readiness?.implementation_ready === true;
  const blockingFinding = findings.find(isBlocking);

  return (
    <aside className="context-panel">
      <div className="context-panel-header">
        <h3>Project state</h3>
        {onClose && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Hide
          </button>
        )}
      </div>

      <section className="panel-section">
        <h3>Readiness Gate</h3>
        {readiness ? (
          <>
            <span className={`readiness-badge ${readiness.status}`}>
              {readinessLabel(readiness.status)}
            </span>
            <div className="progress-block">
              <div className="progress-meta">
                <span>
                  {blockerCount > 0
                    ? `${blockerCount} hard blocker${blockerCount === 1 ? "" : "s"}`
                    : "No hard blockers"}
                </span>
                <strong>{pct}%</strong>
              </div>
              <div className="progress-track" aria-hidden>
                <div
                  className={`progress-fill ${implReady ? "verified" : blockerCount ? "blocking" : ""}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>

            {blockingFinding && (
              <>
                <p className="panel-label danger">Active blocking_contradiction</p>
                <p className="muted" style={{ margin: "0 0 0.5rem", fontSize: "0.75rem" }}>
                  {blockingFinding.title}
                </p>
              </>
            )}

            {readiness.blockers.length > 0 && (
              <>
                <p className="panel-label danger">Blockers</p>
                <ul className="list-tight">
                  {readiness.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </>
            )}

            {readiness.missing_essentials.length > 0 && (
              <>
                <p className="panel-label">Missing</p>
                <ul className="list-tight">
                  {readiness.missing_essentials.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </>
            )}

            {readiness.conflicts && readiness.conflicts.length > 0 && (
              <>
                <p className="panel-label danger">Conflicts</p>
                <ul className="list-tight">
                  {readiness.conflicts.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </>
            )}

            {readiness.checklist && readiness.checklist.length > 0 && (
              <>
                <p className="panel-label">
                  Checklist{implReady ? " · ready" : ""}
                </p>
                <ul className="list-tight checklist">
                  {readiness.checklist.map((item) => (
                    <li key={item.id} className={item.present ? "ok" : "missing"}>
                      {item.present ? "✓" : "○"} {item.label}
                    </li>
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
        {findings.length === 0 && <p className="muted">No open findings</p>}
        {findings.map((f) => (
          <FindingCard
            key={f.id}
            finding={f}
            busy={busy}
            onUpdateFinding={onUpdateFinding}
          />
        ))}
      </section>

      <section className="panel-section">
        <h3>Stack manifest</h3>
        <div className="stack-manifest">
          {techStack.length === 0 && rejectedApproaches.length === 0 && (
            <p className="muted">No locked or rejected options yet</p>
          )}
          {techStack.map((t) => (
            <span key={t} className="state-badge locked">
              {t}: LOCKED
            </span>
          ))}
          {rejectedApproaches.map((r) => (
            <span key={r.id} className="state-badge rejected" title={r.reason}>
              {r.approach}: REJECTED
            </span>
          ))}
        </div>
        {decisions.length > 0 && (
          <>
            <p className="panel-label">Decisions</p>
            <ul className="list-tight">
              {decisions.map((d) => (
                <li key={d.id}>
                  <strong>{d.title}:</strong> {d.choice}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <div className="export-cta">
        <button
          type="button"
          className={`btn btn-block ${implReady ? "" : "btn-locked"}`}
          disabled={busy || !implReady}
          onClick={onExportAgent}
          title={
            implReady
              ? "Generate Cursor / Antigravity / Codex agent prompt"
              : "Locked until Readiness Gate passes"
          }
        >
          Export Agent Spec
        </button>
        <p className="hint">
          {implReady
            ? "Unlocked — Cursor · Antigravity · Codex"
            : "Disabled until Readiness Gate passes"}
        </p>
      </div>
    </aside>
  );
}
