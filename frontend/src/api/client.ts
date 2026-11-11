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
const API_SECRET = (import.meta.env.VITE_API_SECRET || "").trim();
const TOKEN_KEY = "vibeprompt_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(API_SECRET ? { "X-API-Secret": API_SECRET } : {}),
    ...(extra ?? {}),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(init?.headers),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail || `Request failed (${res.status})`;
    try {
      const parsed = JSON.parse(detail) as {
        detail?: { message?: string; code?: string } | string;
      };
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (parsed.detail && typeof parsed.detail === "object" && parsed.detail.message) {
        message = parsed.detail.message;
      }
    } catch {
      /* keep raw text */
    }
    const err = new Error(message) as Error & { status?: number; body?: string };
    err.status = res.status;
    err.body = detail;
    throw err;
  }
  return res.json() as Promise<T>;
}

export const api = {
  authConfig: () => request<AuthConfigPublic>("/auth/config"),
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
    const res = await fetch(`${BASE}/knowledge/books/upload`, {
      method: "POST",
      headers: {
        ...authHeaders(),
      },
      body: form,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Upload failed (${res.status})`);
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
};
