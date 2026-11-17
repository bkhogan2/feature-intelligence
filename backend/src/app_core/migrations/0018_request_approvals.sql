SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE request_approvals (
 feedback_id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 id uuid NOT NULL UNIQUE,
 requested_by text NOT NULL REFERENCES users(id),
 expected_status text NOT NULL,
 status text NOT NULL CHECK(status IN ('queued','running','complete','failed')),
 run_id uuid REFERENCES triage_runs(id),
 error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id)
);
CREATE INDEX request_approval_queue ON request_approvals(workspace_id,created_at,feedback_id) WHERE status IN ('queued','running');
GRANT SELECT,INSERT,UPDATE ON request_approvals TO app_runtime;
ALTER TABLE request_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY approval_read ON request_approvals FOR SELECT TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY approval_write ON request_approvals FOR ALL TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor')) WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
