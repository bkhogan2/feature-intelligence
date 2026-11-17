SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE opportunity_decisions DROP CONSTRAINT opportunity_decisions_note_check;
ALTER TABLE opportunity_decisions ADD CONSTRAINT opportunity_decisions_note_check CHECK(char_length(note) <= 4000);
