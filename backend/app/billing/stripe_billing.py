"""Stripe Checkout + webhook entitlement updates."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.persistence.user_store import UserStore

logger = logging.getLogger("vibeprompt.billing")


def stripe_enabled(settings: Settings) -> bool:
    return bool((settings.stripe_secret_key or "").strip())


def _stripe(settings: Settings):
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(
    settings: Settings,
    store: UserStore,
    *,
    org_id: str,
    plan: str,
    customer_email: str | None,
) -> dict[str, Any]:
    if not stripe_enabled(settings):
        raise RuntimeError("Stripe is not configured")
    price = (
        settings.stripe_price_pro if plan == "pro" else settings.stripe_price_team
    )
    if not price:
        raise RuntimeError(f"Missing Stripe price id for plan={plan}")
    stripe = _stripe(settings)
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        customer_email=customer_email,
        metadata={"org_id": org_id, "plan": plan},
        subscription_data={"metadata": {"org_id": org_id, "plan": plan}},
    )
    return {"id": session.id, "url": session.url}


def create_portal_session(
    settings: Settings, *, customer_id: str
) -> dict[str, Any]:
    if not stripe_enabled(settings):
        raise RuntimeError("Stripe is not configured")
    stripe = _stripe(settings)
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=settings.stripe_success_url,
    )
    return {"url": session.url}


def handle_webhook(
    settings: Settings,
    store: UserStore,
    *,
    payload: bytes,
    signature: str,
) -> dict[str, str]:
    if not stripe_enabled(settings):
        raise RuntimeError("Stripe is not configured")
    stripe = _stripe(settings)
    secret = settings.stripe_webhook_secret
    if secret:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    else:
        import json

        event = json.loads(payload)
    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if etype in ("checkout.session.completed", "customer.subscription.updated"):
        meta = (data.get("metadata") if isinstance(data, dict) else data.metadata) or {}
        org_id = meta.get("org_id")
        plan = meta.get("plan") or "pro"
        customer = (
            data.get("customer") if isinstance(data, dict) else getattr(data, "customer", None)
        )
        sub_id = (
            data.get("subscription")
            if isinstance(data, dict)
            else getattr(data, "subscription", None)
        )
        if isinstance(data, dict) and data.get("object") == "subscription":
            sub_id = data.get("id")
            meta = data.get("metadata") or {}
            org_id = org_id or meta.get("org_id")
            plan = meta.get("plan") or plan
        if org_id:
            store.set_org_plan(
                org_id,
                plan if plan in ("pro", "team") else "pro",
                stripe_customer_id=str(customer) if customer else None,
                stripe_subscription_id=str(sub_id) if sub_id else None,
            )
            store.emit_audit(
                org_id=org_id,
                action="billing.plan_updated",
                target_type="organization",
                target_id=org_id,
                after={"plan": plan, "event": etype},
            )
    elif etype == "customer.subscription.deleted":
        meta = (data.get("metadata") if isinstance(data, dict) else data.metadata) or {}
        org_id = meta.get("org_id")
        if org_id:
            store.set_org_plan(org_id, "free")
            store.emit_audit(
                org_id=org_id,
                action="billing.plan_canceled",
                target_type="organization",
                target_id=org_id,
                after={"plan": "free", "event": etype},
            )
    else:
        logger.info("Ignoring Stripe event %s", etype)
    return {"status": "ok"}
