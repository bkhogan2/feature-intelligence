SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE feedback_comments (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 feedback_id uuid NOT NULL,
 author_id text NOT NULL REFERENCES users(id),
 body text NOT NULL CHECK(char_length(btrim(body)) BETWEEN 1 AND 10000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id)
);
CREATE INDEX feedback_comments_thread ON feedback_comments(workspace_id,feedback_id,created_at,id);
GRANT SELECT,INSERT ON feedback_comments TO app_runtime;
ALTER TABLE feedback_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_comments FORCE ROW LEVEL SECURITY;
CREATE POLICY feedback_comments_read ON feedback_comments FOR SELECT TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY feedback_comments_insert ON feedback_comments FOR INSERT TO app_runtime
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND author_id=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
