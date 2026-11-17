SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE opportunities
  ADD COLUMN description_markdown text CHECK (char_length(description_markdown) BETWEEN 1 AND 20000),
  ADD COLUMN description_revision bigint NOT NULL DEFAULT 0;
GRANT UPDATE (description_markdown, description_revision) ON opportunities TO app_runtime;
