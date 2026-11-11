export type Severity = "critical" | "high" | "medium" | "low";
export type FindingStatus = "open" | "resolved" | "accepted_risk" | "rejected";
export type ReviewProvenance =
  | "deterministic"
  | "primary_only"
  | "two_model"
  | "none";

export type BehaviouralMode =
  | "explore"
  | "plan"
  | "build"
  | "review"
  | "debug"
  | "conversational"
  | "brainstorming"
  | "grill_review";

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
  behavioural_mode?: BehaviouralMode;
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

export interface ReadinessChecklistItem {
  id: string;
  label: string;
  category: string;
  present: boolean;
  detail: string;
}

export interface ReadinessResult {
  ready: boolean;
  status: string;
  blockers: string[];
  warnings: string[];
  missing_essentials: string[];
  accepted_risk_summaries: string[];
  unblock_actions: string[];
  checklist?: ReadinessChecklistItem[];
  score_pct?: number;
  conflicts?: string[];
  implementation_ready?: boolean;
}

export interface FreeTierStatus {
  enabled: boolean;
  allocated: number;
  used: number;
  remaining: number;
  exhausted: boolean;
  provider: string | null;
  model: string | null;
  funding: "PLATFORM" | "BYOK" | "NONE";
  byok_configured: boolean;
  byok_provider: string | null;
  byok_model: string | null;
  requires_byok: boolean;
  inference_provider: string | null;
  message: string | null;
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
  funding_source: string | null;
  free_tier: FreeTierStatus | null;
  behavioural_mode: BehaviouralMode;
}

export interface SpecificationResult {
  readiness: ReadinessResult;
  markdown: string;
  structured: Record<string, unknown>;
}

export type CodingAgent = "cursor" | "antigravity" | "codex";

export interface PromptQualityReport {
  passed: boolean;
  score_pct: number;
  issues: string[];
  checks: Record<string, boolean>;
}

export interface AgentPromptSkillHit {
  slug?: string;
  title?: string;
  summary?: string;
  source_book_id?: string | null;
  chapter_ref?: string | null;
  confidence?: number;
}

export interface AgentPromptResult {
  readiness: ReadinessResult;
  prompt: string;
  blocked: boolean;
  block_reasons: string[];
  structured: Record<string, unknown>;
  agent?: CodingAgent | string;
  skills_used?: AgentPromptSkillHit[];
  skill_reasons?: Record<string, string>;
  quality?: PromptQualityReport | null;
  warnings?: string[];
}

export interface AgentPromptPreview {
  task: string;
  task_class: string;
  selected_slugs: string[];
  reasons: Record<string, string>;
  principles: AgentPromptSkillHit[];
  prompt_block: string;
  readiness: ReadinessResult;
}

export interface UserPublic {
  id: string;
  email: string;
  display_name?: string | null;
  avatar_url?: string | null;
  auth_provider?: string;
  created_at: string;
}

export interface AuthConfigPublic {
  mode: "supabase" | "legacy" | string;
  supabase_configured: boolean;
  google_oauth_hint: boolean;
  github_oauth_hint: boolean;
  email_auth: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserPublic;
}

export interface ByokConfigPublic {
  provider: string;
  model: string;
  base_url: string | null;
  is_active: boolean;
  validated_at: string | null;
  has_api_key: boolean;
}

export type ByokProvider = "gemini" | "openrouter" | "groq" | "qwen";

export interface CatalogBook {
  slug: string;
  title: string;
  author: string;
  target_skill: string;
  full_text_authorized: boolean;
  licensing_notes?: string;
  purpose?: string;
}

export interface BookRecord {
  id: string;
  catalog_slug: string | null;
  title: string;
  author: string;
  category: string;
  description: string;
  target_skill: string | null;
  status: string;
  status_detail: string;
  concept_count: number;
  chapter_count: number;
  enabled: boolean;
  associated_skill_ids: string[];
  usage_permission: string;
  rights_confirmed: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeConcept {
  id: string;
  book_id: string;
  kind: string;
  title: string;
  summary: string;
  application: string;
  chapter_ref: string | null;
  confidence: number;
}

export interface BookPreview {
  book: BookRecord;
  text_preview: string;
  chapters: Array<Record<string, unknown>>;
  concepts: KnowledgeConcept[];
  latest_job: {
    id: string;
    status: string;
    stage: string;
    error: string | null;
  } | null;
}

export interface SkillSummary {
  id: string;
  slug: string;
  name: string;
  description: string;
  status: string;
  mode_binding: string | null;
  version: number;
  source_book_count: number;
  updated_at: string;
}

export interface SkillPrinciple {
  id: string;
  title: string;
  summary: string;
  application: string;
  source_book_id: string | null;
  chapter_ref: string | null;
  confidence: number;
}

export interface SkillPackage {
  id: string;
  slug: string;
  name: string;
  description: string;
  status: string;
  mode_binding: string | null;
  version: number;
  principles: SkillPrinciple[];
  frameworks: string[];
  question_patterns: string[];
  source_book_ids: string[];
  parent_skill_id: string | null;
}

export interface AcquisitionReport {
  generated_at: string;
  book_count: number;
  authorized_full_text_count: number;
  manual_or_purchase_required_count: number;
  markdown: string;
  books: Array<Record<string, unknown>>;
}
