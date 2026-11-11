"""Licensing and rights checks for knowledge ingestion."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class UsagePermission(str, Enum):
    UNKNOWN = "unknown"
    OWNED = "owned"
    LICENSED = "licensed"
    PUBLIC_DOMAIN = "public_domain"
    OPEN_ACCESS = "open_access"
    FAIR_USE_REVIEW = "fair_use_review"
    FORBIDDEN = "forbidden"


ALLOWED_PROCESS = {
    UsagePermission.OWNED,
    UsagePermission.LICENSED,
    UsagePermission.PUBLIC_DOMAIN,
    UsagePermission.OPEN_ACCESS,
}


class RightsConfirmation(BaseModel):
    usage_permission: UsagePermission
    rights_confirmed: bool = False
    confirmation_text: str = ""
    notes: str = ""


class LicensingDecision(BaseModel):
    allowed: bool
    reason: str
    usage_permission: UsagePermission
    may_auto_download: bool = False


REQUIRED_CONFIRMATION = (
    "I confirm I have the legal right to upload and process this material "
    "for generating abstracted skill instructions, and I will not use VibePrompt "
    "to reproduce substantial copyrighted passages."
)


def evaluate_rights(
    *,
    usage_permission: str | UsagePermission,
    rights_confirmed: bool,
    full_text_authorized: bool = False,
    has_authorized_url: bool = False,
) -> LicensingDecision:
    try:
        perm = UsagePermission(str(usage_permission))
    except ValueError:
        perm = UsagePermission.UNKNOWN

    if perm == UsagePermission.FORBIDDEN:
        return LicensingDecision(
            allowed=False,
            reason="Source marked forbidden.",
            usage_permission=perm,
        )

    if perm in {UsagePermission.PUBLIC_DOMAIN, UsagePermission.OPEN_ACCESS}:
        return LicensingDecision(
            allowed=True,
            reason="Public domain / open-access material.",
            usage_permission=perm,
            may_auto_download=bool(full_text_authorized and has_authorized_url),
        )

    if perm in {UsagePermission.OWNED, UsagePermission.LICENSED}:
        if not rights_confirmed:
            return LicensingDecision(
                allowed=False,
                reason="Administrator must confirm rights before processing owned/licensed material.",
                usage_permission=perm,
            )
        return LicensingDecision(
            allowed=True,
            reason="Rights confirmed for owned/licensed material.",
            usage_permission=perm,
            may_auto_download=False,
        )

    if rights_confirmed and perm == UsagePermission.FAIR_USE_REVIEW:
        return LicensingDecision(
            allowed=True,
            reason="Fair-use review confirmed by administrator — process cautiously; no verbatim quotes.",
            usage_permission=perm,
            may_auto_download=False,
        )

    return LicensingDecision(
        allowed=False,
        reason="Insufficient rights metadata. Set usage permission and confirm rights.",
        usage_permission=perm,
    )


class ManualUploadRights(BaseModel):
    usage_permission: UsagePermission = UsagePermission.OWNED
    rights_confirmed: bool = False
    confirmation_text: str = Field(default="")

    def is_valid_confirmation(self) -> bool:
        return (
            self.rights_confirmed
            and self.confirmation_text.strip() == REQUIRED_CONFIRMATION
        )
