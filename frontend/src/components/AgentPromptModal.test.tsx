import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentPromptModal } from "./AgentPromptModal";
import type { ReadinessResult } from "../types";

const notReady: ReadinessResult = {
  ready: false,
  status: "not_ready",
  blockers: ["checklist incomplete"],
  warnings: [],
  missing_essentials: [],
  accepted_risk_summaries: [],
  unblock_actions: [],
  score_pct: 67,
  implementation_ready: false,
  checklist: [
    {
      id: "c1",
      label: "Tech stack locked",
      category: "mandatory",
      present: false,
      detail: "missing",
    },
    {
      id: "c2",
      label: "Objective set",
      category: "mandatory",
      present: true,
      detail: "ok",
    },
  ],
};

const ready: ReadinessResult = {
  ...notReady,
  ready: true,
  status: "ready",
  blockers: [],
  score_pct: 100,
  implementation_ready: true,
  checklist: notReady.checklist?.map((c) => ({ ...c, present: true })),
};

describe("AgentPromptModal export lock", () => {
  it("keeps Generate disabled until Force generate is checked when not ready", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(
      <AgentPromptModal
        readiness={notReady}
        busy={false}
        result={null}
        preview={null}
        onClose={vi.fn()}
        onPreview={vi.fn()}
        onGenerate={onGenerate}
      />
    );

    const generate = screen.getByRole("button", { name: /Generate prompt/i });
    expect(generate).toBeDisabled();

    await user.click(
      screen.getByRole("checkbox", {
        name: /Force generate despite incomplete Readiness Gate/i,
      })
    );
    expect(
      screen.getByRole("button", { name: /Force generate prompt/i })
    ).toBeEnabled();
  });

  it("enables Generate when implementation_ready", () => {
    render(
      <AgentPromptModal
        readiness={ready}
        busy={false}
        result={null}
        preview={null}
        onClose={vi.fn()}
        onPreview={vi.fn()}
        onGenerate={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: /^Generate prompt$/i })).toBeEnabled();
  });
});
