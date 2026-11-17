from datetime import UTC, datetime, timedelta
from uuid import uuid4
from psycopg.types.json import Jsonb
from app_core.domain.models import WorkspaceRole
from app_core.priority_context import PROMPT_VERSION, priority_context


class PriorityStore:
    def save_priority(self, p, oid, decision):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            if not self._save_priority(db, p, oid, decision):
                return None
        return self.opportunity(p, oid)

    def _save_priority(self, db, p, oid, decision):
        row = db.execute(
            "SELECT priority_revision,evidence_revision,priority_analysis,effort,dependencies FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE",
            (oid, p.tenant_id),
        ).fetchone()
        if row is None:
            return None
        if (
            getattr(decision, "expected_evidence_revision", row["evidence_revision"])
            != row["evidence_revision"]
        ):
            raise ValueError(
                "Linked evidence changed. Refresh and review before saving."
            )
        if row["priority_revision"] != decision.expected_revision:
            raise ValueError("Priority changed. Refresh and review before saving.")
        if decision.accepted_analysis_id:
            analysis = row["priority_analysis"] or {}
            if analysis.get("status") != "complete" or analysis.get("id") != str(
                decision.accepted_analysis_id
            ):
                raise ValueError("Review the latest assessment before accepting.")
            if (
                analysis.get("batch_id")
                and analysis.get("based_on_revision") != row["priority_revision"]
            ):
                raise ValueError(
                    "Priority changed since the joint assessment. Reassess before accepting."
                )
            if (
                analysis.get("based_on_evidence_revision", 0)
                != row["evidence_revision"]
            ):
                raise ValueError("Linked evidence changed. Reassess before accepting.")
            if analysis.get("prompt_version") != PROMPT_VERSION:
                raise ValueError(
                    "Reassess with the current product goals and separate impact/confidence before accepting."
                )
            if (
                decision.priority != analysis["result"]["priority"]
                or decision.rationale != analysis["result"]["rationale"]
            ):
                raise ValueError(
                    "Accepted priority must match the assessment; use Edit for changes."
                )
        # Batch confirmations preserve metadata omitted by API callers.
        effort, dependencies = decision.effort, decision.dependencies
        if hasattr(decision, "expected_evidence_revision"):
            if "effort" not in decision.model_fields_set:
                effort = row["effort"]
            if "dependencies" not in decision.model_fields_set:
                dependencies = row["dependencies"]
        db.execute(
            """UPDATE opportunities SET priority=%s,priority_rationale=%s,effort=%s,dependencies=%s,
        priority_revision=priority_revision+1,priority_updated_by=%s,priority_updated_at=now()
        WHERE id=%s AND workspace_id=%s""",
            (
                decision.priority,
                decision.rationale,
                effort,
                dependencies,
                p.subject,
                oid,
                p.tenant_id,
            ),
        )
        self._audit(db, p.tenant_id, p.subject, "opportunity.priority_confirmed")
        return True

    def enqueue_priority_after_link(self, db, p, oid):
        # Same transaction as approval. Repeated confirmations return before this hook.
        opportunity = db.execute(
            "UPDATE opportunities SET evidence_revision=evidence_revision+1 WHERE id=%s AND workspace_id=%s RETURNING evidence_revision",
            (oid, p.tenant_id),
        ).fetchone()
        settings = db.execute(
            "SELECT priority_enabled FROM auto_triage_settings WHERE workspace_id=%s",
            (p.tenant_id,),
        ).fetchone()
        if not settings or not settings["priority_enabled"]:
            return
        queued = db.execute(
            "SELECT id,analysis FROM priority_jobs WHERE opportunity_id=%s AND workspace_id=%s AND status='queued' FOR UPDATE",
            (oid, p.tenant_id),
        ).fetchone()
        analysis = {
            "id": str(queued["id"] if queued else uuid4()),
            "status": "queued",
            "automatic": True,
            "model": "pending",
            "prompt_version": PROMPT_VERSION,
            "product_context": priority_context(),
            "requested_by": p.subject,
            "created_at": datetime.now(UTC).isoformat(),
            "based_on_evidence_revision": opportunity["evidence_revision"],
            "error": "Queued after PM approval. Priority and lifecycle remain unchanged.",
        }
        if queued:
            analysis["created_at"] = queued["analysis"]["created_at"]
            db.execute(
                "UPDATE priority_jobs SET analysis=%s,requested_by=%s WHERE id=%s",
                (Jsonb(analysis), p.subject, queued["id"]),
            )
        else:
            db.execute(
                "INSERT INTO priority_jobs(id,workspace_id,opportunity_id,requested_by,status,automatic,analysis) VALUES(%s,%s,%s,%s,'queued',true,%s)",
                (analysis["id"], p.tenant_id, oid, p.subject, Jsonb(analysis)),
            )
        db.execute(
            "UPDATE opportunities SET priority_analysis=%s WHERE id=%s AND workspace_id=%s",
            (Jsonb(analysis), oid, p.tenant_id),
        )

    def expire_priority(self, db, p):
        rows = db.execute(
            "SELECT id,opportunity_id FROM priority_jobs WHERE workspace_id=%s AND status='running' AND deadline_at<now()",
            (p.tenant_id,),
        ).fetchall()
        for job in rows:
            # Consistent opportunity -> job lock order with confirmation and finish.
            db.execute(
                "SELECT id FROM opportunities WHERE id=%s FOR UPDATE",
                (job["opportunity_id"],),
            ).fetchone()
            row = db.execute(
                "SELECT analysis FROM priority_jobs WHERE id=%s AND status='running' AND deadline_at<now() FOR UPDATE",
                (job["id"],),
            ).fetchone()
            if not row:
                continue
            failed = {
                **row["analysis"],
                "status": "failed",
                "error": "Assessment expired or was interrupted. Retry explicitly when ready.",
                "completed_at": datetime.now(UTC).isoformat(),
            }
            db.execute(
                "UPDATE priority_jobs SET status='failed',analysis=%s WHERE id=%s",
                (Jsonb(failed), job["id"]),
            )
            db.execute(
                "UPDATE opportunities SET priority_analysis=%s WHERE id=%s AND priority_analysis->>'id'=%s",
                (Jsonb(failed), job["opportunity_id"], str(job["id"])),
            )

    def queued_priority(self, p):
        with self.connection(p) as db:
            self.expire_priority(db, p)
            return db.execute(
                "SELECT id,opportunity_id,requested_by FROM priority_jobs WHERE workspace_id=%s AND status='queued' ORDER BY created_at,id LIMIT 5",
                (p.tenant_id,),
            ).fetchall()

    def fail_queued_priority(self, p, oid, job_id):
        with self.connection(p) as db:
            db.execute(
                "SELECT id FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE",
                (oid, p.tenant_id),
            ).fetchone()
            row = db.execute(
                "SELECT analysis FROM priority_jobs WHERE id=%s AND status='queued' FOR UPDATE",
                (job_id,),
            ).fetchone()
            if not row:
                return
            failed = {
                **row["analysis"],
                "status": "failed",
                "error": "Approver no longer has analysis access. An editor may retry explicitly.",
                "completed_at": datetime.now(UTC).isoformat(),
            }
            db.execute(
                "UPDATE priority_jobs SET status='failed',analysis=%s WHERE id=%s",
                (Jsonb(failed), job_id),
            )
            db.execute(
                "UPDATE opportunities SET priority_analysis=%s WHERE id=%s AND priority_analysis->>'id'=%s",
                (Jsonb(failed), oid, str(job_id)),
            )

    def start_priority(self, p, oid, model, timeout, budget=0.05):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            # Shared with triage/settings for allocation across both kinds of work.
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6243))",
                (p.tenant_id,),
            )
            self.expire_priority(db, p)
            row = db.execute(
                "SELECT priority_analysis,evidence_revision FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE",
                (oid, p.tenant_id),
            ).fetchone()
            if row is None:
                return None, False
            active = db.execute(
                "SELECT analysis FROM priority_jobs WHERE opportunity_id=%s AND workspace_id=%s AND status='running'",
                (oid, p.tenant_id),
            ).fetchone()
            if active:
                return active["analysis"], False
            # Compatibility with an already-running pre-migration assessment.
            previous = row["priority_analysis"] or {}
            if previous.get("status") == "running" and datetime.fromisoformat(
                previous["deadline_at"]
            ) > datetime.now(UTC):
                return previous, False
            queued = db.execute(
                "SELECT id,analysis FROM priority_jobs WHERE opportunity_id=%s AND workspace_id=%s AND status='queued' FOR UPDATE",
                (oid, p.tenant_id),
            ).fetchone()
            capacity = db.execute(
                "SELECT count(DISTINCT COALESCE(analysis->>'batch_id',id::text)) AS n FROM priority_jobs WHERE workspace_id=%s AND status='running'",
                (p.tenant_id,),
            ).fetchone()["n"]
            reason = None
            if capacity >= 2:
                reason = (
                    "Workspace assessment capacity is busy. Queued work will resume."
                )
            if queued:
                config = db.execute(
                    "SELECT priority_enabled,daily_budget_usd FROM auto_triage_settings WHERE workspace_id=%s",
                    (p.tenant_id,),
                ).fetchone()
                if not config or not config["priority_enabled"]:
                    reason = (
                        "Automatic priority is paused. Enable it in Settings to resume."
                    )
                from decimal import Decimal

                if (
                    config
                    and self.automatic_allocation_used(db, p) + Decimal(str(budget))
                    > config["daily_budget_usd"]
                ):
                    reason = "Shared automatic daily allocation reached. Queued work resumes after UTC midnight or an explicit allocation change."
                if reason:
                    pending = {**queued["analysis"], "error": reason}
                    db.execute(
                        "UPDATE priority_jobs SET analysis=%s WHERE id=%s",
                        (Jsonb(pending), queued["id"]),
                    )
                    db.execute(
                        "UPDATE opportunities SET priority_analysis=%s WHERE id=%s",
                        (Jsonb(pending), oid),
                    )
                    return pending, False
            elif reason:
                raise ValueError(reason)
            now = datetime.now(UTC)
            analysis = {
                "id": str(queued["id"] if queued else uuid4()),
                "status": "running",
                "automatic": bool(queued),
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "product_context": priority_context(),
                "requested_by": p.subject,
                "created_at": queued["analysis"]["created_at"]
                if queued
                else now.isoformat(),
                "deadline_at": (now + timedelta(seconds=timeout)).isoformat(),
                "based_on_evidence_revision": row["evidence_revision"],
            }
            if queued:
                db.execute(
                    "UPDATE priority_jobs SET status='running',analysis=%s,deadline_at=%s,reserved_budget=%s,budget_reserved_at=now() WHERE id=%s",
                    (Jsonb(analysis), analysis["deadline_at"], budget, queued["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO priority_jobs(id,workspace_id,opportunity_id,requested_by,status,analysis,deadline_at) VALUES(%s,%s,%s,%s,'running',%s,%s)",
                    (
                        analysis["id"],
                        p.tenant_id,
                        oid,
                        p.subject,
                        Jsonb(analysis),
                        analysis["deadline_at"],
                    ),
                )
            db.execute(
                "UPDATE opportunities SET priority_analysis=%s WHERE id=%s AND workspace_id=%s",
                (Jsonb(analysis), oid, p.tenant_id),
            )
            return analysis, True

    def finish_priority(self, p, oid, run, result=None, error=None):
        with self.connection(p) as db:
            row = db.execute(
                "SELECT evidence_revision FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE",
                (oid, p.tenant_id),
            ).fetchone()
            if not row:
                return
            if run.get("based_on_evidence_revision", 0) != row["evidence_revision"]:
                result = None
                error = "Linked evidence changed during assessment. A newer queued assessment will use it; otherwise retry explicitly."
            if datetime.fromisoformat(run["deadline_at"]) < datetime.now(UTC):
                result = None
                error = "Assessment expired. Retry explicitly when ready."
            complete = {
                **run,
                "status": "complete" if result is not None else "failed",
                "result": result,
                "error": error,
                "completed_at": datetime.now(UTC).isoformat(),
            }
            # Ledger keeps reported cost even for late results; never revive expired work.
            db.execute(
                "UPDATE priority_jobs SET cost_usd=COALESCE(%s,cost_usd) WHERE id=%s AND workspace_id=%s",
                (run.get("cost_usd"), run["id"], p.tenant_id),
            )
            changed = db.execute(
                "UPDATE priority_jobs SET status=%s,analysis=%s WHERE id=%s AND workspace_id=%s AND status='running' RETURNING id",
                (complete["status"], Jsonb(complete), run["id"], p.tenant_id),
            ).fetchone()
            if changed:
                db.execute(
                    "UPDATE opportunities SET priority_analysis=%s WHERE id=%s AND workspace_id=%s AND priority_analysis->>'id'=%s AND priority_analysis->>'status'='running'",
                    (Jsonb(complete), oid, p.tenant_id, run["id"]),
                )
