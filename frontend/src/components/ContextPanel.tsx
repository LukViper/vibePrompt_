import type { Finding, FindingStatus, ReadinessResult } from "../types";

type Props = {
  readiness: ReadinessResult | null;
  findings: Finding[];
  decisions: { id: string; title: string; choice: string }[];
  busy: boolean;
  onUpdateFinding: (id: string, status: FindingStatus) => void;
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

export function ContextPanel({
  readiness,
  findings,
  decisions,
  busy,
  onUpdateFinding,
  onClose,
}: Props) {
  const pct = progressFromReadiness(readiness);

  return (
    <aside className="context-panel">
      <div className="context-panel-header">
        <h3>Project readiness</h3>
        {onClose && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Hide
          </button>
        )}
      </div>

      <section className="panel-section">
        {readiness ? (
          <>
            <span className={`readiness-badge ${readiness.status}`}>
              {readinessLabel(readiness.status)}
            </span>
            <div className="progress-block">
              <div className="progress-meta">
                <span>Definition progress</span>
                <strong>{pct}%</strong>
              </div>
              <div className="progress-track" aria-hidden>
                <div className="progress-fill" style={{ width: `${pct}%` }} />
              </div>
            </div>

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
                <p className="panel-label">Missing information</p>
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

            {readiness.unblock_actions.length > 0 && (
              <>
                <p className="panel-label">Suggested actions</p>
                <ul className="list-tight">
                  {readiness.unblock_actions.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </>
            )}

            {readiness.checklist && readiness.checklist.length > 0 && (
              <>
                <p className="panel-label">
                  Implementation checklist
                  {readiness.implementation_ready ? " · ready" : ""}
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
          <div key={f.id} className="finding-card">
            <p className="title">
              <span className={`sev ${f.severity}`}>{f.severity}</span>
              {f.title}
            </p>
            <p className="claim">{f.challenged_claim}</p>
            <p className="next-step">{f.recommended_next_step}</p>
            <div className="finding-actions">
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                disabled={busy}
                onClick={() => onUpdateFinding(f.id, "resolved")}
              >
                Resolve
              </button>
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                disabled={busy}
                onClick={() => onUpdateFinding(f.id, "accepted_risk")}
              >
                Accept risk
              </button>
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                disabled={busy}
                onClick={() => onUpdateFinding(f.id, "rejected")}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </section>

      {decisions.length > 0 && (
        <section className="panel-section">
          <h3>Decisions</h3>
          <ul className="list-tight">
            {decisions.map((d) => (
              <li key={d.id}>
                <strong>{d.title}:</strong> {d.choice}
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
