SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE update_notifications (
 message_id uuid NOT NULL,
 workspace_id text NOT NULL,
 user_id text NOT NULL REFERENCES users(id),
 read_at timestamptz,
 PRIMARY KEY(message_id,user_id),
 FOREIGN KEY(message_id,workspace_id) REFERENCES submitter_messages(id,workspace_id)
);
INSERT INTO update_notifications(message_id,workspace_id,user_id)
 SELECT m.id,m.workspace_id,f.submitted_by FROM submitter_messages m
 JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
 UNION
 SELECT m.id,m.workspace_id,s.user_id FROM submitter_messages m
 JOIN feedback_support s ON s.feedback_id=m.feedback_id AND s.workspace_id=m.workspace_id
 WHERE m.kind='update' AND s.created_at<=m.created_at;
GRANT SELECT,INSERT ON update_notifications TO app_runtime;
GRANT UPDATE(read_at) ON update_notifications TO app_runtime;
ALTER TABLE update_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE update_notifications FORCE ROW LEVEL SECURITY;
CREATE POLICY notifications_read ON update_notifications FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND user_id=current_setting('app.subject',true)
 AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY notifications_insert ON update_notifications FOR INSERT TO app_runtime WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY notifications_update ON update_notifications FOR UPDATE TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND user_id=current_setting('app.subject',true)
 AND active_workspace_role(workspace_id) IS NOT NULL)
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true) AND user_id=current_setting('app.subject',true));
CREATE POLICY messages_notified_read ON submitter_messages FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND EXISTS(
 SELECT 1 FROM update_notifications n WHERE n.message_id=id AND n.workspace_id=submitter_messages.workspace_id));
