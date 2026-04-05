import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import * as api from '../api/client';
import type { BillingStatus, QuotaStatus, QuotaHistoryItem, QuotaHistoryResponse, QuotaDailyUsageResponse } from '../types/api';

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

function formatPeriod(period: string): string {
  const [year, month] = period.split('-').map(Number);
  return new Date(year, month - 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

function formatResetDate(period: string): string {
  const [year, month] = period.split('-').map(Number);
  const nextMonth = new Date(year, month); // month (not month-1) is next month in 0-indexed
  return nextMonth.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
}

function formatEventDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function eventLabel(type: QuotaHistoryItem['event_type']): string {
  if (type === 'consumed') return 'Analyzed';
  if (type === 'released') return 'Refunded';
  return 'Processing';
}

function UsageChart({ data }: { data: QuotaDailyUsageResponse }) {
  const [year, month] = data.period_month.split('-').map(Number);
  const daysInMonth = new Date(year, month, 0).getDate();

  const countMap = new Map<number, number>();
  for (const d of data.days) {
    const day = parseInt(d.date.split('-')[2], 10);
    countMap.set(day, d.count);
  }

  const maxCount = Math.max(...Array.from(countMap.values()), 1);

  const svgW = 700;
  const svgH = 140;
  const padL = 32;
  const padR = 8;
  const padT = 16;
  const padB = 28;
  const chartW = svgW - padL - padR;
  const chartH = svgH - padT - padB;
  const slotW = chartW / daysInMonth;
  const barW = Math.max(2, Math.floor(slotW) - 2);

  return (
    <div className="usage-chart-card">
      <div className="usage-card-header">
        <span className="usage-card-title">Daily Activity</span>
        <span className="usage-card-period">{formatPeriod(data.period_month)}</span>
      </div>
      <svg
        className="usage-chart-svg"
        viewBox={`0 0 ${svgW} ${svgH}`}
        preserveAspectRatio="xMidYMid meet"
        aria-label="Daily usage bar chart"
      >
        {[0, 0.5, 1].map((frac) => {
          const y = padT + chartH - frac * chartH;
          return (
            <g key={frac}>
              <line x1={padL} x2={svgW - padR} y1={y} y2={y} className="chart-gridline" />
              <text x={padL - 4} y={y + 4} className="chart-axis-label" textAnchor="end">
                {Math.round(frac * maxCount)}
              </text>
            </g>
          );
        })}
        {Array.from({ length: daysInMonth }, (_, i) => {
          const day = i + 1;
          const count = countMap.get(day) ?? 0;
          const barH = count > 0 ? Math.max(4, (count / maxCount) * chartH) : 0;
          const x = padL + i * slotW + (slotW - barW) / 2;
          const showLabel = day === 1 || day % 5 === 0 || day === daysInMonth;
          return (
            <g key={day}>
              <rect x={x} y={padT} width={barW} height={chartH} className="chart-bar-ghost" rx={2} />
              {count > 0 && (
                <rect x={x} y={padT + chartH - barH} width={barW} height={barH} className="chart-bar" rx={2}>
                  <title>{`Day ${day}: ${count} ${count === 1 ? 'analysis' : 'analyses'}`}</title>
                </rect>
              )}
              {showLabel && (
                <text x={x + barW / 2} y={svgH - 4} className="chart-axis-label" textAnchor="middle">
                  {day}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

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
  const [quota, setQuota] = useState<QuotaStatus | null>(null);
  const [history, setHistory] = useState<QuotaHistoryResponse | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [dailyUsage, setDailyUsage] = useState<QuotaDailyUsageResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [searchParams] = useSearchParams();

  const sessionResult = searchParams.get('session');

  useEffect(() => {
    Promise.all([
      api.getBillingStatus(),
      api.getQuotaStatus(),
      api.getQuotaHistory(undefined, 1, 25),
      api.getQuotaDailyUsage(),
    ])
      .then(([b, q, h, d]) => {
        setBilling(b);
        setQuota(q);
        setHistory(h);
        setDailyUsage(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  async function loadMoreHistory() {
    if (!history || historyLoading) return;
    const nextPage = historyPage + 1;
    setHistoryLoading(true);
    try {
      const more = await api.getQuotaHistory(undefined, nextPage, 25);
      setHistory((prev) =>
        prev ? { ...more, items: [...prev.items, ...more.items] } : more,
      );
      setHistoryPage(nextPage);
    } finally {
      setHistoryLoading(false);
    }
  }

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

      {errorMsg && (
        <div className="alert alert-error" role="alert">
          {errorMsg}
        </div>
      )}

      {quota && (
        <div className="usage-card">
          <div className="usage-card-header">
            <span className="usage-card-title">Usage This Month</span>
            <span className="usage-card-period">{formatPeriod(quota.period_month)}</span>
          </div>
          <div className="usage-progress-bar">
            <div
              className="usage-progress-fill"
              style={{
                width: `${Math.min(100, ((quota.consumed + quota.reserved) / quota.monthly_limit) * 100)}%`,
              }}
            />
          </div>
          <div className="usage-stats">
            <span className="usage-used">
              <strong>{(quota.consumed + quota.reserved).toLocaleString()}</strong> of{' '}
              <strong>{quota.monthly_limit.toLocaleString()}</strong> analyses used
            </span>
            <span className="usage-remaining">{quota.remaining.toLocaleString()} remaining</span>
          </div>
          {quota.reserved > 0 && (
            <p className="usage-in-progress">{quota.reserved} in progress</p>
          )}
          <p className="usage-reset">Resets {formatResetDate(quota.period_month)}</p>
        </div>
      )}

      {dailyUsage && <UsageChart data={dailyUsage} />}

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
              {isCurrent && (
                <div className="billing-plan-banner">Active Plan</div>
              )}
              <div className="billing-plan-body">
                <div className="billing-plan-header">
                  <h3>{plan.name}</h3>
                  <span className="billing-plan-price">{plan.priceLabel}</span>
                </div>
                <p className="billing-plan-desc">{plan.description}</p>
                <p className="billing-plan-limit">
                  <strong>{plan.limit.toLocaleString()}</strong> analyses / month
                </p>
                <div className="billing-plan-action">
                  {isCurrent && hasActiveSubscription && billing?.stripe_customer_id ? (
                    <button
                      className="btn btn-secondary btn-block"
                      onClick={handleManage}
                      disabled={actionLoading}
                    >
                      {actionLoading ? 'Loading…' : 'Manage Subscription'}
                    </button>
                  ) : isUpgrade && plan.priceId ? (
                    <button
                      className="btn btn-primary btn-block"
                      onClick={() => handleUpgrade(plan.priceId)}
                      disabled={actionLoading}
                    >
                      {actionLoading ? 'Loading…' : `Upgrade to ${plan.name}`}
                    </button>
                  ) : isUpgrade && !plan.priceId ? (
                    <span className="billing-plan-contact">Contact sales to upgrade</span>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {history && history.total > 0 && (
        <div className="usage-history">
          <h2 className="usage-history-title">Recent Activity</h2>
          <div className="usage-history-list">
            {history.items.map((item) => (
              <div key={item.id} className="usage-history-row">
                <span className="usage-history-filename">
                  {item.original_filename ?? '(unknown file)'}
                </span>
                <span className={`usage-event-badge usage-event-${item.event_type}`}>
                  {eventLabel(item.event_type)}
                </span>
                <span className="usage-history-date">{formatEventDate(item.created_at)}</span>
              </div>
            ))}
          </div>
          {history.items.length < history.total && (
            <button
              className="btn btn-secondary usage-load-more"
              onClick={loadMoreHistory}
              disabled={historyLoading}
            >
              {historyLoading
                ? 'Loading…'
                : `Load more (${(history.total - history.items.length).toLocaleString()} remaining)`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
