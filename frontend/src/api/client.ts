import { Capacitor } from "@capacitor/core";
import type {
  AcquisitionReport,
  AuthConfigPublic,
  AuthResponse,
  BookPreview,
  BookRecord,
  ByokConfigPublic,
  ByokProvider,
  AgentPromptPreview,
  AgentPromptResult,
  BehaviouralMode,
  CatalogBook,
  ChatResponse,
  Finding,
  FindingStatus,
  FreeTierStatus,
  ProjectState,
  ProjectSummary,
  ReadinessResult,
  SkillPackage,
  SkillSummary,
  SpecificationResult,
  UserPublic,
} from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
const TOKEN_KEY = "vibeprompt_token";
const GUEST_TOKEN_KEY = "vibeprompt_guest_token";

/** Capacitor WebView has no Vite /api proxy — require an absolute API base. */
if (Capacitor.isNativePlatform() && !/^https?:\/\//i.test(BASE)) {
  console.error(
    "[VibePrompt] Set VITE_API_BASE_URL to an absolute https API URL before building the APK " +
      `(got "${BASE}"). Example: VITE_API_BASE_URL=https://api.example.com/api`,
  );
}

export type ApiError = Error & {
  status?: number;
  code?: string;
  body?: string;
  quotaExhausted?: boolean;
};

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(GUEST_TOKEN_KEY);
}

export function getUserToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
    sessionStorage.removeItem(GUEST_TOKEN_KEY);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function setGuestToken(token: string | null): void {
  if (token) sessionStorage.setItem(GUEST_TOKEN_KEY, token);
  else sessionStorage.removeItem(GUEST_TOKEN_KEY);
}

export function clearGuestToken(): void {
  sessionStorage.removeItem(GUEST_TOKEN_KEY);
}

let guestBootstrap: Promise<string | null> | null = null;

/** Ensure a short-lived guest JWT exists when no logged-in user token is present. */
export async function ensureGuestToken(): Promise<string | null> {
  if (getUserToken()) return getUserToken();
  const existing = sessionStorage.getItem(GUEST_TOKEN_KEY);
  if (existing) return existing;
  if (!guestBootstrap) {
    guestBootstrap = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/guest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        if (!res.ok) return null;
        const data = (await res.json()) as { access_token?: string };
        if (data.access_token) {
          setGuestToken(data.access_token);
          return data.access_token;
        }
      } catch {
        return null;
      } finally {
        guestBootstrap = null;
      }
      return null;
    })();
  }
  return guestBootstrap;
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(extra ?? {}),
  };
}

/** Exported for unit tests — maps HTTP failures to BYOK/quota UX flags. */
export function parseError(res: Response, detail: string): ApiError {
  let message = detail || `Request failed (${res.status})`;
  let code: string | undefined;
  try {
    const parsed = JSON.parse(detail) as {
      detail?: { message?: string; code?: string } | string;
    };
    if (typeof parsed.detail === "string") message = parsed.detail;
    else if (parsed.detail && typeof parsed.detail === "object") {
      if (parsed.detail.message) message = parsed.detail.message;
      if (parsed.detail.code) code = parsed.detail.code;
    }
  } catch {
    /* keep raw text */
  }
  // Empty-body 405 is typical when POST /api/* hits a static SPA host (e.g. Vercel)
  // instead of the FastAPI backend — usually missing VITE_API_BASE_URL.
  if (
    res.status === 405 &&
    (!detail || !detail.trim() || message === `Request failed (${res.status})`)
  ) {
    message =
      "API not reachable (405). Point VITE_API_BASE_URL at your FastAPI host " +
      "(include /api), or use the Vite/nginx proxy locally.";
    code = code || "api_unreachable";
  }
  const err = new Error(message) as ApiError;
  err.status = res.status;
  err.body = detail;
  err.code = code;
  err.quotaExhausted =
    res.status === 429 ||
    code === "rate_limited" ||
    code === "free_tier_exhausted" ||
    code === "byok_required" ||
    code === "guest_mint_rate_limited";
  return err;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getUserToken() && !sessionStorage.getItem(GUEST_TOKEN_KEY)) {
    await ensureGuestToken();
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(init?.headers),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    // One retry after minting a fresh guest token on auth failure
    if (
      res.status === 401 &&
      !getUserToken() &&
      path !== "/auth/guest"
    ) {
      clearGuestToken();
      const refreshed = await ensureGuestToken();
      if (refreshed) {
        const retry = await fetch(`${BASE}${path}`, {
          ...init,
          headers: {
            "Content-Type": "application/json",
            ...authHeaders(init?.headers),
          },
        });
        if (!retry.ok) {
          throw parseError(retry, await retry.text());
        }
        return retry.json() as Promise<T>;
      }
    }
    throw parseError(res, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authConfig: () => request<AuthConfigPublic>("/auth/config"),
  mintGuest: () =>
    request<{
      access_token: string;
      expires_in_minutes: number;
      generations_allocated: number;
      user: UserPublic;
    }>("/auth/guest", { method: "POST" }),
  syncProfile: (body?: {
    display_name?: string | null;
    avatar_url?: string | null;
    auth_provider?: string | null;
  }) =>
    request<UserPublic>("/auth/sync", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  register: (email: string, password: string) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  loginWithGoogle: (id_token: string) =>
    request<AuthResponse>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ id_token }),
    }),
  me: () => request<UserPublic>("/auth/me"),
  freeTierStatus: () => request<FreeTierStatus>("/free-tier/status"),
  listByok: () => request<ByokConfigPublic[]>("/byok"),
  upsertByok: (body: {
    provider: ByokProvider;
    api_key: string;
    model: string;
    base_url?: string;
    set_active?: boolean;
  }) =>
    request<ByokConfigPublic>("/byok", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listProjects: () => request<ProjectSummary[]>("/projects"),
  createProject: (body: {
    name: string;
    objective?: string;
    initial_message?: string;
  }) =>
    request<ProjectState>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getProject: (id: string) => request<ProjectState>(`/projects/${id}`),
  sendMessage: (id: string, content: string, behavioural_mode?: BehaviouralMode) =>
    request<ChatResponse>(`/projects/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({
        content,
        ...(behavioural_mode ? { behavioural_mode } : {}),
      }),
    }),
  updateFinding: (
    projectId: string,
    findingId: string,
    status: FindingStatus,
    note?: string
  ) =>
    request<Finding>(`/projects/${projectId}/findings/${findingId}`, {
      method: "PATCH",
      body: JSON.stringify({ status, note }),
    }),
  getReadiness: (id: string) => request<ReadinessResult>(`/projects/${id}/readiness`),
  generateSpec: (id: string) =>
    request<SpecificationResult>(`/projects/${id}/specification`, { method: "POST" }),
  getContext: (id: string) =>
    request<Record<string, unknown>>(`/projects/${id}/context`),
  updateContext: (id: string, body: Record<string, unknown>) =>
    request<{ applied: string[]; context: Record<string, unknown> }>(
      `/projects/${id}/context`,
      { method: "PATCH", body: JSON.stringify(body) }
    ),
  generateAgentPrompt: (
    id: string,
    opts?: {
      task?: string;
      force?: boolean;
      agent?: string;
      include_skills?: boolean;
      user_selected_skills?: string[];
      refine_notes?: string;
    }
  ) =>
    request<AgentPromptResult>(`/projects/${id}/agent-prompt`, {
      method: "POST",
      body: JSON.stringify({
        task: opts?.task ?? null,
        force: opts?.force ?? false,
        agent: opts?.agent ?? "cursor",
        include_skills: opts?.include_skills ?? true,
        user_selected_skills: opts?.user_selected_skills ?? [],
        refine_notes: opts?.refine_notes ?? null,
      }),
    }),
  previewAgentPromptSkills: (
    id: string,
    opts?: { task?: string; user_selected_skills?: string[] }
  ) =>
    request<AgentPromptPreview>(
      `/projects/${id}/agent-prompt/preview-skills`,
      {
        method: "POST",
        body: JSON.stringify({
          task: opts?.task ?? null,
          user_selected_skills: opts?.user_selected_skills ?? [],
        }),
      }
    ),
  health: () =>
    request<{ status: string; providers: Record<string, unknown> }>("/health"),

  knowledgeCatalog: () => request<CatalogBook[]>("/knowledge/catalog"),
  acquisitionReport: () => request<AcquisitionReport>("/knowledge/acquisition-report"),
  registerCatalogBook: (slug: string) =>
    request<BookRecord>(`/knowledge/catalog/${slug}/register`, { method: "POST" }),
  listKnowledgeBooks: (q?: string) =>
    request<BookRecord[]>(`/knowledge/books${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  getKnowledgeBook: (id: string) => request<BookPreview>(`/knowledge/books/${id}`),
  archiveKnowledgeBook: (id: string) =>
    request<BookRecord>(`/knowledge/books/${id}/archive`, { method: "POST" }),
  processKnowledgeBook: (id: string) =>
    request<Record<string, unknown>>(`/knowledge/books/${id}/process`, { method: "POST" }),
  uploadKnowledgeBook: async (form: FormData) => {
    await ensureGuestToken();
    const res = await fetch(`${BASE}/knowledge/books/upload`, {
      method: "POST",
      headers: {
        ...authHeaders(),
      },
      body: form,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw parseError(res, detail);
    }
    return res.json() as Promise<BookRecord>;
  },
  rightsConfirmation: () =>
    request<{ required_confirmation: string }>("/knowledge/rights-confirmation"),
  listSkills: () => request<SkillSummary[]>("/knowledge/skills"),
  getSkill: (id: string) => request<SkillPackage>(`/knowledge/skills/${id}`),
  generateSkill: (body: {
    book_ids: string[];
    target_slug?: string;
    target_skill_id?: string;
    name?: string;
  }) =>
    request<SkillPackage>("/knowledge/skills/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveSkill: (id: string, note?: string) =>
    request<SkillPackage>(`/knowledge/skills/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  rejectSkill: (id: string, note?: string) =>
    request<SkillPackage>(`/knowledge/skills/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  evaluateSkill: (id: string) =>
    request<Record<string, unknown>>(`/knowledge/skills/${id}/evaluate`, {
      method: "POST",
    }),
  orgMe: () =>
    request<{ org_id: string; plan: string; role: string | null }>("/orgs/me"),
  orgRoi: (orgId: string) =>
    request<{
      findings_blocked_from_implementation: number;
      readiness_gate_passes: number;
      readiness_gate_pass_rate: number;
      estimated_tokens_saved: number;
      agent_runs_before: number;
      agent_runs_after: number;
    }>(`/orgs/${orgId}/roi`),
  reportAgentRuns: (
    orgId: string,
    body: {
      project_id: string;
      runs_before: number;
      runs_after: number;
      notes?: string;
    }
  ) =>
    request<{ id: string; dashboard: Record<string, unknown> }>(
      `/orgs/${orgId}/roi/agent-runs`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  listVerticalSkills: () =>
    request<{ items: SkillSummary[] }>("/skills/verticals"),
};
