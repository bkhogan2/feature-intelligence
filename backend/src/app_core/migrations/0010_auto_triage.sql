SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE triage_runs DROP CONSTRAINT triage_runs_status_check;
ALTER TABLE triage_runs ADD CONSTRAINT triage_runs_status_check CHECK(status IN ('queued','running','complete','failed'));
ALTER TABLE triage_runs ADD COLUMN automatic boolean NOT NULL DEFAULT false,
 ADD COLUMN reserved_budget numeric NOT NULL DEFAULT 0 CHECK(reserved_budget>=0),
 ADD COLUMN budget_reserved_at timestamptz;
DROP INDEX triage_one_running;
CREATE UNIQUE INDEX triage_one_active ON triage_runs(workspace_id,feedback_id) WHERE status IN ('queued','running');
CREATE TABLE auto_triage_settings (
 workspace_id text PRIMARY KEY REFERENCES workspaces(id),
 enabled boolean NOT NULL DEFAULT false,
 daily_budget_usd numeric NOT NULL DEFAULT 0.25 CHECK(daily_budget_usd BETWEEN 0.05 AND 5),
 updated_by text NOT NULL REFERENCES users(id),
 updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON auto_triage_settings TO app_runtime;
ALTER TABLE auto_triage_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_triage_settings FORCE ROW LEVEL SECURITY;
CREATE POLICY auto_triage_read ON auto_triage_settings FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY auto_triage_insert ON auto_triage_settings FOR INSERT TO app_runtime WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND updated_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY auto_triage_update ON auto_triage_settings FOR UPDATE TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor')) WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND updated_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));

ALTER TABLE feedback ADD COLUMN submission_key uuid;
CREATE UNIQUE INDEX feedback_submission_key ON feedback(workspace_id,submitted_by,submission_key);
