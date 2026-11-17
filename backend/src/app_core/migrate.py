"""Versioned PostgreSQL migrations using a separate schema-owner connection."""

import hashlib
import os
from pathlib import Path
import psycopg


def migrate(database_url=None):
    dsn = database_url or os.environ["DATABASE_ADMIN_URL"]
    migrations = sorted((Path(__file__).parent / "migrations").glob("*.sql"))
    with psycopg.connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(83142000)")
        exists = db.execute(
            "SELECT to_regclass('app_core.schema_migrations')"
        ).fetchone()[0]
        applied = (
            dict(
                db.execute(
                    "SELECT version,checksum FROM app_core.schema_migrations"
                ).fetchall()
            )
            if exists
            else {}
        )
        known = {int(path.name.split("_")[0]) for path in migrations}
        if set(applied) - known:
            raise RuntimeError("Database has unknown migrations")
        for path in migrations:
            version = int(path.name.split("_")[0])
            source = path.read_text()
            digest = hashlib.sha256(source.encode()).hexdigest()
            if version in applied:
                if applied[version] != digest:
                    raise RuntimeError("Applied migration checksum mismatch")
                continue
            db.execute(source)
            db.execute(
                "INSERT INTO app_core.schema_migrations(version,checksum) VALUES(%s,%s)",
                (version, digest),
            )
    return len(migrations)


if __name__ == "__main__":
    print(f"PostgreSQL schema current ({migrate()} migration versions).")
