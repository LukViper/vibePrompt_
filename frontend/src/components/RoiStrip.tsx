import type { CSSProperties } from "react";

export type RoiDashboard = {
  findings_blocked_from_implementation: number;
  readiness_gate_passes: number;
  readiness_gate_pass_rate: number;
  estimated_tokens_saved: number;
  agent_runs_before: number;
  agent_runs_after: number;
};

type Props = {
  roi: RoiDashboard | null;
  loading?: boolean;
};

const wrap: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: "0.65rem",
  padding: "0.65rem 0.85rem",
  borderBottom: "1px solid var(--hairline)",
  background: "var(--panel)",
};

const cell: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.15rem",
  minWidth: 0,
};

const label: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.625rem",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "var(--ink-faint)",
};

const value: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.9375rem",
  color: "var(--ink)",
  fontVariantNumeric: "tabular-nums",
};

export function RoiStrip({ roi, loading }: Props) {
  if (loading) {
    return (
      <div className="roi-strip" style={wrap} aria-busy="true">
        <span style={label}>Loading ROI…</span>
      </div>
    );
  }
  if (!roi) return null;
  const rate = Math.round((roi.readiness_gate_pass_rate || 0) * 100);
  return (
    <div className="roi-strip" style={wrap} role="region" aria-label="Grill ROI">
      <div style={cell}>
        <span style={label}>Tokens saved (est.)</span>
        <strong style={value}>{roi.estimated_tokens_saved.toLocaleString()}</strong>
      </div>
      <div style={cell}>
        <span style={label}>Findings blocked</span>
        <strong style={value}>{roi.findings_blocked_from_implementation}</strong>
      </div>
      <div style={cell}>
        <span style={label}>Gate pass rate</span>
        <strong style={value}>{rate}%</strong>
      </div>
      <div style={cell}>
        <span style={label}>Agent runs before → after</span>
        <strong style={value}>
          {roi.agent_runs_before} → {roi.agent_runs_after}
        </strong>
      </div>
    </div>
  );
}
