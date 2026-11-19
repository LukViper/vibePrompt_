"""Optional email notifications for blocking findings / mentions."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable

from app.config import Settings

logger = logging.getLogger("vibeprompt.notify")


def email_configured(settings: Settings) -> bool:
    return bool(
        (getattr(settings, "smtp_host", "") or "").strip()
        and (getattr(settings, "notify_from_email", "") or "").strip()
    )


def send_notification_email(
    settings: Settings,
    *,
    to_addresses: Iterable[str],
    subject: str,
    body: str,
) -> dict:
    """
    Send a plain-text notification.

    No-op (logged) when SMTP is not configured — safe for local/dev.
    """
    recipients = [a.strip() for a in to_addresses if a and a.strip()]
    if not recipients:
        return {"sent": False, "reason": "no_recipients"}
    if not email_configured(settings):
        logger.info(
            "email_notify skipped (SMTP not configured) subject=%s to=%s",
            subject,
            recipients,
        )
        return {"sent": False, "reason": "smtp_not_configured", "to": recipients}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.notify_from_email
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    host = settings.smtp_host
    port = int(getattr(settings, "smtp_port", 587) or 587)
    user = (getattr(settings, "smtp_user", "") or "").strip()
    password = (getattr(settings, "smtp_password", "") or "").strip()
    use_tls = bool(getattr(settings, "smtp_use_tls", True))

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    return {"sent": True, "to": recipients}
