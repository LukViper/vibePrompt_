import { FormEvent, useEffect, useRef, useState } from "react";
import { api, type ApiError } from "../api/client";
import type {
  AgentPromptPreview,
  AgentPromptResult,
  CodingAgent,
  FindingStatus,
  FreeTierStatus,
  ProjectState,
  ReadinessResult,
  SpecificationResult,
} from "../types";

type Options = {
  project: ProjectState | null;
  setProject: (p: ProjectState | null) => void;
  setReadiness: (r: ReadinessResult | null) => void;
  setLimitations: (v: string[]) => void;
  setProviderStatus: (v: string | null) => void;
  setFundingSource: (v: string | null) => void;
  setFreeTier: (v: FreeTierStatus | null) => void;
  refreshFreeTier: () => Promise<void>;
  refreshList: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
  setShowByok: (v: boolean) => void;
  busy: boolean;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
};

export function followUpsFrom(
  readiness: ReadinessResult | null,
  project: ProjectState | null
): string[] {
  return (
    readiness?.unblock_actions?.slice(0, 3) ??
    (project
      ? [
          "Clarify target users",
          "List must-have features",
          "Confirm the tech stack",
        ]
      : [])
  );
}

export function useChat({
  project,
  setProject,
  setReadiness,
  setLimitations,
  setProviderStatus,
  setFundingSource,
  setFreeTier,
  refreshFreeTier,
  refreshList,
  loadProject,
  setShowByok,
  busy,
  setBusy,
  setError,
}: Options) {
  const [draft, setDraft] = useState("");
  const [spec, setSpec] = useState<SpecificationResult | null>(null);
  const [showAgentPrompt, setShowAgentPrompt] = useState(false);
  const [agentPromptResult, setAgentPromptResult] =
    useState<AgentPromptResult | null>(null);
  const [agentPromptPreview, setAgentPromptPreview] =
    useState<AgentPromptPreview | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [project?.messages]);

  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    if (!project || !draft.trim() || busy) return;
    setBusy(true);
    setError(null);
    const content = draft.trim();
    setDraft("");
    try {
      const res = await api.sendMessage(project.id, content);
      setProject(res.project);
      setReadiness(res.readiness);
      setLimitations(res.review_limitations);
      setProviderStatus(res.provider_status);
      setFundingSource(res.funding_source);
      if (res.free_tier) setFreeTier(res.free_tier);
      else await refreshFreeTier();
      await refreshList();
    } catch (err) {
      const apiErr = err as ApiError;
      setError(String(err));
      setDraft(content);
      if (
        apiErr.quotaExhausted ||
        apiErr.status === 429 ||
        apiErr.status === 402
      ) {
        setShowByok(true);
      }
      await refreshFreeTier();
    } finally {
      setBusy(false);
    }
  }

  async function updateFinding(
    findingId: string,
    status: FindingStatus,
    note?: string
  ) {
    if (!project) return;
    setBusy(true);
    try {
      await api.updateFinding(project.id, findingId, status, note);
      await loadProject(project.id);
      await refreshList();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function exportSpec() {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.generateSpec(project.id);
      setSpec(result);
      setReadiness(result.readiness);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function openAgentPrompt() {
    setAgentPromptResult(null);
    setAgentPromptPreview(null);
    setShowAgentPrompt(true);
  }

  async function previewAgentSkills(opts: {
    task: string;
    agent: CodingAgent;
    includeSkills: boolean;
  }) {
    if (!project) return;
    try {
      const preview = await api.previewAgentPromptSkills(project.id, {
        task: opts.task || undefined,
      });
      setAgentPromptPreview(preview);
      setReadiness(preview.readiness);
    } catch (err) {
      setError(String(err));
    }
  }

  async function generateAgentPrompt(opts: {
    task: string;
    agent: CodingAgent;
    force: boolean;
    includeSkills: boolean;
    refineNotes: string;
  }) {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.generateAgentPrompt(project.id, {
        task: opts.task || undefined,
        agent: opts.agent,
        force: opts.force,
        include_skills: opts.includeSkills,
        refine_notes: opts.refineNotes || undefined,
      });
      setAgentPromptResult(result);
      setReadiness(result.readiness);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const openFindings =
    project?.findings.filter((f) => f.status === "open") ?? [];

  return {
    draft,
    setDraft,
    spec,
    setSpec,
    showAgentPrompt,
    setShowAgentPrompt,
    agentPromptResult,
    setAgentPromptResult,
    agentPromptPreview,
    chatEnd,
    sendMessage,
    updateFinding,
    exportSpec,
    openAgentPrompt,
    previewAgentSkills,
    generateAgentPrompt,
    openFindings,
  };
}
