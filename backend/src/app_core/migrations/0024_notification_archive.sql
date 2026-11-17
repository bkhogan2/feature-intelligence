SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE update_notifications ADD COLUMN archived_at timestamptz;
GRANT UPDATE(archived_at) ON update_notifications TO app_runtime;
