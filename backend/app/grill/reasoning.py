"""Grill Mentor reasoning pipeline — stages produce structured conclusions, not chain-of-thought."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.grill.context import Contradiction, detect_contradictions, retrieve_relevant_context
from app.grill.modes import BehaviouralMode, canonical_mode
from app.projects.models import (
    Assumption,
    Decision,
    ProjectState,
    Severity,
    VerificationStatus,
)
from app.providers.base import CandidateFinding, StatePatch


# ---------------------------------------------------------------------------
# Structured reasoning artefacts (user-facing conclusions only)
# ---------------------------------------------------------------------------


class ContradictionKind:
    DIRECT = "direct_contradiction"
    POTENTIAL = "potential_contradiction"
    OPERATIONAL = "operational_conflict"
    TECHNICAL = "technical_incompatibility"
    BUDGET = "budget_conflict"
    MISSING_DEP = "missing_dependency"


class AssumptionClass:
    VERIFIED = "verified"
    USER_PROVIDED = "user_provided"
    REASONABLE_INFERENCE = "reasonable_inference"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


@dataclass
class ContradictionFinding:
    kind: str
    statements: list[str]
    why: str
    severity: str
    consequence: str
    resolution: str
    field: str = ""


@dataclass
class AssumptionFinding:
    statement: str
    classification: str
    evidence: str = ""
    why_matters: str = ""
    how_to_verify: str = ""


@dataclass
class FailureScenario:
    name: str
    description: str
    impact: str
    detection: str
    prevention: str
    recovery: str
    likelihood_note: str = ""  # qualitative only — never invent numeric probabilities
    severity: str = Severity.MEDIUM.value


@dataclass
class AlternativeOption:
    name: str
    summary: str
    cost: str = ""
    complexity: str = ""
    reliability: str = ""
    maintainability: str = ""
    security: str = ""
    scalability: str = ""
    user_effort: str = ""


@dataclass
class Recommendation:
    problem: str
    root_cause: str
    recommended: str
    alternatives: list[str] = field(default_factory=list)
    trade_offs: str = ""
    implementation: str = ""
    required_decision: str | None = None
    severity: str = Severity.HIGH.value


@dataclass
class MentorReasoning:
    """Output of the 10-stage mentor pipeline (conclusions only)."""

    intent: str = "general"
    goals: list[str] = field(default_factory=list)
    context_keys: list[str] = field(default_factory=list)
    contradictions: list[ContradictionFinding] = field(default_factory=list)
    assumptions: list[AssumptionFinding] = field(default_factory=list)
    feasibility_notes: list[str] = field(default_factory=list)
    failure_scenarios: list[FailureScenario] = field(default_factory=list)
    alternatives: list[AlternativeOption] = field(default_factory=list)
    recommendation: Recommendation | None = None
    decision_proposals: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = ""
    strengths: list[str] = field(default_factory=list)
    acknowledge_reasonable: bool = False
    stages_run: list[str] = field(default_factory=list)

    def prioritized_contradictions(self) -> list[ContradictionFinding]:
        order = {
            Severity.CRITICAL.value: 0,
            Severity.HIGH.value: 1,
            Severity.MEDIUM.value: 2,
            Severity.LOW.value: 3,
        }
        return sorted(
            self.contradictions,
            key=lambda c: order.get(c.severity, 9),
        )

    def to_findings(self, *, max_findings: int = 6) -> list[CandidateFinding]:
        """Convert material mentor issues into CandidateFinding for project merge."""
        out: list[CandidateFinding] = []
        for c in self.prioritized_contradictions():
            if c.severity == Severity.LOW.value and len(out) >= 2:
                continue
            out.append(
                CandidateFinding(
                    title=c.kind.replace("_", " ").title()[:120],
                    challenged_claim=c.statements[0] if c.statements else c.why,
                    reasoning=f"{c.why} Consequence: {c.consequence}",
                    evidence=list(c.statements[:4]),
                    assumptions_to_verify=[],
                    severity=c.severity,
                    confidence=0.75 if c.kind == ContradictionKind.DIRECT else 0.55,
                    potential_impact=c.consequence,
                    recommended_next_step=c.resolution,
                    invalidation_criteria=(
                        "User explicitly resolves the conflict or provides evidence "
                        "that both constraints can hold together."
                    ),
                )
            )
            if len(out) >= max_findings:
                return out
        for a in self.assumptions:
            if a.classification in (
                AssumptionClass.VERIFIED,
                AssumptionClass.USER_PROVIDED,
                AssumptionClass.REASONABLE_INFERENCE,
            ):
                continue
            out.append(
                CandidateFinding(
                    title="Unverified assumption",
                    challenged_claim=a.statement,
                    reasoning=a.why_matters or "Lacks supporting evidence in project context.",
                    evidence=[a.evidence] if a.evidence else [],
                    assumptions_to_verify=[a.statement],
                    severity=Severity.MEDIUM.value,
                    confidence=0.5,
                    potential_impact=a.why_matters,
                    recommended_next_step=a.how_to_verify or "Verify with a concrete check.",
                    invalidation_criteria="Provide verifying evidence or retract the claim.",
                )
            )
            if len(out) >= max_findings:
                break
        return out

    def to_state_patch_hints(self) -> StatePatch:
        """Propose assumptions/risks/questions — never auto-confirm decisions."""
        assumptions = [
            a.statement
            for a in self.assumptions
            if a.classification
            in (AssumptionClass.UNVERIFIED, AssumptionClass.UNSUPPORTED, AssumptionClass.REASONABLE_INFERENCE)
        ][:8]
        risks = [f.name + ": " + f.impact for f in self.failure_scenarios[:5]]
        questions: list[str] = []
        if self.recommendation and self.recommendation.required_decision:
            questions.append(self.recommendation.required_decision)
        # Proposed decisions stay provisional — never as confirmed user decisions
        decisions = []
        for d in self.decision_proposals[:3]:
            item = dict(d)
            item["status"] = "proposed"
            item.setdefault("source", "grill_mentor")
            decisions.append(item)
        return StatePatch(
            add_assumptions=assumptions or None,
            add_known_risks=risks or None,
            add_open_questions=questions or None,
            add_decisions=decisions or None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NORM = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _NORM.sub(" ", (text or "").lower()).strip()


def _blob(project: ProjectState, user_message: str = "") -> str:
    parts = [
        project.objective or "",
        project.problem_statement or "",
        project.architecture_notes or "",
        " ".join(project.scope_in or []),
        " ".join(project.scope_out or []),
        " ".join(c.text for c in project.constraints or []),
        " ".join(f"{d.title} {d.choice}" for d in project.decisions or []),
        " ".join(r.text for r in project.functional_requirements or []),
        " ".join(a.statement for a in project.assumptions or []),
        " ".join(project.known_risks or []),
        " ".join(m.content for m in (project.messages or [])[-12:]),
        user_message or "",
    ]
    return _norm(" ".join(parts))


def _has_any(blob: str, phrases: Iterable[str]) -> bool:
    return any(_norm(p) in blob for p in phrases if p)


def _severity_cap(items: list[ContradictionFinding], *, keep_low_if_empty: bool = False) -> list[ContradictionFinding]:
    """Prefer critical/high; avoid flooding with low issues."""
    critical = [c for c in items if c.severity in (Severity.CRITICAL.value, Severity.HIGH.value)]
    if critical:
        medium = [c for c in items if c.severity == Severity.MEDIUM.value][:2]
        return critical + medium
    medium = [c for c in items if c.severity == Severity.MEDIUM.value]
    if medium:
        return medium
    if keep_low_if_empty:
        return [c for c in items if c.severity == Severity.LOW.value][:2]
    return []


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def stage_intent_and_goals(user_message: str, project: ProjectState) -> tuple[str, list[str]]:
    text = (user_message or "").lower()
    intent = "general"
    if any(w in text for w in ("review", "critique", "challenge", "grill", "what's wrong")):
        intent = "review"
    elif any(w in text for w in ("decide", "choose", "which", "recommend", "should i")):
        intent = "decision"
    elif any(w in text for w in ("build", "implement", "how do i")):
        intent = "implementation"
    elif any(w in text for w in ("fail", "break", "risk", "what if")):
        intent = "risk"
    goals: list[str] = []
    if project.objective:
        goals.append(project.objective.strip()[:240])
    for sc in (project.success_criteria or [])[:3]:
        goals.append(sc.strip()[:200])
    if not goals and user_message.strip():
        goals.append(user_message.strip()[:200])
    return intent, goals


def enrich_patch_contradictions(
    project: ProjectState, patch: StatePatch
) -> list[ContradictionFinding]:
    """Map lexical patch contradictions into the richer taxonomy."""
    raw = detect_contradictions(project, patch)
    out: list[ContradictionFinding] = []
    for c in raw:
        kind = ContradictionKind.DIRECT
        severity = Severity.HIGH.value
        lower = c.message.lower()
        if "ambiguous" in lower:
            kind = ContradictionKind.POTENTIAL
            severity = Severity.MEDIUM.value
        elif "rejected" in lower:
            kind = ContradictionKind.OPERATIONAL
        elif c.field == "tech_stack":
            kind = ContradictionKind.TECHNICAL
        elif c.field == "scope":
            kind = ContradictionKind.OPERATIONAL
        out.append(
            ContradictionFinding(
                kind=kind,
                statements=[c.existing, c.incoming],
                why=c.message,
                severity=severity,
                consequence="Proceeding without resolution risks building the wrong system.",
                resolution="Keep the prior decision, or explicitly replace it with rationale.",
                field=c.field,
            )
        )
    return out


def stage_requirement_contradictions(
    project: ProjectState, user_message: str
) -> list[ContradictionFinding]:
    """Domain-aware requirement conflicts from project memory + latest message."""
    blob = _blob(project, user_message)
    findings: list[ContradictionFinding] = []

    # --- Pharmacy / catalogue experiment patterns (A–I) ---
    findings.extend(
        _pharmacy_contradictions(blob, project, user_message=user_message)
    )

    # Generic: realtime sync without integration
    if _has_any(blob, ("real time", "realtime", "live sync", "live stock")) and _has_any(
        blob, ("no integration", "no api", "no known integration", "manual only", "no manual update")
    ):
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.OPERATIONAL,
                statements=[
                    "Real-time or live inventory accuracy promised",
                    "No known integration / no reliable update path",
                ],
                why="Live accuracy requires a data feed or disciplined manual process; neither is established.",
                severity=Severity.CRITICAL.value,
                consequence="Customers will see wrong availability; trust and compliance risk rise.",
                resolution="Downgrade to 'last updated' accuracy, add a POS/API sync, or define a manual update SLA.",
            )
        )

    # Generic: exact pricing vs stale source
    if _has_any(blob, ("exact price", "exact marg", "live price", "always accurate price")) and _has_any(
        blob, ("weekly", "stale", "csv", "batch upload", "not synced")
    ):
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.DIRECT,
                statements=[
                    "Exact / live pricing promised",
                    "Batch or infrequent inventory updates",
                ],
                why="Exact prices cannot be guaranteed from a lagging catalogue source.",
                severity=Severity.HIGH.value,
                consequence="Wrong prices at checkout or misleading storefront listings.",
                resolution="Show 'indicative' prices, sync more often, or integrate the billing/POS source of truth.",
            )
        )

    # Budget vs large-scope polish
    if _has_any(blob, ("small budget", "low budget", "tight budget", "no budget", "mvp budget")) and _has_any(
        blob, ("1mg", "enterprise", "full marketplace", "parity with")
    ):
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.BUDGET,
                statements=[
                    "Small / constrained budget",
                    "Large-marketplace polish or parity expectations",
                ],
                why="Parity with mature marketplaces is a multi-year product investment, not an MVP.",
                severity=Severity.HIGH.value,
                consequence="Scope explosion, unfinished build, or quality that still disappoints users.",
                resolution="Define an MVP slice (catalogue + enquiry) and defer marketplace parity.",
            )
        )

    # Professional UX vs hiding uncertainty
    if _has_any(blob, ("professional", "premium look", "polished")) and _has_any(
        blob, ("hide availability", "hide uncertainty", "always show in stock", "fake in stock")
    ):
        findings.append(
            ContradictionFinding(
                kind=ContradictionKind.OPERATIONAL,
                statements=[
                    "Professional / trustworthy appearance",
                    "Hiding availability uncertainty",
                ],
                why="Trustworthy UX discloses uncertainty; hiding it looks polished until the first stock miss.",
                severity=Severity.HIGH.value,
                consequence="Customer distrust and refunds after false availability.",
                resolution="Show last-updated timestamps and soft-availability states instead of hard 'in stock'.",
            )
        )

    return _severity_cap(findings, keep_low_if_empty=True)


def _pharmacy_contradictions(
    blob: str, project: ProjectState, *, user_message: str = ""
) -> list[ContradictionFinding]:
    """Explicit pharmacy-experiment detectors (regression cases A–I).

    Detectors require cue phrases in the *user message* so a focused review
    does not flood every A–I finding from latent fixture state alone.
    """
    out: list[ContradictionFinding] = []
    msg = _norm(user_message)
    pharmacy_ish = _has_any(
        blob,
        (
            "pharmacy",
            "medicine",
            "medical store",
            "marg",
            "1mg",
            "tata 1mg",
            "woocommerce",
            "wordpress",
            "drug",
            "chemist",
        ),
    )
    if not pharmacy_ish:
        return out

    def _focus(*phrases: str) -> bool:
        """True when the latest user turn is asking about this conflict."""
        return _has_any(msg, phrases) if msg else True

    # A — Exact Marg pricing vs potentially stale inventory
    if (
        _focus("marg", "exact price", "exact pricing", "pricing", "price")
        and _has_any(blob, ("marg", "exact price", "exact pricing", "billing software"))
        and _has_any(blob, ("csv", "weekly", "upload", "stale", "inventory file", "batch"))
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.DIRECT,
                statements=[
                    "Exact Marg billing prices as the customer-facing truth",
                    "Inventory / price updates via delayed CSV or batch file",
                ],
                why="Marg is the live billing source; a delayed CSV is a lagging copy, so 'exact' prices are not guaranteed.",
                severity=Severity.CRITICAL.value,
                consequence="Listed prices diverge from what the counter charges.",
                resolution="Either integrate Marg (or export more often) or label prices as approximate / enquire.",
                field="pricing",
            )
        )

    # B — Real-time sync vs no integration / no manual updates
    if _focus("real time", "realtime", "live sync", "synchronization", "integration") and _has_any(
        blob, ("real time", "realtime", "live sync", "always up to date")
    ) and (
        _has_any(blob, ("no integration", "no api", "no known integration", "cannot integrate"))
        or (
            _has_any(blob, ("no manual", "without manual", "no staff update"))
            and _has_any(blob, ("sync", "update", "inventory"))
        )
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.MISSING_DEP,
                statements=[
                    "Real-time inventory synchronization",
                    "No known Marg/POS integration and no manual update process",
                ],
                why="Real-time sync needs an integration or a human process; both are absent.",
                severity=Severity.CRITICAL.value,
                consequence="Storefront stock will drift from shelf reality with no recovery path.",
                resolution="Add an API/export job, or define a manual update cadence with clear freshness labels.",
                field="inventory_sync",
            )
        )

    # C — Professional appearance vs hiding availability uncertainty
    if _focus("professional", "hide", "uncertainty", "appearance") and _has_any(
        blob, ("professional", "look professional", "premium")
    ) and _has_any(
        blob, ("hide", "don't show", "do not show", "never show uncertainty", "always available")
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.OPERATIONAL,
                statements=[
                    "Professional customer-facing appearance",
                    "Hide or suppress availability uncertainty",
                ],
                why="Professional medical retail UX earns trust by disclosing freshness — not by implying certainty you lack.",
                severity=Severity.HIGH.value,
                consequence="Customers act on false certainty; complaints and regulatory attention follow.",
                resolution="Use 'last checked' / 'confirm before visit' patterns while keeping a clean layout.",
                field="ux_honesty",
            )
        )

    # D — Tata 1mg-level expectations vs small budget
    if _focus("1mg", "tata", "budget", "experience") and _has_any(
        blob, ("1mg", "tata 1mg", "like 1mg", "amazon pharmacy")
    ) and _has_any(
        blob, ("small budget", "low budget", "tight budget", "limited budget", "cheap", "mvp only")
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.BUDGET,
                statements=[
                    "Experience expectations comparable to Tata 1mg / large pharmacies",
                    "Small initial budget",
                ],
                why="1mg-class polish implies logistics, catalog ops, payments, and compliance spend beyond a small MVP.",
                severity=Severity.HIGH.value,
                consequence="Either the build stalls or the UX feels unfinished against the promised bar.",
                resolution="Keep the business goal (local pharmacy discovery) but MVP as catalogue + enquiry, not marketplace parity.",
                field="scope_budget",
            )
        )

    # E — Weekly CSV vs rapid stock changes
    if _focus("weekly", "rapid", "stock change", "csv", "turnover") and _has_any(
        blob, ("weekly csv", "weekly update", "once a week", "weekly inventory")
    ) and _has_any(
        blob, ("fast", "rapid", "daily change", "changes quickly", "high turnover", "stock changes")
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.OPERATIONAL,
                statements=[
                    "Weekly CSV inventory updates",
                    "Stock that can change rapidly",
                ],
                why="A weekly batch cannot track high-turnover pharmacy SKUs.",
                severity=Severity.HIGH.value,
                consequence="Frequent false in-stock / out-of-stock signals.",
                resolution="Increase export frequency, sync critical SKUs daily, or drop hard availability claims.",
                field="update_cadence",
            )
        )

    # F — Easy bulk uploads vs accidental catalogue overwrites
    if not _focus("bulk", "overwrite", "accidental", "dry run", "replace the catalogue"):
        bulk_ops = False
        overwrite_risk = False
    else:
        bulk_ops = _has_any(
            blob,
            (
                "bulk upload",
                "bulk csv",
                "easy bulk",
                "easy upload",
                "csv upload",
                "csv overwrite",
                "one click upload",
                "full replace",
            ),
        )
        overwrite_risk = _has_any(
            blob,
            (
                "overwrite",
                "replace catalogue",
                "full replace",
                "accidental",
                "no dry run",
                "no backup",
            ),
        )
    # Require affirmative safeguards — "no dry run" must not count as having one
    has_safeguard = (
        _has_any(blob, ("with dry run", "dry-run enabled", "diff review", "backup before import"))
        or (" staging " in f" {blob} " and "no staging" not in blob)
    ) and not _has_any(blob, ("no dry run", "without dry run", "no backup", "no staging"))
    if bulk_ops and overwrite_risk and not has_safeguard:
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.OPERATIONAL,
                statements=[
                    "Easy bulk catalogue uploads",
                    "No stated safeguard against accidental full overwrites",
                ],
                why="Unvalidated bulk replace can wipe correct SKUs or push bad prices in one action.",
                severity=Severity.HIGH.value,
                consequence="Catalogue corruption requiring painful recovery.",
                resolution="Add dry-run/diff, backups, and row-level validation before apply.",
                field="bulk_upload",
            )
        )

    # G — No developer dependency vs custom software maintenance
    if _focus("developer", "custom software", "maintain", "coder") and _has_any(
        blob, ("no developer", "without developer", "non technical", "no coder")
    ) and _has_any(
        blob, ("custom software", "custom app", "bespoke", "custom build", "maintain ourselves")
    ):
        out.append(
            ContradictionFinding(
                kind=ContradictionKind.TECHNICAL,
                statements=[
                    "No ongoing developer dependency",
                    "Custom software that still needs maintenance",
                ],
                why="Custom code always needs ownership for security patches, hosting, and breakages.",
                severity=Severity.HIGH.value,
                consequence="System freezes when something breaks and no one can fix it.",
                resolution="Prefer configurable SaaS/WordPress plugins for MVP, or budget a retainer.",
                field="ops_ownership",
            )
        )

    # H — WordPress recommendation vs unnecessary WooCommerce
    if _focus("wordpress", "woocommerce", "checkout", "cart", "enquiry") and _has_any(
        blob, ("wordpress",)
    ) and _has_any(blob, ("woocommerce", "full cart", "checkout")):
        # Conflict only if sales/checkout not needed / enquiry-only
        if _has_any(
            blob,
            (
                "enquiry only",
                "no online payment",
                "no checkout",
                "call to order",
                "visit store",
                "no ecommerce",
                "catalogue only",
                "not selling online",
            ),
        ) or _has_any(blob, ("unnecessary", "overkill", "too much")):
            out.append(
                ContradictionFinding(
                    kind=ContradictionKind.TECHNICAL,
                    statements=[
                        "WordPress site for local pharmacy presence",
                        "WooCommerce / full e-commerce stack enabled or assumed",
                    ],
                    why="Catalogue + enquiry does not need cart, tax, and checkout complexity.",
                    severity=Severity.MEDIUM.value,
                    consequence="Extra plugins, attack surface, and ops burden without matching the sales model.",
                    resolution="Use WordPress + catalogue/forms; add WooCommerce only when online checkout is a confirmed goal.",
                    field="cms_commerce",
                )
            )

    # I — Regulatory assumptions vs unresolved India online medicine rules
    if _focus(
        "india", "legal", "license", "regul", "sell medicine", "online medicine"
    ) and _has_any(
        blob, ("india", "indian", "online medicine", "sell medicine", "e pharmacy", "list medicines")
    ):
        legal_resolved = any(
            "regul" in (d.title + d.choice + d.rationale).lower()
            and getattr(d, "status", "") in ("confirmed", "accepted", "resolved")
            for d in project.decisions or []
        )
        if not legal_resolved and (
            _has_any(blob, ("assume legal", "probably allowed", "should be fine", "no license needed"))
            or not _has_any(blob, ("consult lawyer", "license confirmed", "schedule h", "drug license"))
        ):
            out.append(
                ContradictionFinding(
                    kind=ContradictionKind.MISSING_DEP,
                    statements=[
                        "Plan to list or sell medicines online in India",
                        "Legal / licensing requirements still unresolved",
                    ],
                    why="Online medicine listing/sales in India have license and advertising constraints that are not settled in project state.",
                    severity=Severity.CRITICAL.value,
                    consequence="Building sales flows that cannot legally launch, or regulatory exposure.",
                    resolution="Treat legal clearance as a blocking decision; MVP as information/enquiry until counsel confirms.",
                    field="regulatory",
                )
            )

    return out


def stage_assumptions(project: ProjectState, user_message: str) -> list[AssumptionFinding]:
    findings: list[AssumptionFinding] = []
    blob = _blob(project, user_message)

    for a in project.assumptions or []:
        status = a.status.value if hasattr(a.status, "value") else str(a.status)
        if status == VerificationStatus.VERIFIED.value or a.evidence:
            cls = AssumptionClass.VERIFIED
        elif status == VerificationStatus.INVALIDATED.value:
            cls = AssumptionClass.UNSUPPORTED
        else:
            cls = AssumptionClass.UNVERIFIED
        findings.append(
            AssumptionFinding(
                statement=a.statement,
                classification=cls,
                evidence=a.evidence or "",
                why_matters="Stored project assumption without fresh verification.",
                how_to_verify="Attach evidence or mark verified/invalidated explicitly.",
            )
        )

    # Heuristic: AI-sounding recommendations appearing as facts in user text
    speculative = [
        ("users will always", AssumptionClass.UNSUPPORTED),
        ("customers never", AssumptionClass.UNSUPPORTED),
        ("integration is easy", AssumptionClass.UNVERIFIED),
        ("no license needed", AssumptionClass.UNSUPPORTED),
        ("woocommerce is required", AssumptionClass.UNVERIFIED),
        ("real-time is free", AssumptionClass.UNSUPPORTED),
    ]
    lower_msg = (user_message or "").lower()
    for phrase, cls in speculative:
        if phrase in lower_msg or phrase in blob:
            findings.append(
                AssumptionFinding(
                    statement=phrase,
                    classification=cls,
                    why_matters="Claim lacks evidence in project context.",
                    how_to_verify="Replace with a measurable check or drop the claim.",
                )
            )

    if _has_any(blob, ("india", "medicine", "pharmacy")) and not any(
        "regul" in f.statement.lower() or "license" in f.statement.lower() for f in findings
    ):
        findings.append(
            AssumptionFinding(
                statement="Online medicine listing/sales are legally cleared for this MVP",
                classification=AssumptionClass.UNVERIFIED,
                why_matters="Regulatory status changes what you may publish or sell.",
                how_to_verify="Confirm with qualified counsel / licensing checklist before sales features.",
            )
        )

    # Dedup
    seen: set[str] = set()
    unique: list[AssumptionFinding] = []
    for f in findings:
        key = _norm(f.statement)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique[:12]


def stage_feasibility(project: ProjectState, contradictions: list[ContradictionFinding]) -> list[str]:
    notes: list[str] = []
    if any(c.severity == Severity.CRITICAL.value for c in contradictions):
        notes.append(
            "Critical conflicts block a defensible implementation plan until resolved."
        )
    budget_hit = any(c.kind == ContradictionKind.BUDGET for c in contradictions)
    if budget_hit:
        notes.append("Budget and scope are misaligned; feasibility depends on cutting scope, not adding hours.")
    if project.constraints:
        notes.append(
            "Respect stated constraints: "
            + "; ".join(c.text for c in project.constraints[:3])
        )
    if not notes:
        notes.append("No hard feasibility blockers detected from structured context alone.")
    return notes


def stage_failure_scenarios(
    project: ProjectState, user_message: str, contradictions: list[ContradictionFinding]
) -> list[FailureScenario]:
    blob = _blob(project, user_message)
    scenarios: list[FailureScenario] = []

    if _has_any(blob, ("csv", "upload", "bulk")):
        scenarios.append(
            FailureScenario(
                name="Invalid or partial CSV upload",
                description="Malformed rows, wrong units, or encoding errors enter the catalogue.",
                impact="Bad prices/stock published; hard to spot without validation.",
                detection="Schema validation report + sample diff before publish.",
                prevention="Dry-run import, required columns, reject on error threshold.",
                recovery="Roll back to last good snapshot; re-import fixed file.",
                likelihood_note="Common whenever bulk file ops are the primary update path.",
                severity=Severity.HIGH.value,
            )
        )
        scenarios.append(
            FailureScenario(
                name="Accidental catalogue overwrite",
                description="A full-replace upload wipes good SKUs.",
                impact="Empty or wrong catalogue until restore.",
                detection="Pre-apply row-count / checksum alerts.",
                prevention="Staging + explicit confirm; soft-delete with backup.",
                recovery="Restore from automatic pre-upload backup.",
                likelihood_note="Elevated if 'easy bulk upload' lacks safeguards.",
                severity=Severity.CRITICAL.value,
            )
        )

    if _has_any(blob, ("api", "provider", "openai", "llm", "marg")):
        scenarios.append(
            FailureScenario(
                name="Upstream API / POS outage",
                description="Billing or model provider unavailable.",
                impact="Sync or assisted features stop; storefront may show stale data.",
                detection="Health checks and sync lag monitors.",
                prevention="Cache last-good snapshot; degrade to enquire-only.",
                recovery="Replay sync queue when provider recovers.",
                likelihood_note="External dependencies fail intermittently; plan for degradation.",
                severity=Severity.HIGH.value,
            )
        )

    if _has_any(blob, ("auth", "login", "jwt", "password")):
        scenarios.append(
            FailureScenario(
                name="Authentication failure",
                description="Staff cannot log in to update catalogue.",
                impact="Stale data persists longer; ops blocked.",
                detection="Failed-login alerts; secondary admin path.",
                prevention="Backup admin account; password reset runbook.",
                recovery="Reset credentials; publish freeze notice if needed.",
                severity=Severity.MEDIUM.value,
            )
        )

    if _has_any(blob, ("sqlite", "database", "db")):
        scenarios.append(
            FailureScenario(
                name="Database corruption or bad migration",
                description="Store file damaged or migration half-applied.",
                impact="Site down or inconsistent catalogue.",
                detection="Integrity checks on backup; smoke tests after deploy.",
                prevention="Online backups + tested restore drill.",
                recovery="Restore verified backup; replay recent CSVs if needed.",
                severity=Severity.HIGH.value,
            )
        )

    if any(c.field == "regulatory" for c in contradictions) or _has_any(
        blob, ("medicine", "pharmacy", "india")
    ):
        scenarios.append(
            FailureScenario(
                name="Regulatory / listing compliance gap",
                description="Online medicine listing or sales without required clearances.",
                impact="Forced takedown, fines, or blocked launch.",
                detection="Legal review checklist before enabling sales features.",
                prevention="Gate checkout/listing behind confirmed licensing decision.",
                recovery="Disable sales paths; keep information-only mode.",
                likelihood_note="Risk is material whenever legal status is unverified — do not invent odds.",
                severity=Severity.CRITICAL.value,
            )
        )

    if _has_any(blob, ("scale", "traffic", "many users", "performance")):
        scenarios.append(
            FailureScenario(
                name="Performance under increased usage",
                description="Catalogue search or sync jobs slow under load.",
                impact="Timeouts and abandoned visits.",
                detection="Latency SLOs and slow-query logs.",
                prevention="Index hot fields; cache public catalogue pages.",
                recovery="Scale read replicas / CDN; shed noncritical jobs.",
                severity=Severity.MEDIUM.value,
            )
        )

    # Dedup by name
    seen: set[str] = set()
    unique: list[FailureScenario] = []
    for s in scenarios:
        if s.name in seen:
            continue
        seen.add(s.name)
        unique.append(s)
    return unique[:6]


def stage_alternatives(
    project: ProjectState,
    contradictions: list[ContradictionFinding],
    user_message: str,
) -> list[AlternativeOption]:
    blob = _blob(project, user_message)
    alts: list[AlternativeOption] = []

    if any(c.field in {"pricing", "inventory_sync", "update_cadence"} for c in contradictions) or _has_any(
        blob, ("marg", "csv", "inventory")
    ):
        alts = [
            AlternativeOption(
                name="Freshness-labelled catalogue",
                summary="Publish Marg/CSV data with last-updated timestamps and 'confirm before visit' CTAs.",
                cost="Low",
                complexity="Low",
                reliability="Medium — honest about lag",
                maintainability="High",
                security="Low attack surface",
                scalability="Good for local traffic",
                user_effort="Staff export on a defined cadence",
            ),
            AlternativeOption(
                name="Scheduled Marg export sync",
                summary="Automate daily/hourly export from Marg into a staging DB with validation.",
                cost="Medium",
                complexity="Medium",
                reliability="Higher freshness",
                maintainability="Needs light ops",
                security="Protect export credentials",
                scalability="Fine for single store",
                user_effort="Low after setup",
            ),
            AlternativeOption(
                name="Enquiry-only MVP (no hard stock/price)",
                summary="Show medicines as information; customers enquire; staff confirm live from Marg.",
                cost="Lowest",
                complexity="Lowest",
                reliability="Highest truthfulness",
                maintainability="Highest",
                security="Minimal",
                scalability="N/A",
                user_effort="Answer enquiries",
            ),
        ]
    elif any(c.field == "cms_commerce" for c in contradictions) or (
        _has_any(blob, ("wordpress",)) and _has_any(blob, ("woocommerce",))
    ):
        alts = [
            AlternativeOption(
                name="WordPress catalogue + form",
                summary="WordPress site with searchable catalogue and enquiry form — no cart.",
                cost="Low",
                complexity="Low",
                reliability="High for MVP",
                maintainability="Plugin updates only",
                security="Fewer commerce plugins",
                scalability="Enough for local discovery",
                user_effort="Content updates",
            ),
            AlternativeOption(
                name="WordPress + WooCommerce",
                summary="Full checkout when online sales and payments are confirmed goals.",
                cost="Higher",
                complexity="Higher",
                reliability="Depends on ops",
                maintainability="Heavier",
                security="PCI / plugin surface",
                scalability="Better for online sales",
                user_effort="Order ops",
            ),
            AlternativeOption(
                name="Hosted directory listing",
                summary="Use a simple business listing / Google profile until catalogue ops mature.",
                cost="Lowest",
                complexity="Lowest",
                reliability="High",
                maintainability="Trivial",
                security="Vendor-managed",
                scalability="Limited",
                user_effort="Minimal",
            ),
        ]
    elif contradictions:
        alts = [
            AlternativeOption(
                name="Keep prior decision",
                summary="Preserve the confirmed project choice and adjust the new requirement.",
                cost="Low",
                complexity="Low",
                reliability="Preserves continuity",
                maintainability="Stable",
                security="Unchanged",
                scalability="Unchanged",
                user_effort="Clarify the new need",
            ),
            AlternativeOption(
                name="Explicitly replace decision",
                summary="Supersede the prior decision with rationale and update dependent plans.",
                cost="Medium",
                complexity="Medium",
                reliability="Depends on migration",
                maintainability="Requires follow-through",
                security="Re-check assumptions",
                scalability="Re-evaluate",
                user_effort="Confirm replace",
            ),
            AlternativeOption(
                name="Hybrid / phased approach",
                summary="Meet the new goal partially without abandoning the MVP constraint.",
                cost="Medium",
                complexity="Medium",
                reliability="Good if scoped",
                maintainability="Watch dual paths",
                security="Review both paths",
                scalability="Phase 2",
                user_effort="Prioritize phases",
            ),
        ]
    return alts[:3]


def stage_recommendation(
    *,
    goals: list[str],
    contradictions: list[ContradictionFinding],
    alternatives: list[AlternativeOption],
    assumptions: list[AssumptionFinding],
) -> tuple[Recommendation | None, bool, str]:
    """Returns (recommendation, acknowledge_reasonable, verdict)."""
    if not contradictions and not any(
        a.classification in (AssumptionClass.UNVERIFIED, AssumptionClass.UNSUPPORTED)
        for a in assumptions
    ):
        verdict = (
            "Your current direction looks reasonable given the evidence in project context. "
            "I am not inventing objections."
        )
        return None, True, verdict

    top = contradictions[0] if contradictions else None
    alt_names = [a.name for a in alternatives]
    recommended = alternatives[0].name if alternatives else (
        top.resolution if top else "Clarify the blocking uncertainty before building further."
    )
    problem = top.statements[0] if top and top.statements else (goals[0] if goals else "Unresolved project tension")
    root = top.why if top else "Material assumptions remain unverified."
    trade = ""
    if len(alternatives) >= 2:
        trade = (
            f"{alternatives[0].name} optimizes honesty/cost; "
            f"{alternatives[1].name} trades more ops effort for freshness or features."
        )
    req = None
    if top and top.severity in (Severity.CRITICAL.value, Severity.HIGH.value):
        req = f"Decide how to resolve: {top.resolution}"
    rec = Recommendation(
        problem=problem,
        root_cause=root,
        recommended=recommended,
        alternatives=alt_names[1:],
        trade_offs=trade,
        implementation=alternatives[0].summary if alternatives else (top.resolution if top else ""),
        required_decision=req,
        severity=top.severity if top else Severity.MEDIUM.value,
    )
    verdict = (
        f"Main issue: {root} Recommended: {recommended}."
        if top
        else f"Verify weak assumptions before locking the plan. Suggested focus: {recommended}."
    )
    return rec, False, verdict


def stage_decision_proposals(
    recommendation: Recommendation | None,
    contradictions: list[ContradictionFinding],
) -> list[dict[str, Any]]:
    if not recommendation:
        return []
    title = "Mentor recommendation"
    if contradictions:
        field = contradictions[0].field or "approach"
        title = f"Resolve {field.replace('_', ' ')}"
    return [
        {
            "title": title[:200],
            "choice": recommendation.recommended[:500],
            "rationale": recommendation.root_cause[:1000],
            "status": "proposed",
            "source": "grill_mentor",
            "alternatives_considered": list(recommendation.alternatives)[:5],
        }
    ]


# ---------------------------------------------------------------------------
# Response formatting (user-facing; no private CoT)
# ---------------------------------------------------------------------------


def _reasoning_depth(
    result: MentorReasoning, *, mode: BehaviouralMode | str | None = None
) -> str:
    """Proportional depth: quiet | light | full — never criticize for show."""
    canon = canonical_mode(mode) if mode is not None else BehaviouralMode.EXPLORE
    material = result.prioritized_contradictions()
    critical = [c for c in material if c.severity in (Severity.CRITICAL.value, Severity.HIGH.value)]
    if not material and result.acknowledge_reasonable:
        return "quiet"
    if not critical and canon in (BehaviouralMode.EXPLORE, BehaviouralMode.BUILD):
        return "light" if material else "quiet"
    if critical or canon in (BehaviouralMode.REVIEW, BehaviouralMode.PLAN, BehaviouralMode.DEBUG):
        return "full" if critical or material else "light"
    return "light" if material else "quiet"


def format_mentor_reply(
    result: MentorReasoning,
    *,
    base_reply: str | None = None,
    mode: BehaviouralMode | str | None = None,
    expose_structure: bool = False,
) -> str:
    """
    One coherent conversational answer. Never expose internal stage names,
    mode labels, or analysis-report headings unless expose_structure=True.
    """
    depth = _reasoning_depth(result, mode=mode)
    base = (base_reply or "").strip()
    material = result.prioritized_contradictions()

    if depth == "quiet":
        if result.acknowledge_reasonable and result.verdict and not material:
            if base and result.verdict not in base:
                # Prefer answering the latest ask; add a brief nod if useful
                if len(base) >= 40:
                    return base
                return f"{base}\n\n{result.verdict}".strip()
            return base or result.verdict
        return base or result.verdict or ""

    # Conversational weaving — no **Verdict.** / report template by default
    if not expose_structure:
        bits: list[str] = []
        if base:
            bits.append(base)
        if material:
            top = material[0]
            already = bool(base) and top.why[:48].lower() in base.lower()
            if not already:
                reso = top.resolution or "resolve that before building further."
                bits.append(f"One tension to watch: {top.why} A practical path: {reso}")
            if depth == "full" and result.alternatives:
                alt = result.alternatives[0]
                bits.append(f"I'd lean toward {alt.name}: {alt.summary}")
            if depth == "full" and result.recommendation and result.recommendation.required_decision:
                bits.append(result.recommendation.required_decision)
        elif result.recommendation and depth == "full":
            r = result.recommendation
            bits.append(f"I'd recommend {r.recommended}. {r.implementation}".strip())
        # Single follow-up max
        weak_asmp = [
            a
            for a in result.assumptions
            if a.classification in (AssumptionClass.UNVERIFIED, AssumptionClass.UNSUPPORTED)
        ]
        if depth == "full" and weak_asmp and result.recommendation is None:
            bits.append(f"Worth checking: {weak_asmp[0].statement}?")
        text = "\n\n".join(b for b in bits if b).strip()
        return text or base or result.verdict or ""

    # Explicit structured form only when requested (tests / debug tooling)
    parts: list[str] = []
    if result.verdict:
        parts.append(f"**Verdict.** {result.verdict}")
    if material:
        parts.append(
            "**Main weaknesses.** "
            + " ".join(f"({i+1}) {c.why}" for i, c in enumerate(material[:3]))
        )
    if result.recommendation:
        r = result.recommendation
        parts.append(f"**Recommended approach.** {r.recommended}. {r.implementation}")
        if r.required_decision:
            parts.append(f"**Decisions required.** {r.required_decision}")
    return "\n\n".join(parts).strip() or base or result.verdict or ""


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------


def run_mentor_reasoning(
    project: ProjectState,
    user_message: str,
    *,
    mode: BehaviouralMode | str | None = None,
    patch: StatePatch | None = None,
) -> MentorReasoning:
    """
    Run reasoning stages. Stages contribute to a coherent MentorReasoning object.
    Does not call models. Safe for offline regression and engine enrichment.
    """
    result = MentorReasoning()
    mode_c = canonical_mode(mode or project.behavioural_mode)

    # 1. Intent and goals
    intent, goals = stage_intent_and_goals(user_message, project)
    result.intent = intent
    result.goals = goals
    result.stages_run.append("intent_and_goals")

    # 2. Project-context retrieval
    bundle = retrieve_relevant_context(project, mode=mode_c, user_message=user_message)
    result.context_keys = sorted(bundle.snapshot.keys())
    result.stages_run.append("project_context_retrieval")

    # 3. Contradiction detection
    cons = stage_requirement_contradictions(project, user_message)
    if patch is not None:
        cons.extend(enrich_patch_contradictions(project, patch))
    # Dedup by why
    seen: set[str] = set()
    deduped: list[ContradictionFinding] = []
    for c in cons:
        if c.why in seen:
            continue
        seen.add(c.why)
        deduped.append(c)
    # Drop issues the user already resolved / accepted / rejected unless new info
    deduped = _filter_resolved_contradictions(project, deduped, user_message)
    # Topic-shift: unrelated new asks should not revive old project tensions
    if _looks_unrelated_to_project(project, user_message):
        deduped = []
    result.contradictions = _severity_cap(deduped, keep_low_if_empty=True)
    result.stages_run.append("contradiction_detection")

    # 4. Assumption identification
    result.assumptions = stage_assumptions(project, user_message)
    if _looks_unrelated_to_project(project, user_message):
        result.assumptions = []
    result.stages_run.append("assumption_identification")

    # 5. Evidence / feasibility
    result.feasibility_notes = stage_feasibility(project, result.contradictions)
    result.stages_run.append("feasibility_assessment")

    # 6. Failure scenarios — proportional: skip when quiet / unrelated
    if result.contradictions and not _looks_unrelated_to_project(project, user_message):
        result.failure_scenarios = stage_failure_scenarios(
            project, user_message, result.contradictions
        )
    result.stages_run.append("failure_scenario_analysis")

    # 7–8. Alternatives + trade-off comparison (embedded in AlternativeOption fields)
    result.alternatives = stage_alternatives(project, result.contradictions, user_message)
    result.stages_run.append("alternative_generation")
    result.stages_run.append("tradeoff_comparison")

    # 9. Prioritized recommendation
    rec, ack, verdict = stage_recommendation(
        goals=goals,
        contradictions=result.contradictions,
        alternatives=result.alternatives,
        assumptions=result.assumptions,
    )
    result.recommendation = rec
    result.acknowledge_reasonable = ack
    result.verdict = verdict
    result.stages_run.append("prioritized_recommendation")

    # 10. Decision tracking proposals (proposed only)
    result.decision_proposals = stage_decision_proposals(rec, result.contradictions)
    result.stages_run.append("decision_tracking")

    if ack:
        result.strengths.append("No material contradictions manufactured.")

    return result


def _filter_resolved_contradictions(
    project: ProjectState,
    findings: list[ContradictionFinding],
    user_message: str,
) -> list[ContradictionFinding]:
    """Avoid re-raising previously resolved/rejected/accepted-risk issues."""
    from app.projects.models import FindingStatus

    closed = [
        f
        for f in project.findings or []
        if f.status
        in (
            FindingStatus.RESOLVED,
            FindingStatus.REJECTED,
            FindingStatus.ACCEPTED_RISK,
        )
    ]
    if not closed:
        return findings
    msg = _norm(user_message)
    kept: list[ContradictionFinding] = []
    for c in findings:
        claim_blob = _norm(" ".join(c.statements) + " " + c.why)
        revived_by_new_info = False
        # New info can revive: user reintroduces the same tension explicitly
        if any(tok and tok in msg for tok in claim_blob.split() if len(tok) > 5):
            # Only revive if message clearly re-opens it (contains conflict cues)
            if _has_any(
                msg,
                (
                    "again",
                    "still",
                    "revisit",
                    "changed my mind",
                    "instead",
                    "switch to",
                    "replace",
                ),
            ):
                revived_by_new_info = True
        matched_closed = any(
            _overlap_text(claim_blob, f.challenged_claim)
            or _overlap_text(claim_blob, f.title)
            for f in closed
        )
        if matched_closed and not revived_by_new_info:
            continue
        kept.append(c)
    return kept


def _overlap_text(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    aw, bw = set(na.split()), set(nb.split())
    if len(aw) < 2 or len(bw) < 2:
        return False
    return len(aw & bw) / max(len(aw), len(bw)) >= 0.5


def _looks_unrelated_to_project(project: ProjectState, user_message: str) -> bool:
    """True only for clear domain shifts (e.g. dinner recipe after a tech project)."""
    msg = _norm(user_message)
    if not msg or len(msg.split()) < 4:
        return False
    # Explicit project-bound / decision cues — always related
    if _has_any(
        msg,
        (
            "this project",
            "our app",
            "the stack",
            "the decision",
            "we chose",
            "our mvp",
            "same project",
            "requirement",
            "consistent",
            "contradict",
            "instead",
            "replace",
            "switch to",
        ),
    ):
        return False
    obj = _norm(project.objective or "")
    name = _norm(project.name or "")
    stack = _norm(" ".join(project.tech_stack or []))
    decisions = _norm(
        " ".join(f"{d.title} {d.choice}" for d in project.decisions or [])
    )
    reqs = _norm(
        " ".join(r.text for r in (project.functional_requirements or [])[:8])
    )
    notes = _norm(
        " ".join(
            [
                project.architecture_notes or "",
                project.problem_statement or "",
                " ".join(project.preferences or []),
            ]
        )
    )
    memory = " ".join(x for x in (obj, name, stack, decisions, reqs, notes) if x)
    if not memory.strip():
        return False
    mw, memw = set(msg.split()), set(memory.split())
    stop = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "for",
        "of",
        "in",
        "on",
        "with",
        "we",
        "i",
        "my",
        "our",
        "is",
        "are",
        "be",
        "can",
        "should",
        "want",
        "need",
        "build",
        "make",
        "use",
        "using",
        "about",
        "what",
        "how",
        "do",
        "does",
        "this",
        "that",
        "new",
        "just",
        "also",
        "from",
        "have",
        "has",
        "no",
        "not",
        "known",
    }
    mw -= stop
    memw -= stop
    if not mw:
        return False
    overlap = len(mw & memw) / max(len(mw), 1)
    if overlap >= 0.08:
        return False
    # Clear lifestyle / off-domain asks
    off_domain = _has_any(
        msg,
        (
            "recipe",
            "pasta",
            "dinner",
            "cooking",
            "weather",
            "joke",
            "lyrics",
            "horoscope",
            "workout",
            "birthday party",
        ),
    )
    return off_domain and len(mw) >= 5


def merge_reasoning_into_analysis(
    analysis_reply: str,
    project: ProjectState,
    user_message: str,
    *,
    mode: BehaviouralMode | str | None = None,
    existing_findings: list[CandidateFinding] | None = None,
    existing_patch: StatePatch | None = None,
) -> tuple[str, list[CandidateFinding], StatePatch, MentorReasoning]:
    """
    Enrich a primary analysis with mentor reasoning.
    Never converts mentor recommendations into confirmed decisions.
    User-facing reply stays one coherent conversation turn.
    """
    reasoning = run_mentor_reasoning(
        project, user_message, mode=mode, patch=existing_patch
    )
    reply = format_mentor_reply(
        reasoning, base_reply=analysis_reply, mode=mode, expose_structure=False
    )

    findings = list(existing_findings or [])
    # Skip re-opening closed findings; only add material new ones
    from app.projects.models import FindingStatus

    closed_claims = {
        _norm(f.challenged_claim)
        for f in project.findings or []
        if f.status
        in (
            FindingStatus.RESOLVED,
            FindingStatus.REJECTED,
            FindingStatus.ACCEPTED_RISK,
        )
    }
    mentor_findings = reasoning.to_findings()
    if mentor_findings:
        existing_claims = {_norm(f.challenged_claim) for f in findings}
        for mf in mentor_findings:
            key = _norm(mf.challenged_claim)
            if key in existing_claims or key in closed_claims:
                continue
            if any(_overlap_text(key, c) for c in closed_claims):
                continue
            findings.append(mf)
            existing_claims.add(key)

    hints = reasoning.to_state_patch_hints()
    patch = existing_patch or StatePatch()
    # Merge assumptions/risks/questions; keep decisions as proposed only
    merged_assumptions = list(patch.add_assumptions or [])
    for a in hints.add_assumptions or []:
        if a not in merged_assumptions:
            merged_assumptions.append(a)
    merged_risks = list(patch.add_known_risks or [])
    for r in hints.add_known_risks or []:
        if r not in merged_risks:
            merged_risks.append(r)
    merged_qs = list(patch.add_open_questions or [])
    for q in hints.add_open_questions or []:
        if q not in merged_qs:
            merged_qs.append(q)
    # Only add proposed decisions if primary did not already confirm something
    merged_decisions = list(patch.add_decisions or [])
    for d in hints.add_decisions or []:
        title = str(d.get("title") or "").lower()
        if any(str(x.get("title") or "").lower() == title for x in merged_decisions):
            continue
        merged_decisions.append(d)

    new_patch = patch.model_copy(
        update={
            "add_assumptions": merged_assumptions or None,
            "add_known_risks": merged_risks or None,
            "add_open_questions": merged_qs or None,
            "add_decisions": merged_decisions or None,
        }
    )
    return reply, findings, new_patch, reasoning
