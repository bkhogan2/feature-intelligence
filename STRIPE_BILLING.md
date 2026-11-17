# Stripe subscription billing

Optional hosted subscription Checkout, customer portal, signed webhooks, reconciliation,
and Settings billing UI build on [PLAN_GATES.md](PLAN_GATES.md). The official Python SDK
is locked in `backend/uv.lock`; API version `2026-10-28.endive` is explicitly pinned.
No account, products, credentials, charges, or deployment are bundled.

## Access policy

- `BILLING_ENABLED=false` bypasses only plan checks. Auth, membership, roles, and tenant
  isolation still apply. `STRIPE_ENABLED=true` requires billing enabled.
- With Stripe disabled, only operator-managed assignments provide gated access.
- With Stripe enabled, one `active` or `trialing` subscription with a recognized price,
  one item, quantity one, and a future period end grants the mapped plan. Trial access
  is also bounded by `trial_end`; scheduled cancellation is bounded by `cancel_at`.
- Active access also requires a paid latest invoice with a nonnegative line matching
  the current subscription item, price, and full current period. An old paid Pro invoice
  cannot grant an uninvoiced Enterprise upgrade. Pending updates deny access until resolved.
  Configure portal upgrades to invoice immediately; schedule downgrades at period end
  where Stripe supports that product/price combination, otherwise use explicit invoiced changes.
  This deliberately conservative policy can temporarily pause even the previous paid
  tier during a pending/failed update. Voided/uncollectible latest invoices do not qualify.
- `past_due`, `unpaid`, `incomplete`, `incomplete_expired`, `paused`, `canceled`, paused
  collection, unknown prices, unsupported item shapes, and multiple nonterminal
  subscriptions deny access. Past-due subscriptions have **no grace period**.
- Cancel-at-period-end retains access until the current period ends. Database-time
  expiry is checked on every gated request even if the final webhook is missed.
- Manual assignments explicitly override subscription state, including cancellation.
  They block new checkout but **do not cancel existing subscriptions or charges**.
  Clear a manual assignment to return to subscription policy.
- Disabling a plan removes its features immediately. Hiding a price from checkout
  preserves its existing subscribers' price-to-plan mapping.

The existing `records.write` example gate never overrides viewer restrictions.

## Database and secrets

Run the migration command with the migration-only `DATABASE_ADMIN_URL`. Migrations
0002 and 0003 are additive. If your provider disallows role creation, have a DBA create
the NOLOGIN roles with migration-specified attributes before migrating.

A DBA must create separate non-owner, non-superuser, NOBYPASSRLS, NOINHERIT login users:

```sql
GRANT app_runtime TO your_api_login;
GRANT app_billing_service TO your_billing_login;
GRANT app_plan_operator TO your_operator_login;
```

Use `DATABASE_URL` for the normal API login, `BILLING_DATABASE_URL` for the billing
login, and `PLAN_OPERATOR_DATABASE_URL` only in the trusted operator shell. Never grant
billing/operator roles to the runtime login. Billing startup rejects owner, superuser,
BYPASSRLS, and runtime/operator-membership credentials. Its role mutates only billing
accounts, attempts, subscription snapshots, and processed event IDs—not memberships,
plans, features, or manual grants. Normal runtime reads remain tenant-scoped.

The API process needs runtime/billing DSNs and Stripe/webhook secrets, **not** migration
or operator credentials. Agent subprocesses receive no billing, Stripe, or database secrets.

## Sandbox setup

1. Install `uv sync --extra dev --extra billing` from `backend`, adding other extras your
   app requires. Container builds support `BACKEND_EXTRAS=billing` or a comma-separated list.
2. In your Stripe sandbox, create fixed recurring licensed prices for each plan. Only
   a single item/quantity one is supported; not metered, tiered, seat-based, or multi-item billing.
   For tiers sharing the same interval (for example Pro monthly and Enterprise monthly),
   use separate Stripe Products: the customer portal rejects duplicate billing intervals
   within a single configured product. Keep plan keys mapped to their respective prices.
3. Configure the sandbox customer portal: cancellation, payment methods, invoice history,
   and optionally plan switching. Allow only database-mapped prices; disable quantity changes.
   Select proration and downgrade timing in Stripe. Optional `STRIPE_PORTAL_CONFIGURATION`
   chooses a `bpc_...` configuration; otherwise Stripe uses the default.
4. Supply these through an ignored private environment file or secret manager. The app
   does not load dotenv files automatically; never put secrets in `VITE_*` variables:

```sh
BILLING_ENABLED=true
STRIPE_ENABLED=true
STRIPE_MODE=test
STRIPE_ALLOW_LIVE=false
STRIPE_SECRET_KEY=rk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
BILLING_DATABASE_URL=postgresql://your_billing_login:...@localhost:55439/starter
APP_PUBLIC_URL=http://localhost:5173
```

Secret or restricted keys are accepted. Runtime scopes: Customers write, Checkout Sessions
write, Customer Portal write, Subscriptions read, Invoices read, Prices read. Product/Price creation needs
additional permissions in your separate setup workflow, not the running app.

`APP_PUBLIC_URL` is a trusted frontend origin, never browser input. Local HTTP is permitted
only for localhost/127.0.0.1 in test mode. Match the existing CORS configuration. No public
Stripe key is needed: the browser navigates to hosted URLs. Custom Stripe domains are not
supported; redirect checks allow only `checkout.stripe.com` / `billing.stripe.com`.

5. Forward local **snapshot** events with Stripe CLI. Use the listener's printed signing
   secret, which differs from a dashboard endpoint's secret:

```sh
stripe listen --events customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,customer.subscription.paused,customer.subscription.resumed,customer.subscription.trial_will_end,customer.subscription.pending_update_applied,customer.subscription.pending_update_expired,checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,invoice.paid,invoice.payment_failed,invoice.finalization_failed --forward-to localhost:8000/api/v1/billing/webhook
```

For a hosted endpoint, configure those events with the pinned API version in Workbench.
Connect/organization events and thin-event destinations are not supported. Hosted webhook
delivery requires HTTPS. CLI authentication/listening may require its own permissions.

## Configure plans and prices

In a trusted operator shell, supply `PLAN_OPERATOR_DATABASE_URL`. Price mapping additionally
uses the same Stripe settings to retrieve and validate the provider Price before saving it.

```sh
uv run --extra billing python -m app_core.plan_admin put-plan pro 'Pro' --feature records.write
uv run --extra billing python -m app_core.plan_admin put-plan enterprise 'Enterprise' --feature records.write
uv run --extra billing python -m app_core.plan_admin map-price pro price_YOUR_PRO_PRICE
uv run --extra billing python -m app_core.plan_admin map-price enterprise price_YOUR_ENTERPRISE_PRICE
uv run --extra billing python -m app_core.plan_admin hide-price pro price_YOUR_OLD_PRICE
```

One price per plan/mode is offered at checkout. Mapping a new price hides the old one but
retains its mapping for existing subscribers. A price cannot be remapped to another plan.
Pricing/interval changes require a new Stripe Price. Names and feature assignments are
database-configurable; new feature keys require implementation/registration and a migration.
Commands are transactional and audited. There is no workspace-admin configuration API.

## Preview and recovery

With the private environment exported, start the API from `backend` using
`uv run --extra billing uvicorn app_core.main:create_app --factory --host 127.0.0.1 --port 8000`
and start the frontend with `bun run dev` from `frontend`. Keep the Stripe listener running.

As an administrator, open Settings → Plan & billing, choose a plan, and complete hosted
Checkout using test payment details. On return, press **Refresh billing**. Redirects never
grant access or confirm payment. **Manage billing** opens the portal for this workspace's
stored customer; it stays available when feature access is suspended. Editors/viewers
can read billing status but cannot create checkout/portal sessions or reconcile.

Checkout accepts only a plan key; the server resolves its price/customer. Per-workspace/mode
session locks serialize checkout, reconciliation, and webhooks. Attempts commit before
provider calls with immutable parameters and persistent idempotency keys. An open checkout
is reused for its original plan; switching requires completing it or waiting for one-hour
expiry. Existing nonterminal subscriptions must use the portal instead of another checkout.

After an ambiguous provider response, retries discover the customer's session using the
server-created attempt ID before creating anything. If no session can be discovered near
expiry, or an ambiguous customer creation is older than 23 hours, the app stops for operator
reconciliation rather than risk using an expired idempotency key. Inspect the local request
ID and Stripe request logs; confirm provider state before repairing mapping/attempt rows
with a trusted DBA session. Never blindly clear an attempt. No destructive automatic
recovery command is provided.

Webhooks verify the raw-body signature with five-minute tolerance and a 256 KiB limit,
reject wrong mode/Connect events, and exempt only the exact webhook POST from browser CSRF.
Event IDs and snapshots commit together; failures return 503 for Stripe retry, duplicates
are no-ops. The handler fetches current subscriptions under the workspace lock, so old or
same-second event payloads cannot restore stale access. Tenant linkage uses stored customer
IDs, never subscription metadata or browser-provided tenant IDs.

**Refresh billing** reconciles missed events. Monitor Stripe delivery failures and retry
them. Webhook processing is synchronous with provider timeouts; high-volume deployments
should add a durable queue while preserving atomic deduplication and workspace serialization.
There is no scheduled reconciliation job. Missed renewals fail closed at the old period
end until a successful webhook or admin refresh. Frontend state is not realtime; backend
checks are authoritative.

## Live readiness and testing

Live operation requires `STRIPE_MODE=live`, `STRIPE_ALLOW_LIVE=true`, matching live secret
or restricted key, live signing secret, HTTPS frontend origin, live portal configuration,
and live price mappings. Mode is persisted on customers, prices, attempts, and subscriptions.
The signing secret's mode cannot be inferred from its prefix; verify matching endpoint delivery.
No live setup or charges were performed during implementation.

Before launch, validate actual sandbox Checkout/Portal/webhooks, failed renewals, cancellation,
tax/invoice settings, account activation, support/refund procedures, monitoring, and recovery.
Automatic tax, refunds/disputes, usage metering, referrals, and onboarding billing logic are
not implemented. Tests use a fake Stripe transport, real signatures, and real PostgreSQL;
they do not prove a real account's configuration.

```sh
cd backend
uv sync --extra dev --extra billing
# Set TEST_DATABASE_ADMIN_URL and TEST_DATABASE_URL to a disposable PostgreSQL cluster.
# Tests create/drop isolated databases and a restricted starter_billing test login.
uv run --extra dev --extra billing pytest
uv run --extra dev ruff check src tests
cd ../frontend
bun install --frozen-lockfile
bun test
bun run build
```

Primary references: [Checkout](https://docs.stripe.com/api/checkout/sessions/create),
[subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks),
[signatures/ordering](https://docs.stripe.com/webhooks),
[idempotency](https://docs.stripe.com/api/idempotent_requests),
[portal configuration](https://docs.stripe.com/customer-management/configure-portal),
[versioning](https://docs.stripe.com/api/versioning).
