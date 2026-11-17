SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE feedback ADD COLUMN status text NOT NULL DEFAULT 'new'
 CHECK(status IN ('new','needs_clarification','triaged','archived'));
ALTER TABLE opportunities ADD COLUMN status text NOT NULL DEFAULT 'considering'
 CHECK(status IN ('considering','planned','in_progress','shipped','not_pursuing'));
-- Existing links record actual human approval. Do not invent decisions or dates.
UPDATE feedback f SET status='triaged' WHERE EXISTS (
 SELECT 1 FROM feedback_opportunity_links l WHERE l.feedback_id=f.id AND l.workspace_id=f.workspace_id
);
CREATE INDEX feedback_workspace_status_created ON feedback(workspace_id,status,created_at DESC,id DESC);
GRANT UPDATE(status) ON feedback,opportunities TO app_runtime;
CREATE POLICY feedback_update ON feedback FOR UPDATE TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'))
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY opportunities_update ON opportunities FOR UPDATE TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'))
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE TABLE opportunity_decisions (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 opportunity_id uuid NOT NULL,
 actor_id text NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 previous_status text NOT NULL CHECK(previous_status IN ('considering','planned','in_progress','shipped','not_pursuing')),
 new_status text NOT NULL CHECK(new_status IN ('considering','planned','in_progress','shipped','not_pursuing')),
 note text NOT NULL CHECK(char_length(btrim(note)) BETWEEN 1 AND 4000),
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id)
);
GRANT SELECT,INSERT ON opportunity_decisions TO app_runtime;
ALTER TABLE opportunity_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY opportunity_decisions_read ON opportunity_decisions FOR SELECT TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY opportunity_decisions_insert ON opportunity_decisions FOR INSERT TO app_runtime
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND actor_id=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
