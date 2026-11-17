"""Seed fixed synthetic fixtures in an existing workspace, without creating accounts."""

import argparse
import os

from app_core.agent_tools import seed_demo_records
from app_core.auth.identity import _principal_from_access
from app_core.store import PostgresStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    if os.getenv("APP_ENV", "development") != "development":
        parser.error("Synthetic demo setup is development only")
    with PostgresStore(os.environ["DATABASE_URL"]) as store:
        user = store.user_by_email(args.email.strip().casefold())
        access = (
            store.get_active_global_access(user["id"], args.workspace) if user else None
        )
        if not access:
            parser.error("User must already have access to this workspace")
        principal = _principal_from_access(access)
        if str(principal.role) not in {"admin", "editor"}:
            parser.error("An admin or editor membership is required for demo setup")
        seed_demo_records(store, principal)
    print("Synthetic demo records are ready.")


if __name__ == "__main__":
    main()
