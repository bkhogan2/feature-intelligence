# Platform administration — plan feature controls

Platform owners and platform admins operate the application across workspaces.
They are not workspace roles and cannot be granted through customer invitations,
subscription purchases, workspace creation, or the browser.

## Owner-controlled bootstrap

An app owner (or their trusted deployment operator) configures verified identity
subject IDs in server-side environment configuration:

```
PLATFORM_OWNER_SUBJECTS=verified-owner-subject-id
PLATFORM_ADMIN_SUBJECTS=verified-trusted-admin-subject-id
```

Both are comma-separated lists. Empty lists grant no platform access. Admins
cannot be configured without at least one owner; wildcards are rejected. Owners
also have platform-admin access. Use stable subject IDs from the configured
identity provider, never an email address, workspace slug, or client-supplied role.
For local authentication use the application's user ID; for Firebase use the
verified Firebase UID. Lists are specific to the deployment/authentication provider.
Review them whenever changing authentication providers or cloning the starter.

Restrict deployment configuration changes to app owners and explicitly trusted
operators. Never put these values in VITE_ frontend configuration. Restart the
backend after changing them. Revoking an ID and restarting denies subsequent API
requests even for an existing session. The Settings menu refreshes after sign-in
or page reload; every catalog read and save rechecks server access.

There are intentionally no platform invitation or role-mutation HTTP endpoints.
A future invitation workflow must authorize an **owner** on the server, not merely
any platform admin. Delegated platform admins must never grant their own peers or
owners. Workspace admins can continue inviting workspace admins/editors/viewers.

## Current UI and API

Settings → Platform admin appears only for accounts with a server-reported
platform role. `/api/v1/me` returns `platform_role` (`owner`, `admin`, or null).
`GET /api/v1/platform/plans` authenticates the caller and checks their verified
subject against the configured lists on every request. It reports plans, active
status, known feature assignments, and whether plan enforcement is enabled.

The catalog is global, independent of the selected workspace. It contains no
customer records, member list, billing secrets, or identity allowlists. Platform
access does not bypass workspace membership, roles, plan gates, or row security.
The existing app_runtime database role has only read access to plan configuration;
the editor uses a separate restricted credential described below.

## Enable plan switches

Run migrations with the schema-owner credential. Migration 0004 creates the
NOLOGIN `app_plan_editor` role. Provision a dedicated login with membership in
**only** that role (not app_runtime, app_plan_operator, or app_billing_service):

```sql
CREATE ROLE starter_plan_editor LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOBYPASSRLS PASSWORD '<secret-from-your-secret-manager>';
GRANT app_plan_editor TO starter_plan_editor;
```

Configure `PLATFORM_DATABASE_URL` server-side with that login's connection string
for the same database as `DATABASE_URL`, then restart the backend. Never expose
this credential as VITE_ configuration. Omitting it leaves a read-only catalog.
Owner/superuser and broad operator credentials are rejected at startup.

Owners and delegated platform admins can toggle registered features, then choose
**Save changes** or **Cancel** per plan. Saving affects all workspaces on that
plan. Backend gates evaluate the new assignments on the next request; pages
already open may need a refresh to update their disabled buttons.

`PATCH /api/v1/platform/plans/{plan_key}/features` accepts only `features` and
`revision`. A stale revision returns 409; the UI retains the draft until the admin
explicitly reloads/discards it. Tab focus does not discard unsaved edits. Updates
serialize with the operator CLI and audit the verified subject, platform role,
plan, and before/after assignments in the same transaction. No-op saves add no
audit record. Unrecognized stored assignments are preserved for compatibility;
clients may only submit features registered in this backend version.

The editor cannot change plan activation, names, prices, subscriptions, workspace
assignments, or platform identities. Disabled plans remain disabled. When
`BILLING_ENABLED=false`, plan checks remain bypassed regardless of assignments;
workspace membership and roles always apply.

Add a new feature in the backend `FEATURES` registry with a migration adding its
`plan_features` row, then enforce it at the relevant API operation and expose its
availability in the frontend. A switch alone does not enforce an unguarded API.

## Verification

Real PostgreSQL tests cover owner/admin saves, customer/anonymous denial,
conflicting edits, unknown features, audit records, live backend gating, disabled
plans, restricted DB grants, readonly fallback, logout and role revocation.
Billing configuration, payment provider resources, and cancellation are unchanged.
