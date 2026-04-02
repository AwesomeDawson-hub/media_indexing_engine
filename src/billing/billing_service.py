"""Billing service: Stripe integration, plan management, webhook event processing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import StripeEvent, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------

PLAN_LIMITS: dict[str, int] = {
    "basic": 500,
    "advanced": 1500,
    "premium": 5000,
    "enterprise": 50000,
}

# Populated at runtime from settings (price_id → plan_name)
def _price_to_plan() -> dict[str, str]:
    result: dict[str, str] = {}
    if settings.stripe.price_id_advanced:
        result[settings.stripe.price_id_advanced] = "advanced"
    if settings.stripe.price_id_premium:
        result[settings.stripe.price_id_premium] = "premium"
    return result


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stripe_client() -> stripe.Stripe | None:
    """Return a configured Stripe client, or None if no key is set."""
    if not settings.stripe.secret_key:
        return None
    return stripe.Stripe(settings.stripe.secret_key)


# ---------------------------------------------------------------------------
# Checkout / Portal
# ---------------------------------------------------------------------------

async def create_checkout_session(user: User, price_id: str, success_url: str, cancel_url: str) -> str:
    """Create a Stripe Checkout Session and return the URL.

    If Stripe is not configured (empty key), returns a placeholder URL for dev/test.
    """
    client = _stripe_client()
    if client is None:
        logger.warning("Stripe not configured — returning placeholder checkout URL")
        return "https://checkout.stripe.com/test-mode-placeholder"

    price_to_plan = _price_to_plan()
    if price_id not in price_to_plan:
        raise ValueError(f"Unknown price_id: {price_id}")

    # Reuse existing customer or create a new one
    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = client.customers.create(
            email=user.email,
            name=user.display_name,
            metadata={"user_id": user.id},
        )
        customer_id = customer.id

    session = client.checkout.sessions.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": user.id},
    )
    return session.url


async def create_portal_session(user: User, return_url: str) -> str:
    """Create a Stripe Customer Portal session URL.

    If Stripe is not configured, returns a placeholder URL.
    """
    client = _stripe_client()
    if client is None:
        logger.warning("Stripe not configured — returning placeholder portal URL")
        return "https://billing.stripe.com/test-mode-placeholder"

    if not user.stripe_customer_id:
        raise ValueError("User has no Stripe customer ID")

    session = client.billing_portal.sessions.create(
        customer=user.stripe_customer_id,
        return_url=return_url,
    )
    return session.url


# ---------------------------------------------------------------------------
# Webhook event processing
# ---------------------------------------------------------------------------

def construct_stripe_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify webhook signature and construct a Stripe Event object.

    Raises stripe.error.SignatureVerificationError on invalid signature.
    When webhook_secret is empty, skips verification (dev mode only — never in prod).
    """
    if not settings.stripe.webhook_secret:
        # Dev/test mode: parse without verification
        import json
        data = json.loads(payload)
        return stripe.Event.construct_from(data, settings.stripe.secret_key or "sk_test_placeholder")

    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe.webhook_secret
    )


async def apply_subscription_event(db: AsyncSession, event: stripe.Event) -> bool:
    """Process a Stripe subscription webhook event.

    Returns True if processed, False if already seen (idempotency).
    Handles: customer.subscription.created, .updated, .deleted
    """
    # Idempotency: check if we've already processed this event
    existing = await db.execute(
        select(StripeEvent).where(StripeEvent.stripe_event_id == event.id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Stripe event %s already processed — skipping", event.id)
        return False

    event_type: str = event.type
    subscription = event.data.object  # stripe.Subscription

    # Find user by stripe_customer_id
    customer_id: str = subscription.customer
    user_result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        # Try to find by metadata user_id embedded at checkout
        meta_user_id = (subscription.metadata or {}).get("user_id")
        if meta_user_id:
            user_result2 = await db.execute(
                select(User).where(User.id == meta_user_id)
            )
            user = user_result2.scalar_one_or_none()

    if user is None:
        logger.warning("Stripe event %s: no user found for customer %s", event.id, customer_id)
        # Still record the event so we don't retry it
        db.add(StripeEvent(
            stripe_event_id=event.id,
            event_type=event_type,
        ))
        await db.commit()
        return True

    price_to_plan = _price_to_plan()

    if event_type == "customer.subscription.deleted":
        # Revert to basic
        user.plan_name = "basic"
        user.monthly_limit = PLAN_LIMITS["basic"]
        user.billing_status = "canceled"
        user.stripe_subscription_id = None
    else:
        # created or updated
        billing_status: str = subscription.status  # active, trialing, past_due, etc.
        user.stripe_customer_id = customer_id
        user.stripe_subscription_id = subscription.id
        user.billing_status = billing_status

        # Determine plan from price_id on first line item
        plan_name = user.plan_name  # default: keep current
        items = subscription.items.data if subscription.items else []
        for item in items:
            price_id = item.price.id
            if price_id in price_to_plan:
                plan_name = price_to_plan[price_id]
                break

        if billing_status in ("active", "trialing"):
            user.plan_name = plan_name
            user.monthly_limit = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["basic"])
        elif billing_status in ("past_due", "unpaid"):
            # Keep plan assigned, don't bump limit, but mark status
            pass
        else:
            # canceled, incomplete_expired, etc.
            user.plan_name = "basic"
            user.monthly_limit = PLAN_LIMITS["basic"]
            user.billing_status = "canceled"

    # Record this event as processed
    db.add(StripeEvent(
        stripe_event_id=event.id,
        event_type=event_type,
    ))

    await db.commit()
    logger.info("Processed Stripe event %s (%s) for user %s → plan=%s status=%s",
                event.id, event_type, user.id, user.plan_name, user.billing_status)
    return True
