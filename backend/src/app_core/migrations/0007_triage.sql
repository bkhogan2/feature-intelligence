SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE opportunities (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL REFERENCES workspaces(id),
 name text NOT NULL CHECK(char_length(btrim(name)) BETWEEN 1 AND 160),
 problem text NOT NULL CHECK(char_length(btrim(problem)) BETWEEN 1 AND 4000),
 created_by text NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,workspace_id)
);
CREATE TABLE triage_runs (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL REFERENCES workspaces(id),
 feedback_id uuid NOT NULL,
 requested_by text NOT NULL REFERENCES users(id),
 status text NOT NULL CHECK(status IN ('running','complete','failed')),
 model text NOT NULL,
 prompt_version text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 deadline_at timestamptz NOT NULL,
 completed_at timestamptz,
 result jsonb,
 error text,
 cost_usd numeric,
 confirmed_opportunity_id uuid,
 UNIQUE(id,workspace_id),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id),
 FOREIGN KEY(confirmed_opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id),
 CHECK((status='complete' AND result IS NOT NULL AND completed_at IS NOT NULL) OR (status<>'complete' AND result IS NULL))
);
CREATE UNIQUE INDEX triage_one_running ON triage_runs(workspace_id,feedback_id) WHERE status='running';
CREATE INDEX triage_feedback_history ON triage_runs(workspace_id,feedback_id,created_at DESC);
CREATE TABLE feedback_opportunity_links (
 feedback_id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 opportunity_id uuid NOT NULL,
 confirmed_run_id uuid NOT NULL,
 linked_by text NOT NULL REFERENCES users(id),
 linked_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id),
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id),
 FOREIGN KEY(confirmed_run_id,workspace_id) REFERENCES triage_runs(id,workspace_id)
);
GRANT SELECT,INSERT ON opportunities,feedback_opportunity_links TO app_runtime;
GRANT SELECT,INSERT,UPDATE ON triage_runs TO app_runtime;
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities FORCE ROW LEVEL SECURITY;
ALTER TABLE feedback_opportunity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_opportunity_links FORCE ROW LEVEL SECURITY;
ALTER TABLE triage_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY opportunities_read ON opportunities FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY opportunities_insert ON opportunities FOR INSERT TO app_runtime WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND created_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY feedback_links_read ON feedback_opportunity_links FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY feedback_links_insert ON feedback_opportunity_links FOR INSERT TO app_runtime WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND linked_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY triage_read ON triage_runs FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY triage_insert ON triage_runs FOR INSERT TO app_runtime WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND requested_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY triage_update ON triage_runs FOR UPDATE TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor')) WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
