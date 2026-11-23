import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useProjects } from "./useProjects";

vi.mock("../api/client", () => ({
  api: {
    listProjects: vi.fn().mockResolvedValue([]),
    createProject: vi.fn(),
    getProject: vi.fn(),
    getReadiness: vi.fn(),
  },
}));

import { api } from "../api/client";

describe("useProjects create flow", () => {
  beforeEach(() => {
    vi.mocked(api.createProject).mockReset();
    vi.mocked(api.getProject).mockReset();
    vi.mocked(api.getReadiness).mockReset();
    vi.mocked(api.listProjects).mockResolvedValue([]);
  });

  it("creates a project then loads it", async () => {
    vi.mocked(api.createProject).mockResolvedValue({
      id: "p1",
      name: "Alpha",
    } as never);
    vi.mocked(api.getProject).mockResolvedValue({
      id: "p1",
      name: "Alpha",
      messages: [],
      findings: [],
    } as never);
    vi.mocked(api.getReadiness).mockResolvedValue({
      ready: false,
      status: "not_ready",
      blockers: [],
      warnings: [],
      missing_essentials: [],
      accepted_risk_summaries: [],
      unblock_actions: [],
      score_pct: 10,
      implementation_ready: false,
    } as never);

    const refreshFreeTier = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useProjects({
        refreshFreeTier,
        setBusy: vi.fn(),
        setError: vi.fn(),
        setMobileNav: vi.fn(),
      })
    );

    act(() => {
      result.current.setNewName("Alpha");
      result.current.setNewObjective("Ship Grill");
    });

    await act(async () => {
      await result.current.handleCreate({
        preventDefault() {},
      } as unknown as React.FormEvent);
    });

    expect(api.createProject).toHaveBeenCalledWith({
      name: "Alpha",
      objective: "Ship Grill",
      initial_message: undefined,
    });
    expect(api.getProject).toHaveBeenCalledWith("p1");
    expect(result.current.project?.id).toBe("p1");
    expect(refreshFreeTier).toHaveBeenCalled();
  });
});
