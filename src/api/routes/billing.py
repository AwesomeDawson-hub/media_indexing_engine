"""Billing API routes — Stripe checkout, portal, status, and webhook."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.api.schemas import (
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionResponse,
)
from src.billing.billing_service import (
    apply_subscription_event,
    construct_stripe_event,
    create_checkout_session,
    create_portal_session,
)
from src.config import settings
from src.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    current_user: User = Depends(get_current_user),
) -> BillingStatusResponse:
    """Return the authenticated user's current billing state."""
    return BillingStatusResponse(
        billing_status=current_user.billing_status,
        plan_name=current_user.plan_name,
        monthly_limit=current_user.monthly_limit,
        stripe_customer_id=current_user.stripe_customer_id,
        stripe_subscription_id=current_user.stripe_subscription_id,
    )


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout(
    body: CheckoutSessionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> CheckoutSessionResponse:
    """Create a Stripe Checkout Session for a subscription plan upgrade."""
    valid_price_ids = {settings.stripe.price_id_advanced, settings.stripe.price_id_premium} - {""}
    if valid_price_ids and body.price_id not in valid_price_ids:
        raise HTTPException(status_code=400, detail="Invalid price_id")

    base = str(request.base_url).rstrip("/")
    success_url = f"{base}/billing?session=success"
    cancel_url = f"{base}/billing?session=cancelled"

    url = await create_checkout_session(
        user=current_user,
        price_id=body.price_id,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return CheckoutSessionResponse(checkout_url=url)


@router.post("/create-portal-session", response_model=PortalSessionResponse)
async def create_portal(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> PortalSessionResponse:
    """Create a Stripe Billing Portal session for subscription management."""
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No active subscription found")

    base = str(request.base_url).rstrip("/")
    return_url = f"{base}/billing"

    url = await create_portal_session(user=current_user, return_url=return_url)
    return PortalSessionResponse(portal_url=url)


@router.post("/webhook", status_code=200)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict:
    """Handle incoming Stripe webhook events."""
    payload = await request.body()

    try:
        event = construct_stripe_event(payload, stripe_signature)
    except Exception as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    handled_event_types = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }

    if event["type"] in handled_event_types:
        processed = await apply_subscription_event(db=db, event=event)
        if not processed:
            logger.debug("Stripe event %s already processed (idempotent skip)", event["id"])
    else:
        logger.debug("Unhandled Stripe event type: %s", event["type"])

    return {"received": True}
