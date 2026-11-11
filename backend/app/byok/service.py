"""BYOK configuration: validate, encrypt, store. Never return raw keys."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.credentials.encryption import CredentialCipher
from app.free_tier.models import ByokConfigPublic, ByokUpsertRequest
from app.persistence.user_store import UserStore
from app.providers.qwen import DEFAULT_QWEN_BASE_URL


class ByokValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def validate_and_save_byok(
    *,
    store: UserStore,
    settings: Settings,
    user_id: str,
    request: ByokUpsertRequest,
) -> ByokConfigPublic:
    api_key = request.api_key.strip()
    model = request.model.strip()
    base_url = (request.base_url or "").strip() or None

    await _validate_credentials(
        provider=request.provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        settings=settings,
    )

    cipher = CredentialCipher(settings.credentials_encryption_key)
    encrypted = cipher.encrypt(api_key)
    return store.upsert_provider_config(
        user_id,
        provider=request.provider,
        model=model,
        encrypted_api_key=encrypted,
        base_url=base_url,
        set_active=request.set_active,
    )


async def _validate_credentials(
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None,
    settings: Settings,
) -> None:
    """Lightweight auth check — rejects invalid keys before saving."""
    timeout = min(settings.provider_timeout_seconds, 15.0)

    if provider == "gemini":
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{model}:generateContent"
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
        if resp.status_code in (401, 403):
            raise ByokValidationError("Gemini API key was rejected.")
        if resp.status_code == 404:
            raise ByokValidationError(f"Gemini model '{model}' was not found.")
        if resp.status_code >= 400 and resp.status_code != 429:
            raise ByokValidationError(
                f"Gemini credential check failed ({resp.status_code})."
            )
        return

    # OpenAI-compatible providers
    if provider == "openrouter":
        endpoint = (base_url or settings.openrouter_base_url).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if settings.openrouter_site_url.strip():
            headers["HTTP-Referer"] = settings.openrouter_site_url.strip()
        if settings.openrouter_app_name.strip():
            headers["X-Title"] = settings.openrouter_app_name.strip()
    elif provider == "groq":
        endpoint = (base_url or settings.groq_base_url).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    elif provider == "qwen":
        endpoint = (base_url or settings.qwen_base_url or DEFAULT_QWEN_BASE_URL).rstrip(
            "/"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    else:
        raise ByokValidationError(f"Unsupported provider: {provider}")

    body = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{endpoint}/chat/completions",
            json=body,
            headers=headers,
        )
    if resp.status_code in (401, 403):
        raise ByokValidationError(f"{provider} API key was rejected.")
    if resp.status_code in (400, 404, 422):
        # Auth may be fine but model invalid — still surface clearly.
        detail = resp.text[:200]
        raise ByokValidationError(
            f"{provider} rejected the request (check model/base URL). {detail}"
        )
    if resp.status_code >= 500:
        raise ByokValidationError(
            f"{provider} is temporarily unavailable ({resp.status_code}). Try again."
        )
    if resp.status_code >= 400 and resp.status_code != 429:
        raise ByokValidationError(
            f"{provider} credential check failed ({resp.status_code})."
        )
