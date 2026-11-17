# Optional workspace plan gates

This is the configurable entitlement foundation. Optional hosted Stripe Checkout,
subscriptions, signed webhook reconciliation, and customer portal support are now
implemented; see [STRIPE_BILLING.md](STRIPE_BILLING.md) for setup, lifecycle policy,
test/live separation, and limitations. Browser redirects never grant access.

`BILLING_ENABLED=false` (default) preserves existing behavior: registered plan gates
are bypassed, but authentication, active workspace membership, roles, and PostgreSQL
row-level security still apply. `true` requires an operator-assigned active plan or,
when Stripe is enabled, an eligible subscription. Unassigned workspaces have no gated features. Invalid values stop startup.
The setting is read at startup; restart to change it.

## Local setup and operator configuration

1. Run the existing PostgreSQL setup and `python -m app_core.migrate` with the
   schema-owner `DATABASE_ADMIN_URL`. Migrations 0002/0003 are additive; never edit 0001.
2. A database administrator grants `app_plan_operator` to a **separate trusted operator
   login**. Never grant it to `app_runtime` or the API login. Never expose the operator
   credential to the web server, browser, or a workspace administrator.
3. Set `PLAN_OPERATOR_DATABASE_URL` only in the operator shell. From `backend`, use:

```sh
uv run python -m app_core.plan_admin put-plan pro 'Pro' --feature records.write
uv run python -m app_core.plan_admin put-plan enterprise 'Enterprise' --feature records.write
uv run python -m app_core.plan_admin assign YOUR_WORKSPACE_SLUG pro
uv run python -m app_core.plan_admin clear YOUR_WORKSPACE_SLUG
uv run python -m app_core.plan_admin disable pro
```

`put-plan` replaces the complete feature assignment and reactivates that plan;
omit `--feature` for an empty plan. It can create arbitrary plan names without
code changes, but only known developer-registered features can be assigned.
`disable` removes access for every assigned workspace; `clear` removes one assignment.
Commands are transactional and write a database-actor audit record. The API runtime
has read-only grants on plan tables, and there is no plan-mutation HTTP endpoint.

## Preview

Start the normal backend with `BILLING_ENABLED=true` and frontend with `bun run dev`.
Sign in as an admin/editor and open Records. Before assignment, editing is gated.
Assign Pro with the operator CLI, then refocus/reload the page: creation/deletion
become available. Viewers remain read-only on every plan. Clear/disable the plan:
the next backend mutation is denied immediately; refocus/reload refreshes presentation.
Turning billing off restores record editing for admins/editors without assigning plans.

## Adding real application features

Register the key in `app_core.entitlements.FEATURES`, add an additive migration to
`plan_features`, implement the capability, and call `Entitlements.require(principal,
key)` after normal authorization on **every** protected entry point (including agent
tools or jobs if later introduced). Never accept a tenant ID from an untrusted body.
Use `useEntitlements(workspace)` and `FeatureGate` for presentation only. They fail
closed on missing data and discard previous identity/workspace snapshots.

The example gates only the existing record-create/delete HTTP routes using
`records.write`; plan policy does not replace database role/tenant policies. The
read-only `/api/v1/entitlements` endpoint derives workspace scope from authenticated
membership. It is deliberately not a general-purpose authorization API.

Plan changes take effect on the next backend request, without entitlement caching.
Frontend refresh is on mount, identity/workspace change, and window focus; it is not
real-time. Plan configuration is operator CLI-only; customers use Settings for checkout,
subscription refresh, and the customer portal. Manual grants override Stripe subscription
state and block new checkout, but do not cancel an existing subscription or its charges.
