import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useChat } from "./useChat";
import type { ProjectState } from "../types";

vi.mock("../api/client", () => ({
  api: {
    sendMessage: vi.fn(),
  },
  type: {},
}));

import { api, type ApiError } from "../api/client";

const project = {
  id: "proj_1",
  name: "Demo",
  messages: [],
  findings: [],
  behavioural_mode: "grill_review",
} as unknown as ProjectState;

describe("useChat BYOK modal on 429", () => {
  beforeEach(() => {
    vi.mocked(api.sendMessage).mockReset();
  });

  it("opens BYOK modal when sendMessage hits quota exhaustion", async () => {
    const setShowByok = vi.fn();
    const setOfflineReview = vi.fn();
    const err = new Error("Free tier exhausted") as ApiError;
    err.status = 429;
    err.quotaExhausted = true;
    err.code = "free_tier_exhausted";
    vi.mocked(api.sendMessage).mockRejectedValue(err);

    const { result } = renderHook(() =>
      useChat({
        project,
        setProject: vi.fn(),
        setReadiness: vi.fn(),
        setLimitations: vi.fn(),
        setProviderStatus: vi.fn(),
        setFundingSource: vi.fn(),
        setOfflineReview,
        setFreeTier: vi.fn(),
        refreshFreeTier: vi.fn().mockResolvedValue(undefined),
        refreshList: vi.fn().mockResolvedValue(undefined),
        loadProject: vi.fn().mockResolvedValue(undefined),
        setShowByok,
        busy: false,
        setBusy: vi.fn(),
        setError: vi.fn(),
      })
    );

    act(() => {
      result.current.setDraft("Ship it");
    });

    await act(async () => {
      await result.current.sendMessage({
        preventDefault() {},
      } as unknown as React.FormEvent);
    });

    expect(setShowByok).toHaveBeenCalledWith(true);
  });
});
