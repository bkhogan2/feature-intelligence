SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE feedback DROP CONSTRAINT feedback_status_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_status_check CHECK(status IN ('new','needs_clarification','triaged','rejected','archived'));
ALTER TABLE feedback DROP CONSTRAINT feedback_archived_from_status_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_archived_from_status_check CHECK(archived_from_status IN ('new','needs_clarification','triaged','rejected'));
