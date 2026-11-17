# Google Cloud deployment configuration

Target: the existing container on Cloud Run, with PostgreSQL on Cloud SQL. This is an operator runbook; it creates no resources until you run the commands. Hosting and identity remain independent (`AUTH_PROVIDER=local`, `google`, or a custom verifier).

## Database and identities

Use a Cloud SQL PostgreSQL instance and a dedicated app database. Create a schema-owner database user for migrations, and a separate runtime database user. The runtime user must not own the schema, be a superuser, or have BYPASSRLS. The migration creates `app_runtime` as a restricted NOLOGIN role if it does not exist; have a DBA create it first when your migration account lacks CREATEROLE. Grant `app_runtime` to the runtime database user after migrating. The API checks its effective role before serving requests.

Store the two database connection strings in separate Secret Manager secrets. Only the migration job receives the owner secret. Only the web service receives the runtime secret. Give their service accounts Secret Accessor on their respective secrets and Cloud SQL Client for the instance; grant no database-admin role to the web service. Configure the Cloud Run Cloud SQL connection on both services/jobs.

Cloud Run's integrated Cloud SQL connection exposes a Unix socket under `/cloudsql/PROJECT:REGION:INSTANCE`. Psycopg/libpq supports it through a connection URI such as:

```
postgresql://RUNTIME_USER:URL_ENCODED_PASSWORD@/APP_DATABASE?host=/cloudsql/PROJECT:REGION:INSTANCE
```

Put the actual URI in the runtime secret, never in a checked-in environment file. The owner secret uses the same socket and a schema-owner database user. Native libpq keyword connection strings are also accepted, avoiding URI escaping when generated through your secret-management tooling. The Cloud SQL connection encrypts the network transport; a direct TCP connection to another provider should use its required TLS configuration, normally `sslmode=verify-full` and the provider's CA.

Reference: [Cloud SQL connections from Cloud Run](https://docs.cloud.google.com/sql/docs/postgres/connect-run).

## Build, migrate, then deploy

Build the root Dockerfile into your Artifact Registry using Cloud Build, or explicitly target `linux/amd64` when building on Apple Silicon (`docker buildx build --platform linux/amd64 ...`). Cloud Run requires a Linux x86_64 image; the locally tested native-architecture image is a development artifact, not an already-published Cloud Run image. See the [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract). Build-time Firebase web variables are optional and public; server credentials stay in runtime secrets. The default image uses local identity and listens on `$PORT` (8080 by default).

Create a migration job with the same image. Set its command to `python` and arguments to `-m,app_core.migrate`. Attach the Cloud SQL instance and give it only `DATABASE_ADMIN_URL` from the owner secret. Execute the job and require a successful completion before deploying the service. Migrations are transaction-backed, advisory-locked, checksum-checked, and are never run by the web server. Grant the restricted runtime role to your runtime database login with a DBA connection:

```sql
GRANT app_runtime TO your_runtime_database_user;
```

Configure the web service with:

- The Cloud SQL instance connection and its runtime service account.
- `DATABASE_URL` from the runtime secret.
- `APP_ENV=production`, `COOKIE_SECURE=true`, and `DB_POOL_MAX_SIZE=4` (adjust for the instance's connection budget).
- `APP_ALLOWED_ORIGINS=https://YOUR-APP-DOMAIN`.
- Real application `TERMS_VERSION` and `PRIVACY_VERSION`.
- `AUTH_PROVIDER=local` initially, or `google` with `GOOGLE_PROJECT_ID` and the matching frontend build settings.

The image serves compiled React and `/api` from one origin, so local cookie auth does not depend on cross-site cookies. Set a deliberate Cloud Run maximum instance count: each instance can open up to `DB_POOL_MAX_SIZE` connections. The database, not the container filesystem, holds users, memberships, sessions, preferences and application data. Configure backups and recovery on the managed database.

Provision initial workspaces/accounts through an operator environment connected to the same database (Cloud SQL Auth Proxy works for a local operator), using `python -m app_core.cli provision`. Do not run the demo seeder against a deployed database. Cloud Run runtime IAM invocation settings are separate from application login; choose them to fit your intended audience.

## Interview demo deployment

The authorized interview deployment uses the dedicated project
`feature-intelligence-demo-1115` in `us-central1`, linked to My Billing Account 1. The checked-in Cloud Build configuration
builds the frontend and backend together with the AI SDK included; `.gcloudignore`
excludes local secrets and databases from the source upload. No API keys belong in
build arguments or the image.

For the initial demo, use local email/password authentication and provision unique
interviewer accounts with `cli provision`. Public Cloud Run invocation allows the
login screen to load; application sessions and workspace membership still protect
the API. Share credentials separately from the URL. Local password reset is
operator-assisted; Firebase is an alternative if self-service recovery is needed.

Set `TRIAGE_ENABLED=true` and `AGENT_ENABLED=true`, and inject `ANTHROPIC_API_KEY`
from Secret Manager into the web service only. Start with a single Cloud Run
instance (minimum and maximum both 1), instance-based CPU allocation
(`--no-cpu-throttling`), 1 CPU and 2 GiB memory. The current AI dispatcher runs
background work inside the API process, so request-only CPU allocation and scaling
to zero are unsuitable for reliable queued work. This is a demo configuration,
not a distributed job queue. Instance-based billing and Cloud SQL incur ongoing
costs; configure a budget alert and remove demo resources after review.

Before sharing: require successful migrations, verify unauthenticated API denial,
sign in with an interviewer account, submit and support a request, approve it
through live AI linking, review priority, publish a comment and verify its
notification, then restart the service and confirm persistence. Do not copy local
sessions or known demo credentials into production.

See [Cloud Run billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings)
for CPU allocation and background work behavior.

## Other providers

For another PostgreSQL provider, change the database secrets, network/TLS settings, and hosting configuration. Keep the schema, migration command, Python driver, auth services and frontend. The runtime connection string must still select a login granted `app_runtime`; never use the migration owner as a shortcut.

A separate Firebase Authentication development project exists for this starter; see `../firebase/README.md`. The interview deployment uses local application authentication, independently of that Firebase project. See `DEPLOYMENT.md` for the deployed resources and verification results.
