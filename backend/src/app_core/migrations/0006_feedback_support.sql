-- Support expresses member interest; it does not grant feedback editing rights.
SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE feedback ADD CONSTRAINT feedback_id_workspace_unique UNIQUE(id,workspace_id);
CREATE TABLE feedback_support (
 feedback_id uuid NOT NULL,
 workspace_id text NOT NULL,
 user_id text NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(feedback_id,user_id),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id) ON DELETE CASCADE
);
CREATE INDEX feedback_support_workspace ON feedback_support(workspace_id,feedback_id);
GRANT SELECT,INSERT,DELETE ON feedback_support TO app_runtime;
ALTER TABLE feedback_support ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_support FORCE ROW LEVEL SECURITY;
CREATE POLICY feedback_support_read ON feedback_support FOR SELECT TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
);
CREATE POLICY feedback_support_insert ON feedback_support FOR INSERT TO app_runtime WITH CHECK (
 workspace_id=current_setting('app.workspace_id',true)
 AND user_id=current_setting('app.subject',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
 AND EXISTS(SELECT 1 FROM feedback f WHERE f.id=feedback_id AND f.workspace_id=feedback_support.workspace_id)
);
CREATE POLICY feedback_support_delete ON feedback_support FOR DELETE TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true)
 AND user_id=current_setting('app.subject',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
);
