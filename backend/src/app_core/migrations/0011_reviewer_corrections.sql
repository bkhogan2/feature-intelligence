SET LOCAL search_path=app_core,pg_catalog;
-- Link rows are insert-only for runtime; immutable decision snapshot complements original run.
ALTER TABLE feedback_opportunity_links ADD COLUMN confirmation jsonb;
ALTER TABLE feedback_opportunity_links ADD CONSTRAINT confirmation_object CHECK(confirmation IS NULL OR jsonb_typeof(confirmation)='object');
