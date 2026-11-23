# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are developers and technical founders who are about to spend coding-agent tokens on an idea. They use VibePrompt when shaping product scope, locking tech choices, and clearing weak assumptions—before implementation starts. [inferred: README + redesign brief]

## Product Purpose

VibePrompt is an evidence-driven adversarial project mentor. It challenges unsupported claims, contradictory requirements, and unjustified stack choices, then gates export of agent-ready specs until a readiness checklist passes. Success means fewer wasted agent runs and a locked, exportable project state. [inferred: README]

## Positioning

Be difficult to convince with unsupported claims, but easy to convince with good evidence. Distinctive mechanism: structured project state + readiness gate + finding lifecycle (including `blocking_contradiction` that cannot be dismissed without counterevidence) → Cursor / Antigravity / Codex agent prompt export. [inferred: README]

## Capabilities

- Guest JWT bootstrap and authenticated sessions
- Project conversation with behavioural stages (explore → plan → build → review → debug)
- Open findings with severity, evidence, and resolution notes
- Readiness gate / implementation checklist
- Free-tier quota + BYOK (429 / exhaustion opens API key modal)
- Knowledge Library / active skills
- Export specification and agent prompts (Cursor, Antigravity, Codex)

## Constraints

- Do not alter backend API contracts, guest JWT bootstrap (`POST /api/auth/guest`), `429` BYOK triggers, `blocking_contradiction` semantics, or Cursor/Antigravity/Codex export payloads
- Never bundle `VITE_API_SECRET` / `API_SECRET` in the SPA
- Single-node beta positioning (SQLite WAL); not multi-tenant SaaS claims
- Frontend stack: React + TypeScript + Vite

## Terminology

- Readiness Gate — checklist/score that unlocks agent export
- Finding — challenged claim with severity and evidence requirements
- Blocking contradiction — finding kind that requires state/artifact counterevidence to clear
- BYOK — bring your own API key
- Stages — EXPLORE, PLAN, BUILD, REVIEW, DEBUG
- Export Agent Spec — primary CTA once readiness passes

## Accessibility

Keyboard-first workbench: Cmd/Ctrl+Enter (and Cmd/Ctrl+K where appropriate) to submit, Esc to close modals, visible 2px focus rings. [from redesign brief]

## Open Questions

- Light vs dark as default theme: brief allows either architectural light or obsidian dark; implement both with dark default for IDE use scene. [inferred]
