"""Task lifecycle, workspace assignment and discussion."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Query
from pydantic import Field, StringConstraints, model_validator

from app_core.comments import CommentCreate
from app_core.domain.models import StrictModel, WorkspaceRole

TaskStatus = Literal["backlog", "todo", "in_progress", "blocked", "done"]
Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[^\x00]*$"
    ),
]
Description = Annotated[str, Field(max_length=20000, pattern=r"^[^\x00]*$")]
Assignee = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00]*$")]


class TaskCreate(StrictModel):
    id: UUID
    opportunity_id: UUID
    title: Title
    description: Description = ""
    assignee_id: Assignee | None = None


class ReviewedTask(StrictModel):
    id: UUID
    title: Title
    description: Description


def task_title_key(title):
    return " ".join(title.casefold().split())


class TaskBatch(StrictModel):
    tasks: Annotated[list[ReviewedTask], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def unique_tasks(self):
        if len({item.id for item in self.tasks}) != len(self.tasks):
            raise ValueError("Each task needs a unique id.")
        if len({task_title_key(item.title) for item in self.tasks}) != len(self.tasks):
            raise ValueError("Give the selected drafts distinct titles.")
        return self


class TaskUpdate(StrictModel):
    expected_revision: Annotated[int, Field(ge=0)]
    title: Title | None = None
    description: Description | None = None
    status: TaskStatus | None = None
    assignee_id: Assignee | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        changes = self.model_fields_set - {"expected_revision"}
        if not changes or any(
            getattr(self, name) is None for name in changes - {"assignee_id"}
        ):
            raise ValueError("Provide a valid task change.")
        return self


_TASKS = """SELECT t.*,o.name AS opportunity_name,u.email AS assignee_name
    FROM tasks t JOIN opportunities o ON o.id=t.opportunity_id AND o.workspace_id=t.workspace_id
    LEFT JOIN users u ON u.id=t.assignee_id"""


class TaskStore:
    def task_assignees(self, p):
        with self.connection(p) as db:
            return db.execute(
                """SELECT m.user_id AS id,u.email AS name
                FROM memberships m JOIN users u ON u.id=m.user_id
                WHERE m.workspace_id=%s AND m.status='active' ORDER BY u.email,u.id""",
                (p.tenant_id,),
            ).fetchall()

    def list_tasks(self, p, opportunity_id, limit, offset):
        with self.connection(p) as db:
            rows = db.execute(
                _TASKS
                + """ WHERE t.workspace_id=%s AND (%s::uuid IS NULL OR t.opportunity_id=%s)
                ORDER BY t.created_at DESC,t.id LIMIT %s OFFSET %s""",
                (p.tenant_id, opportunity_id, opportunity_id, limit + 1, offset),
            ).fetchall()
        return {"items": rows[:limit], "has_more": len(rows) > limit}

    def _task(self, db, p, task_id):
        row = db.execute(
            _TASKS + " WHERE t.workspace_id=%s AND t.id=%s",
            (p.tenant_id, task_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Task not found")
        return row

    def task(self, p, task_id):
        with self.connection(p) as db:
            return self._task(db, p, task_id)

    @staticmethod
    def _require_task_editor(p):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Read-only membership")

    @staticmethod
    def _check_assignee(db, p, assignee_id):
        if assignee_id is None:
            return
        member = db.execute(
            """SELECT id FROM memberships WHERE workspace_id=%s AND user_id=%s
            AND status='active' FOR SHARE""",
            (p.tenant_id, assignee_id),
        ).fetchone()
        if member is None:
            raise HTTPException(422, "Choose an active workspace member.")

    @staticmethod
    def _lock_task_parent(db, p, opportunity_id):
        # Serialize creation for this opportunity with archive changes and batch review.
        parent = db.execute(
            "SELECT archived FROM opportunities WHERE workspace_id=%s AND id=%s FOR UPDATE",
            (p.tenant_id, opportunity_id),
        ).fetchone()
        if parent is None:
            raise HTTPException(404, "Opportunity not found")
        if parent["archived"]:
            raise HTTPException(409, "Restore the opportunity before adding tasks.")

    def create_task(self, p, payload):
        self._require_task_editor(p)
        with self.connection(p) as db:
            self._lock_task_parent(db, p, payload.opportunity_id)
            return self._insert_task(db, p, payload)

    def create_task_batch(self, p, opportunity_id, payload):
        self._require_task_editor(p)
        with self.connection(p) as db:
            self._lock_task_parent(db, p, opportunity_id)
            existing = db.execute(
                """SELECT title FROM tasks WHERE workspace_id=%s AND opportunity_id=%s
                   AND NOT (id = ANY(%s))""",
                (p.tenant_id, opportunity_id, [item.id for item in payload.tasks]),
            ).fetchall()
            titles = {task_title_key(item["title"]) for item in existing}
            for item in payload.tasks:
                if task_title_key(item.title) in titles:
                    raise HTTPException(
                        409,
                        f'A sub-issue named "{item.title}" already exists. Edit or deselect that draft.',
                    )
            return {
                "items": [
                    self._insert_task(
                        db,
                        p,
                        TaskCreate(opportunity_id=opportunity_id, **item.model_dump()),
                    )
                    for item in payload.tasks
                ]
            }

    def _insert_task(self, db, p, payload):
        self._check_assignee(db, p, payload.assignee_id)
        created = db.execute(
            """INSERT INTO tasks(id,workspace_id,opportunity_id,title,description,assignee_id,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING id""",
            (
                payload.id,
                p.tenant_id,
                payload.opportunity_id,
                payload.title,
                payload.description,
                payload.assignee_id,
                p.subject,
            ),
        ).fetchone()
        if created is None:
            existing = self._task(db, p, payload.id)
            if existing["created_by"] != p.subject or any(
                existing[field] != getattr(payload, field)
                for field in (
                    "opportunity_id",
                    "title",
                    "description",
                    "assignee_id",
                )
            ):
                raise HTTPException(
                    409, "Task creation conflicts with an existing task."
                )
            return existing
        self._audit(db, p.tenant_id, p.subject, "task.created")
        return self._task(db, p, payload.id)

    def update_task(self, p, task_id, payload):
        self._require_task_editor(p)
        with self.connection(p) as db:
            self._task(db, p, task_id)
            changes_assignee = "assignee_id" in payload.model_fields_set
            if changes_assignee:
                self._check_assignee(db, p, payload.assignee_id)
            updated = db.execute(
                """UPDATE tasks SET title=coalesce(%s,title),description=coalesce(%s,description),
                status=coalesce(%s,status),assignee_id=CASE WHEN %s THEN %s ELSE assignee_id END,
                revision=revision+1
                WHERE id=%s AND workspace_id=%s AND revision=%s RETURNING id""",
                (
                    payload.title,
                    payload.description,
                    payload.status,
                    changes_assignee,
                    payload.assignee_id,
                    task_id,
                    p.tenant_id,
                    payload.expected_revision,
                ),
            ).fetchone()
            if updated is None:
                raise HTTPException(409, "This task changed. Reload it before saving.")
            self._audit(db, p.tenant_id, p.subject, "task.updated")
            return self._task(db, p, task_id)


def register_task_routes(app, store, principal_dependency):
    @app.get("/api/v1/tasks")
    def tasks(
        p: principal_dependency,
        opportunity_id: UUID | None = None,
        limit: int = Query(100, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100_000),
    ):
        return store.list_tasks(p, opportunity_id, limit, offset)

    @app.post("/api/v1/tasks", status_code=201)
    def create(payload: TaskCreate, p: principal_dependency):
        return store.create_task(p, payload)

    @app.post("/api/v1/opportunities/{opportunity_id}/tasks/batch", status_code=201)
    def create_batch(opportunity_id: UUID, payload: TaskBatch, p: principal_dependency):
        return store.create_task_batch(p, opportunity_id, payload)

    @app.get("/api/v1/tasks/assignees")
    def assignees(p: principal_dependency):
        return {"items": store.task_assignees(p)}

    @app.get("/api/v1/tasks/{task_id}")
    def detail(task_id: UUID, p: principal_dependency):
        return store.task(p, task_id)

    @app.patch("/api/v1/tasks/{task_id}")
    def update(task_id: UUID, payload: TaskUpdate, p: principal_dependency):
        return store.update_task(p, task_id, payload)

    @app.get("/api/v1/tasks/{task_id}/comments")
    def comments(task_id: UUID, p: principal_dependency):
        return store.task_comments(p, task_id)

    @app.post("/api/v1/tasks/{task_id}/comments", status_code=201)
    def add_comment(task_id: UUID, payload: CommentCreate, p: principal_dependency):
        return store.task_comments(p, task_id, payload)
