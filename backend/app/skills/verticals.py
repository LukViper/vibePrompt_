"""Curated vertical skill packs (healthtech, fintech, SaaS) — independently authored."""

from __future__ import annotations

from app.skills.models import (
    SkillModeBinding,
    SkillPackage,
    SkillPrinciple,
    SkillStatus,
    new_id,
)


def vertical_skill_packs() -> list[SkillPackage]:
    return [
        _pack(
            slug="vertical_healthtech_compliance",
            name="Healthtech Compliance Grill",
            description="Pre-loaded compliance challenges for clinical / PHI-adjacent products.",
            vertical="healthtech",
            principles=[
                (
                    "PHI boundary first",
                    "Ask where PHI is stored, processed, and who is the covered entity vs vendor.",
                    "Any health data claim",
                    "Pure wellness with no identifiable health data",
                ),
                (
                    "Audit trail requirement",
                    "Challenge designs without immutable access logs for clinical actions.",
                    "Clinical workflows",
                    "Marketing-only sites",
                ),
                (
                    "BAA before vendor lock",
                    "Reject vendor choices that cannot sign a BAA when PHI is in scope.",
                    "Third-party infra with PHI",
                    "Non-PHI analytics only",
                ),
            ],
            findings=[
                "PHI residency and encryption-at-rest not evidenced",
                "No break-glass / emergency access policy",
            ],
        ),
        _pack(
            slug="vertical_fintech_controls",
            name="Fintech Controls Grill",
            description="Money-movement, KYC/AML, and ledger integrity challenges.",
            vertical="fintech",
            principles=[
                (
                    "Double-entry or explain",
                    "Challenge balances that are not derived from an append-only ledger.",
                    "Wallet / balance features",
                    "Display-only market data",
                ),
                (
                    "Idempotent money moves",
                    "Require idempotency keys and replay protection on transfers.",
                    "Payment / payout APIs",
                    "Read-only reporting",
                ),
                (
                    "KYC gate before risk",
                    "Block high-risk actions until KYC/AML status is explicit in state.",
                    "Onboarding to transact",
                    "Educational sandboxes with fake money",
                ),
            ],
            findings=[
                "No reconciliation job for ledger vs processor",
                "Chargeback / dispute path undefined",
            ],
        ),
        _pack(
            slug="vertical_saas_tenancy",
            name="SaaS Multi-tenant Grill",
            description="Tenant isolation, RBAC, and noisy-neighbor challenges for B2B SaaS.",
            vertical="saas",
            principles=[
                (
                    "Tenant id on every query",
                    "Challenge data paths that omit org/tenant predicates.",
                    "Shared-database SaaS",
                    "Single-tenant dedicated deploys",
                ),
                (
                    "Export + delete rights",
                    "Require customer data export and deletion runbooks before GA.",
                    "B2B contracts",
                    "Internal tools only",
                ),
                (
                    "Seat vs usage metering",
                    "Clarify billing unit (seat, project, API call) before growth claims.",
                    "Pricing conversations",
                    "Free internal prototypes",
                ),
            ],
            findings=[
                "Cross-tenant cache key collision risk",
                "Admin impersonation without audit",
            ],
        ),
    ]


def _pack(
    *,
    slug: str,
    name: str,
    description: str,
    vertical: str,
    principles: list[tuple[str, str, str, str]],
    findings: list[str],
) -> SkillPackage:
    return SkillPackage(
        id=new_id(f"vert_{slug}_"),
        slug=slug,
        name=name,
        description=description,
        status=SkillStatus.ACTIVE,
        mode_binding=SkillModeBinding.GRILL_REVIEW,
        principles=[
            SkillPrinciple(
                title=t,
                summary=s,
                application=s,
                when_to_use=w,
                when_not_to_use=n,
                confidence=0.75,
            )
            for t, s, w, n in principles
        ],
        frameworks=[f"vertical:{vertical}"],
        question_patterns=[f"How do you evidence: {f}?" for f in findings],
        decision_rules=[
            f"[{vertical}] Prefer '{p[0]}' when: {p[2]}; avoid when: {p[3]}"
            for p in principles
        ],
        examples=[
            {
                "type": "vertical",
                "vertical": vertical,
                "finding_seeds": findings,
            }
        ],
    )


def playbook_to_skill(
    *,
    org_id: str,
    title: str,
    content: str,
    vertical: str | None = None,
) -> SkillPackage:
    """Convert an org internal playbook into a Grill skill draft."""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    bullets = [
        ln.lstrip("-*• ").strip()
        for ln in lines
        if ln.startswith(("-", "*", "•"))
    ]
    principles_src = bullets[:8] or lines[:5] or ["Follow internal playbook rules."]
    slug_base = "".join(c if c.isalnum() else "_" for c in title.lower())[:40] or "playbook"
    vert = vertical or "custom"
    return SkillPackage(
        id=new_id("orgplay_"),
        slug=f"org_{org_id[:8]}_{slug_base}",
        name=title.strip()[:120],
        description=f"Org playbook skill ({vert}).",
        status=SkillStatus.DRAFT,
        mode_binding=SkillModeBinding.GRILL_REVIEW,
        principles=[
            SkillPrinciple(
                title=(p[:80] or "Playbook rule"),
                summary=p,
                application=p,
                when_to_use="When reviewing projects in this organization",
                when_not_to_use="When the playbook is explicitly waived with evidence",
                confidence=0.65,
            )
            for p in principles_src
        ],
        frameworks=["org-playbook", f"vertical:{vert}"],
        question_patterns=[
            f"Does the plan comply with: {p[:100]}?" for p in principles_src[:5]
        ],
        decision_rules=[f"Org playbook ({org_id}): {p[:120]}" for p in principles_src],
        examples=[{"type": "org_playbook", "org_id": org_id, "vertical": vert}],
    )


# Extend grill_review retrieval with vertical packs when seeded
VERTICAL_SLUGS = [s.slug for s in vertical_skill_packs()]
