"""Human-managed request evidence links, independent of AI availability."""

from uuid import UUID
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, model_validator
from app_core.domain.models import StrictModel, WorkspaceRole


class RequestLinks(StrictModel):
    opportunity_ids: list[UUID] = Field(max_length=50)
    expected_ids: list[UUID] = Field(max_length=50)
    approve: bool = False

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.opportunity_ids)) != len(self.opportunity_ids) or len(
            set(self.expected_ids)
        ) != len(self.expected_ids):
            raise ValueError("Duplicate opportunity IDs")
        if self.approve and not self.opportunity_ids:
            raise ValueError("Link at least one opportunity before approving")
        return self


class RequestStatus(StrictModel):
    status: Literal["new", "rejected"]
    expected_status: str


class RequestLinkStore:
    def set_request_status(self, p, feedback_id, payload):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Read-only membership")
        with self.connection(p) as db:
            request = self._lock_triage_feedback(db, p, feedback_id)
            if not request:
                raise HTTPException(404, "Request not found")
            if request["status"] != payload.expected_status:
                raise HTTPException(409, "Request changed. Refresh before saving.")
            if request["status"] == "archived":
                raise HTTPException(409, "Restore the request before changing status")
            self._record_request_decision(
                db, p, feedback_id, request["status"], payload.status
            )
            db.execute(
                "UPDATE request_approvals SET status='failed',error='Request status changed. Review before retrying.',updated_at=now() WHERE workspace_id=%s AND feedback_id=%s AND status IN ('queued','running')",
                (p.tenant_id, feedback_id),
            )
            self._audit(db, p.tenant_id, p.subject, "feedback.status_updated")
            return {"status": payload.status}

    def set_request_links(self, p, feedback_id, payload):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Read-only membership")
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                (p.tenant_id,),
            )
            request = self._lock_triage_feedback(db, p, feedback_id)
            if not request:
                raise HTTPException(404, "Request not found")
            if (
                payload.approve
                and request["status"] == "needs_clarification"
                and self._waiting_for_clarification(db, p, feedback_id)
            ):
                raise HTTPException(
                    409, "Wait for the submitter’s clarification before approving."
                )
            if request["status"] == "archived":
                raise HTTPException(409, "Restore the request before changing links")
            rows = db.execute(
                "SELECT opportunity_id FROM feedback_opportunity_links WHERE workspace_id=%s AND feedback_id=%s",
                (p.tenant_id, feedback_id),
            ).fetchall()
            before = {r["opportunity_id"] for r in rows}
            after = set(payload.opportunity_ids)
            if before != set(payload.expected_ids):
                raise HTTPException(
                    409, "Opportunity links changed. Refresh before saving."
                )
            if request["status"] == "triaged" and not after:
                raise HTTPException(
                    409, "An approved request must retain at least one opportunity"
                )
            targets = db.execute(
                "SELECT id,archived FROM opportunities WHERE workspace_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                (p.tenant_id, sorted(before | after)),
            ).fetchall()
            if not after.issubset({r["id"] for r in targets}):
                raise HTTPException(404, "Opportunity not found")
            if any(
                r["archived"]
                and r["id"] in after
                and (r["id"] not in before or payload.approve)
                for r in targets
            ):
                raise HTTPException(409, "Choose active opportunities")
            db.execute(
                "DELETE FROM feedback_opportunity_links WHERE workspace_id=%s AND feedback_id=%s AND opportunity_id=ANY(%s)",
                (p.tenant_id, feedback_id, sorted(before - after)),
            )
            for target in sorted(after - before):
                db.execute(
                    "INSERT INTO feedback_opportunity_links(feedback_id,workspace_id,opportunity_id,linked_by) VALUES(%s,%s,%s,%s)",
                    (feedback_id, p.tenant_id, target, p.subject),
                )
            if payload.approve:
                self._record_request_decision(
                    db, p, feedback_id, request["status"], "triaged"
                )
            approved_targets = (
                after
                if payload.approve and request["status"] != "triaged"
                else (after - before if request["status"] == "triaged" else set())
            )
            for target in sorted(approved_targets):
                self.enqueue_priority_after_link(db, p, target)
            for target in sorted((before ^ after) - approved_targets):
                db.execute(
                    "UPDATE opportunities SET evidence_revision=evidence_revision+1 WHERE workspace_id=%s AND id=%s",
                    (p.tenant_id, target),
                )
            self._audit(
                db,
                p.tenant_id,
                p.subject,
                "feedback.links_approved"
                if payload.approve
                else "feedback.links_updated",
            )
            return {
                "opportunity_ids": sorted(after),
                "status": "triaged" if payload.approve else request["status"],
            }
