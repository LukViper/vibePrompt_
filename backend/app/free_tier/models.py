"""Free-tier and usage tracking models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FundingSource(str, Enum):
    PLATFORM = "PLATFORM"
    BYOK = "BYOK"


class GenerationStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RELEASED = "released"


class FreeTierStatus(BaseModel):
    enabled: bool
    allocated: int = 0
    used: int = 0
    remaining: int = 0
    exhausted: bool = False
    provider: str | None = None
    model: str | None = None
    funding: Literal["PLATFORM", "BYOK", "NONE"] = "NONE"
    byok_configured: bool = False
    byok_provider: str | None = None
    byok_model: str | None = None
    requires_byok: bool = False
    inference_provider: str | None = None
    message: str | None = None


class ByokUpsertRequest(BaseModel):
    provider: Literal["gemini", "openrouter", "groq", "qwen"]
    api_key: str = Field(min_length=8, max_length=512)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    set_active: bool = True


class ByokConfigPublic(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    is_active: bool
    validated_at: datetime | None = None
    has_api_key: bool = True
    # Never expose the key itself.
