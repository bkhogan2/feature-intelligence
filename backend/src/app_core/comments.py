"""Workspace-scoped, persisted request and opportunity discussions."""

from uuid import UUID
from fastapi import HTTPException
from psycopg import sql
from pydantic import Field, field_validator
from app_core.domain.models import StrictModel, WorkspaceRole


class CommentCreate(StrictModel):
    id: UUID
    body: str = Field(min_length=1, max_length=10000, pattern=r"^[^\x00]*$")

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Comment cannot be blank")
        return value.strip()


class CommentStore:
    def feedback_comments(self, p, feedback_id, payload=None):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Request internal notes are for reviewers only")
        return self._thread_comments(
            p,
            feedback_id,
            payload,
            "feedback",
            "feedback_comments",
            "feedback_id",
            "Request",
        )

    def opportunity_comments(self, p, opportunity_id, payload=None):
        return self._thread_comments(
            p,
            opportunity_id,
            payload,
            "opportunities",
            "opportunity_comments",
            "opportunity_id",
            "Opportunity",
        )

    def task_comments(self, p, task_id, payload=None):
        return self._thread_comments(
            p, task_id, payload, "tasks", "task_comments", "task_id", "Task"
        )

    def _thread_comments(
        self, p, thread_id, payload, parent, comments, foreign_key, label
    ):
        parent, comments, foreign_key = map(
            sql.Identifier, (parent, comments, foreign_key)
        )
        if payload is not None and p.role not in {
            WorkspaceRole.ADMIN,
            WorkspaceRole.EDITOR,
        }:
            raise HTTPException(403, "Read-only membership")
        with self.connection(p) as db:
            if not db.execute(
                sql.SQL("SELECT id FROM {} WHERE workspace_id=%s AND id=%s").format(
                    parent
                ),
                (p.tenant_id, thread_id),
            ).fetchone():
                raise HTTPException(404, f"{label} not found")
            if payload is not None:
                row = db.execute(
                    sql.SQL("""INSERT INTO {}(id,workspace_id,{},author_id,body)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING *""").format(
                        comments, foreign_key
                    ),
                    (payload.id, p.tenant_id, thread_id, p.subject, payload.body),
                ).fetchone()
                if row is None:
                    row = db.execute(
                        sql.SQL(
                            "SELECT * FROM {} WHERE id=%s AND workspace_id=%s AND {}=%s AND author_id=%s"
                        ).format(comments, foreign_key),
                        (payload.id, p.tenant_id, thread_id, p.subject),
                    ).fetchone()
                    if row is None or row["body"] != payload.body:
                        raise HTTPException(
                            409, "Comment submission conflicts with an existing comment"
                        )
                return row
            return {
                "items": db.execute(
                    sql.SQL(
                        "SELECT * FROM {} WHERE workspace_id=%s AND {}=%s ORDER BY created_at,id"
                    ).format(comments, foreign_key),
                    (p.tenant_id, thread_id),
                ).fetchall()
            }
