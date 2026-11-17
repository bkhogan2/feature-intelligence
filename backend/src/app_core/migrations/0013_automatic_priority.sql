SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE auto_triage_settings ADD COLUMN priority_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE opportunities ADD COLUMN evidence_revision bigint NOT NULL DEFAULT 0;
GRANT UPDATE(evidence_revision) ON opportunities TO app_runtime;
CREATE TABLE priority_jobs (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL REFERENCES workspaces(id),
 opportunity_id uuid NOT NULL,
 requested_by text NOT NULL REFERENCES users(id),
 status text NOT NULL CHECK(status IN ('queued','running','complete','failed')),
 automatic boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 deadline_at timestamptz,
 reserved_budget numeric NOT NULL DEFAULT 0 CHECK(reserved_budget>=0),
 budget_reserved_at timestamptz,
 cost_usd numeric CHECK(cost_usd>=0),
 analysis jsonb NOT NULL,
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id)
);
CREATE UNIQUE INDEX priority_one_queued ON priority_jobs(workspace_id,opportunity_id) WHERE status='queued';
CREATE UNIQUE INDEX priority_one_running ON priority_jobs(workspace_id,opportunity_id) WHERE status='running';
CREATE INDEX priority_pending ON priority_jobs(workspace_id,status,created_at);
GRANT SELECT,INSERT,UPDATE ON priority_jobs TO app_runtime;
ALTER TABLE priority_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE priority_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY priority_jobs_read ON priority_jobs FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY priority_jobs_insert ON priority_jobs FOR INSERT TO app_runtime WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND requested_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY priority_jobs_update ON priority_jobs FOR UPDATE TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor')) WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
