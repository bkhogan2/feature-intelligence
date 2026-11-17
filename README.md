# Feature Intelligence System

Turn incoming feedback into product decisions. Capture a request, support it, review the AI grouping suggestion, and link it to an opportunity. On Opportunities, reviewers can compare and set priorities, decide what to plan, and track the delivery status. Tasks track the implementation underneath each opportunity.

## Close the loop

- On a Request or Opportunity, choose **Update submitters**. Write an update or draft one with AI, edit and preview it, then publish. It appears in the **Updates** page for the original submitters. Reviewers can review the workspace history there as well.
- On a request awaiting review, choose **Ask for clarification**. The original submitter replies in Updates; the request returns to **New** with its original wording intact and the answer available for the next triage pass.
- On a **Shipped** opportunity, record an **Outcome check** and attach a short note or evidence link. Shipping records delivery; the check records whether the problem improved.

This is an authenticated workspace app. Submitting a request sends an in-app receipt. Approval and rejection notify the submitter, and reviewers can publish additional updates. The app does not send email. Run the versioned database migrations before starting the app. See [the product pipeline](docs/PRODUCT_PIPELINE.md) and [starter provenance](STARTER_PROVENANCE.md).

The inherited starter documentation follows.

# Verified starter baseline

See [STARTER_CHECKPOINT.md](STARTER_CHECKPOINT.md) for the selected baseline, copy checklist, validation and deployment limitations.

# Workspace App Starter

A reusable React + Tailwind + shadcn frontend and Python backend. The UI comes from Referral Focus. Identity verification, workspace membership mapping, invitation acceptance, role policies, and administrator services were extracted from the existing GI Triage backend and renamed for general applications. Both original repositories remain untouched.

## Repository layout

- `frontend/`: React screens, UI components, styles, public assets, and Bun/Vite configuration.
- `backend/`: Python API, authentication, workspace services, database migrations, and tests.
- `deploy/`: Google Cloud and Firebase guides, plus local PostgreSQL initialization.
- Root: shared README, Makefile, Dockerfile, Compose, and Firebase project configuration.

Each application has its own dependencies and environment files. The frontend calls the backend HTTP API; only the backend connects to PostgreSQL. Run commands from the directory shown below.

## Run locally

For the current review app (frontend port 5189, database port 55439), run `bash scripts/dev-backend.sh` from the project root. This explicitly loads the ignored `backend/.env.local` before starting the API on port 8019, including saved `ANTHROPIC_API_KEY`, `TRIAGE_ENABLED`, and `TRIAGE_MODEL`. Restart this command after changing that file. Keys remain server-side; direct Uvicorn commands do not load the file automatically.

From the repository root:

```sh
cd frontend
cp .env.example .env
bun install --frozen-lockfile
bun run dev
```

Start PostgreSQL, then start the backend in another terminal, beginning at the repository root:

```sh
docker compose up -d db
cd backend
cp .env.example .env
set -a
. ./.env
set +a
uv sync --extra dev
uv run python -m app_core.migrate
uv run python -m app_core.cli demo
uv run uvicorn app_core.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:5173. The explicit `demo` command creates synthetic local accounts, never on server startup:

- `demo@example.com` / `starter-demo-pass`: administrator in Product Feedback.
- `viewer@example.com` / `starter-demo-pass`: read-only member of Product Feedback.

Sign in to Product Feedback and submit a request. Settings includes appearance, members, roles, and invitations for administrators. Local development, tests, and deployment all use PostgreSQL. Docker Compose persists the local database in a named volume. The web application uses a restricted database login, separate from the migration owner.

Optional database-configured plans and Stripe subscriptions are documented in [PLAN_GATES.md](PLAN_GATES.md) and [STRIPE_BILLING.md](STRIPE_BILLING.md). Billing is off by default. Enable the `billing` backend extra and separate restricted billing credentials for hosted Checkout, customer portal, signed webhook reconciliation, and the Settings billing panel. Real checkout requires your own Stripe sandbox configuration; no credentials are bundled.

## What is reusable

- Real local email/password sign-in with Argon2 hashes, opaque HttpOnly cookie sessions, expiry, logout revocation, login throttling, mutation-origin checks, and bounded request bodies.
- A provider-independent token verifier and frontend auth adapter. Google/Firebase is an optional adapter with no inherited live configuration.
- Server-checked active workspace memberships and `admin`, `editor`, `viewer` roles. A workspace selection is a request, never proof of access.
- Member disabling and role changes, last-administrator protection, invitation creation/revocation, verified-email acceptance, expiry, replay protection, and versioned policy acceptance.
- Per-user saved appearance, workspace activity, and an example tenant-scoped JSON record repository.
- A responsive shell, workspace selector, login screen, reusable UI components, and light/dark themes.

The records API is an extension example. Add application-specific models and validation while preserving the authenticated principal and scoped repository pattern; a JSON object is not a substitute for your domain schema.

## Provisioning and password reset

Provision users and workspaces as an operator, never through public self-service endpoints:

```sh
cd backend
uv run python -m app_core.cli provision --email owner@example.com --workspace my-company --name 'My Company'
uv run python -m app_core.cli user --email invited@example.com
uv run python -m app_core.cli reset-password --email invited@example.com
```

Passwords are prompted without terminal echo. `provision` creates the initial workspace membership; `user` creates an account without workspace access so it can accept an invitation. The operator must verify ownership of local account emails before provisioning. Local password reset is operator-assisted and revokes existing sessions. Automated email verification/reset delivery is not configured. Google mode delegates verification and password-reset emails to Firebase.

Invitations are manual share links: creating one sends no email. Tokens travel in URL fragments and POST bodies, are removed from the visible URL on loading, and only token digests are stored. A new recipient signs in first, then explicitly accepts the policies and invitation. Replace `frontend/public/terms.html`, `frontend/public/privacy.html`, and the policy versions for each application.

## Optional Firebase identity

Install the optional backend dependency with `uv sync --extra google`. Set backend `AUTH_PROVIDER=firebase` and `GOOGLE_PROJECT_ID`. Supply credentials through your hosting platform's Application Default Credentials mechanism. Set frontend `VITE_AUTH_PROVIDER=firebase` plus the public Firebase web settings in `frontend/.env.example`, then rebuild. The frontend module is loaded only in Firebase mode. The legacy `google` provider name remains an alias. Use the project-level user pool; application workspace membership remains in the app database.

Provision a Google UID with `cli provision --subject GOOGLE_UID --email owner@example.com --workspace my-company --name 'My Company'`. Only verified email identities are accepted. Identities are never silently merged by matching email. A separate Firebase development project and web app have now been registered. Firebase terms have been accepted and Email/Password Authentication is enabled; a live synthetic sign-in and PostgreSQL isolation smoke test passed. A real administrator account still needs verification and workspace provisioning. See [the Firebase setup guide](deploy/firebase/README.md) for prepared local profiles and activation steps.

For another provider, implement `AuthProvider` in `frontend/src/lib/auth-provider.ts` and `IdentityTokenVerifier.verify` in Python. Compose it with `create_app(store=..., verifier=...)`, setting `AUTH_PROVIDER=custom`. The verifier must validate issuer, audience, signature, expiry, and relevant revocation policies and return a stable subject and verified email. The app retains workspace/role checks independently of the provider.

## Storage and hosting

PostgreSQL is the only supported backend. Configure `DATABASE_URL` for the web process and operator CLI; configure a separate `DATABASE_ADMIN_URL` only for migrations. Both standard PostgreSQL URIs and libpq connection strings work, including TCP/TLS and Cloud SQL Unix sockets. No database filesystem path or SQLite fallback remains.

The adapter uses Psycopg with a bounded connection pool (`DB_POOL_MAX_SIZE=4` by default). Each transaction assumes the restricted `app_runtime` role and sets identity/workspace context from the authenticated server principal. PostgreSQL row security is enabled and forced on tenant-owned application records and audit entries. An unscoped query returns no rows; writes require the appropriate active workspace membership. Global identity/session metadata and workspace administration are service-managed with explicit permission checks, rather than tenant data exposed directly to clients.

Run the versioned migration command before starting a new application version. It uses an advisory lock, an atomic transaction, and checksums for applied SQL files. The web server validates the schema version and rejects superuser, BYPASSRLS, and schema-owner runtime credentials. Migration-owned tables and roles must remain separate from the app login. Local Docker initialization creates both roles; another provider's DBA must grant `app_runtime` to the runtime login. Future schema changes belong in new numbered SQL migrations, never edits to an already applied migration.

Development uses a Vite API proxy. The container serves the compiled frontend and API from one origin and listens on `$PORT` (8080 by default). Outside development, `COOKIE_SECURE=true` and exact allowed origins are required. Keep cookie-authenticated frontend/API traffic on the same site, normally through the same reverse proxy.

For Google Cloud, see [the Cloud Run + Cloud SQL runbook](deploy/gcp/README.md). It covers separate migration/runtime secrets and service accounts, socket connections, migration jobs, connection budgets, and provider changes. No cloud resources are provisioned by this starter. CopilotKit remains deferred.

Build the deployable image with `docker build -t workspace-starter .`. Supply the restricted database connection string via your hosting provider's secret mechanism, and run `python -m app_core.migrate` as a separate one-off job with owner credentials before deploying. The web process does not run migrations or seed accounts.

Root shortcuts are available through `make frontend-install`, `make frontend-dev`, `make backend-install`, `make backend-dev`, `make db-up`, and `make build`. Backend commands expect the environment variables to be exported first, as shown above. Install the optional Firebase dependency and use the Firebase profiles when testing Firebase.

## Validation

```sh
# From the repository root:
(cd frontend && bun run build)
cd backend
# Against the local Docker database; each test creates and drops its own temporary database.
export TEST_DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL"
export TEST_DATABASE_URL="$DATABASE_URL"
uv run pytest
uv run ruff check src tests
```

Tests run against real PostgreSQL databases and cover forced row security without SQL workspace filters, denied cross-tenant inserts, pool context reset, concurrent last-admin changes, migration repeatability, runtime-owner rejection, cross-workspace reads/deletes and forged tenant input, role restrictions, disabled memberships, last-admin protection, session expiry/logout, origin checks, persistence, invitation email binding/replay/expiry/revocation, account preferences, request size limits, throttling, and a custom identity adapter. Browser verification covered actual login and record creation against PostgreSQL; integration tests verified cross-workspace isolation. The container image built successfully, served its health endpoint against PostgreSQL, and ran the packaged migration command. Firebase frontend compilation and adapter tests are checked separately; live Firebase identity and a GCP deployment require their own environment validation.

See `backend/PROVENANCE.md` for the extraction boundary. To start a new app, copy this repository without `.git`, `node_modules`, `dist`, `.venv`, `.env` files, or `backend/data`, then change the branding and add your domain models.

## Shell source and customization

The generic shell is extracted from `bkhogan2/referral-focus` revision `2a289009a3cde2373988de88822b71afda509f98`, matching the current GI Triage icon rail, workspace sidebar, centered header, and joined rounded content inset. The reusable sidebar/sheet primitives and shell geometry were copied from that revision. Clinic routes, medical workflows, tenant branding APIs, and Ample AI assets are excluded.

Edit `frontend/src/lib/app-config.ts` for the name/support destination, and `frontend/src/components/app-shell.tsx` for modules and contextual navigation. Existing local/Firebase login, workspace selection, backend access checks, records, activity, and people management remain connected. Header history is bounded to the active signed-in workspace session. This `shell-refresh` branch is separate from the local `copilotkit-frontend` preview branch.

## Empty right sidebar

The right rail and panel mirror the left workspace sidebar’s width, navigation surface, divider, rounded outer corners, and header offset. Its header toggle and edge handle operate independently of the left sidebar. On narrow screens it uses the same sheet behavior. This step leaves the panel and rail empty; CopilotKit is not included. The original left keyboard shortcut remains independent.

## Switchable shell layouts

Settings → Shell layout switches between **Left inset** (one outer workspace frame extends to the thin right margin and contains the right sidebar, without a right activity rail) and **Dual inset** (both outer edges use the inset treatment). Both sidebars remain available and preserve their independent open states. The choice persists on this device in `app-starter:shell-layout`; it is separate from backend account appearance settings and does not change the color palette.

`frontend/src/lib/shell-layout.ts` owns the preset contract and shared desktop/mobile dimensions. `frontend/src/components/shell-layout.css` owns geometry; `app-shell.css` owns navigation surface colors, while the existing global theme tokens continue to control the color palette. `AppShell` accepts a typed `layout` prop, so another control can change it without remounting content or sidebars. Portalled mobile drawers receive the same resolved layout variables. New presets can extend this contract without copying the shell or changing authentication, workspace services, or page components.

Run `bun run test:shell` from `frontend/` for layout contract checks. No CopilotKit integration is included in this refactor.

### Read-only assistant demo (local, synthetic data only)

The right sidebar uses CopilotKit's controlled chat view with a server-side Claude Agent SDK adapter. The model can search fixed synthetic fixtures in the signed-in workspace and ask the browser to open Records with a filter. The browser acknowledges the rendered view before the model reports navigation success. Existing backend authentication, workspace membership checks, and PostgreSQL RLS apply. No write, shell, filesystem, or web tools are available to the model.

Install optional dependencies from `backend/` with `uv sync --extra google --extra agent --extra dev`. Create an ignored `backend/.env.agent.local` containing:

```env
ANTHROPIC_API_KEY=your-server-side-key
AGENT_ENABLED=true
AGENT_MODEL=claude-haiku-5-5
```

Load your existing backend database/auth profile and this file into the backend environment, then run `PORT=8000 uv run --extra google --extra agent python -m app_core.serve`. Environment files are not loaded automatically. Never set the key in `VITE_*` or commit it. To include the optional harness in the container, build with `--build-arg BACKEND_EXTRAS=google,agent` and inject credentials at runtime.

Seed the three fixed fixtures once in an existing workspace (this does not create identities or memberships):

```sh
uv run --extra google --extra agent python -m app_core.agent_demo --email YOUR_EMAIL --workspace YOUR_WORKSPACE
```

Open the app and click **Find demo records**. Requests are independent; the visible chat history is not replayed to the model. New chat, sign out, or workspace switching cancels active work and clears the conversation. Drag the assistant panel's inner edge to resize it; focus the separator and use arrow keys for keyboard resizing. Width persists locally under `app-starter:assistant-width`.

Cost controls: default Haiku model, no automatic expensive-model fallback, four model turns, 768 output tokens per model response, a 90-second request timeout, and a $0.05 SDK budget per run. The SDK budget is checked between model calls, not an absolute billing guarantee; the last call may exceed it. The reported model cost appears in the chat after a completed run. There is no daily/account spending cap in this starter; use provider-side billing controls as well. Stop aborts the request and terminates the isolated worker process group. Worker environments exclude database and Firebase credentials and use temporary session storage.

The application-owned tool implementation is in `backend/src/app_core/agent_tools.py`; Claude-specific behavior is in `agent_worker.py`, and the authenticated transport is in `agent.py`. CopilotKit renders the conversation through `frontend/src/lib/assistant-transport.ts`. This separation permits other harness adapters; a Deep Agents adapter has not been implemented or certified compatible.

This is not a HIPAA-approved deployment. Send synthetic prompts only. The model receives the user's prompt and fixed fixture fields; it does not receive ordinary record titles/payloads, account email, or authentication tokens. BAA eligibility, hosting, retention, telemetry and enabled features must be reviewed before any PHI use. API credentials remain in the ignored server configuration.

### Customizing the reusable shell and assistant

`frontend/src/lib/app-config.ts` owns the app ID, branding/icon, home copy, page/module navigation metadata, assistant title/welcome copy, starter prompts and panel sizing policy. Set a unique app ID when cloning the starter so preferences and Firebase client instances are namespaced. Navigation metadata is shared by the router and shell; new page behavior still needs an explicit renderer in `app.tsx`. Color themes remain token-driven and separate from the inset layout presets. The legacy browser theme preference migrates to the app namespace without resetting it.

Assistant presentation is split into `assistant-chat-view.tsx` and the compact shadcn-style `assistant-composer.tsx`; `use-assistant.ts` owns request state and cancellation. `assistant-contracts.ts` validates server config and streamed events, including message-size bounds, before they can trigger a UI action. `assistant-actions.ts` contains the application-specific Records navigation; the transport itself does not render UI. Panel width restoration is clamped to the current viewport, and blocked local storage cannot break startup or resizing. Mobile drawers omit the empty desktop activity rail.

Server policy is centralized in `backend/src/app_core/agent_settings.py`. `AGENT_MODEL`, `AGENT_MAX_TURNS`, `AGENT_MAX_BUDGET_USD`, `AGENT_MAX_OUTPUT_TOKENS`, `AGENT_MAX_MESSAGE_CHARS`, `AGENT_REQUEST_TIMEOUT_SECONDS`, `AGENT_ACTION_TIMEOUT_SECONDS` and `AGENT_MAX_CONCURRENT_RUNS` are validated at startup and passed to the harness. Defaults remain Haiku, four turns and the $0.05 SDK budget. The UI reads the actual server values; its model menu is informational, not a way to override policy. Invalid limits fail startup rather than silently removing a limit. Restart the backend after changing them. The SDK budget is still a between-call check, not an absolute billing cap.

Deliberate boundaries remain in code: authentication, workspace authorization/RLS, the read-only tool allowlist, permitted UI action names and the synthetic fixture data. They are not browser-editable settings. The Records/Activity sample features and demo agent instructions must be adapted when building a new domain app; arbitrary database access and generic writes are not enabled by configuration. Existing `VITE_API_BASE_URL` selects the deployed API base, while `DEV_API_TARGET` selects only Vite's local proxy.

Run `bun run test` in `frontend/` for layout/stream/configuration boundary checks. For no-charge visual review, start Vite and open `/tests/fixtures/assistant.html`: this clearly labeled offline fixture uses the same view/composer and covers narrow/dark, complete, running, stopped, error, multiline input and reset states. It makes no backend or model requests and is not included in the production build. Backend tests use the existing PostgreSQL test setup and fake the harness for protocol checks.

### Feedback support

Active workspace members (including viewers) can support or withdraw support on an Inbox request. Each member counts at most once per request; creating a request does not automatically support it. Support signals interest, not priority or permission to edit/triage. Capture remains form-only.

`GET /api/v1/feedback` includes `support_count` and `supported_by_me`. Authenticated `POST /api/v1/feedback/{id}/support` and `DELETE` on the same path return the saved count/current-user state and are idempotent. The server derives both user and workspace from the authenticated membership, never from a request body. A unique key, workspace-matching foreign key, forced RLS, and own-support-only deletion enforce the boundary in PostgreSQL. Actual changes emit audit events; retries do not create duplicate events.

Migration `0006_feedback_support.sql` adds support storage without changing existing feedback. Run the normal migration command against the intended deployment database before starting the updated API (schema version 6). For the local review, only `feature_intelligence_preview` was migrated; its eight original requests were verified unchanged.

### Manual AI triage

The Inbox supports explicit analysis, three saved suggestion outcomes and human-confirmed opportunity creation/linking. See [TRIAGE_WORKFLOW.md](TRIAGE_WORKFLOW.md) for setup, security boundaries, deadlines/recovery and current limitations. The current API requires schema version 13. Workspace opt-in can automatically triage new capture; Support never triggers model work. Human confirmation supports explicit reviewer corrections; see TRIAGE_WORKFLOW.md.


### Opportunity priority

Priority (High, Medium, Low) is separate from opportunity lifecycle status. Editors/admins can request an AI assessment, inspect quoted linked feedback, workflow impact, evidence strength, dependencies and missing information, then explicitly accept or edit priority. Viewers can read. Effort remains unknown until a PM supplies an estimate. Saving priority does not plan, ship or otherwise change lifecycle status.

Migration `0009_priority.sql` stores the latest AI assessment separately from confirmed priority, PM rationale/effort/dependencies, author, timestamp and an optimistic revision. Writes use workspace RLS and server role checks. Assessment runs reuse the configured triage model, isolated Claude SDK worker, turn/budget/deadline controls and environment filtering; priority mode has no tools. Exact source quotations are independently validated. The model receives at most 20 linked requests with descriptions bounded to 3,000 characters; missing/truncated evidence is identified in context. Expired/interrupted runs can be retried. Earlier assessment versions are replaced on reassessment; confirmed priority is preserved.

The opportunity list shows confirmed priority, lifecycle status, linked-request count and priority rationale. Priority sorting applies to the loaded newest 30 opportunities, with an explicit notice when more exist. Full portfolio pagination is not included.

#### Goal-aware priority assessment (priority-v2)

Assessments independently rate **potential impact**, **confidence**, and **suggested priority**. Potential impact explains the workflow benefit if solved; confidence describes how well evidence supports that benefit. Priority weighs product goals, current stage, alternatives, effort and dependencies. Sparse evidence and zero votes do not mechanically force Low; no fixed replacement rating is prescribed.

The Product goals context panel shows server configuration, not workspace-entered goals. This focused internal MVP uses the agreed goals (turn feedback into decisions, reduce manual PM work, preserve evidence and human approval) and the current internal-dogfood stage. Server operators can override `PRIORITY_PRODUCT_GOALS` (up to 4,000 characters) and `PRIORITY_PRODUCT_STAGE` (up to 2,000 characters) in the API environment, then restart it. These defaults describe this product, not a general assertion about every tenant. Workspace-specific editable goals are not implemented.

Each assessment snapshots the exact configured goals/stage and considers up to 20 workspace opportunity summaries as bounded alternatives, without inferring their demand or outcomes. The panel distinguishes a saved context from changed current configuration. Legacy suggestions stay readable and require reassessment before AI acceptance; manual PM editing remains available. Reassessment never changes confirmed PM priority or lifecycle. New runs save the model-reported cost when supplied; old run costs are not reconstructed.


### Opt-in automatic triage (local MVP)
Automatic triage defaults off per workspace and does not backfill old requests. Editors/admins can enable it on Feedback capture. A new request and its queued run are saved atomically; optional submission keys deduplicate capture retries. The same bounded three-outcome Claude harness runs, while feedback remains New and creating/linking an opportunity still requires explicit PM approval.

PostgreSQL owns queued/running uniqueness and atomic claims. The API dispatcher resumes pending jobs after restart, with two triage tasks per process and two running triage jobs per workspace. Interrupted running jobs fail after their deadline and require explicit retry, avoiding silent duplicate provider charges. Disabling opt-in pauses queued work; membership is rechecked before execution. This is a local MVP dispatcher, not a production distributed queue service.

The server reserves $0.05 per automatic start against a workspace daily UTC allocation (default $0.25); failed/interrupted starts retain reservations and reported overruns count against later starts. Exhausted queues wait for the next UTC day or an explicit allocation increase. This is an automatic-run allocation, not a hard provider billing cap: the SDK's final model call can overshoot its budget. Explicit manual retries use the existing separate per-run budget.
