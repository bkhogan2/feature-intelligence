# Firebase Authentication adapter

The pluggable frontend registry supports `local` and `firebase`; `google` remains a compatibility alias. The Python factory accepts the same Firebase alias or an injected custom verifier. Database access and workspace permissions stay in PostgreSQL.

## Project setup

Create a dedicated Firebase project, register a web app, accept Firebase's terms in the console, and initialize Authentication with Email/Password enabled. `firebase.json` includes a reusable email/password-only provider configuration. After accepting terms, apply it to an explicitly chosen project with `firebase deploy --only auth --project YOUR_PROJECT_ID` using a current Firebase CLI. The sample `.firebaserc.example` contains a placeholder; each app supplies its own local binding.

Add the development/production hostnames to Authentication's authorized domains. Configure a password policy and email-enumeration protection appropriate to your application. Do not enable anonymous sign-in for this shell.

For this development copy, the separate project is `standard-starter-bh-20261031` (Standard App Starter Dev). The project and web app have been created without linking a billing account. The owner accepted Firebase terms, Authentication was initialized, and Email/Password sign-in is enabled. A live smoke test on 2026-10-31 verified password sign-in, token verification with disabled-user checks, PostgreSQL workspace membership and data isolation, and rejection of missing tokens and inaccessible workspaces. It used a synthetic verified identity and a fresh test database; both were removed afterward. No verification or reset emails were sent. A real initial administrator still needs to create and verify their Firebase account and have its UID provisioned into a workspace.

The prepared `frontend/.env.firebase.local` and `backend/.env.firebase.local` files are ignored by Git and are specific to this local development copy. They contain the public web configuration and PostgreSQL development settings. They are not template defaults and should not be copied to a new application.

## Activate locally after console setup

Frontend, from the repository root:

```sh
cd frontend
bun run dev --mode firebase
```

Backend (with the PostgreSQL database running):

```sh
cd backend
set -a
. ./.env.firebase.local
set +a
uv sync --extra dev --extra google
uv run uvicorn app_core.main:create_app --factory --host 127.0.0.1 --port 8000
```

Supply Application Default Credentials authorized for this Firebase project, such as a hosting-platform identity or `gcloud auth application-default login` for local development. Runtime revocation/disabled-user checks require permission to read Firebase users; do not distribute service-account keys in the frontend or repository. The app checks project agreement between frontend and backend before sign-in and does not fall back to local password/cookie authentication in Firebase mode.

For another app, configure `VITE_AUTH_PROVIDER=firebase`, `VITE_GOOGLE_API_KEY`, `VITE_GOOGLE_AUTH_DOMAIN`, `VITE_GOOGLE_PROJECT_ID`, optional `VITE_GOOGLE_APP_ID`, backend `AUTH_PROVIDER=firebase`, and `GOOGLE_PROJECT_ID`. All VITE values are public build-time settings. Backend credentials are runtime secrets/identities.

## Accounts and invitations

Provision the initial administrator's Firebase UID into a workspace using the operator CLI's `--subject` flag. Never link an existing local account to a new Firebase UID just by matching email. Use a fresh development database/workspace or plan an explicit account migration when switching existing users between providers.

Invited people can create a Firebase account from the invitation login screen. Account creation alone grants no workspace access. The UI provides explicit email verification, rechecking after verification, and password reset actions. The backend requires a verified email and a valid, unrevoked Firebase token before allowing invitation acceptance. The invited email must match, and access is created only after the invitation and policies are explicitly accepted. These UI actions can send email through Firebase when clicked; the automated tests do not send emails.

Firebase tokens are refreshed through the SDK. The backend uses the configured Firebase project, verifies tokens with revocation checks, rejects provider-level tenant claims, and does not accept emulator configuration in the live adapter. Global workspace membership and admin/editor/viewer permissions remain independent of Firebase.

## Validation boundary

From `frontend/`, build both profiles with `bun run build` and `bun run build --mode firebase`. Run the PostgreSQL and Firebase adapter tests with `uv sync --extra dev --extra google`, the TEST_DATABASE connection variables, and `uv run pytest`. Without the optional Firebase Admin dependency, the Firebase-specific test module is skipped. Tests cover verifier options, revoked/disabled/invalid tokens, transient verification failures, project/tenant mismatch, verified-email gating, provider isolation, duplicate-email identity collisions, and no automatic workspace access for new identities. These checks do not substitute for a live sign-in test once Firebase is activated.

Sources: [Firebase web authentication](https://firebase.google.com/docs/auth/web/start), [managing Firebase users](https://firebase.google.com/docs/auth/web/manage-users).

## Manual local walkthrough

1. In the development project's Authentication → Users tab, choose **Add user** and enter your own email and password. The console account used to administer Firebase is separate from an application's email/password account.
2. Open http://127.0.0.1:5173 and sign in with that new account. Choose **Send verification email**, follow the link in your inbox, then return and recheck verification.
3. Copy your user's UID from Firebase Authentication → Users. In a terminal, run the following from this repository, replacing `YOUR_FIREBASE_UID` and the email. This assigns the initial administrator to a new workspace; it does not change the Firebase password.

```sh
cd backend
set -a
. ./.env.firebase.local
set +a
PYTHONPATH=src .venv/bin/python -m app_core.cli provision \
  --subject YOUR_FIREBASE_UID \
  --email YOUR_EMAIL \
  --workspace my-workspace \
  --name 'My workspace'
```

4. Sign out and back in or reload the app. Select the workspace and create a record. To see isolation, provision the same UID into a second workspace with a different slug/name, then switch workspaces: each has its own records.

The local preview must be running with both frontend and backend Firebase profiles. The old local demo password does not authenticate a Firebase account. Creating a Firebase account alone does not grant workspace membership.
