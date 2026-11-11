"""Coding-agent-specific prompt adapters."""

from __future__ import annotations

from app.compilation.agents.antigravity import compile_antigravity_prompt
from app.compilation.agents.base import AgentCompileInput, AgentFamily, normalize_agent
from app.compilation.agents.codex import compile_codex_prompt
from app.compilation.agents.cursor import compile_cursor_prompt

__all__ = [
    "AgentCompileInput",
    "AgentFamily",
    "compile_for_agent",
    "normalize_agent",
]


def compile_for_agent(agent: str, payload: AgentCompileInput) -> str:
    family = normalize_agent(agent)
    if family == AgentFamily.ANTIGRAVITY:
        return compile_antigravity_prompt(payload)
    if family == AgentFamily.CODEX:
        return compile_codex_prompt(payload)
    return compile_cursor_prompt(payload)
