# VibePrompt
User Manual and NLP Implementation Guide

**VibePrompt** helps developers and technical founders stress-test a product idea before they spend coding-agent tokens, using natural-language project descriptions and chat.

> **Figure 1.** VibePrompt workbench showing a Grill review turn, open findings, and the Readiness Gate.

---

## Project and team

| Field | Value |
|---|---|
| Team name | [Name] |
| Team number | [Number, if assigned] |

| Team member | Roll number / ID | Project contribution |
|---|---|---|
| [Full name] | [ID] | [Feature, design, NLP or testing work] |
| [Full name] | [ID] | [Specific contribution] |
| [Full name] | [ID] | [Specific contribution] |

| Field | Value |
|---|---|
| Course and section | [Course code, course name and section] |
| Department / institution | [Department and institution] |
| Faculty guide | [Name, if applicable] |
| Manual version and date | 1.0 · [Date] |

---

# Product overview

## About the app and contents

### What the app does

Developers and founders often jump into coding agents with vague scope, contradictory requirements, or unjustified stack choices. VibePrompt accepts a project description and follow-up chat, runs adversarial **Grill** review with structured findings, and unlocks **Export Agent Spec** only after a deterministic readiness checklist passes. The result is a locked, exportable project state aimed at fewer wasted agent runs.

### When to use it

| User goal | Feature to use | What the user receives |
|---|---|---|
| Challenge weak assumptions before building | Grill review (REVIEW stage) | Open findings with severity, evidence requirements, and resolution notes |
| Lock a project so coding agents can implement safely | Readiness Gate → Export Agent Spec | Cursor / Antigravity / Codex agent prompts once `implementation_ready` |
| Shape ideas without premature commitment | EXPLORE / PLAN stages (Chat or Brainstorm) | Structured project state updates without forcing export |

### Contents

1. About the app and contents  
2. Getting started  
3. How to use the app  
4. Features and a worked example  
5. How NLP is implemented  
6. NLP workflow diagram  
7. Troubleshooting and reference  

### Who should read which sections

- **First-time users** — Start with Getting started, then follow the illustrated walkthrough.  
- **Faculty and reviewers** — Use the worked example to check how each NLP method contributes to the result.

---

# User guide

## Getting started

### What you need

| Requirement | Details for this app |
|---|---|
| Platform and access | Modern browser (Chrome, Firefox, Edge, Safari). Local demo: frontend at `http://localhost:5173`, API at `http://127.0.0.1:8000`. Optional Android APK via Capacitor against a hosted HTTPS API. |
| Permissions or account | Guest JWT is minted automatically for short sessions. Sign-in is available for registered users, free-tier quota, BYOK keys, and Knowledge Library admin flows. |
| Supported input | English natural-language project descriptions and chat turns. Optional BYOK API keys (Gemini / OpenRouter / Groq / Qwen). Without provider keys the app runs **offline heuristic mode** (demo/tests only — not live adversarial review). |

### Open the app for the first time

1. Start the backend (`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` from `backend/`) and the frontend (`npm run dev` from `frontend/`), or open the deployed SPA URL your team provides.  
2. On first load the SPA bootstraps a guest session (`POST /api/auth/guest`). Sign in if you need free-tier generations, BYOK, or Knowledge Library.  
3. You land on the workbench: left rail (projects and stages), center composer, right inspector (Readiness Gate and findings). Create or select a project to begin.

> **Figure 2.** Workbench home. Point out the project switcher, stage stepper (EXPLORE → PLAN → BUILD → REVIEW → DEBUG), composer, and Readiness Gate panel.

### Find your way around

| Control | Where it is and what it opens |
|---|---|
| Left rail | Project switcher, behavioural stage stepper, Knowledge Library status (`N/N Active Skills`) |
| Center workspace | Conversation / review briefs; type or paste project text; submit with the send control or Cmd/Ctrl+Enter |
| Right inspector | Readiness Gate score/checklist, open findings (including blocking contradictions), Export Agent Spec CTA |
| Top bar | Breadcrumb, inference mode pill, theme and export shortcuts |

---

# Illustrated user guide

## How to use the app

Task: describe a small product idea, run Grill review, resolve blockers, then export an agent-ready spec.

### 1. Enter the input

Open or create a project. In the composer, paste a short project brief — for example: *“Build a habit tracker with React Native, offline sync, and AI coaching that always works without a network.”*

> **Figure 3a.** Composer containing the example project brief.

### 2. Run the feature

Select **REVIEW** (or let intent routing choose Grill review). Send the message. The backend runs primary analysis (and an optional critic on review turns), validates the reply, and updates structured project state.

> **Figure 3b.** REVIEW stage selected and send / submit trigger.

### 3. Read the result

In the center pane, read the Grill brief. In the right inspector, open findings list severity and evidence requirements. Resolve findings with counterevidence (a `blocking_contradiction` cannot be dismissed without state/artifact support). When the Readiness Gate shows ready, use **Export Agent Spec** and choose Cursor, Antigravity, or Codex.

> **Figure 3c.** Findings and Readiness Gate for the input shown in Figure 3a.

---

# Feature reference

## Features and a worked example

### Feature details

| Feature | When to use it | How to open it | Output to expect |
|---|---|---|---|
| Grill review | Challenge unsupported claims, contradictions, and weak stack choices | Stage → REVIEW (or grill intent in chat) | Structured findings with severity; optional critic pass; updated project state |
| Readiness Gate | Decide whether the project is safe to hand to a coding agent | Right inspector — Readiness checklist | Pass/fail checklist; unlocks export when `implementation_ready` |
| Export Agent Spec | Produce Cursor / Antigravity / Codex prompts | Export Agent Spec CTA (enabled after readiness) | Agent-ready Markdown / prompt payloads |
| Knowledge Library / Active Skills | Inject approved book-derived principles into chat | Left rail → Knowledge Library (admin for uploads) | Ranked short principle block in Chat / Brainstorm / Grill — not full book text |
| BYOK / free tier | Continue live LLM review after free quota | Settings / API key modal on `429` | Encrypted user keys; provider status in replies |

### Worked example for Grill review

**Purpose:** Show how an overstated offline + AI claim becomes a finding the user must resolve before export.

| Record from your demonstration | Fill in from one actual run |
|---|---|
| **Input** | “Habit tracker: React Native, full offline sync, AI coaching that always works with zero network.” |
| **Settings** | Stage = REVIEW; live providers configured (or note offline heuristic banner if demoing without keys) |
| **Output** | Finding such as a `blocking_contradiction` or high-severity claim: always-on AI coaching conflicts with zero-network requirement; readiness remains incomplete until resolved |
| **Interpretation** | The contradiction is tied to the “always works without network” + “AI coaching” pair. User should narrow the claim (e.g. on-device model, degraded offline mode) or drop one requirement, then re-run review |

### A case that needs review

- **Input variation:** Change “always works without a network” to “queues coaching requests until online.”  
- **What happened:** The hard offline/AI contradiction should soften or clear; remaining findings may cover sync conflict resolution or stack justification. User should still verify stack and sync claims manually before treating readiness as final.

---

# Technical guide

## How NLP is implemented

VibePrompt performs intent-aware dialogue understanding, structured information extraction into project state, adversarial claim critique, and (on review) optional multi-model critic reconciliation. The user-facing Grill review, findings lifecycle, and readiness-gated export all depend on this pipeline.

### Map course concepts to the app

| App feature | NLP concept | Actual method or component | Visible effect |
|---|---|---|---|
| Mode routing (EXPLORE→DEBUG) | Intent classification / dialogue act selection | Cue regexes + sticky follow-ups in `app/grill/modes.py`; explicit UI mode wins | Stage badge and behaviour of the reply |
| Grill findings | Information extraction + claim verification | LLM primary analysis → `state_patch` → `apply_state_patch`; contradiction detection in context/state apply | Open findings with severity and evidence requirements |
| Critic pass (REVIEW) | Multi-agent / dual-model critique | Primary provider chain + Groq critic when `CRITIC_ENABLED` | Stronger review briefs; critic does not rewrite conversational replies |
| Readiness + export | Deterministic compilation / NLG constrained by checklist | `app/compilation` readiness gate + Markdown / agent-prompt compilers | Export Agent Spec enabled only when checklist passes |
| Knowledge / skills | Retrieval-augmented generation (RAG-lite) | Book-to-Skill abstracts → ranked principle injection | Short principle block influencing Chat / Brainstorm / Grill |

### Explain one feature in detail: Grill review

**Input preparation.** The engine builds a mode-scoped context snapshot (not a full history dump): problem statement, decisions, stack, open findings, and recent messages. Skills inject a short ranked principle block when approved skills are active. Trivial greetings may skip model debate for cost control.

**Processing.** One user turn flows through: mode resolve → policy → context retrieval → primary LLM (Gemini → OpenRouter → Groq failover, or offline heuristics) → optional critic on REVIEW → validation → state apply (dedupe, contradiction surfacing) → persist. Findings such as `blocking_contradiction` require counterevidence in state/artifacts; insistence without evidence does not withdraw them.

**Output in the interface.** The assistant brief appears in the center workspace. Findings and readiness update in the right inspector — the same surfaces shown in the worked example on the Feature reference page.

### What the team built

- **Team implementation:** Grill orchestration, finding lifecycle and readiness gate, project-state persistence, React workbench UI, export compilers, guest JWT / BYOK / free-tier routing, Knowledge Library Book-to-Skill pipeline.  
- **Reused components:** External LLM APIs (Gemini, OpenRouter, Groq, optional Qwen/MuleRouter); FastAPI; React + TypeScript + Vite; SQLite (local) / PostgreSQL (prod). Model IDs are configurable via environment variables.

---

## NLP workflow diagram

> **Figure 4.** Grill review processing a project chat turn and returning findings + updated readiness.

```text
[User brief / chat turn]
        │
        ▼
[Mode resolve: EXPLORE|PLAN|BUILD|REVIEW|DEBUG]
        │
        ▼
[Context snapshot + optional skill principles]
        │
        ▼
[Primary LLM analysis ──failover──► next provider / offline heuristic]
        │
        ▼
[Optional critic (REVIEW only)]
        │
        ▼
[Validate reply + apply state_patch]
        │
        ├──────────────► [Findings / contradictions in inspector]
        └──────────────► [Readiness Gate]
                                │
                                ▼ (when ready)
                         [Export Agent Spec]
```

### Trace one input through the diagram

| Point in the flow | What to put here |
|---|---|
| Input | Habit-tracker brief claiming full offline AI coaching |
| Intermediate stage | Mode = REVIEW; context includes prior stack/decisions; primary model returns analysis + `state_patch`; critic may add pressure on the offline/AI claim |
| Final output | Finding listed in the inspector; readiness incomplete; user sees recovery path via evidence or scope change; export stays disabled until gate passes |

---

# Help and reference

## Troubleshooting and reference

### Troubleshooting

| What the user sees | What to check | What to do next |
|---|---|---|
| Banner: “Offline heuristic mode — not live adversarial review” | No provider keys, or `DEMO_MODE=true` | Add `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `GROQ_API_KEY` (or BYOK), restart API, confirm health endpoint |
| `429` / API key modal | Free-tier generations exhausted or rate limit | Configure BYOK in the modal; wait if rate-limited; failures and chat-only turns should not consume a generation |
| Export Agent Spec disabled | Open findings or failed readiness checklist | Resolve blockers with evidence; re-run REVIEW; confirm `implementation_ready` |
| Guest session ends / access error | Expired guest JWT | Refresh the page to mint a new guest token, or sign in |
| Android APK cannot reach API | `VITE_API_BASE_URL` and `CORS_ORIGINS` | Point APK at HTTPS API; add Capacitor WebView origin to API CORS |

### Limits and responsible use

- **Known limitation:** Offline heuristics and weak or contradictory user text can produce incomplete findings. Treat Grill output as advisory; verify stack and compliance claims yourself before shipping.  
- **Handling user input:** Project text and chat are sent to the configured LLM providers (platform keys or BYOK). Retention follows those providers’ policies — do not submit secrets, credentials, or personal data you are not allowed to share. BYOK keys are stored encrypted; raw keys are never returned by the API. Knowledge uploads must be rights-confirmed; pirate sources are refused.

### Glossary and references

| Term | Meaning |
|---|---|
| Readiness Gate | Deterministic checklist/score that unlocks agent export |
| Finding | Challenged claim with severity and evidence requirements |
| Blocking contradiction | Finding kind that requires state/artifact counterevidence to clear |
| Grill review | Adversarial REVIEW-mode analysis of the project |
| BYOK | Bring your own API key for live inference after free quota |
| Stages | EXPLORE, PLAN, BUILD, REVIEW, DEBUG |
| Export Agent Spec | Primary CTA once readiness passes (Cursor / Antigravity / Codex) |
| Critic | Optional second-model review pass used only in REVIEW |

**References (update URLs for your deployment):**

- Project README — repository root `README.md`  
- Grill mentor architecture — `docs/GRILL_MENTOR_ARCHITECTURE.md`  
- Book-to-Skill architecture — `docs/BOOK_TO_SKILL_ARCHITECTURE.md`  
- Deployment and recovery — `docs/DEPLOYMENT_AND_RECOVERY.md`  
- Provider / model cards — Gemini, OpenRouter, Groq, Qwen documentation for the configured model IDs  

### Support and version history

**Support:** [Team contact or course-approved channel]. When reporting an issue, include feature name, a non-sensitive example input, and the observed result (plus whether the offline heuristic banner was shown).

| Manual version | Date | Change |
|---|---|---|
| 1.0 | [Date] | Initial VibePrompt draft from NLP course template |

---

## Screenshot checklist (replace figures before submit)

1. Workbench overview (Figure 1 / 2)  
2. Composer with example input (Figure 3a)  
3. REVIEW stage + send (Figure 3b)  
4. Findings + Readiness Gate (Figure 3c)  
5. Simple workflow diagram image if required instead of the ASCII diagram (Figure 4)  

Crop to relevant controls, keep labels readable in print, and remove personal data.
