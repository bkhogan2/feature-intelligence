"""Durable human approval intent. The browser can leave after POST succeeds."""

from uuid import uuid4
from fastapi import HTTPException
from app_core.domain.models import StrictModel, WorkspaceRole
from app_core.triage_models import TriageConfirmation


class ApprovalRequest(StrictModel):
    expected_status: str


class ApprovalStore:
    def approval_state(self, p, feedback_id):
        with self.connection(p) as db:
            if not db.execute(
                "SELECT id FROM feedback WHERE id=%s AND workspace_id=%s",
                (feedback_id, p.tenant_id),
            ).fetchone():
                raise HTTPException(404, "Request not found")
            return db.execute(
                "SELECT * FROM request_approvals WHERE feedback_id=%s AND workspace_id=%s",
                (feedback_id, p.tenant_id),
            ).fetchone()

    def request_approval(self, p, feedback_id, expected_status):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Read-only membership")
        with self.connection(p) as db:
            feedback = self._lock_triage_feedback(db, p, feedback_id)
            if not feedback:
                raise HTTPException(404, "Request not found")
            job = db.execute(
                "SELECT * FROM request_approvals WHERE feedback_id=%s AND workspace_id=%s FOR UPDATE",
                (feedback_id, p.tenant_id),
            ).fetchone()
            if job and job["status"] in ("queued", "running"):
                return job
            if feedback["status"] == "triaged":
                return {"status": "complete"}
            if feedback["status"] == "archived":
                raise HTTPException(409, "Restore the request before approving")
            if feedback[
                "status"
            ] == "needs_clarification" and self._waiting_for_clarification(
                db, p, feedback_id
            ):
                raise HTTPException(
                    409, "Wait for the submitter’s clarification before approving."
                )
            if feedback["status"] != expected_status:
                raise HTTPException(409, "Request changed. Refresh before approving.")
            job = db.execute(
                """INSERT INTO request_approvals(feedback_id,workspace_id,id,requested_by,expected_status,status)
                VALUES(%s,%s,%s,%s,%s,'queued') ON CONFLICT(feedback_id) DO UPDATE SET id=excluded.id,requested_by=excluded.requested_by,
                expected_status=excluded.expected_status,status='queued',run_id=NULL,error=NULL,created_at=now(),updated_at=now() RETURNING *""",
                (feedback_id, p.tenant_id, uuid4(), p.subject, expected_status),
            ).fetchone()
            self._audit(db, p.tenant_id, p.subject, "feedback.approval_requested")
            return job

    def pending_approval(self, p):
        with self.connection(p) as db:
            self._expire_triage(db, p)
            # One opportunity decision at a time per workspace. The next AI run
            # sees opportunities committed by the previous approval.
            return db.execute(
                "SELECT * FROM request_approvals WHERE workspace_id=%s AND status IN ('queued','running') ORDER BY created_at,feedback_id LIMIT 1",
                (p.tenant_id,),
            ).fetchone()

    def fail_approval(self, p, job_id, message):
        with self.connection(p) as db:
            db.execute(
                "UPDATE request_approvals SET status='failed',error=%s,updated_at=now() WHERE id=%s AND workspace_id=%s AND status IN ('queued','running')",
                (message, job_id, p.tenant_id),
            )

    def advance_approval(self, p, job):
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                (p.tenant_id,),
            )
            feedback = self._lock_triage_feedback(db, p, job["feedback_id"])
            current = db.execute(
                "SELECT * FROM request_approvals WHERE id=%s AND workspace_id=%s FOR UPDATE",
                (job["id"], p.tenant_id),
            ).fetchone()
            if not current or current["status"] not in ("queued", "running"):
                return True
            if not feedback or feedback["status"] != current["expected_status"]:
                db.execute(
                    "UPDATE request_approvals SET status='failed',error='Request status changed. Review it before retrying.',updated_at=now() WHERE id=%s",
                    (job["id"],),
                )
                return True
            links = db.execute(
                "SELECT opportunity_id FROM feedback_opportunity_links WHERE workspace_id=%s AND feedback_id=%s ORDER BY opportunity_id",
                (p.tenant_id, job["feedback_id"]),
            ).fetchall()
            if links:
                ids = [link["opportunity_id"] for link in links]
                targets = db.execute(
                    "SELECT id,archived FROM opportunities WHERE workspace_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                    (p.tenant_id, ids),
                ).fetchall()
                if len(targets) != len(ids) or any(
                    target["archived"] for target in targets
                ):
                    raise ValueError(
                        "A linked opportunity is archived. Update the links before retrying."
                    )
                self._record_request_decision(
                    db, p, job["feedback_id"], feedback["status"], "triaged"
                )
                for target in ids:
                    self.enqueue_priority_after_link(db, p, target)
            elif current["run_id"]:
                run = db.execute(
                    "SELECT * FROM triage_runs WHERE id=%s AND workspace_id=%s",
                    (current["run_id"], p.tenant_id),
                ).fetchone()
                if run["status"] == "failed":
                    raise ValueError(
                        run["error"] or "AI linking failed. Retry approval."
                    )
                if run["status"] != "complete":
                    return False
                if run["result"]["outcome"] == "insufficient_context":
                    raise ValueError(
                        "More detail is needed. Edit the request or link an opportunity manually, then retry approval."
                    )
                self._confirm_triage(
                    db, p, job["feedback_id"], run["id"], TriageConfirmation()
                )
            else:
                return False
            db.execute(
                "UPDATE request_approvals SET status='complete',error=NULL,updated_at=now() WHERE id=%s",
                (job["id"],),
            )
            self._audit(db, p.tenant_id, p.subject, "feedback.approval_completed")
            return True
