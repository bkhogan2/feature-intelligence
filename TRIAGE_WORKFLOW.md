# AI triage and human review

Inbox → **Analyze request** starts a durable server-side run. Admins/editors can start or retry; viewers can read saved results and continue using Support. A completed analysis is a suggestion, never a lifecycle change.

Three validated outcomes:
- `existing_opportunity`: a real observed opportunity in the same workspace, rationale, and exact feedback quotes.
- `new_opportunity`: proposed name/problem, rationale, and exact feedback quotes.
- `insufficient_context`: material ambiguity, one or two focused questions, rationale and evidence. Optional missing metrics alone should not block understanding.

The original request is always included. Read-only `search_opportunities`, `get_opportunity`, and `search_feedback` tools return bounded workspace context. The server rechecks the session, membership and editor role before every tool response and before completion. Output is validated independently of the model: discriminated schema, allowed fields/lengths, citations to observed feedback, exact description quotes including the original request, and existing opportunity IDs seen and rechecked in the workspace. These checks establish provenance, not the correctness of the model's interpretation; PM review remains necessary.

**Create opportunity and link** / **Confirm opportunity link** is an explicit authenticated human action, backed by one transaction. Repeated confirmation is idempotent. It never runs as an agent tool. Only the latest completed suggestion can be confirmed; existing links cannot be silently replaced. Approval atomically changes the request to `triaged`; analysis alone leaves it `new`. The inbox defaults to New, removes approved requests, and selects the next request. Triaged and All requests retain original evidence and saved analysis. Clarification questions remain saved suggestions; clarification/archive actions and reply collection are not implemented, and no placeholder controls are exposed.

## Runtime and limits

The existing `agent_worker.py` harness now dispatches a separate triage mode (`triage_worker.py`). Chat's demo instructions/tools are unchanged. The Claude Agent SDK runs in a fresh isolated subprocess with an empty home/config directory, no persisted sessions, no project settings/skills, no filesystem/shell/web tools, and only the Anthropic credential plus explicit model policy. Database/auth credentials remain in the parent server. Worker stderr and provider exception details are never returned to clients.

Triage defaults: `claude-haiku-5-5`, 6 turns, 1,800 output tokens, SDK run budget $0.05, parent timeout 120 seconds, at most 8 read-tool calls and 2 concurrent jobs per API process. The SDK budget is a spending control, not an exact bill guarantee; a model call already in progress may finish before a limit is recognized. Use one API process for this milestone. PostgreSQL claims prevent duplicate starts across processes and limit triage runs to two per workspace; automatic starts also reserve workspace daily allocation. This remains a local MVP dispatcher, not a production distributed queue service.

Durable `triage_runs` hold status, model, prompt version, timestamps/deadline, validated result, reported cost, failure message and confirmation link. Jobs continue after navigating away; clients poll the latest record. Duplicate starts while a request is running return that run rather than spawning another. Retrying a failed/completed analysis creates a new run; older records remain in the database. The current UI shows the latest run, not a history browser.

Graceful shutdown cancels local jobs and records failure when membership still permits it. After a crash or access revocation, the 130-second durable deadline prevents indefinite running: viewer reads report expired runs as failed; the next admin/editor read or retry durably marks expired runs failed and clears the running uniqueness slot. A late worker cannot overwrite an expired/terminal run. A bounded dispatcher resumes durable queued automatic work and expires overdue running work. Interrupted running jobs are never silently re-executed; retry is explicit. A hard-killed parent can leave a child finishing its bounded SDK work; there is no result adoption after restart.

## Server configuration

Install the already-declared optional dependency: `uv sync --extra agent --extra dev --extra billing`.

Set `ANTHROPIC_API_KEY` through the local server/service's private environment or a securely loaded local secret file. **Do not put the key in source, a Vite variable, prompts/logs, a command line argument or chat.** This app does not automatically load `.env` files. Set `TRIAGE_ENABLED=true` on the API service. `TRIAGE_MODEL` optionally selects a provider model accessible to that account. Chat's `AGENT_ENABLED` is independent and can stay false. The frontend config endpoint reports capability/policy only, never credentials.

The official [Haiku 5.5 migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide) confirms the fixed `claude-haiku-5-5` API identifier. Actual account/billing access requires a live authenticated call. Structured output uses the SDK's documented [`output_format` / `structured_output`](https://code.claude.com/docs/en/agent-sdk/structured-outputs) interface, not frontend execution.

Apply all migrations through `0013_automatic_priority.sql` before starting the updated server (schema version 13). Migration 11 adds an immutable human-confirmation snapshot to insert-only feedback links; previous approvals remain readable. Migration 10 adds opt-in automatic triage and capture idempotency; migration 9 adds independent PM priority. Migration 8 adds status and immutable decision history. Existing actual feedback-opportunity links backfill Triaged; opportunities default to Considering without inventing decisions or timestamps. Migration 7 provides the triage tables. It adds opportunities, feedback links and triage runs with composite workspace foreign keys and forced RLS; it does not rewrite feedback or support rows. This task migrates only the isolated `feature_intelligence_preview` database for local review.

## API and tests

- `GET /api/v1/triage/config`
- `GET` / `POST /api/v1/feedback/{feedback_id}/triage`
- `POST /api/v1/feedback/{feedback_id}/triage/{run_id}/confirm`
- `GET /api/v1/opportunities` and `GET /api/v1/opportunities/{id}`

`backend/tests/test_triage.py` uses real isolated PostgreSQL and mocked worker events, covering all outcomes, confirmation/retry/idempotence, stale recovery, evidence validation, RLS/tenant/role/auth boundaries, denied tools, tool budgets and bounded concurrency. These tests do not demonstrate real Claude access and create no paid model requests. The production UI does not contain fake analysis or seeded opportunities.

## Live validation note

On 2026-11-14 UTC, a real bounded Claude Haiku 5.5 analysis completed for the synthetic decision-summary request. It saved a `new_opportunity` suggestion with Markdown rationale and a validated verbatim source quote; reported cost was $0.00110193. No opportunity was confirmed or support changed. Two preceding failed records remain in history: the CLI rejected Pydantic's OpenAPI `discriminator` hint before inference. The exported SDK schema now omits only that hint, retaining standard `oneOf`/`const` constraints and the strict discriminated server validator. SDK startup was verified without inference before retrying. Known worker/model failure categories and available cost are now retained without exposing raw provider exceptions.

## Opportunity lifecycle

Opportunity statuses are Considering (default), Planned, In progress, Shipped and Not pursuing. Considering recognizes a problem without committing to build. Editor/admin PMs can move between any statuses, including reopening, with an optional decision note. Same-status notes are allowed. Viewers can read history but cannot write.

`POST /api/v1/opportunities/{id}/decisions` accepts status, expected_status and an optional note (up to 4,000 characters). Stale status returns 409. Status update and history append share one transaction. History records actor, time, previous/new status and note. Runtime RLS enforces workspace/editor boundaries and runtime grants prohibit history editing/deletion.

`GET /api/v1/feedback?status=new|triaged|all` filters requests (API default remains all for existing consumers). Optional feedback_id enables exact scoped evidence lookup.

`backend/tests/test_lifecycle.py` covers atomic approval/rollback, filtering, repeated confirmation, status/note validation, conflicts, workspace/role/RLS boundaries and migration of existing schema7 records without invented decisions. The inbox DOM test covers removal, next-request selection and rediscovery in Triaged.


## Reviewer corrections

For a completed grouping suggestion, the PM may accept unchanged, choose an existing workspace opportunity (searchable, bounded results), or edit the title/problem of a proposed new opportunity. A correction requires a reason. The human draft is separate from unchanged AI rationale and original feedback. Insufficient-context results still require clarification; this feature does not override them into grouping.

`POST /api/v1/feedback/{feedback_id}/triage/{run_id}/confirm` accepts optional JSON: `{"mode":"accept"}` (or the legacy empty body), `{"mode":"existing","opportunity_id":"UUID","reason":"..."}`, or `{"mode":"edit_new","name":"...","problem":"...","reason":"..."}`. The server rechecks role, latest run, and target workspace inside the confirmation transaction. It records the exact choice and target snapshot on the insert-only link, alongside actor/time and original run. Same-choice repeats are idempotent; a competing/different approval returns 409, with no silent relink. Failure rolls back opportunity/link/status together. Request details retain the confirmed original analysis even if a later analysis exists. Opportunity details explicitly distinguish a human correction from the unchanged AI rationale.

Five real PostgreSQL correction tests cover alternate targets, edited proposals, original evidence retention, role/tenant boundaries, stale/insufficient-context rejection, same-choice duplicate and conflicting-choice races. Browser acceptance on 2026-11-14 used synthetic test request `56f77bdb-a934-49c5-9c2e-f018866df706`: edited new title/problem and reason were saved, the original AI proposal stayed unchanged, and explicit confirmation moved New to Triaged. Its export topic is a labeled acceptance artifact, not a delivered/export commitment or customer demand.


## Opportunity sidebar filters

All opportunities is the default. Considering, Planned, In progress, Shipped and Not pursuing filter saved lifecycle status on the server before the newest-30 result bound. Priority/newest sorting is independent and retained in the URL across filter changes. No approximate sidebar counts are shown. Sorting applies to the displayed set; when more exist, the UI states the bound. A directly linked opportunity outside the initial set remains accessible when it matches the active status. An excluded selection falls back to the first matching item; filtered empty states say that no opportunities match, rather than implying the workspace is empty.

`GET /api/v1/opportunities?status=shipped` supports those statuses plus `all`; invalid values return 422. Existing `search` remains compatible with the reviewer target chooser. Status filtering does not edit decisions or priority.


## Automatic priority after approval

Settings → AI triage has independent workspace opt-ins for submission triage and priority assessment after PM approval. Both default off; enabling priority does not backfill past approvals. Creating/linking an opportunity (including a reviewer-corrected target) atomically increments its evidence revision and queues a suggestion when enabled. Multiple pending approvals coalesce into one queued assessment using combined linked evidence. An approval during a running assessment queues its successor; the old result cannot replace the newer queued suggestion. Changes to evidence also prevent acceptance of an older completed suggestion.

Migration 13 adds forced-RLS `priority_jobs`, retaining automatic allocation reservations and reported cost even after later assessments. Triage and priority share the existing daily UTC allocation: each automatic start reserves $0.05, failed/interrupted starts keep reservations, known overruns count against subsequent starts. This is not a hard provider billing cap. No allocation increase is automatic. Manual assessment/retry remains an explicit separately bounded model call; an already-queued automatic job cannot bypass allocation through the manual button.

The local dispatcher resumes queued priority jobs after restart, validates the approver's current membership and opt-in, and fails interrupted running work after its deadline for explicit retry. Each API process and each workspace allow at most two priority assessments concurrently (separate from triage's two). PostgreSQL locks/unique active-job indexes arbitrate manual/automatic starts across processes; this is still local MVP infrastructure, not a production distributed queue guarantee. The UI polls queued/running assessments and shows paused/allocation/failed reasons.

Automatic assessment only updates the AI suggestion. Confirmed PM priority, rationale, effort, dependencies and lifecycle are unchanged. PM Accept/Edit and lifecycle actions remain separate. Six real PostgreSQL tests cover approval hooks, corrected targets, idempotence, coalescing and concurrent starts, stale completion/acceptance, confirmed-field preservation, shared budget/expiry/recovery, combined evidence, revoked approvers and tenant/role boundaries.
