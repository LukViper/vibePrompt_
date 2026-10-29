"""HTTP-level provider tests with mocked transports — no real API calls."""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import CandidateFinding, ProviderError, ProviderErrorKind
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider


@pytest.mark.asyncio
async def test_gemini_parses_structured_response():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "reply": "Clarify the deadline.",
                                    "intent": "scope_change",
                                    "findings": [
                                        {
                                            "title": "Tight deadline",
                                            "challenged_claim": "Ship tomorrow",
                                            "reasoning": "Too much scope",
                                            "evidence": ["deadline stated"],
                                            "severity": "critical",
                                            "confidence": 0.9,
                                        }
                                    ],
                                    "most_important_question": "What is MVP?",
                                    "state_patch": {},
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-goog-api-key" in request.headers
        assert "super-secret" not in request.content.decode()  # key is header only
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider("test-key", "gemini-3.8-flash", client=client)
        result = await provider.analyze_primary(
            project_snapshot={"name": "P"},
            user_message="Ship marketplace tomorrow",
            conversation_tail=[],
        )
    assert result.reply.startswith("Clarify")
    assert len(result.findings) == 1
    assert result.findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_gemini_rate_limit():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider("k", "m", client=client, max_retries=0)
        with pytest.raises(ProviderError) as exc:
            await provider.analyze_primary(
                project_snapshot={}, user_message="hi", conversation_tail=[]
            )
    assert exc.value.kind == ProviderErrorKind.RATE_LIMIT


@pytest.mark.asyncio
async def test_groq_parses_critic_response():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "actions": [
                                {
                                    "finding_index": 0,
                                    "action": "disagree",
                                    "notes": "weak",
                                }
                            ],
                            "overall_notes": "ok",
                            "insufficient_context": False,
                        }
                    )
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider("groq-key", "openai/gpt-oss-20b", client=client)
        review = await provider.critique(
            project_snapshot={},
            user_message="x",
            candidate_findings=[
                CandidateFinding(
                    title="t",
                    challenged_claim="c",
                    reasoning="r",
                )
            ],
            primary_reply="reply",
        )
    assert review.actions[0].action == "disagree"


@pytest.mark.asyncio
async def test_groq_timeout():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider("k", "m", client=client, max_retries=0)
        with pytest.raises(ProviderError) as exc:
            await provider.critique(
                project_snapshot={},
                user_message="x",
                candidate_findings=[],
                primary_reply="r",
            )
    assert exc.value.kind == ProviderErrorKind.TIMEOUT
