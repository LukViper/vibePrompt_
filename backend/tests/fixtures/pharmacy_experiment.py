"""Pharmacy conversation fixture for Grill Mentor regression (cases A–I)."""

from __future__ import annotations

from app.grill.modes import BehaviouralMode
from app.projects.models import (
    Assumption,
    Constraint,
    Decision,
    ProjectState,
    Requirement,
)


PHARMACY_OBJECTIVE = (
    "Help a local Indian pharmacy publish medicine availability online so nearby "
    "customers can discover stock — without pretending to be Tata 1mg on day one."
)


def build_pharmacy_project() -> ProjectState:
    """Shared project state encoding the pharmacy experiment tensions."""
    return ProjectState(
        name="Local Pharmacy Catalogue MVP",
        objective=PHARMACY_OBJECTIVE,
        problem_statement=(
            "Customers call to ask if medicines are in stock. Owner wants a simple "
            "online presence using Marg billing data via weekly CSV uploads."
        ),
        intended_users=["Local walk-in customers", "Pharmacy counter staff"],
        success_criteria=[
            "Customers can see approximate availability before visiting",
            "Staff can update catalogue without hiring a full-time developer",
        ],
        functional_requirements=[
            Requirement(
                text="Show medicine catalogue with prices sourced from Marg billing software"
            ),
            Requirement(text="Support easy bulk CSV uploads for inventory"),
            Requirement(text="WordPress website for professional appearance"),
        ],
        constraints=[
            Constraint(text="Small initial budget", category="resource"),
            Constraint(text="No ongoing developer dependency preferred", category="skill"),
            Constraint(text="No known Marg API integration available today", category="tech"),
        ],
        decisions=[
            Decision(
                title="CMS",
                choice="WordPress",
                rationale="Familiar, low cost for a brochure + catalogue site",
                status="confirmed",
                source="user",
            ),
            Decision(
                title="Inventory source",
                choice="Weekly CSV export from Marg",
                rationale="Owner can export from existing billing software",
                status="confirmed",
                source="user",
            ),
        ],
        assumptions=[
            Assumption(
                statement="Exact Marg prices can be shown as live customer prices from weekly CSV",
            ),
            Assumption(
                statement="Real-time synchronization is required for a professional look",
            ),
            Assumption(
                statement="Online medicine listing/sales in India need no special license for MVP",
            ),
        ],
        preferences=[
            "Look professional like Tata 1mg",
            "Hide availability uncertainty from customers",
            "Prefer WooCommerce if WordPress is chosen",
            "Stock changes quickly during the day",
            "No manual staff updates between weekly CSVs",
            "Custom software must still be maintainable without a developer",
            "Enquiry / visit store — not full online checkout yet",
        ],
        architecture_notes=(
            "Proposed: WordPress + WooCommerce, bulk CSV overwrite uploads, "
            "exact Marg pricing, real-time sync expectations, small budget, "
            "India online medicine listing."
        ),
        known_risks=[],
        behavioural_mode=BehaviouralMode.REVIEW,
    )


# Review prompts that should surface each conflict without inventing extras
CASE_PROMPTS: dict[str, str] = {
    "A": (
        "Review our plan: we will show exact Marg pricing on the website using the "
        "weekly CSV inventory export. Is that sound?"
    ),
    "B": (
        "We need real-time synchronization of stock, but we have no known integration "
        "with Marg and no manual updates between exports. Challenge this."
    ),
    "C": (
        "We want a professional appearance and also want to hide availability "
        "uncertainty from customers. What do you think?"
    ),
    "D": (
        "Customers expect a Tata 1mg-level experience but we only have a small initial "
        "budget. How should we decide?"
    ),
    "E": (
        "We will update via weekly CSV even though stock changes quickly / rapidly "
        "during the day. Is weekly enough?"
    ),
    "F": (
        "Staff love easy bulk CSV uploads that replace the catalogue. We have no dry run "
        "or backup — any risk of accidental catalogue overwrites?"
    ),
    "G": (
        "Requirement: no developer dependency, but we are also planning custom software "
        "maintenance ourselves. Please review."
    ),
    "H": (
        "We chose WordPress for a catalogue-only / enquiry-only site (no online payment, "
        "no checkout). Is enabling WooCommerce unnecessary here?"
    ),
    "I": (
        "We plan to list and eventually sell medicines online in India. We assumed "
        "no license needed and that it should be fine. Challenge regulatory assumptions."
    ),
}


EXPECTED_FIELDS: dict[str, str] = {
    "A": "pricing",
    "B": "inventory_sync",
    "C": "ux_honesty",
    "D": "scope_budget",
    "E": "update_cadence",
    "F": "bulk_upload",
    "G": "ops_ownership",
    "H": "cms_commerce",
    "I": "regulatory",
}
