"""Selective multi-model orchestration for Grill reviews."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.compilation.readiness import assess_readiness
from app.grill.lifecycle import apply_critic_review, merge_candidates_into_project
from app.grill.policy import ReviewAction, decide_review_policy
from app.persistence.repository import ProjectRepository
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


class GrillEngine:
    def __init__(
        self,
        *,
        repo: ProjectRepository,
        primary: ModelProvider,
        critic: ModelProvider | None,
        settings: Settings,
        using_offline_primary: bool = False,
    ) -> None:
        self.repo = repo
        self.primary = primary
        self.critic = critic
        self.settings = settings
        self.using_offline_primary = using_offline_primary

    async def handle_message(self, project_id: str, content: str) -> ChatResponse:
        project = self.repo.get(project_id)
        if project is None:
            raise KeyError(f"Project {project_id} not found")

        content = content.strip()[: self.settings.max_request_chars]
        metrics = OrchestrationMetrics()

        user_msg = Message(role="user", content=content)
        project.messages.append(user_msg)

        critic_available = bool(
            self.critic and self.critic.is_available() and self.settings.critic_enabled
        )
        policy = decide_review_policy(
            message=content,
            project=project,
            intensity=self.settings.review_intensity,
            critic_available=critic_available,
        )
        user_msg.intent = policy.detected_intent

        if policy.action == ReviewAction.CONVERSATION_ONLY:
            reply = self._conversation_only_reply(policy.detected_intent, project)
            assistant = Message(
                role="assistant",
                content=reply,
                intent=policy.detected_intent,
                provenance=ReviewProvenance.NONE,
            )
            project.messages.append(assistant)
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
            )

        analysis, metrics = await self._run_primary(project, content, metrics)

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

        should_critic = (
            policy.action in (ReviewAction.TWO_MODEL, ReviewAction.REASSESS)
            and critic_available
            and self._findings_warrant_critic(candidates, project, policy.action)
        )

        if should_critic and self.critic is not None:
            try:
                metrics.critic_calls += 1
                review = await self.critic.critique(
                    project_snapshot=self._snapshot(project),
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

        elif policy.action in (ReviewAction.TWO_MODEL, ReviewAction.REASSESS) and not critic_available:
            metrics.limitations.append(
                "Independent critic not configured or disabled; primary-only review."
            )

        if metrics.offline_review:
            metrics.limitations.append(
                "Offline heuristic review — findings are deterministic heuristics, not live model output."
            )

        # Apply state mutations exactly once after a successful (possibly failover) analysis
        project = apply_state_patch(project, analysis.state_patch)
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
            },
        )
        project.messages.append(assistant)
        project = self.repo.save(project)

        return ChatResponse(
            message=assistant,
            findings=project.findings,
            project=project,
            readiness=assess_readiness(project),
            review_limitations=metrics.limitations,
            provider_status=metrics.provider_status,
            provider_used=metrics.provider_used,
            offline_review=metrics.offline_review,
        )

    async def _run_primary(
        self,
        project: ProjectState,
        content: str,
        metrics: OrchestrationMetrics,
    ) -> tuple[PrimaryAnalysis, OrchestrationMetrics]:
        tail = [
            {"role": m.role, "content": m.content[:2000]}
            for m in project.messages[-8:]
        ]
        snapshot = self._snapshot(project)

        if isinstance(self.primary, FailoverPrimaryProvider):
            result: FailoverResult = await self.primary.run_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
            )
            metrics.primary_calls = sum(1 for a in result.attempts if not a.skipped)
            metrics.provider_status = result.status_message
            metrics.provider_used = result.provider
            metrics.offline_review = result.offline
            return result.analysis, metrics

        # Single-provider path (tests / custom wiring)
        try:
            metrics.primary_calls += 1
            if not self.primary.is_available():
                from app.providers.base import ProviderErrorKind

                raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Primary not available")
            analysis = await self.primary.analyze_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
            )
            metrics.provider_used = getattr(self.primary, "name", "primary")
            metrics.provider_status = f"{metrics.provider_used} responding"
            metrics.offline_review = False
        except ProviderError as exc:
            metrics.limitations.append(
                f"Primary provider issue ({exc.kind.value}): falling back to offline heuristics."
            )
            analysis = heuristic_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
            )
            metrics.provider_used = "offline"
            metrics.provider_status = "All external providers unavailable; offline review active"
            metrics.offline_review = True
        except Exception:
            metrics.limitations.append(
                "Primary provider unavailable; falling back to offline heuristics."
            )
            analysis = heuristic_primary(
                project_snapshot=snapshot,
                user_message=content,
                conversation_tail=tail,
            )
            metrics.provider_used = "offline"
            metrics.provider_status = "All external providers unavailable; offline review active"
            metrics.offline_review = True

        return analysis, metrics

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

    def _snapshot(self, project: ProjectState) -> dict:
        data = project.model_dump(mode="json")
        data["messages"] = [
            {"role": m["role"], "content": m["content"][:500]}
            for m in data.get("messages", [])[-6:]
        ]
        return data

    def _conversation_only_reply(self, intent: MessageIntent, project: ProjectState) -> str:
        if intent == MessageIntent.GREETING:
            if project.objective:
                return (
                    f"Hi — we're reviewing **{project.name}**. "
                    "Share a decision, constraint, or more detail and I'll challenge what looks weak."
                )
            return (
                "Hi — I'm Grill. Describe the project you want to build and I'll challenge "
                "weak assumptions before you spend agent tokens implementing it."
            )
        return "Understood. What decision or constraint should we examine next?"

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
