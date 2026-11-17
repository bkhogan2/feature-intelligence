"""Exercise PostgreSQL itself, including queries that accidentally omit tenant filters."""

from uuid import uuid4
import psycopg
import pytest
from psycopg.types.json import Jsonb
from app_core.auth.identity import Principal
from app_core.domain.models import WorkspaceRole
from app_core.migrate import migrate
from app_core.store import PostgresStore, now_iso


def test_rls_denies_unscoped_reads_and_cross_tenant_writes(pg_store):
    store, _ = pg_store
    uid = store.provision("owner@example.com", None, "alpha", "Alpha")
    store.provision("owner@example.com", None, "beta", "Beta")
    store.provision("viewer@example.com", None, "alpha", "Alpha", "viewer")
    alpha = store.get_active_global_access(uid, "alpha")
    beta = store.get_active_global_access(uid, "beta")
    a = Principal(uid, alpha.workspace, WorkspaceRole.ADMIN)
    b = Principal(uid, beta.workspace, WorkspaceRole.ADMIN)
    store.create_record(a, "Alpha only", {"nested": {"anything": [1, True]}})
    store.create_record(b, "Beta only", {})
    with store.connection() as db:
        assert db.execute("SELECT * FROM records").fetchall() == []
        assert db.execute("SELECT * FROM audit").fetchall() == []
    with store.connection(a) as db:
        # Deliberately no WHERE clause: database policy supplies the isolation.
        assert [r["title"] for r in db.execute("SELECT * FROM records")] == [
            "Alpha only"
        ]
        assert len(db.execute("SELECT * FROM audit").fetchall()) == 1
        assert (
            db.execute("SELECT current_user AS name").fetchone()["name"]
            == "app_runtime"
        )
    with store.connection() as db:
        assert db.execute("SELECT * FROM records").fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.connection(a) as db:
            db.execute(
                "INSERT INTO records VALUES(%s,%s,%s,%s,%s)",
                (str(uuid4()), beta.workspace.id, "forged", Jsonb({}), now_iso()),
            )
    vuid = store.user_by_email("viewer@example.com")["id"]
    viewer = Principal(vuid, alpha.workspace, WorkspaceRole.VIEWER)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.connection(viewer) as db:
            db.execute(
                "INSERT INTO records VALUES(%s,%s,%s,%s,%s)",
                (str(uuid4()), alpha.workspace.id, "blocked", Jsonb({}), now_iso()),
            )
    forged = Principal(vuid, beta.workspace, WorkspaceRole.ADMIN)
    with store.connection(forged) as db:
        assert db.execute("SELECT * FROM records").fetchall() == []
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET status='disabled' WHERE user_id=%s AND workspace_id=%s",
            (uid, alpha.workspace.id),
        )
    with store.connection(a) as db:
        assert db.execute("SELECT * FROM records").fetchall() == []


def test_migrations_idempotent_and_owner_runtime_rejected(pg_store):
    store, admin_url = pg_store
    query = "SELECT count(*) AS count FROM schema_migrations"
    with store.connection() as db:
        before = db.execute(query).fetchone()["count"]
    assert migrate(admin_url) == before
    with pytest.raises(RuntimeError, match="non-owner"):
        PostgresStore(admin_url)
    with store.connection() as db:
        assert db.execute(query).fetchone()["count"] == before



def test_concurrent_last_admin_changes_keep_one_active_admin(pg_store):
    from concurrent.futures import ThreadPoolExecutor
    from app_core.auth.workspace_admin import (
        LastWorkspaceAdminError,
        WorkspaceAdminForbiddenError,
    )

    store, _ = pg_store
    first = store.provision("first@example.com", None, "alpha", "Alpha")
    second = store.provision("second@example.com", None, "alpha", "Alpha")
    workspace = store.get_active_global_access(first, "alpha").workspace.id
    members = store.list_members(first, workspace)
    targets = {m.email: m.membership_id for m in members}

    def demote(args):
        uid, email = args
        try:
            store.update_member(
                actor_uid=uid,
                tenant_id=workspace,
                membership_id=targets[email],
                role=WorkspaceRole.VIEWER,
                status=None,
            )
            return "changed"
        except (LastWorkspaceAdminError, WorkspaceAdminForbiddenError):
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(
            pool.map(
                demote, [(first, "first@example.com"), (second, "second@example.com")]
            )
        ) == ["blocked", "changed"]
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) AS count FROM memberships WHERE workspace_id=%s AND role='admin' AND status='active'",
                (workspace,),
            ).fetchone()["count"]
            == 1
        )
