# Starter hardening checkpoint

## Baseline

Selected `platform-feature-switches` at `99b8b0b64087f68faa55cae6eb965bb22cd8f7ed`.
It includes main `3b41d41`, optional billing, settings/assistant reload fixes,
platform administration, and audited plan-feature switches. The unrelated
`sandbox/shadcn-example-mail-app` branch and its uncommitted mail-agent work
were not included. No original worktree was modified.

## Hardening changes

- Agent tools recheck the original request's current identity and workspace membership
  after model latency, so revoked sessions cannot continue invoking application tools.
- A terminal worker event ends processing immediately; subsequent worker tools are ignored.
- The assistant explicitly states that requests are independent. Conversation history
  remains a domain-app extension rather than an implied capability.
- Production Python dependencies install from `backend/uv.lock` using a frozen sync.
  Select agent/Firebase dependencies with `BACKEND_EXTRAS=google,agent`.
- `STARTER_DB_PORT` allows an isolated Compose database alongside an existing starter.

## Copying into a new application

1. Use the committed hardening branch, not a working folder containing local secrets.
   Export tracked files with `git archive HEAD | tar -x -C /path/to/empty/destination`.
   This excludes ignored credentials, dependencies, build output and Git history.
2. Initialize the new repository. For the Metacto assessment, run its exact first
   setup prompt before implementation and log subsequent prompts in `prompts.txt`.
   Document this starter as pre-existing infrastructure and record its source commit.
3. Change `frontend/src/lib/app-config.ts` (including unique app ID), terms/privacy
   documents and policy versions. Replace the Records/Activity examples with domain
   models, routes and explicit server-side tools.
4. Use a separate PostgreSQL database and migration/runtime identities. Install with
   `bun install --frozen-lockfile` and `uv sync --frozen --all-extras` for verification.
   Run `python -m app_core.migrate` with `DATABASE_ADMIN_URL` before web startup.
   Provision users via `python -m app_core.cli provision`; there is no default
   production account or automatic public workspace signup.
5. Keep `BILLING_ENABLED=false`, `STRIPE_ENABLED=false` and omit platform/billing
   database credentials unless the application needs those capabilities.
6. For local auth, use same-origin frontend/API hosting and secure cookies in production.
   For Firebase, configure the new project, verified identities and explicit workspace
   memberships. Frontend Firebase settings are build-time configuration.
7. Build with `docker build --build-arg BACKEND_EXTRAS=google,agent -t your-app .`.
   Inject runtime secrets through the host. Never pass model keys in VITE variables.
   Keep migration-owner credentials out of the serving container.
8. Run backend tests against a disposable PostgreSQL instance with
   `TEST_DATABASE_ADMIN_URL` and `TEST_DATABASE_URL`, then `ruff check src tests`.
   Run `bun run test` and `bun run build` in frontend. Confirm provisioning, login,
   workspace isolation, and a model-enabled smoke call in the target environment.

## Deliberate limitations

- The agent is a read-only synthetic-record demonstration, not feature intelligence.
- Requests are independent; visible transcript is not replayed as model history.
- Active runs and browser action acknowledgments are process-local. Use a single
  backend process/instance for the initial agent demo. Scaling requires shared run
  coordination or request affinity; per-process concurrency is not a global budget.
- Model calls already in flight cannot be recalled after session revocation. Access is
  checked again before each subsequent tool, and the browser aborts on context changes.
- Tests simulate the model adapter; they do not establish live provider/model availability.
- Billing lifecycle tests use a fake gateway; live Stripe and production Firebase setup
  remain separate deployment checks. No cloud deployment is implied by this checkpoint.
- The assistant bundle is large; the frontend build warns about chunk size. It builds
  successfully and the assistant is lazy-loaded, but performance tuning remains useful.

## Local Docker bind-mount fallback

If Docker cannot execute `deploy/local/init-db.sh` from a protected/synced macOS
folder, use a local unsynced checkout. For an isolated disposable database whose
initialization stopped at that script, restart it and pipe the script to
`docker exec -i CONTAINER sh`. Only do this before runtime roles exist.

## Verification completed

- Clean locked dependency installation in an unsynced developer checkout.
- Backend: 60 tests passed against isolated PostgreSQL 17; Ruff passed.
- Frontend: 21 tests passed; TypeScript/Vite production build passed in Docker.
- Container built successfully with `BACKEND_EXTRAS=google,agent`.
- Packaged migration command applied all four migrations on the fresh database.
- Packaged application served `/health` and the static UI, provisioned a synthetic
  administrator, authenticated it, and returned scoped assistant configuration
  with billing and Stripe disabled. Agent SDK import succeeded inside the image.
- Regression cases cover session revocation during model latency, ignoring tools
  after terminal output, unexpected worker exit, timeout, and concurrency-slot reuse.
- Live Anthropic inference, production Firebase/Stripe, cloud routing, and visual
  browser QA were not performed in this pass.

The canonical hardened checkout is
`/Users/brianhogan/Developer/assessments/data_annotation/starter-hardening`,
branch `harden/assessment-baseline`. The earlier Documents-folder clone is superseded.
