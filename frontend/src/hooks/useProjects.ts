import { FormEvent, useCallback, useState } from "react";
import { api } from "../api/client";
import type { ProjectState, ProjectSummary, ReadinessResult } from "../types";

type Options = {
  refreshFreeTier: () => Promise<void>;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
  setMobileNav: (v: "none" | "left" | "right") => void;
};

export function useProjects({
  refreshFreeTier,
  setBusy,
  setError,
  setMobileNav,
}: Options) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectState | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResult | null>(null);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [providerStatus, setProviderStatus] = useState<string | null>(null);
  const [fundingSource, setFundingSource] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newObjective, setNewObjective] = useState("");
  const [newMessage, setNewMessage] = useState("");
  const [projectQuery, setProjectQuery] = useState("");
  const [skillsActive, setSkillsActive] = useState(0);
  const [skillsTotal, setSkillsTotal] = useState(6);

  const refreshList = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
  }, []);

  const refreshSkills = useCallback(async (hasUser: boolean) => {
    if (!hasUser) {
      setSkillsActive(0);
      setSkillsTotal(6);
      return;
    }
    try {
      const skills = await api.listSkills();
      const active = skills.filter(
        (s) =>
          (s.status || "").toLowerCase() === "active" ||
          (s.status || "").toLowerCase() === "published"
      );
      setSkillsTotal(Math.max(skills.length, 6));
      setSkillsActive(active.length || skills.length);
    } catch {
      setSkillsActive(0);
      setSkillsTotal(6);
    }
  }, []);

  const loadProject = useCallback(
    async (id: string) => {
      const p = await api.getProject(id);
      setProject(p);
      const r = await api.getReadiness(id);
      setReadiness(r);
      setLimitations([]);
      setProviderStatus(null);
      setFundingSource(null);
      setMobileNav("none");
    },
    [setMobileNav]
  );

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createProject({
        name: newName.trim(),
        objective: newObjective.trim() || undefined,
        initial_message: newMessage.trim() || undefined,
      });
      setShowCreate(false);
      setNewName("");
      setNewObjective("");
      setNewMessage("");
      await refreshList();
      await loadProject(p.id);
      await refreshFreeTier();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createFromBrief(brief: {
    name: string;
    problem: string;
    stack: string;
    constraints: string;
  }) {
    setBusy(true);
    setError(null);
    const parts = [
      `Problem: ${brief.problem}`,
      brief.stack ? `Target stack: ${brief.stack}` : "",
      brief.constraints ? `Constraints: ${brief.constraints}` : "",
    ].filter(Boolean);
    try {
      const p = await api.createProject({
        name: brief.name,
        objective: brief.problem,
        initial_message: parts.join("\n"),
      });
      await refreshList();
      await loadProject(p.id);
      await refreshFreeTier();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function openCreateWithExample(name: string, idea: string) {
    setNewName(name);
    setNewMessage(idea);
    setNewObjective("");
    setShowCreate(true);
  }

  function clearProjects() {
    setProject(null);
    setProjects([]);
  }

  return {
    projects,
    project,
    setProject,
    readiness,
    setReadiness,
    limitations,
    setLimitations,
    providerStatus,
    setProviderStatus,
    fundingSource,
    setFundingSource,
    showCreate,
    setShowCreate,
    newName,
    setNewName,
    newObjective,
    setNewObjective,
    newMessage,
    setNewMessage,
    projectQuery,
    setProjectQuery,
    skillsActive,
    skillsTotal,
    refreshList,
    refreshSkills,
    loadProject,
    handleCreate,
    createFromBrief,
    openCreateWithExample,
    clearProjects,
  };
}
