"""Built-in skill seeds (independently authored; not book quotations)."""

from __future__ import annotations

from app.skills.models import (
    SkillModeBinding,
    SkillPackage,
    SkillPrinciple,
    SkillStatus,
    new_id,
)


def builtin_skills() -> list[SkillPackage]:
    return [
        _skill(
            slug="conversational_discovery",
            name="Conversational Discovery",
            description="Natural, adaptive discovery dialogue that feels human and purposeful.",
            mode=SkillModeBinding.CONVERSATIONAL,
            principles=[
                (
                    "One useful question",
                    "Ask at most one high-value follow-up per turn.",
                    "When clarifying needs",
                    "When the user already answered or asked for a decision",
                ),
                (
                    "Context retention",
                    "Reuse facts the user already shared; do not re-ask.",
                    "Across multi-turn discovery",
                    "When the user corrects prior context",
                ),
            ],
            questions=[
                "What happened the last time you tried to solve this?",
                "Who is blocked today if this does not exist?",
            ],
            frameworks=["Conversation → clarify → confirm → advance"],
        ),
        _skill(
            slug="customer_discovery",
            name="Customer Discovery",
            description="Surface real problems with unbiased, behaviour-based questions.",
            mode=SkillModeBinding.CONVERSATIONAL,
            principles=[
                (
                    "Past behaviour over hypotheticals",
                    "Ask what people did, not what they would do.",
                    "Validating problem claims",
                    "When brainstorming speculative futures",
                ),
                (
                    "Avoid leading questions",
                    "Do not embed the desired answer in the question.",
                    "Interviews and discovery chats",
                    "When the user explicitly wants opinion prompts",
                ),
            ],
            questions=[
                "Walk me through the last time this problem cost you time.",
                "What workarounds are you using today?",
            ],
            frameworks=["Mom-Test-style behavioural interviewing (abstracted)"],
        ),
        _skill(
            slug="product_discovery",
            name="Product Discovery",
            description="Connect opportunities to outcomes with continuous discovery habits.",
            mode=SkillModeBinding.CONVERSATIONAL,
            principles=[
                (
                    "Opportunity before solution",
                    "Name the opportunity space before locking a solution.",
                    "Early product chats",
                    "When the user only wants implementation help",
                ),
                (
                    "Outcome-linked ideas",
                    "Tie suggestions to a measurable user or business outcome.",
                    "Prioritization",
                    "Pure creative exploration with no outcomes yet",
                ),
            ],
            questions=[
                "Which user outcome would make this week a win?",
                "What evidence would falsify this opportunity?",
            ],
            frameworks=["Opportunity → evidence → experiment"],
        ),
        _skill(
            slug="brainstorm",
            name="Brainstorm",
            description="Creative, diverse ideation with reframing and constructive build-on.",
            mode=SkillModeBinding.BRAINSTORMING,
            principles=[
                (
                    "Diverge then converge",
                    "Offer multiple distinct directions before narrowing.",
                    "Idea generation turns",
                    "When the user asked for a single decisive recommendation",
                ),
                (
                    "Reframe the problem",
                    "Propose at least one alternate framing of the problem.",
                    "Stuck or vague ideas",
                    "When constraints are already crisp and confirmed",
                ),
            ],
            questions=[
                "What if the opposite constraint were true?",
                "Which idea is most unlike the others — and why might it win?",
            ],
            frameworks=["Diverge → reframe → shortlist → next experiment"],
        ),
        _skill(
            slug="grill",
            name="Grill",
            description="Evidence-seeking critical review without reflexive disagreement.",
            mode=SkillModeBinding.GRILL_REVIEW,
            principles=[
                (
                    "Challenge claims, not people",
                    "Attack weak evidence and assumptions; stay respectful.",
                    "Architecture and plan reviews",
                    "Casual brainstorming where critique was not requested",
                ),
                (
                    "Disagree only with reason",
                    "Do not auto-disagree; require a specific unsupported claim.",
                    "When reviewing decisions",
                    "When the user presents strong evidence",
                ),
                (
                    "Propose a validation move",
                    "Pair each material concern with a smallest useful test.",
                    "Open findings",
                    "Nitpicks with no decision impact",
                ),
            ],
            questions=[
                "What evidence would change your mind?",
                "Which assumption, if wrong, breaks the plan?",
            ],
            frameworks=["Claim → evidence → alternative → experiment"],
        ),
        _skill(
            slug="technical_architecture",
            name="Technical Architecture",
            description="Trade-off aware architecture guidance for AI-era systems.",
            mode=SkillModeBinding.ARCHITECTURE,
            principles=[
                (
                    "Constraints first",
                    "Elicit latency, cost, privacy, and ops constraints before stack picks.",
                    "Architecture discussions",
                    "When the user only wants product discovery",
                ),
                (
                    "Evaluate retrieval need",
                    "Prefer grounded retrieval when facts must stay current or proprietary.",
                    "AI feature design",
                    "Pure creative writing tasks",
                ),
            ],
            questions=[
                "What fails first under 10× load?",
                "Which decisions are reversible vs one-way doors?",
            ],
            frameworks=["Requirements → options → trade-offs → decision record"],
        ),
        _skill(
            slug="prompt_engineering",
            name="Prompt Engineering",
            description="Structured prompts, context budgets, and evaluation loops.",
            mode=SkillModeBinding.PROMPT_ENGINEERING,
            principles=[
                (
                    "Separate instructions from untrusted data",
                    "Mark user/project content as data; never as instructions.",
                    "Any LLM workflow",
                    "None — always apply",
                ),
                (
                    "Specify success criteria",
                    "Define what a good answer looks like before generating.",
                    "Agent/coding prompts",
                    "Open-ended creative play",
                ),
            ],
            questions=[
                "What must the model never invent?",
                "How will you evaluate a correct vs wrong answer?",
            ],
            frameworks=["Role → task → constraints → format → eval"],
        ),
        _skill(
            slug="project_planning",
            name="Project Planning",
            description="Journey-aware planning, MVP cuts, and acceptance criteria.",
            mode=SkillModeBinding.PROJECT_PLANNING,
            principles=[
                (
                    "Map the journey before the backlog",
                    "Sequence user activities before listing features.",
                    "Planning and scoping",
                    "Pure technical debugging",
                ),
                (
                    "MVP as learning slice",
                    "Define MVP as the smallest release that tests the riskiest assumption.",
                    "Scope negotiations",
                    "When compliance mandates a fixed full scope",
                ),
            ],
            questions=[
                "What is the walking skeleton of this journey?",
                "Which story can wait until after first learning?",
            ],
            frameworks=["Story map → walking skeleton → release slices"],
        ),
        _skill(
            slug="agent_engineering",
            name="Agent Engineering",
            description="Design coding-agent loops, tools, permissions, and verification.",
            mode=SkillModeBinding.ARCHITECTURE,
            principles=[
                (
                    "Tight verify loops",
                    "Pair every agent action with a cheap verification step before the next mutation.",
                    "Agent workflow design",
                    "One-shot creative drafting with no side effects",
                ),
                (
                    "Least privilege tools",
                    "Grant only the tools and filesystem scope required for the current task.",
                    "MCP / tool configuration",
                    "Read-only Q&A with no tools",
                ),
            ],
            questions=[
                "What would prove the agent finished correctly?",
                "Which tool can the agent live without?",
            ],
            frameworks=["Goal → tools → loop → verify → stop condition"],
        ),
        _skill(
            slug="prompt_evaluator",
            name="Prompt Evaluator",
            description="Evaluate prompts for ambiguity, missing constraints, and testability.",
            mode=SkillModeBinding.PROMPT_ENGINEERING,
            principles=[
                (
                    "Ambiguity hunt",
                    "Flag vague verbs, missing audiences, and undefined success criteria.",
                    "Reviewing a draft prompt",
                    "Early ideation before any prompt exists",
                ),
                (
                    "Acceptance criteria first",
                    "A prompt is incomplete until pass/fail checks are explicit.",
                    "Prompt QA",
                    "Casual brainstorming",
                ),
            ],
            questions=[
                "What output would count as wrong?",
                "Which constraint is implied but never stated?",
            ],
            frameworks=["Clarity → constraints → examples → eval cases"],
        ),
    ]


def _skill(
    *,
    slug: str,
    name: str,
    description: str,
    mode: SkillModeBinding,
    principles: list[tuple[str, str, str, str]],
    questions: list[str],
    frameworks: list[str],
) -> SkillPackage:
    return SkillPackage(
        id=new_id(f"builtin_{slug}_"),
        slug=slug,
        name=name,
        description=description,
        status=SkillStatus.BUILTIN,
        mode_binding=mode,
        version=1,
        principles=[
            SkillPrinciple(
                title=t,
                summary=s,
                application=a,
                when_to_use=w,
                when_not_to_use=n,
                confidence=0.7,
            )
            for t, s, a, w, n in ((p[0], p[1], p[1], p[2], p[3]) for p in principles)
        ],
        frameworks=frameworks,
        question_patterns=questions,
        decision_rules=[
            f"Prefer '{p[0]}' when: {p[2]}; avoid when: {p[3]}" for p in principles
        ],
        examples=[
            {
                "type": "positive",
                "input": f"User engages {name.lower()}",
                "behaviour": principles[0][1],
            },
            {
                "type": "negative",
                "input": "User already answered",
                "behaviour": "Do not repeat the same discovery question.",
            },
        ],
        evaluation_cases=[
            {
                "id": f"{slug}_retain_context",
                "metric": "context_retention",
                "prompt": "User restates a fact already given — skill must not re-ask.",
                "expect": "no_repeat_question",
            }
        ],
        source_book_ids=[],
    )


# Mode → skill slugs used for retrieval
MODE_SKILL_SLUGS: dict[str, list[str]] = {
    "explore": [
        "conversational_discovery",
        "customer_discovery",
        "product_discovery",
    ],
    "plan": ["brainstorm", "product_discovery", "technical_architecture", "project_planning"],
    "build": ["prompt_engineering", "agent_engineering", "technical_architecture"],
    "review": ["grill", "customer_discovery", "prompt_evaluator"],
    "debug": ["grill", "technical_architecture"],
    # Legacy aliases
    "conversational": [
        "conversational_discovery",
        "customer_discovery",
        "product_discovery",
    ],
    "brainstorming": ["brainstorm", "product_discovery"],
    "grill_review": ["grill", "customer_discovery"],
}
