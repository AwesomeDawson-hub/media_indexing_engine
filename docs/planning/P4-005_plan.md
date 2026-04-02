# P4-005: Billing Groundwork & Commercial Modeling

**Phase:** Phase 4 — Beta Operations & Commercial Foundations  
**Status:** In Progress  
**Started:** 2026-04-01  
**Objective:** Measure per-image processing cost, encode plan tiers in the system, integrate Stripe in test mode for recurring monthly subscriptions, map subscription state to plan entitlements, and implement idempotent webhook processing as the sole billing-state authority — without enabling live paid launch.

---

## Explicit Phase 4 Boundary

This workstream does **not** enable real paid subscriptions for production users. All Stripe keys used are test-mode keys only. Live commercialization is blocked until a stable HTTPS domain, verified webhook delivery, and explicit operator approval.

---

## Plan Tiers

| Plan | Monthly Limit | Stripe Price ID (test) |
|------|--------------|------------------------|
| basic | 500 | (free, no Stripe sub) |
| advanced | 1,500 | `price_advanced_test` (created in Stripe test dashboard) |
| premium | 5,000 | `price_premium_test` |
| enterprise | 50,000 | (manual / contact) |

The `basic` plan is the default free tier — no Stripe subscription required. Paid plans require an active Stripe subscription in `active` or `trialing` status.

---

## Architecture Overview

```
User clicks "Upgrade" 
  → POST /api/v1/billing/create-checkout-session
  → Stripe Checkout (test mode)
  → User completes checkout
  → Stripe sends webhook: customer.subscription.created / updated / deleted
  → POST /api/v1/billing/webhook (signature-verified, idempotent)
  → DB: user.stripe_customer_id, user.stripe_subscription_id, user.plan_name, user.monthly_limit updated
  → User's quota automatically reflects new plan
```

**Webhook is the ONLY path that updates plan/limit.** Frontend redirects (success_url) only show a confirmation message — they never grant entitlements.

---

## Cost Model

Approximate per-image processing cost (to be measured and documented in `docs/planning/cost_model.md`):
- Anthropic Claude API: ~$0.002–$0.005 per image (varies by image size → token count)
- Embedding (local sentence-transformers): ~$0 (CPU inference)
- Storage (S3-equivalent): ~$0.023/GB — negligible at current scale
- **Estimated cost per processed image:** ~$0.003–$0.006

Plans are priced to achieve ~3–5× margin at expected usage:
- Advanced (1,500 imgs/mo): ~$4.50–$9/mo cost → target $19/mo
- Premium (5,000 imgs/mo): ~$15–$30/mo cost → target $49/mo

---

## Steps

### Step 1: Cost Model Documentation + StripeConfig
- Add `StripeConfig` dataclass to `src/config.py`:
  - `secret_key: str` (env var `STRIPE_SECRET_KEY`, default empty)
  - `webhook_secret: str` (env var `STRIPE_WEBHOOK_SECRET`, default empty)
  - `test_mode: bool = True`
  - Plan price IDs: `price_id_advanced: str`, `price_id_premium: str`
- Add `stripe: StripeConfig` to `Settings`
- Wire env var overrides in `load_settings()`
- Install `stripe` Python SDK (`pip install stripe`)
- Add `stripe` to `pyproject.toml` dependencies
- Create `docs/planning/cost_model.md` with cost analysis

### Step 2: DB Model + Migration
New columns on `users`:
- `stripe_customer_id: str | None` (String 100, nullable, unique)
- `stripe_subscription_id: str | None` (String 100, nullable)
- `billing_status: str` (String 30, default `"none"`) — values: `"none"` | `"active"` | `"trialing"` | `"past_due"` | `"canceled"` | `"unpaid"`

New table `stripe_events`:
- `id: str` (PK, UUID)
- `stripe_event_id: str` (String 100, unique — Stripe event.id, for idempotency)
- `event_type: str` (String 100)
- `processed_at: datetime`
- Index on `stripe_event_id`

Migration ID: `c3d4e5f6a7b8_billing`

### Step 3: Billing Service
Create `src/billing/billing_service.py`:
- `PLAN_LIMITS: dict[str, int]` — maps plan name to monthly_limit
- `PRICE_TO_PLAN: dict[str, str]` — maps Stripe price_id to plan name
- `async def create_checkout_session(user: User, price_id: str) -> str` — creates/reuses Stripe customer, creates Checkout Session, returns `session.url`
- `async def create_customer_portal_session(user: User) -> str` — creates Billing Portal session URL for subscription management
- `async def apply_subscription_event(db: AsyncSession, event: stripe.Event) -> None` — handles `customer.subscription.created`, `.updated`, `.deleted`; looks up user by `stripe_customer_id`; updates `plan_name`, `monthly_limit`, `billing_status`, `stripe_subscription_id`; marks event as processed (idempotency check)

### Step 4: Billing API Routes
Create `src/api/routes/billing.py`:
- `POST /api/v1/billing/create-checkout-session` — requires auth; body: `{price_id: str}`; validates price_id is known; returns `{checkout_url: str}`
- `POST /api/v1/billing/create-portal-session` — requires auth; user must have stripe_customer_id; returns `{portal_url: str}`
- `GET /api/v1/billing/status` — requires auth; returns billing status summary for current user
- `POST /api/v1/billing/webhook` — **no auth** (Stripe-signed); verifies `Stripe-Signature` header; idempotency check on `stripe_event_id`; dispatches to `apply_subscription_event`

Register `billing.router` in `src/api/app.py`.

### Step 5: Schemas
Add to `src/api/schemas.py`:
- `BillingStatusResponse` — `billing_status`, `plan_name`, `monthly_limit`, `stripe_customer_id: str | None`, `stripe_subscription_id: str | None`
- `CheckoutSessionRequest` — `price_id: str`
- `CheckoutSessionResponse` — `checkout_url: str`
- `PortalSessionResponse` — `portal_url: str`

### Step 6: Admin Billing View
Extend `PATCH /api/v1/admin/users/{user_id}` to accept `billing_status` override (for manual plan adjustment without Stripe — e.g., enterprise, comped accounts).  
Add `billing_status` and `stripe_customer_id` to `AdminUserDetailResponse` and `AdminUserSummary` schemas and frontend admin table.

### Step 7: Frontend Billing UI
Create `frontend/src/pages/BillingPage.tsx`:
- Shows current plan + billing_status
- "Upgrade" buttons for Advanced and Premium — calls `createCheckoutSession()`, redirects to Stripe Checkout
- "Manage Subscription" button (if has stripe_customer_id) — calls `createPortalSession()`, redirects to Billing Portal
- Success/cancel return URL handling from URL params (`?billing=success` / `?billing=canceled`)
- Plan comparison table (Basic / Advanced / Premium / Enterprise contact)

Add billing API functions to `frontend/src/api/client.ts`:
- `getBillingStatus()`
- `createCheckoutSession(priceId)`
- `createPortalSession()`

Add `BillingPage` to `App.tsx` at `/billing`.  
Add "Billing" nav link to `Layout.tsx`.

### Step 8: Tests
`tests/test_billing.py`:
- `test_billing_status_authenticated` — GET /billing/status returns billing fields
- `test_create_checkout_session_valid_price` — returns checkout_url (mocked Stripe)
- `test_create_checkout_session_invalid_price` — returns 400
- `test_webhook_subscription_created` — POST /billing/webhook with valid event updates user plan
- `test_webhook_idempotency` — same event_id processed twice; second is no-op, returns 200
- `test_webhook_invalid_signature` — returns 400
- `test_webhook_subscription_deleted` — reverts user to basic plan
- `test_admin_can_override_billing_status` — PATCH /admin/users/{id} with billing_status updates field + audit log

### Step 9: Full suite, commit, deploy
- Run full test suite (target: 135 + ~8 new = ~143 pass)
- Git commit
- AWS: git pull → rebuild → verify webhook endpoint returns 400 on bad sig
- Document Stripe test-mode setup instructions in `docs/planning/stripe_setup.md`

---

## Dev Mode Stripe Behavior

When `settings.stripe.secret_key` is empty:
- `POST /billing/create-checkout-session` returns `{"checkout_url": "https://stripe.com/test-mode-placeholder"}` — no real Stripe call
- `POST /billing/create-portal-session` returns `{"portal_url": "https://stripe.com/test-mode-placeholder"}`
- `GET /billing/status` works normally (reads DB)
- `POST /billing/webhook` requires a real or mocked Stripe signature

Tests mock the Stripe SDK directly and never make real API calls.

---

## Exit Criteria
- [ ] Cost model documented
- [ ] Stripe test-mode checkout + portal URLs work locally
- [ ] Subscription webhook updates plan/limit correctly
- [ ] Webhook idempotency enforced
- [ ] Webhook signature verification enforced
- [ ] Admin can manually override billing_status
- [ ] BillingPage visible in frontend
- [ ] All tests pass
- [ ] AWS deployed and webhook endpoint responds correctly to bad-sig test
