# Existing backend extraction

Source: `/Users/brianhogan/Documents/ChatGPT/Ample AI/work/gi-triage-ai-runtime`, observed HEAD `bec7289001b2debb91740df95ac89db7347acefe`. Files were read from its working tree without changing it.

Retained and adapted:

- `auth/identity.py`: Principal, VerifiedIdentity, identity-verifier and authentication interfaces, bearer parsing, membership-based principal construction. Firebase verification moved to optional `auth/google.py`.
- `auth/onboarding.py`: token hashing, expiry, verified-email matching, tenant identity checks, atomic repository acceptance contract, policy versioning.
- `auth/clinic_admin.py`: renamed workspace admin repository/service contracts and policies; invitation expiry/token generation and delivery result handling.
- `domain/models.py`: only workspace, membership, invitation, role and appearance models.
- `repositories/clinic_access_repository.py`: renamed workspace access contract.
- `services/workspace.py`: generic workspace catalog contract.
- `auth/invitation_email.py`: disabled sender plus adapter interface; no live mail delivery.
- Frontend Firebase adapter follows the original project-level auth pattern without synthetic Cloud Run fallbacks.

New composition/glue: FastAPI endpoints, PostgreSQL adapter with a restricted runtime role and transaction-scoped RLS, local password/session adapter, CLI provisioning, generic record/activity example, frontend provider/context and generic management screens, tests. These let the extracted services run without GCP. Medical models, source documents, EMR/Retell integrations, cloud resources, credentials, live endpoints, original deployment settings and PostgreSQL medical schema are excluded.

The extraction is an independent snapshot, not an import of the original backend and not automatic synchronization with it. Port security fixes deliberately between the projects. Existing production/GCP deployments were not modified.

PostgreSQL migration: `migrations/0001_workspace_core.sql` adapts the source restricted-role and `SET LOCAL` transaction-context pattern for generic records and audit. Authentication metadata remains service-managed. Every database path and integration test now uses PostgreSQL; there is no SQLite adapter or fallback.
