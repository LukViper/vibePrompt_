export type Severity = "critical" | "high" | "medium" | "low";
export type FindingStatus = "open" | "resolved" | "accepted_risk" | "rejected";
export type ReviewProvenance =
  | "deterministic"
  | "primary_only"
  | "two_model"
  | "none";

export interface Finding {
  id: string;
  title: string;
  challenged_claim: string;
  reasoning: string;
  evidence: string[];
  assumptions_to_verify: string[];
  severity: Severity;
  confidence: number;
  potential_impact: string;
  recommended_next_step: string;
  provenance: ReviewProvenance;
  critic_outcome: string | null;
  critic_notes: string | null;
  status: FindingStatus;
  invalidation_criteria: string;
  resolution_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  intent: string | null;
  provenance: ReviewProvenance | null;
  finding_ids: string[];
  created_at: string;
}

export interface Decision {
  id: string;
  title: string;
  choice: string;
  rationale: string;
}

export interface Requirement {
  id: string;
  text: string;
  kind: string;
}

export interface ProjectState {
  id: string;
  name: string;
  objective: string;
  intended_users: string[];
  success_criteria: string[];
  functional_requirements: Requirement[];
  non_functional_requirements: Requirement[];
  scope_in: string[];
  scope_out: string[];
  decisions: Decision[];
  tech_stack: string[];
  findings: Finding[];
  messages: Message[];
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  objective: string;
  open_finding_count: number;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReadinessResult {
  ready: boolean;
  status: string;
  blockers: string[];
  warnings: string[];
  missing_essentials: string[];
  accepted_risk_summaries: string[];
  unblock_actions: string[];
}

export interface ChatResponse {
  message: Message;
  findings: Finding[];
  project: ProjectState;
  readiness: ReadinessResult;
  review_limitations: string[];
  provider_status: string | null;
  provider_used: string | null;
  offline_review: boolean;
}

export interface SpecificationResult {
  readiness: ReadinessResult;
  markdown: string;
  structured: Record<string, unknown>;
}
