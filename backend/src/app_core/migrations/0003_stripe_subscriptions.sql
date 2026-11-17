SET LOCAL search_path=app_core,pg_catalog;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_billing_service') THEN
  CREATE ROLE app_billing_service NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE billing_prices (
 price_id text NOT NULL,
 livemode boolean NOT NULL,
 plan_key text NOT NULL REFERENCES plans(key),
 currency text NOT NULL,
 unit_amount bigint NOT NULL CHECK(unit_amount >= 0),
 interval text NOT NULL CHECK(interval IN ('day','week','month','year')),
 interval_count integer NOT NULL CHECK(interval_count > 0),
 checkout_enabled boolean NOT NULL DEFAULT true,
 PRIMARY KEY(price_id,livemode)
);
CREATE UNIQUE INDEX billing_prices_one_checkout ON billing_prices(plan_key,livemode) WHERE checkout_enabled;
CREATE TABLE billing_accounts (
 workspace_id text NOT NULL REFERENCES workspaces(id),
 livemode boolean NOT NULL,
 customer_id text,
 customer_request_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,livemode),
 UNIQUE(customer_id,livemode)
);
CREATE TABLE billing_checkout_attempts (
 id text PRIMARY KEY,
 workspace_id text NOT NULL,
 livemode boolean NOT NULL,
 price_id text NOT NULL,
 session_id text UNIQUE,
 url text,
 return_url text NOT NULL,
 expires_at bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','open','complete','expired')),
 FOREIGN KEY(workspace_id,livemode) REFERENCES billing_accounts(workspace_id,livemode),
 FOREIGN KEY(price_id,livemode) REFERENCES billing_prices(price_id,livemode)
);
CREATE UNIQUE INDEX billing_one_pending_checkout ON billing_checkout_attempts(workspace_id,livemode) WHERE status IN ('pending','open');
CREATE TABLE billing_subscriptions (
 subscription_id text PRIMARY KEY,
 workspace_id text NOT NULL,
 livemode boolean NOT NULL,
 price_id text,
 status text NOT NULL,
 period_end timestamptz,
 cancel_at_period_end boolean NOT NULL DEFAULT false,
 collection_paused boolean NOT NULL DEFAULT false,
 payment_confirmed boolean NOT NULL DEFAULT false,
 synced_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(workspace_id,livemode) REFERENCES billing_accounts(workspace_id,livemode)
);
CREATE INDEX billing_subscription_scope ON billing_subscriptions(workspace_id,livemode);
CREATE TABLE billing_events (
 event_id text PRIMARY KEY,
 livemode boolean NOT NULL,
 event_type text NOT NULL,
 processed_at timestamptz NOT NULL DEFAULT now()
);
GRANT USAGE ON SCHEMA app_core TO app_billing_service;
GRANT SELECT ON workspaces,memberships,workspace_plans,plans,billing_prices TO app_billing_service;
GRANT SELECT,INSERT,UPDATE ON billing_accounts,billing_checkout_attempts,billing_subscriptions TO app_billing_service;
GRANT SELECT,INSERT ON billing_events TO app_billing_service;
CREATE POLICY workspace_plans_billing_read ON workspace_plans FOR SELECT TO app_billing_service USING (true);
GRANT SELECT,INSERT,UPDATE ON billing_prices TO app_plan_operator;
GRANT SELECT ON billing_prices,billing_accounts,billing_subscriptions TO app_runtime;
ALTER TABLE billing_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY billing_accounts_read ON billing_accounts FOR SELECT TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY billing_subscriptions_read ON billing_subscriptions FOR SELECT TO app_runtime USING (
 workspace_id=current_setting('app.workspace_id',true) AND active_workspace_role(workspace_id) IS NOT NULL);
CREATE POLICY billing_accounts_service ON billing_accounts TO app_billing_service USING (true) WITH CHECK (true);
CREATE POLICY billing_subscriptions_service ON billing_subscriptions TO app_billing_service USING (true) WITH CHECK (true);
-- Runtime never gets INSERT/UPDATE on billing state or access to webhook/event ledgers.
-- The billing service cannot mutate feature configuration or manual plan grants.
