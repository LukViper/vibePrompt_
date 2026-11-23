import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { ensureGuestToken, parseError, setGuestToken, clearGuestToken } from "./client";

describe("parseError BYOK / quota contract", () => {
  it("marks 429 as quotaExhausted for BYOK modal trigger", () => {
    const err = parseError(
      { status: 429 } as Response,
      JSON.stringify({ detail: { message: "Slow down", code: "rate_limited" } })
    );
    expect(err.status).toBe(429);
    expect(err.code).toBe("rate_limited");
    expect(err.quotaExhausted).toBe(true);
  });

  it("marks free_tier_exhausted and byok_required as quotaExhausted", () => {
    for (const code of ["free_tier_exhausted", "byok_required"]) {
      const err = parseError(
        { status: 402 } as Response,
        JSON.stringify({ detail: { message: "Need key", code } })
      );
      expect(err.quotaExhausted).toBe(true);
      expect(err.code).toBe(code);
    }
  });

  it("does not flag ordinary 500s as quota exhaustion", () => {
    const err = parseError(
      { status: 500 } as Response,
      JSON.stringify({ detail: { message: "boom", code: "server_error" } })
    );
    expect(err.quotaExhausted).toBe(false);
  });

  it("explains empty-body 405 as unreachable API", () => {
    const err = parseError({ status: 405 } as Response, "");
    expect(err.status).toBe(405);
    expect(err.code).toBe("api_unreachable");
    expect(err.message).toMatch(/VITE_API_BASE_URL/);
  });

  it("explains Vercel NOT_FOUND 404 as unreachable API", () => {
    const err = parseError(
      { status: 404 } as Response,
      "The page could not be found\nNOT_FOUND\nbom1::abc-123"
    );
    expect(err.status).toBe(404);
    expect(err.code).toBe("api_unreachable");
    expect(err.message).toMatch(/VITE_API_BASE_URL/);
  });
});

describe("ensureGuestToken", () => {
  beforeEach(() => {
    clearGuestToken();
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearGuestToken();
  });

  it("mints and stores a guest JWT", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ access_token: "guest.jwt.token" }),
      })
    );
    const token = await ensureGuestToken();
    expect(token).toBe("guest.jwt.token");
    expect(sessionStorage.getItem("vibeprompt_guest_token")).toBe("guest.jwt.token");
  });

  it("reuses an existing guest token without refetch", async () => {
    setGuestToken("existing.guest");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const token = await ensureGuestToken();
    expect(token).toBe("existing.guest");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
