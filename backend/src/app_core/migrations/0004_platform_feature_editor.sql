SET LOCAL search_path=app_core,pg_catalog;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_plan_editor') THEN
  CREATE ROLE app_plan_editor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
GRANT USAGE ON SCHEMA app_core TO app_plan_editor;
GRANT SELECT ON plans,plan_features,plan_feature_assignments TO app_plan_editor;
GRANT INSERT,DELETE ON plan_feature_assignments TO app_plan_editor;
GRANT INSERT ON plan_configuration_audit TO app_plan_editor;
GRANT USAGE ON SEQUENCE plan_configuration_audit_id_seq TO app_plan_editor;
