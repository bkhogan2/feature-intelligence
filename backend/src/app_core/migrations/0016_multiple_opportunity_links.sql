SET LOCAL search_path=app_core,pg_catalog;
ALTER TABLE feedback_opportunity_links DROP CONSTRAINT feedback_opportunity_links_pkey;
ALTER TABLE feedback_opportunity_links ADD PRIMARY KEY(feedback_id,opportunity_id);
ALTER TABLE feedback_opportunity_links ALTER COLUMN confirmed_run_id DROP NOT NULL;
GRANT DELETE ON feedback_opportunity_links TO app_runtime;
CREATE POLICY feedback_links_delete ON feedback_opportunity_links FOR DELETE TO app_runtime USING(workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IN ('admin','editor'));
