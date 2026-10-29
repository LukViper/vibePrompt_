import type {
  ChatResponse,
  Finding,
  FindingStatus,
  ProjectState,
  ProjectSummary,
  ReadinessResult,
  SpecificationResult,
} from "../types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
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
  sendMessage: (id: string, content: string) =>
    request<ChatResponse>(`/projects/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  updateFinding: (projectId: string, findingId: string, status: FindingStatus, note?: string) =>
    request<Finding>(`/projects/${projectId}/findings/${findingId}`, {
      method: "PATCH",
      body: JSON.stringify({ status, note }),
    }),
  getReadiness: (id: string) => request<ReadinessResult>(`/projects/${id}/readiness`),
  generateSpec: (id: string) =>
    request<SpecificationResult>(`/projects/${id}/specification`, { method: "POST" }),
  health: () => request<{ status: string; providers: Record<string, unknown> }>("/health"),
};
