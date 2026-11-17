"""Real PostgreSQL tests for captured evidence and its trust boundary."""

from datetime import datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app_core.auth.identity import Principal
from app_core.domain.models import WorkspaceRole
from app_core.main import create_app
from app_core.store import PostgresStore


@pytest.fixture
def feedback_setup(pg_store):
    store, _ = pg_store
    ids = {}
    for email, slug, role in [
        ("admin@example.com", "alpha", "admin"),
        ("admin@example.com", "beta", "admin"),
        ("editor@example.com", "alpha", "editor"),
        ("viewer@example.com", "alpha", "viewer"),
        ("outsider@example.com", "beta", "admin"),
    ]:
        ids[email] = store.provision(email, None, slug, slug.title(), role)
    app = create_app(store)

    def client(name, workspace="alpha"):
        c = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": workspace})
        c.cookies.set("app_session", store.new_session(ids[name + "@example.com"]))
        return c

    return store, ids, client, app


def test_submission_persists_attribution_and_permissions(feedback_setup):
    store, ids, client, app = feedback_setup
    admin = client("admin")
    editor = client("editor")
    payload = {
        "title": "  Faster exports  ",
        "description": "  Exporting takes hours.\nOur team waits.  ",
    }
    before = datetime.now().astimezone()
    response = editor.post("/api/v1/feedback", json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["title"] == "Faster exports"
    assert item["description"] == "Exporting takes hours.\nOur team waits."
    assert item["submitted_by"] == ids["editor@example.com"]
    assert (
        item["workspace_id"]
        == store.get_active_global_access(
            ids["editor@example.com"], "alpha"
        ).workspace.id
    )
    assert datetime.fromisoformat(item["created_at"]) >= before
    assert (
        admin.post(
            "/api/v1/feedback", json={"title": "Second", "description": "Context"}
        ).status_code
        == 201
    )
    viewer = client("viewer")
    assert len(viewer.get("/api/v1/feedback").json()["items"]) == 2
    assert viewer.post("/api/v1/feedback", json=payload).status_code == 403
    assert client("admin", "beta").get("/api/v1/feedback").json()["items"] == []
    assert client("outsider").get("/api/v1/feedback").status_code == 404
    assert TestClient(app).get("/api/v1/feedback").status_code == 401
    # A separate connection pool proves data survives the request and adapter instance.
    with PostgresStore(store.database_url) as reopened:
        access = store.get_active_global_access(ids["editor@example.com"], "alpha")
        principal = Principal(access.user_id, access.workspace, access.role)
        assert item["id"] in [
            str(row["id"]) for row in reopened.list_feedback(principal)["items"]
        ]
    assert [row["action"] for row in admin.get("/api/v1/activity").json()] == [
        "feedback.created",
        "feedback.created",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Bad\x00title", "description": "Context"},
        {"title": "Title", "description": "Bad\x00description"},
        {},
        {"title": "Title"},
        {"description": "Context"},
        {"title": " \n ", "description": "Context"},
        {"title": "Title", "description": " \t "},
        {"title": "x" * 161, "description": "Context"},
        {"title": "Title", "description": "x" * 10001},
        {"title": "Title", "description": "Context", "workspace_id": "beta"},
        {"title": "Title", "description": "Context", "submitted_by": "someone-else"},
        {
            "title": "Title",
            "description": "Context",
            "created_at": "2020-01-01T00:00:00Z",
        },
    ],
)
def test_invalid_or_forged_submission_creates_nothing(feedback_setup, payload):
    _, _, client, _ = feedback_setup
    c = client("admin")
    assert c.post("/api/v1/feedback", json=payload).status_code == 422
    assert c.get("/api/v1/feedback").json()["items"] == []


def test_search_pagination_and_limits(feedback_setup):
    _, _, client, _ = feedback_setup
    c = client("admin")
    for title, description in [
        ("Exports", "Wait for DOWNLOAD"),
        ("100% accurate", "Literal _ character"),
        ("Other", "Normal text"),
    ]:
        assert (
            c.post(
                "/api/v1/feedback", json={"title": title, "description": description}
            ).status_code
            == 201
        )

    def search(value):
        return c.get("/api/v1/feedback", params={"search": value}).json()["items"]

    assert [row["title"] for row in search("exports")] == ["Exports"]
    assert [row["title"] for row in search(" download ")] == ["Exports"]
    assert [row["title"] for row in search("%")] == ["100% accurate"]
    assert len(search("_")) == 1
    assert search("' OR 1=1 --") == []
    first = c.get("/api/v1/feedback?limit=2").json()
    second = c.get("/api/v1/feedback?limit=2&offset=2").json()
    assert first["has_more"] is True and second["has_more"] is False
    assert len({row["id"] for row in first["items"] + second["items"]}) == 3
    for params in [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"search": "x" * 201}]:
        assert c.get("/api/v1/feedback", params=params).status_code == 422


def test_database_rls_blocks_forgery_revocation_and_unscoped_reads(feedback_setup):
    store, ids, client, _ = feedback_setup
    c = client("admin")
    assert (
        c.post(
            "/api/v1/feedback", json={"title": "Alpha", "description": "Evidence"}
        ).status_code
        == 201
    )
    access = store.get_active_global_access(ids["admin@example.com"], "alpha")
    principal = Principal(access.user_id, access.workspace, access.role)
    with store.connection(principal) as db:
        assert len(db.execute("SELECT * FROM feedback").fetchall()) == 1
    with store.connection() as db:
        assert db.execute("SELECT * FROM feedback").fetchall() == []
    beta = store.get_active_global_access(ids["admin@example.com"], "beta")
    viewer = Principal(ids["viewer@example.com"], access.workspace, WorkspaceRole.ADMIN)
    for actor, workspace, submitter in [
        (principal, beta.workspace.id, principal.subject),
        (principal, principal.tenant_id, ids["viewer@example.com"]),
        (viewer, viewer.tenant_id, viewer.subject),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.connection(actor) as db:
                db.execute(
                    "INSERT INTO feedback(id,workspace_id,title,description,submitted_by) VALUES(%s,%s,'Title','Context',%s)",
                    (uuid4(), workspace, submitter),
                )
    with pytest.raises(psycopg.errors.CheckViolation):
        store.create_feedback(principal, "", "Context")
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET status='disabled' WHERE user_id=%s AND workspace_id=%s",
            (principal.subject, principal.tenant_id),
        )
    with store.connection(principal) as db:
        assert db.execute("SELECT * FROM feedback").fetchall() == []
    assert c.get("/api/v1/feedback").status_code == 404
    assert (
        c.post(
            "/api/v1/feedback", json={"title": "Blocked", "description": "Context"}
        ).status_code
        == 404
    )


def create_request(client):
    response = client.post(
        "/api/v1/feedback", json={"title": "Support test", "description": "Evidence"}
    )
    assert response.status_code == 201
    assert response.json()["support_count"] == 0
    assert response.json()["supported_by_me"] is False
    return response.json()["id"]


def test_support_is_explicit_idempotent_and_available_to_all_members(feedback_setup):
    store, ids, client, _ = feedback_setup
    admin = client("admin")
    request_id = create_request(admin)
    path = f"/api/v1/feedback/{request_id}/support"
    for count, role in enumerate(["viewer", "editor", "admin"], 1):
        actor = client(role)
        for _ in range(2):
            response = actor.post(path)
            assert response.status_code == 200, response.text
            assert response.json() == {"support_count": count, "supported_by_me": True}
        row = actor.get("/api/v1/feedback").json()["items"][0]
        assert row["support_count"] == count and row["supported_by_me"] is True
    # A separate pool verifies persistence. A viewer can signal interest but cannot create feedback.
    access = store.get_active_global_access(ids["viewer@example.com"], "alpha")
    with PostgresStore(store.database_url) as reopened:
        row = reopened.list_feedback(
            Principal(access.user_id, access.workspace, access.role)
        )["items"][0]
        assert row["support_count"] == 3 and row["supported_by_me"] is True
    assert (
        client("viewer")
        .post("/api/v1/feedback", json={"title": "No", "description": "No"})
        .status_code
        == 403
    )
    for _ in range(2):
        response = client("viewer").delete(path)
        assert response.json() == {"support_count": 2, "supported_by_me": False}
    assert (
        client("editor").get("/api/v1/feedback").json()["items"][0]["supported_by_me"]
        is True
    )
    actions = [row["action"] for row in admin.get("/api/v1/activity").json()]
    assert actions.count("feedback.supported") == 3
    assert actions.count("feedback.support_withdrawn") == 1


def test_support_tenant_authentication_and_csrf_boundaries(feedback_setup):
    _, _, client, app = feedback_setup
    request_id = create_request(client("admin"))
    path = f"/api/v1/feedback/{request_id}/support"
    assert client("viewer").post(path).status_code == 200
    for method in ["post", "delete"]:
        assert getattr(client("admin", "beta"), method)(path).status_code == 404
        assert getattr(client("outsider"), method)(path).status_code == 404
        assert getattr(client("outsider", "beta"), method)(path).status_code == 404
        assert (
            getattr(
                TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}),
                method,
            )(path).status_code
            == 401
        )
        assert (
            getattr(client("admin"), method)(
                f"/api/v1/feedback/{uuid4()}/support"
            ).status_code
            == 404
        )
        assert (
            getattr(client("admin"), method)(
                "/api/v1/feedback/not-a-uuid/support"
            ).status_code
            == 422
        )
        assert (
            getattr(client("admin"), method)(
                path, headers={"X-App-Request": ""}
            ).status_code
            == 403
        )
        assert (
            getattr(client("admin"), method)(
                path, headers={"Origin": "https://untrusted.invalid"}
            ).status_code
            == 403
        )
    # Request payload cannot impersonate another supporter; identity is always server-derived.
    response = client("admin").post(
        path, json={"user_id": "forged", "workspace_id": "beta"}
    )
    assert response.json() == {"support_count": 2, "supported_by_me": True}


def test_support_rls_prevents_forgery_and_other_users_withdrawals(feedback_setup):
    store, ids, client, _ = feedback_setup
    request_id = create_request(client("admin"))
    beta_id = create_request(client("admin", "beta"))
    path = f"/api/v1/feedback/{request_id}/support"
    client("viewer").post(path)
    access = store.get_active_global_access(ids["admin@example.com"], "alpha")
    principal = Principal(access.user_id, access.workspace, access.role)
    beta = store.get_active_global_access(ids["admin@example.com"], "beta")
    for request, workspace, supporter in [
        (request_id, principal.tenant_id, ids["viewer@example.com"]),
        (request_id, beta.workspace.id, principal.subject),
        (beta_id, principal.tenant_id, principal.subject),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.connection(principal) as db:
                db.execute(
                    "INSERT INTO feedback_support(feedback_id,workspace_id,user_id) VALUES(%s,%s,%s)",
                    (request, workspace, supporter),
                )
    with store.connection(principal) as db:
        assert (
            db.execute(
                "DELETE FROM feedback_support WHERE feedback_id=%s RETURNING *",
                (request_id,),
            ).fetchall()
            == []
        )
    with store.connection() as db:
        assert db.execute("SELECT * FROM feedback_support").fetchall() == []
    client("admin").post(path)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with store.connection(principal) as db:
            db.execute(
                "INSERT INTO feedback_support(feedback_id,workspace_id,user_id) VALUES(%s,%s,%s)",
                (request_id, principal.tenant_id, principal.subject),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.connection(principal) as db:
            db.execute(
                "UPDATE feedback_support SET user_id=%s WHERE feedback_id=%s",
                (ids["editor@example.com"], request_id),
            )
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET status='disabled' WHERE user_id=%s AND workspace_id=%s",
            (principal.subject, principal.tenant_id),
        )
    with store.connection(principal) as db:
        assert db.execute("SELECT * FROM feedback_support").fetchall() == []
        assert db.execute("DELETE FROM feedback_support RETURNING *").fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.connection(principal) as db:
            db.execute(
                "INSERT INTO feedback_support(feedback_id,workspace_id,user_id) VALUES(%s,%s,%s)",
                (request_id, principal.tenant_id, principal.subject),
            )
    assert client("admin").post(path).status_code == 404
    assert client("admin").delete(path).status_code == 404


def test_concurrent_support_retries_do_not_duplicate(feedback_setup):
    from concurrent.futures import ThreadPoolExecutor

    store, ids, client, _ = feedback_setup
    request_id = create_request(client("admin"))
    access = store.get_active_global_access(ids["viewer@example.com"], "alpha")
    principal = Principal(access.user_id, access.workspace, access.role)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: store.set_feedback_support(principal, request_id, True),
                range(8),
            )
        )
    assert all(row == {"support_count": 1, "supported_by_me": True} for row in results)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: store.set_feedback_support(principal, request_id, False),
                range(8),
            )
        )
    assert all(row == {"support_count": 0, "supported_by_me": False} for row in results)
