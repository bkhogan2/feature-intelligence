"""Trusted operator CLI; never mount this module as a workspace-admin endpoint."""

import argparse
import os
import re
import psycopg
from psycopg.types.json import Jsonb
from app_core.entitlements import FEATURES


def configure(
    database_url,
    command,
    *,
    key=None,
    name=None,
    features=(),
    workspace=None,
    price_id=None,
    gateway=None,
):
    if command not in {
        "put-plan",
        "assign",
        "clear",
        "disable",
        "map-price",
        "hide-price",
    }:
        raise ValueError("Unknown plan command")
    if command != "clear" and (
        not key or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key)
    ):
        raise ValueError("Plan key must be a lowercase slug")
    if command == "put-plan" and (not name or not name.strip() or len(name) > 100):
        raise ValueError("Plan name must contain 1–100 characters")
    if set(features) - FEATURES.keys():
        raise ValueError("Features must be registered in the application")
    price_info = None
    if command in {"map-price", "hide-price"}:
        from app_core.stripe_gateway import (
            StripeSettings,
            StripeGateway,
            validate_price,
        )

        if gateway is None:
            settings = StripeSettings.from_env()
            if not settings:
                raise ValueError("Enable/configure Stripe before mapping prices")
            gateway = StripeGateway(settings)
        if command == "map-price":
            price = gateway.price(price_id)
            price_info = validate_price(price, gateway.settings.livemode)
    with psycopg.connect(database_url) as db:
        db.execute("SET LOCAL ROLE app_plan_operator")
        db.execute("SET LOCAL search_path=pg_catalog,app_core")
        db.execute("SELECT pg_advisory_xact_lock(83142002)")
        if command in {"map-price", "hide-price"}:
            mode = gateway.settings.livemode
            existing = db.execute(
                "SELECT plan_key FROM billing_prices WHERE price_id=%s AND livemode=%s",
                (price_id, mode),
            ).fetchone()
            if existing and existing[0] != key:
                raise ValueError(
                    "A Stripe price cannot be remapped to a different plan; create a new price"
                )
            if command == "map-price":
                db.execute(
                    "UPDATE billing_prices SET checkout_enabled=false WHERE plan_key=%s AND livemode=%s",
                    (key, mode),
                )
                db.execute(
                    """INSERT INTO billing_prices(price_id,livemode,plan_key,currency,unit_amount,interval,interval_count)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(price_id,livemode) DO UPDATE SET checkout_enabled=true""",
                    (
                        price_id,
                        mode,
                        key,
                        price_info["currency"],
                        price_info["unit_amount"],
                        price_info["interval"],
                        price_info["interval_count"],
                    ),
                )
            else:
                if not existing:
                    raise ValueError("Unknown mapped price")
                db.execute(
                    "UPDATE billing_prices SET checkout_enabled=false WHERE price_id=%s AND livemode=%s",
                    (price_id, mode),
                )
        elif command == "put-plan":
            db.execute(
                "INSERT INTO plans(key,name) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET name=excluded.name,active=true",
                (key, name),
            )
            db.execute("DELETE FROM plan_feature_assignments WHERE plan_key=%s", (key,))
            for feature in sorted(set(features)):
                db.execute(
                    "INSERT INTO plan_feature_assignments VALUES (%s,%s)",
                    (key, feature),
                )
        elif command == "disable":
            if not db.execute(
                "UPDATE plans SET active=false WHERE key=%s RETURNING key", (key,)
            ).fetchone():
                raise ValueError("Unknown plan")
        else:
            row = db.execute(
                "SELECT id FROM workspaces WHERE slug=%s", (workspace,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown workspace")
            if command == "assign":
                if not db.execute(
                    "SELECT key FROM plans WHERE key=%s AND active", (key,)
                ).fetchone():
                    raise ValueError("Unknown or disabled plan")
                db.execute(
                    "INSERT INTO workspace_plans VALUES (%s,%s) ON CONFLICT(workspace_id) DO UPDATE SET plan_key=excluded.plan_key",
                    (row[0], key),
                )
            else:
                db.execute(
                    "DELETE FROM workspace_plans WHERE workspace_id=%s", (row[0],)
                )
        db.execute(
            "INSERT INTO plan_configuration_audit(action,details) VALUES (%s,%s)",
            (
                command,
                Jsonb(
                    {
                        "plan": key,
                        "name": name,
                        "features": list(features),
                        "workspace": workspace,
                        "price_id": price_id,
                    }
                ),
            ),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("put-plan")
    put.add_argument("key")
    put.add_argument("name")
    put.add_argument("--feature", action="append", default=[], dest="features")
    assign = commands.add_parser("assign")
    assign.add_argument("workspace")
    assign.add_argument("key")
    clear = commands.add_parser("clear")
    clear.add_argument("workspace")
    disable = commands.add_parser("disable")
    disable.add_argument("key")
    for action in ("map-price", "hide-price"):
        price = commands.add_parser(action)
        price.add_argument("key", help="Registered plan key")
        price.add_argument("price_id", help="Stripe recurring fixed price ID")
    args = vars(parser.parse_args())
    configure(os.environ["PLAN_OPERATOR_DATABASE_URL"], **args)
    print("Plan configuration updated.")


if __name__ == "__main__":
    main()
