"""Operator provisioning; no public workspace creation or default credentials."""

import argparse
import getpass
import os
from app_core.main import HASHER
from app_core.store import PostgresStore
from app_core.domain.models import WorkspaceSlug
from pydantic import TypeAdapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["provision", "user", "reset-password", "demo"]
    )
    parser.add_argument("--email")
    parser.add_argument("--workspace", default="my-workspace")
    parser.add_argument("--name", default="My workspace")
    parser.add_argument(
        "--subject", help="External provider subject; omit for local account"
    )
    parser.add_argument(
        "--role", choices=["admin", "editor", "viewer"], default="admin"
    )
    args = parser.parse_args()
    if os.getenv("AUTH_PROVIDER", "local") in {"firebase", "google"}:
        if args.command != "provision" or not args.subject:
            parser.error(
                "In Firebase mode, manage identities in Firebase and provision workspace membership with --subject FIREBASE_UID"
            )
    with PostgresStore(os.getenv("DATABASE_URL", "")) as store:
        if args.command == "demo":
            if os.getenv("APP_ENV", "development") != "development":
                parser.error("Demo provisioning is development only")
            hashed = HASHER.hash("starter-demo-pass")
            store.provision(
                "demo@example.com", hashed, "alpha-workspace", "Product Feedback"
            )
            store.provision(
                "viewer@example.com",
                hashed,
                "alpha-workspace",
                "Product Feedback",
                "viewer",
            )
            print(
                "Local sample accounts: demo@example.com (admin), viewer@example.com (viewer). Password: starter-demo-pass"
            )
            return
        if not args.email or "@" not in args.email:
            parser.error("--email is required")
        TypeAdapter(WorkspaceSlug).validate_python(args.workspace)
        password = None
        if args.command == "reset-password" and args.subject:
            parser.error("Reset external passwords with their identity provider")
        if not args.subject:
            raw = getpass.getpass("New account password (12+ characters): ")
            if len(raw) < 12 or len(raw) > 256:
                parser.error("Password must have 12–256 characters")
            if raw != getpass.getpass("Confirm password: "):
                parser.error("Passwords do not match")
            password = HASHER.hash(raw)
        if args.command in {"user", "reset-password"}:
            email = args.email.strip().casefold()
            with store.connection() as db:
                db.execute("SELECT pg_advisory_xact_lock(83142001)")
                existing = db.execute(
                    "SELECT id FROM users WHERE email=%s", (email,)
                ).fetchone()
                if args.command == "reset-password":
                    if not existing:
                        parser.error("Account not found")
                    db.execute(
                        "UPDATE users SET password_hash=%s WHERE id=%s",
                        (password, existing["id"]),
                    )
                    db.execute(
                        "DELETE FROM sessions WHERE user_id=%s", (existing["id"],)
                    )
                    print("Password changed; existing sessions revoked.")
                    return
                if existing:
                    parser.error("Account already exists")
                from uuid import uuid4

                uid = args.subject or str(uuid4())
                db.execute(
                    "INSERT INTO users VALUES(%s,%s,%s,1)", (uid, email, password)
                )
            print("Created operator-verified identity:", uid)
            return
        uid = store.provision(
            args.email.strip().casefold(),
            password,
            args.workspace,
            args.name,
            args.role,
            args.subject,
        )
        print("Provisioned identity:", uid)


if __name__ == "__main__":
    main()
