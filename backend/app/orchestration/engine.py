"""Selective multi-model orchestration for Grill reviews."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.compilation.readiness import assess_readiness
from app.free_tier.models import FundingSource
from app.grill.context import retrieve_relevant_context
from app.grill.lifecycle import apply_critic_review, merge_candidates_into_project
from app.grill.memory import (
    AssembledContext,
    assemble_prompt_context,
    maybe_refresh_summary,
    update_working_memory,
)
from app.grill.modes import (
    BehaviouralMode,
    MODE_LABELS,
    resolve_project_mode,
    should_run_critic,
    temperature_for_mode,
)
from app.grill.policy import ReviewAction, decide_review_policy
from app.grill.reasoning import merge_reasoning_into_analysis
from app.grill.validate import validate_analysis_for_mode
from app.inference.router import (
    InferenceRouteError,
    InferenceRouteErrorCode,
    resolve_inference,
)
from app.persistence.repository import ProjectRepository
from app.persistence.user_store import UserStore
from app.projects.models import (
    ChatResponse,
    CriticOutcome,
    FindingStatus,
    Message,
    MessageIntent,
    ProjectState,
    ReviewProvenance,
)
from app.projects.state_apply import apply_state_patch
from app.providers.base import (
    CandidateFinding,
    GenerationSettings,
    ModelProvider,
    PrimaryAnalysis,
    ProviderError,
    StatePatch,
)
from app.providers.failover import FailoverPrimaryProvider, FailoverResult
from app.providers.mock import heuristic_primary


@dataclass
class OrchestrationMetrics:
    primary_calls: int = 0
    critic_calls: int = 0
    limitations: list[str] = field(default_factory=list)
    provider_status: str | None = None
    provider_used: str | None = None
    offline_review: bool = False
    funding_source: str | None = None
    generation_id: str | None = None
    behavioural_mode: BehaviouralMode = BehaviouralMode.EXPLORE


class FreeTierExhaustedError(Exception):
    def __init__(self, message: str, code: str = "free_tier_exhausted") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class GrillEngine:
    def __init__(
        self,
        *,
        repo: ProjectRepository,
        primary: ModelProvider,
        critic: ModelProvider | None,
        settings: Settings,
        using_offline_primary: bool = False,
        user_store: UserStore | None = None,
    ) -> None:
        self.repo = repo
        self.primary = primary
        self.critic = critic
        self.settings = settings
        self.using_offline_primary = using_offline_primary
        self.user_store = user_store

    async def handle_message(
        self,
        project_id: str,
        content: str,
        *,
        user_id: str | None = None,
        idempotency_key: str | None = None,
        behavioural_mode: BehaviouralMode | None = None,
    ) -> ChatResponse:
        project = self.repo.get(project_id)
        if project is None:
            raise KeyError(f"Project {project_id} not found")

        content = content.strip()[: self.settings.max_request_chars]
        metrics = OrchestrationMetrics()

        mode = resolve_project_mode(
            project.behavioural_mode,
            content,
            explicit=behavioural_mode,
        )
        project.behavioural_mode = mode
        metrics.behavioural_mode = mode

        user_msg = Message(
            role="user",
            content=content,
            metadata={"behavioural_mode": mode.value},
        )
        project.messages.append(user_msg)

        # Resolve per-user providers when free tier / BYOK mode is active.
        primary = self.primary
        critic = self.critic
        funding: FundingSource | None = None
        route_provider: str | None = None
        route_model: str | None = None
        reservation_id: str | None = None

        if self.settings.free_tier_enabled:
            if not user_id or self.user_store is None:
                raise FreeTierExhaustedError(
                    "Authentication required to generate with free tier or BYOK.",
                    code=InferenceRouteErrorCode.AUTH_REQUIRED.value,
                )
            allowed, _remaining = self.user_store.check_and_increment_rate_limit(
                f"user:{user_id}:gen",
                limit=self.settings.free_tier_rate_limit_per_minute,
                window_seconds=60,
            )
            if not allowed:
                raise FreeTierExhaustedError(
                    "Rate limit exceeded. Please wait before generating again.",
                    code=InferenceRouteErrorCode.RATE_LIMITED.value,
                )
            try:
                resolved = resolve_inference(
                    settings=self.settings,
                    store=self.user_store,
                    user_id=user_id,
                )
            except InferenceRouteError as exc:
                raise FreeTierExhaustedError(exc.message, code=exc.code.value) from exc
            primary = resolved.primary
            critic = resolved.critic
            funding = resolved.funding_source
            route_provider = resolved.provider
            route_model = resolved.model
            metrics.funding_source = funding.value

        critic_available = bool(
            critic and critic.is_available() and self.settings.critic_enabled
        )
        policy = decide_review_policy(
            message=content,
            project=project,
            intensity=self.settings.review_intensity,
            critic_available=critic_available,
        )
        user_msg.intent = policy.detected_intent
        update_working_memory(
            project,
            user_message=content,
            intent=policy.detected_intent.value if policy.detected_intent else None,
            mode=mode,
        )

        if policy.action == ReviewAction.CONVERSATION_ONLY:
            reply = self._conversation_only_reply(policy.detected_intent, project)
            assistant = Message(
                role="assistant",
                content=reply,
                intent=policy.detected_intent,
                provenance=ReviewProvenance.NONE,
            )
            project.messages.append(assistant)
            try:
                maybe_refresh_summary(
                    project,
                    min_messages=getattr(self.settings, "summary_min_messages", 16),
                    min_new_since_summary=getattr(
                        self.settings, "summary_min_new_messages", 8
                    ),
                    keep_recent=getattr(self.settings, "summary_keep_recent", 8),
                )
            except Exception:
                pass
            project = self.repo.save(project)
            return ChatResponse(
                message=assistant,
                findings=project.findings,
                project=project,
                readiness=assess_readiness(project),
                review_limitations=metrics.limitations,
                provider_status="Conversation only — no model call",
                provider_used=None,
                offline_review=False,
                funding_source=None,
                free_tier=None,
                behavioural_mode=mode,
            )

        # Reserve platform free-tier slot before the provider call (concurrency-safe).
        if (
            funding == FundingSource.PLATFORM
            and user_id
            and self.user_store is not None
            and route_provider
            and route_model
        ):
            try:
                reservation_id = self.user_store.reserve_platform_generation(
                    user_id,
                    provider=route_provider,
                    model=route_model,
                    idempotency_key=idempotency_key,
                )
                metrics.generation_id = reservation_id
            except LookupError as exc:
                # Idempotent replay of a successful generation — load nothing new;
                # treat as already consumed and continue would be wrong. Surface clearly.
                raise FreeTierExhaustedError(
                    f"Duplicate request already completed (generation {exc.args[0]}).",
                    code="duplicate_request",
                ) from exc
            except ValueError as exc:
                raise FreeTierExhaustedError(
                    str(exc),
                    code=InferenceRouteErrorCode.FREE_TIER_EXHAUSTED.value,
                ) from exc

        try:
            analysis, metrics, assembled = await self._run_primary(
                project,
                content,
                metrics,
                primary=primary,
                behavioural_mode=mode,
            )
        except Exception as exc:
            if reservation_id and self.user_store is not None:
                self.user_store.complete_generation(
                    reservation_id,
                    success=False,
                    error_message=str(exc),
                    release_reservation=True,
                )
            raise

        # Platform Qwen failures must not silently consume another provider.
        if (
            funding == FundingSource.PLATFORM
            and metrics.offline_review
            and reservation_id
            and self.user_store is not None
        ):
            self.user_store.complete_generation(
                reservation_id,
                success=False,
                error_message=metrics.provider_status or "Qwen unavailable",
                release_reservation=True,
            )
            raise FreeTierExhaustedError(
                "Platform Qwen is unavailable. Free generation was not consumed. "
                "Try again later or configure BYOK.",
                code=InferenceRouteErrorCode.PLATFORM_PROVIDER_UNAVAILABLE.value,
            )

        # Insistence without evidence: keep existing findings, don't withdraw
        if policy.detected_intent == MessageIntent.INSISTENCE:
            analysis = PrimaryAnalysis(
                reply=(
                    "Disagreement alone isn't evidence. The open findings stay until you "
                    "provide counterevidence, change the project, or explicitly accept the risk. "
                    + (analysis.reply if analysis.reply else "")
                ).strip(),
                intent=analysis.intent,
                findings=[],
                most_important_question=analysis.most_important_question,
                state_patch=StatePatch(),
            )

        if policy.detected_intent == MessageIntent.RESOLUTION:
            analysis = PrimaryAnalysis(
                reply=analysis.reply
                or "Say which finding to resolve, reject, or accept as a risk — and why.",
                intent=analysis.intent,
                findings=[],
                most_important_question=analysis.most_important_question,
                state_patch=analysis.state_patch,
            )

        candidates = list(analysis.findings)
        provenance = ReviewProvenance.PRIMARY_ONLY
        critic_outcome: CriticOutcome | None = None
        critic_notes: str | None = None

        # Critic only in REVIEW (incl. legacy grill_review) — never for explore/plan/build.
        should_critic = (
            should_run_critic(mode)
            and policy.action in (ReviewAction.TWO_MODEL, ReviewAction.REASSESS)
            and critic_available
            and self._findings_warrant_critic(candidates, project, policy.action)
        )

        if should_critic and critic is not None:
            try:
                metrics.critic_calls += 1
                # Critic must see the same current assembled context as primary
                critic_snapshot = assembled.snapshot
                if assembled.diagnostics is not None:
                    from app.grill.context_diagnostics import snapshot_excerpt

                    ckeys, csum = snapshot_excerpt(critic_snapshot)
                    assembled.diagnostics.critic_snapshot_keys = ckeys
                    assembled.diagnostics.critic_summary_excerpt = csum
                    assembled.diagnostics.primary_critic_snapshots_identical = (
                        ckeys == assembled.diagnostics.primary_snapshot_keys
                        and csum == assembled.diagnostics.primary_summary_excerpt
                    )
                review = await critic.critique(
                    project_snapshot=critic_snapshot,
                    user_message=content,
                    candidate_findings=candidates,
                    primary_reply=analysis.reply,
                )
                candidates, critic_outcome, critic_notes = apply_critic_review(
                    candidates, review
                )
                provenance = ReviewProvenance.TWO_MODEL
            except ProviderError as exc:
                metrics.limitations.append(
                    f"Independent critic unavailable ({exc.kind.value}); proceeding with primary review only."
                )
                critic_outcome = CriticOutcome.FAILED
                provenance = ReviewProvenance.PRIMARY_ONLY

        elif (
            should_run_critic(mode)
            and policy.action in (ReviewAction.TWO_MODEL, ReviewAction.REASSESS)
            and not critic_available
        ):
            metrics.limitations.append(
                "Independent critic not configured or disabled; primary-only review."
            )

        if metrics.offline_review:
            metrics.limitations.append(
                "Offline heuristic review — findings are deterministic heuristics, not live model output."
            )

        readiness_preview = assess_readiness(project)
        validation = validate_analysis_for_mode(
            analysis,
            mode=mode,
            has_objective=bool(project.objective),
            readiness_ready=readiness_preview.ready,
        )
        if validation.warnings:
            metrics.limitations.extend(validation.warnings)
        if validation.adjusted_reply:
            analysis = PrimaryAnalysis(
                reply=validation.adjusted_reply,
                intent=analysis.intent,
                findings=analysis.findings,
                most_important_question=analysis.most_important_question,
                state_patch=analysis.state_patch,
                raw_notes=analysis.raw_notes,
            )

        # Mentor reasoning pipeline (deterministic stages) — enriches reply/findings;
        # never confirms decisions on the user's behalf.
        reply_before = analysis.reply or ""
        if assembled.diagnostics is not None:
            assembled.diagnostics.reply_before_postprocess = reply_before
        try:
            enriched_reply, enriched_findings, enriched_patch, mentor = (
                merge_reasoning_into_analysis(
                    analysis.reply or "",
                    project,
                    content,
                    mode=mode,
                    existing_findings=list(candidates),
                    existing_patch=analysis.state_patch,
                )
            )
            analysis = PrimaryAnalysis(
                reply=enriched_reply,
                intent=analysis.intent,
                findings=analysis.findings,
                most_important_question=analysis.most_important_question
                or (
                    mentor.recommendation.required_decision
                    if mentor.recommendation
                    else None
                ),
                state_patch=enriched_patch,
                raw_notes=analysis.raw_notes,
            )
            candidates = enriched_findings
            _ = mentor
        except Exception:
            pass
        if assembled.diagnostics is not None:
            assembled.diagnostics.reply_after_postprocess = analysis.reply or ""

        # Apply state mutations exactly once after a successful (possibly failover) analysis
        project, contradiction_msgs = apply_state_patch(
            project, analysis.state_patch, mode=mode
        )
        if contradiction_msgs:
            metrics.limitations.append(
                "Context contradiction detected — clarification required before overriding prior decisions."
            )
            clarifier = (
                "\n\nBefore we change course: "
                + contradiction_msgs[0]
                + " Should we keep the prior decision or explicitly replace it?"
            )
            if clarifier.strip() not in analysis.reply:
                analysis = PrimaryAnalysis(
                    reply=(analysis.reply or "").rstrip() + clarifier,
                    intent=analysis.intent,
                    findings=analysis.findings,
                    most_important_question=analysis.most_important_question
                    or contradiction_msgs[0],
                    state_patch=analysis.state_patch,
                    raw_notes=analysis.raw_notes,
                )
        if candidates:
            project.findings = merge_candidates_into_project(
                project.findings,
                candidates,
                provenance=provenance,
                critic_outcome=critic_outcome,
                critic_notes=critic_notes,
            )

        new_ids = (
            [f.id for f in project.findings if f.status == FindingStatus.OPEN][-len(candidates) :]
            if candidates
            else []
        )

        # Finalize usage accounting — only successful live generations consume allowance.
        if self.user_store is not None and user_id and funding is not None:
            if funding == FundingSource.PLATFORM and reservation_id:
                if metrics.offline_review:
                    self.user_store.complete_generation(
                        reservation_id,
                        success=False,
                        error_message="offline_review",
                        release_reservation=True,
                    )
                else:
                    self.user_store.complete_generation(
                        reservation_id,
                        success=True,
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                    )
            elif funding == FundingSource.BYOK and not metrics.offline_review:
                self.user_store.record_byok_generation(
                    user_id,
                    provider=route_provider or metrics.provider_used or "unknown",
                    model=route_model or "unknown",
                    success=True,
                    idempotency_key=idempotency_key,
                )

        assistant = Message(
            role="assistant",
            content=self._compose_reply(analysis, provenance, critic_outcome, metrics),
            intent=policy.detected_intent,
            provenance=provenance,
            finding_ids=new_ids,
            metadata={
                "policy_reason": policy.reason,
                "primary_calls": metrics.primary_calls,
                "critic_calls": metrics.critic_calls,
                "critic_outcome": critic_outcome.value if critic_outcome else None,
                "provider_used": metrics.provider_used,
                "provider_status": metrics.provider_status,
                "offline_review": metrics.offline_review,
                "funding_source": metrics.funding_source,
                "generation_id": metrics.generation_id,
                "behavioural_mode": mode.value,
            },
        )
        project.messages.append(assistant)
        # Rolling summary outside the critical LLM path (after reply assembled)
        try:
            maybe_refresh_summary(
                project,
                min_messages=getattr(self.settings, "summary_min_messages", 16),
                min_new_since_summary=getattr(
                    self.settings, "summary_min_new_messages", 8
                ),
                keep_recent=getattr(self.settings, "summary_keep_recent", 8),
            )
        except Exception:
            metrics.limitations.append("Conversation summary refresh skipped after error.")
        project = self.repo.save(project)

        free_tier_status = None
        if self.settings.free_tier_enabled and self.user_store is not None:
            from app.inference.router import build_status

            free_tier_status = build_status(
                self.settings, self.user_store, user_id
            ).model_dump()

        return ChatResponse(
            message=assistant,
            findings=project.findings,
            project=project,
            readiness=assess_readiness(project),
            review_limitations=metrics.limitations,
            provider_status=metrics.provider_status,
            provider_used=metrics.provider_used,
            offline_review=metrics.offline_review,
            funding_source=metrics.funding_source,
            free_tier=free_tier_status,
            behavioural_mode=mode,
        )

    async def _run_primary(
        self,
        project: ProjectState,
        content: str,
        metrics: OrchestrationMetrics,
        *,
        primary: ModelProvider | None = None,
        behavioural_mode: BehaviouralMode = BehaviouralMode.EXPLORE,
    ) -> tuple[PrimaryAnalysis, OrchestrationMetrics, AssembledContext]:
        provider = primary or self.primary
        max_msgs = getattr(self.settings, "history_max_messages", 12)
        max_chars = getattr(self.settings, "history_max_chars", 2000)
        assembled = self._assemble_context(
            project,
            mode=behavioural_mode,
            user_message=content,
            max_msgs=max_msgs,
            max_chars=max_chars,
        )
        tail = list(assembled.conversation_tail)
        # Ensure current user turn is present last for providers that strip trailing user
        if not tail or tail[-1].get("role") != "user" or tail[-1].get("content") != content:
            tail = tail + [{"role": "user", "content": content[:max_chars]}]
        snapshot = assembled.snapshot
        if assembled.notes:
            # Surface budget notes for operators; keep wording factual
            metrics.limitations.extend(
                n for n in assembled.notes if "budget" in n.lower() or "Excluded" in n
            )
        skill_block = self._skill_knowledge_block(behavioural_mode, content)
        gen = GenerationSettings(
            temperature=temperature_for_mode(
                behavioural_mode,
                conversational=self.settings.temperature_conversational,
                brainstorming=self.settings.temperature_brainstorming,
                grill_review=self.settings.temperature_grill_review,
                explore=getattr(self.settings, "temperature_explore", None),
                plan=getattr(self.settings, "temperature_plan", None),
                build=getattr(self.settings, "temperature_build", 0.35),
                review=getattr(self.settings, "temperature_review", None),
                debug=getattr(self.settings, "temperature_debug", 0.3),
            ),
            max_output_tokens=self.settings.max_output_tokens,
            skill_knowledge_block=skill_block,
            review_intensity=str(self.settings.review_intensity or "normal"),
        )

        if isinstance(provider, FailoverPrimaryProvider):
            result: FailoverResult = await provider.run_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
                behavioural_mode=behavioural_mode.value,
                generation=gen,
            )
            metrics.primary_calls = sum(1 for a in result.attempts if not a.skipped)
            metrics.provider_status = result.status_message
            metrics.provider_used = result.provider
            metrics.offline_review = result.offline
            return result.analysis, metrics, assembled

        # Single-provider path (tests / custom wiring / BYOK)
        try:
            metrics.primary_calls += 1
            if not provider.is_available():
                from app.providers.base import ProviderErrorKind

                raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Primary not available")
            analysis = await provider.analyze_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
                behavioural_mode=behavioural_mode.value,
                generation=gen,
            )
            metrics.provider_used = getattr(provider, "name", "primary")
            label = MODE_LABELS.get(behavioural_mode, behavioural_mode.value)
            metrics.provider_status = f"{metrics.provider_used} responding ({label})"
            metrics.offline_review = False
        except ProviderError as exc:
            # In free-tier platform mode, do not fall back to offline — surface failure.
            if metrics.funding_source == FundingSource.PLATFORM.value:
                metrics.provider_used = getattr(provider, "name", "primary")
                metrics.provider_status = f"{metrics.provider_used} failed: {exc.message}"
                metrics.offline_review = True
                metrics.limitations.append(
                    f"Platform provider issue ({exc.kind.value}): {exc.message}"
                )
                analysis = heuristic_primary(
                    project_snapshot=snapshot,
                    user_message=content,
                    conversation_tail=tail,
                    behavioural_mode=behavioural_mode.value,
                )
                return analysis, metrics, assembled

            metrics.limitations.append(
                f"Primary provider issue ({exc.kind.value}): falling back to offline heuristics."
            )
            analysis = heuristic_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
                behavioural_mode=behavioural_mode.value,
            )
            metrics.provider_used = "offline"
            metrics.provider_status = "All external providers unavailable; offline review active"
            metrics.offline_review = True
        except Exception:
            if metrics.funding_source == FundingSource.PLATFORM.value:
                metrics.provider_used = getattr(provider, "name", "primary")
                metrics.provider_status = f"{metrics.provider_used} failed"
                metrics.offline_review = True
                metrics.limitations.append("Platform provider unavailable")
                analysis = heuristic_primary(
                    project_snapshot=snapshot,
                    user_message=content,
                    conversation_tail=tail,
                    behavioural_mode=behavioural_mode.value,
                )
                return analysis, metrics, assembled

            metrics.limitations.append(
                "Primary provider unavailable; falling back to offline heuristics."
            )
            analysis = heuristic_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
                behavioural_mode=behavioural_mode.value,
            )
            metrics.provider_used = "offline"
            metrics.provider_status = "All external providers unavailable; offline review active"
            metrics.offline_review = True

        return analysis, metrics, assembled

    def _findings_warrant_critic(
        self,
        candidates: list[CandidateFinding],
        project: ProjectState,
        action: ReviewAction,
    ) -> bool:
        if action == ReviewAction.REASSESS:
            return True
        if not candidates:
            return False
        sev = {c.severity.lower() for c in candidates}
        if sev & {"critical", "high"}:
            return True
        if self.settings.review_intensity == "high":
            return True
        return True

    def _skill_knowledge_block(
        self, behavioural_mode: BehaviouralMode, user_message: str
    ) -> str | None:
        """Orchestrate relevant skills and inject a compact principle block (never full books)."""
        try:
            from app.api.deps import get_knowledge_store, get_skill_registry
            from app.skills.orchestrator import build_orchestration_context

            store = get_knowledge_store()
            registry = get_skill_registry()
            plan = build_orchestration_context(
                registry,
                store,
                mode=behavioural_mode,
                user_message=user_message,
            )
            block = (plan.prompt_block or "").strip()
            return block or None
        except Exception:
            # Retrieval must never break chat
            return None

    def _snapshot(
        self,
        project: ProjectState,
        *,
        mode: BehaviouralMode | None = None,
        user_message: str = "",
    ) -> dict:
        """Mode-aware structured context (Context Management Engine)."""
        active = mode or project.behavioural_mode
        bundle = retrieve_relevant_context(
            project, mode=active, user_message=user_message
        )
        return bundle.as_prompt_json()

    def _assemble_context(
        self,
        project: ProjectState,
        *,
        mode: BehaviouralMode,
        user_message: str,
        max_msgs: int,
        max_chars: int,
    ):
        structured = self._snapshot(
            project, mode=mode, user_message=user_message
        )
        return assemble_prompt_context(
            project,
            mode=mode,
            user_message=user_message,
            structured_snapshot=structured,
            max_recent_messages=max_msgs,
            max_chars_each=max_chars,
            max_summary_chars=getattr(self.settings, "context_max_summary_chars", 4000),
            max_total_chars=getattr(self.settings, "context_max_total_chars", 28_000),
        )

    def _conversation_only_reply(self, intent: MessageIntent, project: ProjectState) -> str:
        if intent == MessageIntent.GREETING:
            if project.objective:
                return (
                    f"Hi — we're continuing **{project.name}**. "
                    "Share a decision, constraint, or more detail and I'll help you pressure-test it."
                )
            return (
                "Hi — I'm VibePrompt. Describe the project you want to build "
                "and I'll help you clarify the problem before you spend agent tokens implementing it."
            )
        return "Understood. What should we tackle next?"

    def _compose_reply(
        self,
        analysis: PrimaryAnalysis,
        provenance: ReviewProvenance,
        critic_outcome: CriticOutcome | None,
        metrics: OrchestrationMetrics,
    ) -> str:
        parts = [analysis.reply.strip()]
        if provenance == ReviewProvenance.TWO_MODEL and critic_outcome not in (
            CriticOutcome.FAILED,
            CriticOutcome.SKIPPED,
            None,
        ):
            parts.append("_Reviewed with an independent critic model._")
        return "\n\n".join(p for p in parts if p)
