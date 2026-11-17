"""In-app updates, clarification, and outcome checks."""

import asyncio
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Query, Request
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from app_core.domain.models import StrictModel, WorkspaceRole
from app_core.task_drafts import structured_draft


EDITORS = {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}


class MessageBody(StrictModel):
    body: str = Field(min_length=1, max_length=4000, pattern=r"^[^\x00]*$")

    @field_validator("body")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a message")
        return value.strip()


class Publication(MessageBody):
    id: UUID
    kind: Literal["update", "clarification"] = "update"
    expected_status: str
    expected_requests: list[UUID] | None = None


class NotificationBatch(StrictModel):
    ids: list[UUID] = Field(min_length=1, max_length=500)
    action: Literal["read", "unread", "archive", "restore"]


class Outcome(StrictModel):
    status: Literal["not_measured", "improved", "partly_improved", "did_not_improve"]
    evidence: str = Field(default="", max_length=2000, pattern=r"^[^\x00]*$")
    expected_revision: int = Field(ge=0)


def require_reviewer(p):
    if p.role not in EDITORS:
        raise HTTPException(403, "Reviewer access is required.")


class SubmitterUpdatesStore:
    def _record_request_decision(self, db, p, feedback_id, previous_status, status):
        """Save the decision and its submitter notification in the same transaction."""
        db.execute(
            "UPDATE feedback SET status=%s WHERE workspace_id=%s AND id=%s",
            (status, p.tenant_id, feedback_id),
        )
        if status == previous_status or status not in {"triaged", "rejected"}:
            return
        body = "Your request was rejected."
        if status == "triaged":
            body = (
                "Your request was approved and linked to an opportunity. "
                "Approval does not schedule the work."
            )
        self._notify_submitter(db, p, feedback_id, "update", body)

    def _notify_submitter(self, db, p, feedback_id, kind, body):
        db.execute(
            """WITH message AS (
                INSERT INTO submitter_messages(
                    publication_id, workspace_id, feedback_id, author_id, kind, body
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, workspace_id, feedback_id
            )
            INSERT INTO update_notifications(message_id, workspace_id, user_id)
            SELECT m.id, m.workspace_id, f.submitted_by
            FROM message m JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id""",
            (uuid4(), p.tenant_id, feedback_id, p.subject, kind, body),
        )

    def _notify_opportunity_status(self, db, p, opportunity_id, status):
        body = {
            "considering": "We’re reconsidering the opportunity linked to your request.",
            "planned": "We’ve planned work on an opportunity linked to your request.",
            "in_progress": "Work is in progress on an opportunity linked to your request.",
            "shipped": "We’ve shipped work on an opportunity linked to your request.",
            "not_pursuing": "We’ve decided not to pursue an opportunity linked to your request.",
        }[status]
        db.execute(
            """WITH messages AS (
                INSERT INTO submitter_messages(
                    publication_id, workspace_id, feedback_id, opportunity_id,
                    author_id, kind, body
                )
                SELECT %s, f.workspace_id, f.id, l.opportunity_id, %s, 'update', %s
                FROM feedback_opportunity_links l
                JOIN feedback f ON f.id=l.feedback_id AND f.workspace_id=l.workspace_id
                WHERE l.workspace_id=%s AND l.opportunity_id=%s AND f.status='triaged'
                RETURNING id, workspace_id, feedback_id
            )
            INSERT INTO update_notifications(message_id, workspace_id, user_id)
            SELECT m.id, m.workspace_id, f.submitted_by
            FROM messages m JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id""",
            (uuid4(), p.subject, body, p.tenant_id, opportunity_id),
        )

    def submitter_messages(self, p, feedback_id=None, offset=0, mine=False):
        with self.connection(p) as db:
            items = db.execute(
                """SELECT m.id,m.feedback_id,m.opportunity_id,m.kind,m.body,m.created_at,
                    f.title AS request_title, f.status AS request_status,
                    n.read_at,n.archived_at,
                    f.submitted_by=%(subject)s AS is_recipient,
                    m.author_id=%(subject)s AS sent_by_you,
                    m.kind='clarification' AND m.id=(
                      SELECT latest.id FROM submitter_messages latest
                      WHERE latest.feedback_id=m.feedback_id AND latest.workspace_id=m.workspace_id
                      AND latest.kind='clarification' ORDER BY latest.created_at DESC,latest.id DESC LIMIT 1
                    ) AS latest_question,
                    r.body AS reply,r.created_at AS replied_at
                FROM submitter_messages m JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
                LEFT JOIN update_notifications n ON n.message_id=m.id AND n.user_id=%(subject)s AND n.workspace_id=m.workspace_id
                LEFT JOIN clarification_replies r ON r.message_id=m.id AND r.workspace_id=m.workspace_id
                WHERE m.workspace_id=%(workspace)s
                 AND (%(feedback)s::uuid IS NULL OR m.feedback_id=%(feedback)s)
                 AND (NOT %(mine)s OR n.message_id IS NOT NULL)
                ORDER BY m.created_at DESC,m.id DESC LIMIT 51 OFFSET %(offset)s""",
                dict(
                    subject=p.subject,
                    workspace=p.tenant_id,
                    feedback=feedback_id,
                    mine=mine,
                    offset=offset,
                ),
            ).fetchall()
        return {"items": items[:50], "has_more": len(items) > 50}

    def unread_updates(self, p):
        with self.connection(p) as db:
            return db.execute("SELECT count(*) AS count FROM update_notifications WHERE workspace_id=%s AND user_id=%s AND read_at IS NULL AND archived_at IS NULL", (p.tenant_id,p.subject)).fetchone()

    def read_update(self, p, message_id):
        with self.connection(p) as db:
            row = db.execute("UPDATE update_notifications SET read_at=coalesce(read_at,now()) WHERE message_id=%s AND workspace_id=%s AND user_id=%s RETURNING message_id", (message_id,p.tenant_id,p.subject)).fetchone()
            if row is None:
                raise HTTPException(404, "Notification not found")
        return {"ok": True}

    def update_notifications(self, p, payload):
        assignments = {
            "read": "read_at=coalesce(read_at,now())",
            "unread": "read_at=NULL",
            "archive": "archived_at=now()",
            "restore": "archived_at=NULL",
        }
        with self.connection(p) as db:
            rows = db.execute(
                f"UPDATE update_notifications SET {assignments[payload.action]} WHERE message_id=ANY(%s) AND workspace_id=%s AND user_id=%s RETURNING message_id",
                (payload.ids, p.tenant_id, p.subject),
            ).fetchall()
        return {"ids": [row["message_id"] for row in rows]}

    def publish_submitter_message(self, p, target, payload, opportunity=False):
        require_reviewer(p)
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6245))",
                (str(payload.id),),
            )
            previous = db.execute(
                """SELECT feedback_id,opportunity_id,kind,body,author_id FROM submitter_messages
                WHERE workspace_id=%s AND publication_id=%s""",
                (p.tenant_id, payload.id),
            ).fetchall()
            if previous:
                if any(
                    row["author_id"] != p.subject
                    or row["kind"] != payload.kind
                    or row["body"] != payload.body
                    or (
                        row["opportunity_id"] != target
                        if opportunity
                        else row["feedback_id"] != target
                        or row["opportunity_id"] is not None
                    )
                    for row in previous
                ):
                    raise HTTPException(
                        409, "This publication already exists. Start a new update."
                    )
                return {"request_count": len(previous)}
            if opportunity:
                if payload.kind != "update":
                    raise HTTPException(422, "Ask for clarification from a request.")
                # Link writers use the same workspace lock. Snapshot the exact audience.
                db.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                    (p.tenant_id,),
                )
                item = db.execute(
                    """SELECT status,archived FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE""",
                    (target, p.tenant_id),
                ).fetchone()
                if item and item["archived"]:
                    raise HTTPException(
                        409, "Restore the opportunity before publishing an update."
                    )
                ids = [
                    row["feedback_id"]
                    for row in db.execute(
                        """SELECT feedback_id FROM feedback_opportunity_links WHERE opportunity_id=%s AND workspace_id=%s""",
                        (target, p.tenant_id),
                    ).fetchall()
                ]
                if payload.expected_requests is None or set(ids) != set(
                    payload.expected_requests
                ):
                    raise HTTPException(
                        409,
                        "Linked requests changed. Refresh and review the audience before publishing.",
                    )
            else:
                item = self._lock_triage_feedback(db, p, target)
                ids = [target]
            if item is None:
                raise HTTPException(
                    404,
                    "Opportunity not found." if opportunity else "Request not found.",
                )
            if item["status"] != payload.expected_status:
                raise HTTPException(
                    409,
                    "Status changed. Refresh and review your message before publishing.",
                )
            if not ids:
                raise HTTPException(409, "Link at least one request before publishing.")
            if payload.kind == "clarification":
                if item["status"] not in {"new", "needs_clarification"}:
                    raise HTTPException(
                        409, "Only requests awaiting review can need clarification."
                    )
                if item[
                    "status"
                ] == "needs_clarification" and self._waiting_for_clarification(
                    db, p, target
                ):
                    raise HTTPException(
                        409, "This request already has a question waiting for a reply."
                    )
                if db.execute(
                    """SELECT 1 FROM request_approvals WHERE workspace_id=%s AND feedback_id=%s
                    AND status IN ('queued','running')""",
                    (p.tenant_id, target),
                ).fetchone():
                    raise HTTPException(
                        409, "Approval is already running. Wait for it to finish."
                    )
                db.execute(
                    "UPDATE feedback SET status='needs_clarification' WHERE workspace_id=%s AND id=%s",
                    (p.tenant_id, target),
                )
            db.execute(
                """INSERT INTO submitter_messages(publication_id,workspace_id,feedback_id,opportunity_id,author_id,kind,body)
                SELECT %s,%s,feedback_id,%s,%s,%s,%s FROM unnest(%s::uuid[]) AS ids(feedback_id)""",
                (
                    payload.id,
                    p.tenant_id,
                    target if opportunity else None,
                    p.subject,
                    payload.kind,
                    payload.body,
                    ids,
                ),
            )
            db.execute("""INSERT INTO update_notifications(message_id,workspace_id,user_id)
                SELECT m.id,m.workspace_id,f.submitted_by FROM submitter_messages m
                JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
                WHERE m.workspace_id=%s AND m.publication_id=%s
                UNION
                SELECT m.id,m.workspace_id,s.user_id FROM submitter_messages m
                JOIN feedback_support s ON s.feedback_id=m.feedback_id AND s.workspace_id=m.workspace_id
                WHERE m.workspace_id=%s AND m.publication_id=%s AND m.kind='update'
                ON CONFLICT DO NOTHING""", (p.tenant_id,payload.id,p.tenant_id,payload.id))
            self._audit(
                db, p.tenant_id, p.subject, f"submitter.{payload.kind}_published"
            )
            return {"request_count": len(ids)}

    def triage_clarifications(self, p, feedback_id):
        with self.connection(p) as db:
            return db.execute(
                """SELECT left(m.body,1000) AS question,left(r.body,2000) AS answer
                FROM submitter_messages m JOIN clarification_replies r
                ON r.message_id=m.id AND r.workspace_id=m.workspace_id
                WHERE m.workspace_id=%s AND m.feedback_id=%s ORDER BY r.created_at DESC LIMIT 5""",
                (p.tenant_id, feedback_id),
            ).fetchall()

    def _waiting_for_clarification(self, db, p, feedback_id):
        item = db.execute(
            """SELECT r.message_id FROM submitter_messages m LEFT JOIN clarification_replies r
               ON r.message_id=m.id AND r.workspace_id=m.workspace_id
               WHERE m.workspace_id=%s AND m.feedback_id=%s AND m.kind='clarification'
               ORDER BY m.created_at DESC,m.id DESC LIMIT 1""",
            (p.tenant_id, feedback_id),
        ).fetchone()
        return item is not None and item["message_id"] is None

    def reply_to_clarification(self, p, message_id, payload):
        with self.connection(p) as db:
            message = db.execute(
                """SELECT f.id FROM submitter_messages m JOIN feedback f
                ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
                WHERE m.id=%s AND m.workspace_id=%s AND m.kind='clarification' AND f.submitted_by=%s""",
                (message_id, p.tenant_id, p.subject),
            ).fetchone()
            if not message:
                raise HTTPException(404, "Question not found.")
            feedback_id = message["id"]
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6242))",
                (str(feedback_id),),
            )
            existing = db.execute(
                "SELECT body FROM clarification_replies WHERE message_id=%s AND workspace_id=%s",
                (message_id, p.tenant_id),
            ).fetchone()
            if existing and existing["body"] == payload.body:
                return {"feedback_id": feedback_id}
            latest = db.execute(
                """SELECT m.id,f.status FROM submitter_messages m JOIN feedback f ON f.id=m.feedback_id AND f.workspace_id=m.workspace_id
                WHERE m.workspace_id=%s AND m.feedback_id=%s AND m.kind='clarification'
                ORDER BY m.created_at DESC,m.id DESC LIMIT 1""",
                (p.tenant_id, feedback_id),
            ).fetchone()
            if (
                existing
                or latest["id"] != message_id
                or latest["status"] != "needs_clarification"
            ):
                raise HTTPException(409, "This question is no longer open.")
            db.execute(
                "INSERT INTO clarification_replies(message_id,workspace_id,author_id,body) VALUES(%s,%s,%s,%s)",
                (message_id, p.tenant_id, p.subject, payload.body),
            )
            updated = db.execute(
                "UPDATE feedback SET status='new' WHERE workspace_id=%s AND id=%s AND status='needs_clarification'",
                (p.tenant_id, feedback_id),
            )
            if not updated.rowcount:
                raise HTTPException(
                    409, "Request status changed. Refresh before replying."
                )
            self._audit(db, p.tenant_id, p.subject, "submitter.clarification_replied")
            return {"feedback_id": feedback_id}

    def update_draft_context(self, p, target, opportunity):
        require_reviewer(p)
        with self.connection(p) as db:
            if opportunity:
                item = db.execute(
                    """SELECT o.name AS title,o.problem AS description,o.status,o.outcome_status,
                    EXISTS(SELECT 1 FROM feedback_opportunity_links l WHERE l.opportunity_id=o.id AND l.workspace_id=o.workspace_id) AS has_recipients
                    FROM opportunities o WHERE o.id=%s AND o.workspace_id=%s AND NOT o.archived""",
                    (target, p.tenant_id),
                ).fetchone()
            else:
                item = db.execute(
                    "SELECT title,description,status FROM feedback WHERE id=%s AND workspace_id=%s",
                    (target, p.tenant_id),
                ).fetchone()
            if not item:
                raise HTTPException(404, "Request or opportunity not found.")
            if opportunity and not item.pop("has_recipients"):
                raise HTTPException(
                    409, "Link at least one request before drafting an update."
                )
            return {
                **item,
                "description": item["description"][:2500],
                "type": "opportunity" if opportunity else "request",
            }

    def save_opportunity_outcome(self, p, opportunity_id, payload):
        require_reviewer(p)
        evidence = payload.evidence.strip()
        if payload.status != "not_measured" and not evidence:
            raise HTTPException(
                422, "Add an evidence link or a short note about what you observed."
            )
        with self.connection(p) as db:
            item = db.execute(
                """UPDATE opportunities SET outcome_status=%s,outcome_evidence=%s,outcome_revision=outcome_revision+1
                WHERE workspace_id=%s AND id=%s AND status='shipped' AND NOT archived AND outcome_revision=%s
                RETURNING outcome_status,outcome_evidence,outcome_revision""",
                (
                    payload.status,
                    evidence,
                    p.tenant_id,
                    opportunity_id,
                    payload.expected_revision,
                ),
            ).fetchone()
            if not item:
                raise HTTPException(
                    409,
                    "The opportunity changed or is not shipped. Refresh before saving.",
                )
            self._audit(db, p.tenant_id, p.subject, "opportunity.outcome_checked")
            return item


def register_submitter_update_routes(app, store, principal, triage):
    slots = asyncio.Semaphore(2)

    @app.get("/api/v1/updates")
    def list_updates(
        p: principal,
        feedback_id: UUID | None = None,
        offset: int = Query(0, ge=0),
        mine: bool = False,
    ):
        return store.submitter_messages(p, feedback_id, offset, mine)

    @app.get("/api/v1/updates/unread")
    def unread_updates(p: principal):
        return store.unread_updates(p)

    @app.post("/api/v1/updates/bulk")
    def bulk_notifications(payload: NotificationBatch, p: principal):
        return store.update_notifications(p, payload)

    @app.post("/api/v1/updates/{message_id}/read")
    def read_update(message_id: UUID, p: principal):
        return store.read_update(p, message_id)

    @app.post("/api/v1/feedback/{target}/updates")
    def publish_request(target: UUID, payload: Publication, p: principal):
        return store.publish_submitter_message(p, target, payload)

    @app.post("/api/v1/opportunities/{target}/updates")
    def publish_opportunity(target: UUID, payload: Publication, p: principal):
        return store.publish_submitter_message(p, target, payload, opportunity=True)

    @app.post("/api/v1/updates/{message_id}/reply")
    def clarification_reply(message_id: UUID, payload: MessageBody, p: principal):
        return store.reply_to_clarification(p, message_id, payload)

    @app.put("/api/v1/opportunities/{opportunity_id}/outcome")
    def save_outcome(opportunity_id: UUID, payload: Outcome, p: principal):
        return store.save_opportunity_outcome(p, opportunity_id, payload)

    async def draft(target, request, p, opportunity):
        context = await run_in_threadpool(
            store.update_draft_context, p, target, opportunity
        )
        if not triage.configured():
            raise HTTPException(
                503, "AI drafting is not configured. You can write the update yourself."
            )
        if slots.locked():
            raise HTTPException(429, "AI drafting is busy. Try again in a moment.")
        async with slots:
            try:
                async with asyncio.timeout(60):
                    result = await structured_draft(
                        "submitter_update", MessageBody, context, triage.policy
                    )
            except Exception:
                raise HTTPException(
                    502,
                    "AI couldn’t draft this update. Try again or write it yourself.",
                ) from None
        await triage.current(request, p)
        return result

    @app.post("/api/v1/feedback/{target}/updates/draft")
    async def draft_request(target: UUID, request: Request, p: principal):
        return await draft(target, request, p, False)

    @app.post("/api/v1/opportunities/{target}/updates/draft")
    async def draft_opportunity(target: UUID, request: Request, p: principal):
        return await draft(target, request, p, True)
