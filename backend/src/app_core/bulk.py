"""Atomic, tenant-scoped human table actions and board ordering."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from app_core.domain.models import StrictModel, Feedback, WorkspaceRole
from app_core.triage_models import OpportunityStatus, OpportunityDecision

Ids = Annotated[list[UUID], Field(min_length=1, max_length=200)]


class Selection(StrictModel):
    ids: Ids

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Selection contains duplicate IDs")
        return self


class FeedbackBulk(Selection):
    priority: Literal["high", "medium", "low"] | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def action(self):
        if "priority" not in self.model_fields_set and self.archived is None:
            raise ValueError("Choose an action")
        return self


class OpportunityBulk(Selection):
    archived: bool | None = None
    status: OpportunityStatus | None = None
    expected_statuses: dict[UUID, OpportunityStatus] = Field(default_factory=dict)

    @model_validator(mode="after")
    def action(self):
        if self.archived is None and self.status is None:
            raise ValueError("Choose an action")
        if self.status is not None and set(self.expected_statuses) != set(self.ids):
            raise ValueError(
                "Provide the current status for every selected opportunity"
            )
        return self


class BoardItem(StrictModel):
    id: UUID
    status: OpportunityStatus
    expected_status: OpportunityStatus
    order: Annotated[int, Field(ge=0, le=2147483647)]


class BoardUpdate(StrictModel):
    items: Annotated[list[BoardItem], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Board contains duplicate IDs")
        return self


class BulkStore:
    def _bulk_rows(self, db, p, table, ids):
        # Table is chosen exclusively by internal call sites.
        rows = db.execute(
            f"SELECT * FROM {table} WHERE workspace_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
            (p.tenant_id, ids),
        ).fetchall()
        if len(rows) != len(ids):
            raise LookupError("One or more selected items were not found")
        return rows

    def bulk_feedback(self, p, payload):
        require_editor(p)
        with self.connection(p) as db:
            rows = self._bulk_rows(db, p, "feedback", payload.ids)
            for row in rows:
                if "priority" in payload.model_fields_set:
                    db.execute(
                        "UPDATE feedback SET priority=%s WHERE id=%s AND workspace_id=%s",
                        (payload.priority, row["id"], p.tenant_id),
                    )
                if payload.archived is True:
                    db.execute(
                        "UPDATE request_approvals SET status='failed',error='Request was archived.',updated_at=now() WHERE workspace_id=%s AND feedback_id=%s AND status IN ('queued','running')",
                        (p.tenant_id, row["id"]),
                    )
                if payload.archived is True and row["status"] != "archived":
                    db.execute(
                        "UPDATE feedback SET archived_from_status=status,status='archived' WHERE id=%s AND workspace_id=%s",
                        (row["id"], p.tenant_id),
                    )
                elif payload.archived is False and row["status"] == "archived":
                    db.execute(
                        "UPDATE feedback SET status=coalesce(archived_from_status,'new'),archived_from_status=NULL WHERE id=%s AND workspace_id=%s",
                        (row["id"], p.tenant_id),
                    )
            self._audit(db, p.tenant_id, p.subject, "feedback.bulk_updated")
            return {
                "items": db.execute(
                    """SELECT f.*,
                (SELECT count(*) FROM feedback_support s WHERE s.feedback_id=f.id AND s.workspace_id=f.workspace_id) AS support_count,
                EXISTS(SELECT 1 FROM feedback_support s WHERE s.feedback_id=f.id AND s.workspace_id=f.workspace_id AND s.user_id=%s) AS supported_by_me
                FROM feedback f WHERE f.workspace_id=%s AND f.id=ANY(%s)""",
                    (p.subject, p.tenant_id, payload.ids),
                ).fetchall()
            }

    def bulk_opportunities(self, p, payload):
        require_editor(p)
        with self.connection(p) as db:
            rows = self._bulk_rows(db, p, "opportunities", payload.ids)
            for row in rows:
                if payload.status is not None:
                    self._decide_opportunity(
                        db,
                        p,
                        row["id"],
                        OpportunityDecision(
                            status=payload.status,
                            expected_status=payload.expected_statuses[row["id"]],
                        ),
                    )
                if payload.archived is not None:
                    db.execute(
                        "UPDATE opportunities SET archived=%s WHERE id=%s AND workspace_id=%s",
                        (payload.archived, row["id"], p.tenant_id),
                    )
            self._audit(db, p.tenant_id, p.subject, "opportunity.bulk_updated")
            return {
                "items": db.execute(
                    "SELECT * FROM opportunities WHERE workspace_id=%s AND id=ANY(%s)",
                    (p.tenant_id, payload.ids),
                ).fetchall()
            }

    def update_board(self, p, payload):
        require_editor(p)
        with self.connection(p) as db:
            ids = [item.id for item in payload.items]
            rows = self._bulk_rows(db, p, "opportunities", ids)
            if any(row["archived"] for row in rows):
                raise ValueError("Restore archived opportunities before moving them")
            current = {row["id"]: row for row in rows}
            for item in payload.items:
                if current[item.id]["status"] != item.expected_status:
                    raise ValueError(
                        "Status changed. Refresh the board before moving cards."
                    )
                if item.status != item.expected_status:
                    self._decide_opportunity(
                        db,
                        p,
                        item.id,
                        OpportunityDecision(
                            status=item.status, expected_status=item.expected_status
                        ),
                    )
                db.execute(
                    "UPDATE opportunities SET board_order=%s WHERE id=%s AND workspace_id=%s",
                    (item.order, item.id, p.tenant_id),
                )
            self._audit(db, p.tenant_id, p.subject, "opportunity.board_updated")
            return {
                "items": db.execute(
                    "SELECT * FROM opportunities WHERE workspace_id=%s AND id=ANY(%s)",
                    (p.tenant_id, ids),
                ).fetchall()
            }


def require_editor(p):
    if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
        raise PermissionError("Read-only membership")


def register_bulk_routes(app, store, principal_dependency):
    def run(action, p, payload):
        try:
            return action(p, payload)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.patch("/api/v1/feedback/bulk", response_model=dict[str, list[Feedback]])
    def feedback(payload: FeedbackBulk, p: principal_dependency):
        return run(store.bulk_feedback, p, payload)

    @app.patch("/api/v1/opportunities/bulk")
    def opportunities(payload: OpportunityBulk, p: principal_dependency):
        return run(store.bulk_opportunities, p, payload)

    @app.post("/api/v1/opportunities/board")
    def board(payload: BoardUpdate, p: principal_dependency):
        return run(store.update_board, p, payload)
