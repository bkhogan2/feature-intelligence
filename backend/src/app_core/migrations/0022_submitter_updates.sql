SET LOCAL search_path=app_core,pg_catalog;

CREATE TABLE submitter_messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 publication_id uuid NOT NULL,
 workspace_id text NOT NULL,
 feedback_id uuid NOT NULL,
 opportunity_id uuid,
 author_id text NOT NULL REFERENCES users(id),
 kind text NOT NULL CHECK(kind IN ('update','clarification')),
 body text NOT NULL CHECK(char_length(btrim(body)) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(publication_id,feedback_id),
 UNIQUE(id,workspace_id),
 FOREIGN KEY(feedback_id,workspace_id) REFERENCES feedback(id,workspace_id),
 FOREIGN KEY(opportunity_id,workspace_id) REFERENCES opportunities(id,workspace_id),
 CHECK(kind='update' OR opportunity_id IS NULL)
);
CREATE INDEX submitter_messages_feedback ON submitter_messages(workspace_id,feedback_id,created_at DESC,id DESC);
CREATE INDEX submitter_messages_feed ON submitter_messages(workspace_id,created_at DESC,id DESC);
GRANT SELECT,INSERT ON submitter_messages TO app_runtime;
ALTER TABLE submitter_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE submitter_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY submitter_messages_read ON submitter_messages FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
 AND (active_workspace_role(workspace_id) IN ('admin','editor') OR EXISTS(
   SELECT 1 FROM feedback f WHERE f.id=feedback_id AND f.workspace_id=submitter_messages.workspace_id
   AND f.submitted_by=current_setting('app.subject',true)
 ))
);
CREATE POLICY submitter_messages_insert ON submitter_messages FOR INSERT TO app_runtime WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true)
 AND active_workspace_role(workspace_id) IN ('admin','editor')
 AND author_id=current_setting('app.subject',true)
);

CREATE TABLE clarification_replies (
 message_id uuid PRIMARY KEY,
 workspace_id text NOT NULL,
 author_id text NOT NULL REFERENCES users(id),
 body text NOT NULL CHECK(char_length(btrim(body)) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(message_id,workspace_id) REFERENCES submitter_messages(id,workspace_id)
);
GRANT SELECT,INSERT ON clarification_replies TO app_runtime;
ALTER TABLE clarification_replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE clarification_replies FORCE ROW LEVEL SECURITY;
CREATE POLICY clarification_replies_read ON clarification_replies FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND EXISTS(
  SELECT 1 FROM submitter_messages m WHERE m.id=message_id AND m.workspace_id=clarification_replies.workspace_id
 )
);
CREATE POLICY clarification_replies_insert ON clarification_replies FOR INSERT TO app_runtime WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true)
 AND author_id=current_setting('app.subject',true)
 AND EXISTS(
  SELECT 1 FROM submitter_messages m JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
  WHERE m.id=message_id AND m.workspace_id=clarification_replies.workspace_id
  AND m.kind='clarification' AND f.submitted_by=clarification_replies.author_id
 )
);
-- The submitter can return their own request to New after answering the latest question.
-- Other feedback columns remain protected by restrictive policy below.
CREATE FUNCTION has_latest_clarification_reply(workspace text, request_id uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,app_core AS $$
 SELECT EXISTS (
  SELECT 1 FROM clarification_replies WHERE message_id=(
   SELECT id FROM submitter_messages WHERE workspace_id=workspace AND feedback_id=request_id
   AND kind='clarification' ORDER BY created_at DESC,id DESC LIMIT 1
  ) AND author_id=current_setting('app.subject',true)
 )
$$;
CREATE POLICY feedback_submitter_return ON feedback FOR UPDATE TO app_runtime
 USING(workspace_id=current_setting('app.workspace_id',true)
  AND active_workspace_role(workspace_id)='viewer' AND status='needs_clarification'
  AND submitted_by=current_setting('app.subject',true) AND has_latest_clarification_reply(workspace_id,id))
 WITH CHECK(workspace_id=current_setting('app.workspace_id',true)
  AND active_workspace_role(workspace_id)='viewer' AND status='new'
  AND submitted_by=current_setting('app.subject',true) AND has_latest_clarification_reply(workspace_id,id));

-- This invoker trigger keeps the viewer's exceptional update limited to status, even if
-- additional columns are writable by app_runtime for reviewers.
CREATE FUNCTION guard_submitter_feedback_change() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,app_core AS $$
BEGIN
 IF active_workspace_role(OLD.workspace_id)='viewer' AND
   (to_jsonb(NEW)-'status' IS DISTINCT FROM to_jsonb(OLD)-'status') THEN
  RAISE EXCEPTION 'Only request status can change on clarification reply' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END
$$;
CREATE TRIGGER feedback_submitter_update_guard BEFORE UPDATE ON feedback
 FOR EACH ROW EXECUTE FUNCTION guard_submitter_feedback_change();

ALTER TABLE opportunities
 ADD COLUMN outcome_status text NOT NULL DEFAULT 'not_measured'
   CHECK(outcome_status IN ('not_measured','improved','partly_improved','did_not_improve')),
 ADD COLUMN outcome_evidence text NOT NULL DEFAULT '' CHECK(char_length(outcome_evidence)<=2000),
 ADD COLUMN outcome_revision integer NOT NULL DEFAULT 0;
GRANT UPDATE(outcome_status,outcome_evidence,outcome_revision) ON opportunities TO app_runtime;
