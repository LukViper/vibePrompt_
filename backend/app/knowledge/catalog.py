"""Curated target books for VibePrompt Book-to-Skill (legal acquisition metadata only)."""

from __future__ import annotations

from typing import Any

# Independently curated discovery records. full_text_authorized=False unless
# the work is known public-domain / open-access with a verified download URL.
TARGET_BOOKS: list[dict[str, Any]] = [
    {
        "slug": "conversational_design",
        "title": "Conversational Design",
        "author": "Erika Hall",
        "publisher": "A Book Apart",
        "isbn": "9781937557676",
        "year": 2018,
        "category": "conversational_design",
        "target_skill": "conversational_discovery",
        "purpose": (
            "Natural conversational interaction, interface design, "
            "question sequencing, reducing robotic responses."
        ),
        "official_pages": [
            "https://abookapart.com/products/conversational-design",
        ],
        "formats": ["epub", "pdf", "print"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "A Book Apart (official)",
                "url": "https://abookapart.com/products/conversational-design",
            },
            {
                "kind": "library",
                "label": "Institutional / public library ebook lending",
                "url": None,
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": (
            "Commercial title. Acquire via purchase or authorized library lending. "
            "Upload only if you hold processing rights."
        ),
    },
    {
        "slug": "the_mom_test",
        "title": "The Mom Test",
        "author": "Rob Fitzpatrick",
        "publisher": "Founder Centric / Robfitz Ltd",
        "isbn": "9780994182722",
        "year": 2013,
        "category": "customer_discovery",
        "target_skill": "customer_discovery",
        "purpose": (
            "Unbiased questions, real user problems, avoiding leading questions, "
            "assumption validation."
        ),
        "official_pages": [
            "https://www.momtestbook.com/",
        ],
        "formats": ["ebook", "print", "audiobook"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "Official site / major ebook retailers",
                "url": "https://www.momtestbook.com/",
            },
            {
                "kind": "library",
                "label": "Library ebook lending where licensed",
                "url": None,
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": (
            "Commercial title. No authorized free full-text download known. "
            "Manual upload requires rights confirmation."
        ),
    },
    {
        "slug": "continuous_discovery_habits",
        "title": "Continuous Discovery Habits",
        "author": "Teresa Torres",
        "publisher": "Product Talk LLC",
        "isbn": "9781736633304",
        "year": 2021,
        "category": "product_discovery",
        "target_skill": "product_discovery",
        "purpose": (
            "Opportunity identification, customer needs, continuous discovery, "
            "evaluating product opportunities."
        ),
        "official_pages": [
            "https://www.producttalk.org/book/",
        ],
        "formats": ["ebook", "print", "audiobook"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "Product Talk / retailers",
                "url": "https://www.producttalk.org/book/",
            },
            {
                "kind": "library",
                "label": "Library lending where licensed",
                "url": None,
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": "Commercial title. Purchase or licensed lending only.",
    },
    {
        "slug": "the_scout_mindset",
        "title": "The Scout Mindset",
        "author": "Julia Galef",
        "publisher": "Portfolio / Penguin Random House",
        "isbn": "9780735217553",
        "year": 2021,
        "category": "critical_thinking",
        "target_skill": "grill",
        "purpose": (
            "Challenging assumptions, cognitive biases, evidence-based reasoning, "
            "intellectual honesty."
        ),
        "official_pages": [
            "https://www.penguinrandomhouse.com/books/566669/the-scout-mindset-by-julia-galef/",
        ],
        "formats": ["ebook", "print", "audiobook"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "Publisher / retailers",
                "url": "https://www.penguinrandomhouse.com/books/566669/the-scout-mindset-by-julia-galef/",
            },
            {
                "kind": "library",
                "label": "Library lending where licensed",
                "url": None,
            },
            {
                "kind": "preview",
                "label": "Google Books preview (not a full download)",
                "url": "https://books.google.com/books?id=scout-mindset-preview",
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": (
            "Commercial title. Google Books preview is not permission to download "
            "the complete work."
        ),
    },
    {
        "slug": "ai_engineering",
        "title": "AI Engineering",
        "author": "Chip Huyen",
        "publisher": "O'Reilly Media",
        "isbn": "9781098166304",
        "year": 2025,
        "category": "ai_engineering",
        "target_skill": "technical_architecture",
        "purpose": (
            "Foundation model applications, RAG, evaluation, agents, "
            "inference optimization, production AI systems."
        ),
        "official_pages": [
            "https://www.oreilly.com/library/view/ai-engineering/9781098166298/",
            "https://huyenchip.com/",
        ],
        "formats": ["ebook", "print", "safari/oreilly"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "O'Reilly store / retailers",
                "url": "https://www.oreilly.com/library/view/ai-engineering/9781098166298/",
            },
            {
                "kind": "subscription",
                "label": "O'Reilly Online Learning (subscription access)",
                "url": "https://www.oreilly.com/",
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": (
            "Commercial O'Reilly title. Do not scrape Online Learning. "
            "Upload only editions you are licensed to process."
        ),
    },
    {
        "slug": "prompt_engineering_for_llms",
        "title": "Prompt Engineering for LLMs",
        "author": "John Berryman and Albert Ziegler",
        "publisher": "O'Reilly Media",
        "isbn": "9781098153434",
        "year": 2024,
        "category": "prompt_engineering",
        "target_skill": "prompt_engineering",
        "purpose": (
            "Prompt construction, context management, structured instructions, "
            "prompt evaluation, LM workflows."
        ),
        "official_pages": [
            "https://www.oreilly.com/library/view/prompt-engineering-for/9781098156145/",
        ],
        "formats": ["ebook", "print", "safari/oreilly"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "O'Reilly store / retailers",
                "url": "https://www.oreilly.com/library/view/prompt-engineering-for/9781098156145/",
            },
            {
                "kind": "subscription",
                "label": "O'Reilly Online Learning",
                "url": "https://www.oreilly.com/",
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": "Commercial title. No free authorized full-text download.",
    },
    {
        "slug": "creative_confidence",
        "title": "Creative Confidence",
        "author": "Tom Kelley and David Kelley",
        "publisher": "Crown Business",
        "isbn": "9780385349369",
        "year": 2013,
        "category": "creative_thinking",
        "target_skill": "brainstorm",
        "purpose": (
            "Creative problem-solving, idea exploration, experimentation, "
            "reframing, unconventional solutions."
        ),
        "official_pages": [
            "https://www.penguinrandomhouse.com/books/220148/creative-confidence-by-tom-kelley-and-david-kelley/",
        ],
        "formats": ["ebook", "print", "audiobook"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "Publisher / retailers",
                "url": "https://www.penguinrandomhouse.com/books/220148/creative-confidence-by-tom-kelley-and-david-kelley/",
            },
            {
                "kind": "library",
                "label": "Library lending where licensed",
                "url": None,
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": "Commercial title. Purchase or library lending only.",
    },
    {
        "slug": "user_story_mapping",
        "title": "User Story Mapping",
        "author": "Jeff Patton",
        "publisher": "O'Reilly Media",
        "isbn": "9781491904909",
        "year": 2014,
        "category": "project_planning",
        "target_skill": "project_planning",
        "purpose": (
            "User journey mapping, user stories, feature prioritization, "
            "MVP definition, development planning."
        ),
        "official_pages": [
            "https://www.oreilly.com/library/view/user-story-mapping/9781491904893/",
        ],
        "formats": ["ebook", "print", "safari/oreilly"],
        "legal_options": [
            {
                "kind": "purchase",
                "label": "O'Reilly store / retailers",
                "url": "https://www.oreilly.com/library/view/user-story-mapping/9781491904893/",
            },
            {
                "kind": "subscription",
                "label": "O'Reilly Online Learning",
                "url": "https://www.oreilly.com/",
            },
        ],
        "full_text_authorized": False,
        "authorized_download_url": None,
        "licensing_notes": "Commercial title. No free authorized full-text download.",
    },
]


def get_catalog_entry(slug: str) -> dict[str, Any] | None:
    for book in TARGET_BOOKS:
        if book["slug"] == slug:
            return dict(book)
    return None


def list_catalog() -> list[dict[str, Any]]:
    return [dict(b) for b in TARGET_BOOKS]
