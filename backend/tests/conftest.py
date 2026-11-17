"""Every test runs against a fresh real PostgreSQL database, never an in-memory substitute."""

import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from app_core.migrate import migrate
from app_core.store import PostgresStore


@pytest.fixture
def pg_store():
    admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL")
    runtime_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url or not runtime_url:
        pytest.fail(
            "Set TEST_DATABASE_ADMIN_URL and TEST_DATABASE_URL for real PostgreSQL tests"
        )
    database = "starter_test_" + uuid4().hex
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    admin_config = conninfo_to_dict(admin_url)
    admin_config["dbname"] = database
    runtime_config = conninfo_to_dict(runtime_url)
    runtime_config["dbname"] = database
    isolated_admin = make_conninfo(**admin_config)
    isolated_runtime = make_conninfo(**runtime_config)
    store = None
    try:
        migrate(isolated_admin)
        store = PostgresStore(isolated_runtime)
        yield store, isolated_admin
    finally:
        if store:
            store.close()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )
