SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE submitter_messages
    DROP CONSTRAINT submitter_messages_kind_check,
    ADD CONSTRAINT submitter_messages_kind_check CHECK (kind IN ('update', 'clarification', 'receipt'));
