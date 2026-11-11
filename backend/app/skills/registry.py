"""Skill registry — seeds builtins and exposes lookup helpers."""

from __future__ import annotations

from threading import Lock

from app.knowledge.store import KnowledgeStore
from app.skills.builtin import MODE_SKILL_SLUGS, builtin_skills
from app.skills.models import SkillPackage, SkillStatus


class SkillRegistry:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store
        self._lock = Lock()
        self.ensure_builtins()

    def ensure_builtins(self) -> None:
        with self._lock:
            existing = {s.slug for s in self.store.list_skills()}
            for skill in builtin_skills():
                if skill.slug not in existing:
                    self.store.upsert_skill(skill)

    def get(self, skill_id: str) -> SkillPackage | None:
        return self.store.get_skill(skill_id)

    def get_by_slug(self, slug: str) -> SkillPackage | None:
        return self.store.get_skill_by_slug(slug)

    def list_active_for_mode(self, mode: str) -> list[SkillPackage]:
        slugs = MODE_SKILL_SLUGS.get(mode, [])
        out: list[SkillPackage] = []
        for slug in slugs:
            skill = self.get_by_slug(slug)
            if skill and skill.status in {SkillStatus.ACTIVE, SkillStatus.BUILTIN}:
                out.append(skill)
        # Also include any active skill explicitly bound to this mode
        for summary in self.store.list_skills():
            if summary.slug in slugs:
                continue
            if (
                summary.mode_binding
                and summary.mode_binding.value == mode
                and summary.status in {SkillStatus.ACTIVE, SkillStatus.BUILTIN}
            ):
                pkg = self.get(summary.id)
                if pkg:
                    out.append(pkg)
        return out

    def save(self, skill: SkillPackage) -> SkillPackage:
        return self.store.upsert_skill(skill)
