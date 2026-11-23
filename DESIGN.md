# Design System — Editorial Technical Workbench

<!-- impeccable:design-schema 1 -->

## World

**Name:** Editorial Technical Workbench  
**Mode:** Operate  
**Scene:** Late-night IDE desk—high-contrast neutrals, hairline structure, color only for state. Comparable to Linear / Raycast / Zed.  
**Anti-reference:** neon purple/blue gradients, glassmorphic floating cards, chat-bubble clutter, emoji headers, bouncy motion, drop-shadow haze.

## Color strategy

Restrained neutrals + semantic status only.

### Dark (default)

| Token | Value | Role |
|---|---|---|
| `--canvas` | `#0D0F12` | App background |
| `--panel` | `#14171C` | Elevated rails / drawers |
| `--ink` | `#F3F4F6` | Primary text |
| `--ink-muted` | `#9CA3AF` | Secondary text |
| `--ink-faint` | `#6B7280` | Tertiary / labels |
| `--hairline` | `#232730` | 1px borders |
| `--blocking` | `#EF4444` | High severity / blockers |
| `--verified` | `#10B981` | Passed / locked OK |
| `--active` | `#3B82F6` | Selected stage / focus accent |

### Light

| Token | Value | Role |
|---|---|---|
| `--canvas` | `#FAFAFA` | App background |
| `--panel` | `#FFFFFF` | Elevated panels |
| `--ink` | `#111318` | Primary text |
| `--ink-muted` | `#4B5563` | Secondary |
| `--ink-faint` | `#6B7280` | Tertiary |
| `--hairline` | `#E4E7EC` | 1px borders |
| `--blocking` | `#DC2626` | Severity |
| `--verified` | `#059669` | Passed |
| `--active` | `#2563EB` | Selected / focus |

**Bans:** gradients, glow, drop-shadow haze, decorative blur.

## Typography

- UI chrome: `Geist Sans` (fallback Inter, system-ui)
- Data / stages / IDs / prompts / counters: `Geist Mono` (fallback JetBrains Mono, ui-monospace)
- Metrics: `font-variant-numeric: tabular-nums`

## Layout

3-pane IDE shell:

1. **Left rail** — 240px collapsible: project switcher, stage stepper (EXPLORE→PLAN→BUILD→REVIEW→DEBUG), Knowledge Library status (`N/N Active Skills`)
2. **Center** — fluid workspace: structured review briefs (not chat bubbles); inline LOCKED / REJECTED badges
3. **Right inspector** — 360px: Readiness Gate, blockers, findings (evidence-required resolution), locked vs rejected stack, Export Agent Spec CTA
4. **Top bar** — 44px: breadcrumb, inference mode pill, theme/export shortcuts

Responsive: below `1100px`, right inspector becomes slide-over drawer.

## Motion

Minimal opacity/position for drawer open only. No bounce, no decorative entrance cascades.

## Components

- Focus ring: `2px solid var(--active)` with 2px offset
- Finding cards: severity pill, evidence required, resolution note field—no dismiss-without-evidence
- Export Agent Spec: disabled until `implementation_ready`; then Cursor / Antigravity / Codex tabs
