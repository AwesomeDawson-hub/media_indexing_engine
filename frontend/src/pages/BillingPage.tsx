import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import * as api from '../api/client';
import type { BillingStatus } from '../types/api';

const PLANS = [
  {
    key: 'basic',
    name: 'Basic',
    limit: 500,
    description: 'For personal use and exploration.',
    priceLabel: 'Free',
    priceId: '',
  },
  {
    key: 'advanced',
    name: 'Advanced',
    limit: 1500,
    description: 'For professionals with higher volume needs.',
    priceLabel: 'Contact sales',
    priceId: import.meta.env.VITE_STRIPE_PRICE_ID_ADVANCED ?? '',
  },
  {
    key: 'premium',
    name: 'Premium',
    limit: 5000,
    description: 'For teams and power users.',
    priceLabel: 'Contact sales',
    priceId: import.meta.env.VITE_STRIPE_PRICE_ID_PREMIUM ?? '',
  },
];

function statusBadge(status: string) {
  const map: Record<string, string> = {
    none: 'status-none',
    active: 'status-active',
    trialing: 'status-trialing',
    past_due: 'status-warning',
    canceled: 'status-canceled',
    unpaid: 'status-warning',
  };
  const cls = map[status] ?? 'status-none';
  return <span className={`billing-status-badge ${cls}`}>{status}</span>;
}

export default function BillingPage() {
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [searchParams] = useSearchParams();

  const sessionResult = searchParams.get('session');

  useEffect(() => {
    api
      .getBillingStatus()
      .then((b) => {
        setBilling(b);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  async function handleUpgrade(priceId: string) {
    if (!priceId) {
      setErrorMsg('Stripe price not configured. Contact support to upgrade.');
      return;
    }
    setErrorMsg('');
    setActionLoading(true);
    try {
      const res = await api.createCheckoutSession(priceId);
      window.location.href = res.checkout_url;
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to start checkout.');
      setActionLoading(false);
    }
  }

  async function handleManage() {
    setErrorMsg('');
    setActionLoading(true);
    try {
      const res = await api.createPortalSession();
      window.location.href = res.portal_url;
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to open billing portal.');
      setActionLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="page-section">
        <p>Loading billing information…</p>
      </div>
    );
  }

  const currentPlanKey = billing?.plan_name ?? 'basic';
  const hasActiveSubscription =
    billing?.billing_status === 'active' || billing?.billing_status === 'trialing';

  return (
    <div className="page-section">
      <h1 className="page-title">Billing &amp; Plans</h1>

      {sessionResult === 'success' && (
        <div className="alert alert-success" role="alert">
          Subscription activated! Your plan has been updated.
        </div>
      )}
      {sessionResult === 'cancelled' && (
        <div className="alert alert-info" role="alert">
          Checkout cancelled. No charges were made.
        </div>
      )}

      {billing && (
        <div className="billing-current">
          <h2>Current Plan</h2>
          <div className="billing-summary">
            <span className="billing-plan-name">{billing.plan_name}</span>
            {statusBadge(billing.billing_status)}
            <span className="billing-limit">{billing.monthly_limit.toLocaleString()} analyses / month</span>
          </div>
          {hasActiveSubscription && billing.stripe_customer_id && (
            <button
              className="btn btn-secondary"
              onClick={handleManage}
              disabled={actionLoading}
            >
              {actionLoading ? 'Loading…' : 'Manage Subscription'}
            </button>
          )}
        </div>
      )}

      {errorMsg && (
        <div className="alert alert-error" role="alert">
          {errorMsg}
        </div>
      )}

      <div className="billing-plans">
        {PLANS.map((plan) => {
          const isCurrent = plan.key === currentPlanKey;
          const isUpgrade =
            PLANS.findIndex((p) => p.key === plan.key) >
            PLANS.findIndex((p) => p.key === currentPlanKey);

          return (
            <div
              key={plan.key}
              className={`billing-plan-card${isCurrent ? ' billing-plan-card--current' : ''}`}
            >
              <div className="billing-plan-header">
                <h3>{plan.name}</h3>
                <span className="billing-plan-price">{plan.priceLabel}</span>
              </div>
              <p className="billing-plan-desc">{plan.description}</p>
              <p className="billing-plan-limit">
                <strong>{plan.limit.toLocaleString()}</strong> analyses / month
              </p>
              {isCurrent ? (
                <span className="billing-plan-current-label">Current plan</span>
              ) : isUpgrade && plan.priceId ? (
                <button
                  className="btn btn-primary"
                  onClick={() => handleUpgrade(plan.priceId)}
                  disabled={actionLoading}
                >
                  {actionLoading ? 'Loading…' : `Upgrade to ${plan.name}`}
                </button>
              ) : isUpgrade && !plan.priceId ? (
                <span className="billing-plan-contact">Contact sales to upgrade</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
