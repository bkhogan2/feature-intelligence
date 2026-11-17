SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE opportunity_comments (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 opportunity_id uuid NOT NULL,
 author_id text NOT NULL REFERENCES users(id),
 body text NOT NULL CHECK(char_length(btrim(body)) BETWEEN 1 AND 10000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id)
);
CREATE INDEX opportunity_comments_thread ON opportunity_comments(workspace_id,opportunity_id,created_at,id);
GRANT SELECT,INSERT ON opportunity_comments TO app_runtime;
ALTER TABLE opportunity_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_comments FORCE ROW LEVEL SECURITY;
CREATE POLICY opportunity_comments_read ON opportunity_comments FOR SELECT TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY opportunity_comments_insert ON opportunity_comments FOR INSERT TO app_runtime
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND author_id=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
