SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE feedback ADD COLUMN priority text CHECK(priority IN ('high','medium','low'));
ALTER TABLE feedback ADD COLUMN archived_from_status text CHECK(archived_from_status IN ('new','needs_clarification','triaged'));
UPDATE feedback f SET archived_from_status=CASE WHEN EXISTS(SELECT 1 FROM feedback_opportunity_links l WHERE l.workspace_id=f.workspace_id AND l.feedback_id=f.id) THEN 'triaged' ELSE 'new' END WHERE status='archived';
ALTER TABLE opportunities ADD COLUMN archived boolean NOT NULL DEFAULT false;
ALTER TABLE opportunities ADD COLUMN board_order integer CHECK(board_order>=0);
GRANT UPDATE(priority,archived_from_status) ON feedback TO app_runtime;
GRANT UPDATE(archived,board_order) ON opportunities TO app_runtime;
-- Triage may finish while archived: retain its lifecycle result for restoration.
CREATE FUNCTION preserve_feedback_archive() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status='archived' AND NEW.status<>'archived' AND NEW.archived_from_status IS NOT NULL THEN
  NEW.archived_from_status=NEW.status;
  NEW.status='archived';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER preserve_feedback_archive BEFORE UPDATE ON feedback FOR EACH ROW EXECUTE FUNCTION preserve_feedback_archive();
