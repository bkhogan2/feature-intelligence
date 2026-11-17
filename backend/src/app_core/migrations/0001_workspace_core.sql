-- Adapted from GI Triage's restricted runtime role and transaction-scoped RLS pattern.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_runtime') THEN
  CREATE ROLE app_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
CREATE SCHEMA app_core;
REVOKE ALL ON SCHEMA app_core FROM PUBLIC;
GRANT USAGE ON SCHEMA app_core TO app_runtime;
SET LOCAL search_path=app_core,pg_catalog;
CREATE TABLE schema_migrations(version integer PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE users(id text PRIMARY KEY, email text NOT NULL UNIQUE, password_hash text, email_verified integer NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)));
CREATE TABLE workspaces(id text PRIMARY KEY, slug text NOT NULL UNIQUE, name text NOT NULL, theme_color text NOT NULL DEFAULT '#2563eb', status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','disabled')));
CREATE TABLE memberships(id text PRIMARY KEY, workspace_id text NOT NULL REFERENCES workspaces(id), user_id text NOT NULL REFERENCES users(id), role text NOT NULL CHECK(role IN ('admin','editor','viewer')), status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')), created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, UNIQUE(workspace_id,user_id));
CREATE TABLE invitations(id text PRIMARY KEY, workspace_id text NOT NULL REFERENCES workspaces(id), email text NOT NULL, role text NOT NULL CHECK(role IN ('admin','editor','viewer')), token_digest bytea NOT NULL UNIQUE, expires_at timestamptz NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','revoked')), created_at timestamptz NOT NULL, accepted_at timestamptz, revoked_at timestamptz, accepted_by text REFERENCES users(id));

CREATE TABLE legal_acceptances(invitation_id text NOT NULL PRIMARY KEY REFERENCES invitations(id), user_id text NOT NULL REFERENCES users(id), terms_version text NOT NULL, privacy_version text NOT NULL, accepted_at timestamptz NOT NULL);
CREATE TABLE sessions(digest text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id), expires_at double precision NOT NULL);
CREATE TABLE preferences(user_id text PRIMARY KEY REFERENCES users(id), payload jsonb NOT NULL);
CREATE TABLE records(id text PRIMARY KEY, workspace_id text NOT NULL REFERENCES workspaces(id), title text NOT NULL CHECK(char_length(btrim(title)) BETWEEN 1 AND 160), payload jsonb NOT NULL, created_at timestamptz NOT NULL);
CREATE TABLE audit(id text PRIMARY KEY, workspace_id text NOT NULL REFERENCES workspaces(id), actor_id text NOT NULL, action text NOT NULL, created_at timestamptz NOT NULL);
CREATE TABLE login_attempts(bucket text PRIMARY KEY, started double precision NOT NULL, count integer NOT NULL);
CREATE INDEX records_scope ON records(workspace_id);
CREATE INDEX audit_scope ON audit(workspace_id,created_at);
CREATE INDEX memberships_by_subject ON memberships(user_id,workspace_id);
CREATE INDEX sessions_expiry ON sessions(expires_at);
GRANT SELECT ON schema_migrations TO app_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON users,workspaces,memberships,invitations,legal_acceptances,sessions,preferences,login_attempts TO app_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON records TO app_runtime;
GRANT SELECT,INSERT ON audit TO app_runtime;

-- Default-deny without verified identity and workspace context.
CREATE FUNCTION active_workspace_role(requested_workspace text) RETURNS text
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path=pg_catalog,app_core
AS $$ SELECT m.role FROM app_core.memberships m JOIN app_core.workspaces w ON w.id=m.workspace_id
 WHERE m.workspace_id=requested_workspace AND m.user_id=current_setting('app.subject',true)
 AND m.status='active' AND w.status='active' $$;
REVOKE ALL ON FUNCTION active_workspace_role(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION active_workspace_role(text) TO app_runtime;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE records FORCE ROW LEVEL SECURITY;
ALTER TABLE audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit FORCE ROW LEVEL SECURITY;
CREATE POLICY records_read ON records FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY records_insert ON records FOR INSERT TO app_runtime WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY records_update ON records FOR UPDATE TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor')) WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY records_delete ON records FOR DELETE TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
CREATE POLICY audit_read ON audit FOR SELECT TO app_runtime USING(
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY audit_insert ON audit FOR INSERT TO app_runtime WITH CHECK(
 workspace_id=current_setting('app.workspace_id',true) AND actor_id=current_setting('app.subject',true) AND active_workspace_role(workspace_id) IS NOT NULL);
