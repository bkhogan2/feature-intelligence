SET LOCAL search_path=app_core,pg_catalog;

CREATE TABLE tasks (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 opportunity_id uuid NOT NULL,
 title text NOT NULL CHECK(char_length(btrim(title)) BETWEEN 1 AND 160),
 description text NOT NULL DEFAULT '' CHECK(char_length(description) <= 20000),
 status text NOT NULL DEFAULT 'backlog'
   CHECK(status IN ('backlog','todo','in_progress','blocked','done')),
 assignee_id text,
 created_by text NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 revision bigint NOT NULL DEFAULT 0,
 UNIQUE(id, workspace_id),
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id),
 FOREIGN KEY(workspace_id,assignee_id) REFERENCES memberships(workspace_id,user_id) ON DELETE SET NULL (assignee_id)
);
CREATE INDEX tasks_workspace_order ON tasks(workspace_id,created_at DESC,id);
CREATE INDEX tasks_opportunity ON tasks(workspace_id,opportunity_id,created_at DESC,id);
GRANT SELECT,INSERT ON tasks TO app_runtime;
GRANT UPDATE(title,description,status,assignee_id,revision) ON tasks TO app_runtime;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY tasks_read ON tasks FOR SELECT TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY tasks_insert ON tasks FOR INSERT TO app_runtime
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND created_by=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY tasks_update ON tasks FOR UPDATE TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'))
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));

CREATE TABLE task_comments (
 id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 task_id uuid NOT NULL,
 author_id text NOT NULL REFERENCES users(id),
 body text NOT NULL CHECK(char_length(btrim(body)) BETWEEN 1 AND 10000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(task_id,workspace_id) REFERENCES tasks(id,workspace_id)
);
CREATE INDEX task_comments_thread ON task_comments(workspace_id,task_id,created_at,id);
GRANT SELECT,INSERT ON task_comments TO app_runtime;
ALTER TABLE task_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_comments FORCE ROW LEVEL SECURITY;
CREATE POLICY task_comments_read ON task_comments FOR SELECT TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY task_comments_insert ON task_comments FOR INSERT TO app_runtime
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND author_id=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
