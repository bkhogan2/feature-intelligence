SET LOCAL search_path=app_core,pg_catalog;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_plan_operator') THEN
  CREATE ROLE app_plan_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE plan_features (key text PRIMARY KEY, description text NOT NULL);
INSERT INTO plan_features VALUES ('records.write', 'Create and delete example records');
CREATE TABLE plans (key text PRIMARY KEY, name text NOT NULL, active boolean NOT NULL DEFAULT true);
INSERT INTO plans VALUES ('pro', 'Pro', true), ('enterprise', 'Enterprise', true);
CREATE TABLE plan_feature_assignments (
 plan_key text NOT NULL REFERENCES plans(key),
 feature_key text NOT NULL REFERENCES plan_features(key),
 PRIMARY KEY(plan_key,feature_key)
);
INSERT INTO plan_feature_assignments VALUES ('pro','records.write'), ('enterprise','records.write');
CREATE TABLE workspace_plans (
 workspace_id text PRIMARY KEY REFERENCES workspaces(id),
 plan_key text NOT NULL REFERENCES plans(key)
);
CREATE TABLE plan_configuration_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 database_actor text NOT NULL DEFAULT session_user,
 action text NOT NULL,
 details jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT ON plan_features,plans,plan_feature_assignments,workspace_plans TO app_runtime;
ALTER TABLE workspace_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_plans_read ON workspace_plans FOR SELECT TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true)
 AND active_workspace_role(workspace_id) IS NOT NULL
);
-- No runtime writes: configuration uses a separate trusted operator connection.
GRANT USAGE ON SCHEMA app_core TO app_plan_operator;
GRANT SELECT ON workspaces,plan_features TO app_plan_operator;
GRANT SELECT,INSERT,UPDATE,DELETE ON plans,plan_feature_assignments,workspace_plans TO app_plan_operator;
GRANT INSERT ON plan_configuration_audit TO app_plan_operator;
GRANT USAGE ON SEQUENCE plan_configuration_audit_id_seq TO app_plan_operator;
CREATE POLICY workspace_plans_operator ON workspace_plans TO app_plan_operator USING (true) WITH CHECK (true);
