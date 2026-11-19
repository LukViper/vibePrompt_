import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContextPanel } from "./ContextPanel";
import type { Finding, ReadinessResult } from "../types";

const readiness: ReadinessResult = {
  ready: false,
  status: "not_ready",
  blockers: ["Missing tech stack"],
  warnings: [],
  missing_essentials: ["success criteria"],
  accepted_risk_summaries: [],
  unblock_actions: ["Confirm stack"],
  score_pct: 40,
  implementation_ready: false,
};

const finding: Finding = {
  id: "fnd_1",
  title: "Dual-stack contradiction",
  challenged_claim: "SQLite and Vercel serverless conflict",
  reasoning: "Write model mismatch",
  evidence: ["prior decision"],
  assumptions_to_verify: [],
  severity: "critical",
  confidence: 0.9,
  potential_impact: "data loss",
  recommended_next_step: "Pick one deployment model",
  provenance: "deterministic",
  critic_outcome: null,
  critic_notes: null,
  status: "open",
  invalidation_criteria: "",
  kind: "blocking_contradiction",
  resolution_note: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ContextPanel finding resolution", () => {
  it("requires an evidence note before resolve is enabled", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ContextPanel
        readiness={readiness}
        findings={[finding]}
        decisions={[]}
        techStack={["SQLite"]}
        rejectedApproaches={[]}
        busy={false}
        onUpdateFinding={onUpdate}
        onExportAgent={vi.fn()}
      />
    );

    expect(screen.getByText(/Export Agent Spec/i)).toBeDisabled();
    const resolve = screen.getByRole("button", { name: /Resolve w\/ evidence/i });
    expect(resolve).toBeDisabled();

    await user.type(
      screen.getByLabelText(/Resolution evidence note/i),
      "Migrated API off Vercel; evidence in manifest"
    );
    expect(resolve).toBeEnabled();
    await user.click(resolve);
    expect(onUpdate).toHaveBeenCalledWith(
      "fnd_1",
      "resolved",
      "Migrated API off Vercel; evidence in manifest"
    );
  });

  it("shows locked and rejected stack badges", () => {
    render(
      <ContextPanel
        readiness={readiness}
        findings={[]}
        decisions={[]}
        techStack={["SQLite"]}
        rejectedApproaches={[
          {
            id: "rej_1",
            approach: "Vercel API",
            reason: "multi-writer",
            created_at: "2026-01-01T00:00:00Z",
          },
        ]}
        busy={false}
        onUpdateFinding={vi.fn()}
        onExportAgent={vi.fn()}
      />
    );
    expect(screen.getAllByText(/SQLite: LOCKED/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Vercel API: REJECTED/i)).toBeInTheDocument();
  });
});
