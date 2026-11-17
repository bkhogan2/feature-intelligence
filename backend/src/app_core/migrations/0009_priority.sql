SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE opportunities
 ADD COLUMN priority text CHECK(priority IN ('high','medium','low')),
 ADD COLUMN priority_rationale text NOT NULL DEFAULT '',
 ADD COLUMN effort text NOT NULL DEFAULT '',
 ADD COLUMN dependencies text NOT NULL DEFAULT '',
 ADD COLUMN priority_revision integer NOT NULL DEFAULT 0,
 ADD COLUMN priority_updated_by text REFERENCES users(id),
 ADD COLUMN priority_updated_at timestamptz,
 ADD COLUMN priority_analysis jsonb;
GRANT UPDATE(priority,priority_rationale,effort,dependencies,priority_revision,priority_updated_by,priority_updated_at,priority_analysis) ON opportunities TO app_runtime;
