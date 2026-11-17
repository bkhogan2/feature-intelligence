-- Feedback is original evidence; interpretation and prioritization come later.
SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE feedback (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL REFERENCES workspaces(id),
 title text NOT NULL CHECK(char_length(btrim(title)) BETWEEN 1 AND 160),
 description text NOT NULL CHECK(char_length(btrim(description)) BETWEEN 1 AND 10000),
 submitted_by text NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX feedback_workspace_created ON feedback(workspace_id,created_at DESC,id DESC);
GRANT SELECT,INSERT ON feedback TO app_runtime;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY feedback_read ON feedback FOR SELECT TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
);
CREATE POLICY feedback_insert ON feedback FOR INSERT TO app_runtime WITH CHECK (
 workspace_id=current_setting('app.workspace_id',true)
 AND submitted_by=current_setting('app.subject',true)
 AND active_workspace_role(workspace_id) IN ('admin','editor')
);
