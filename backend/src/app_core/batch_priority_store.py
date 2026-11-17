"""Joint assessments reuse the priority ledger and explicit confirmation transaction."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from psycopg.types.json import Jsonb
from app_core.domain.models import WorkspaceRole
from app_core.priority_context import PROMPT_VERSION, priority_context


class BatchPriorityStore:
    def start_batch_priority(self, p, ids, model, timeout, budget):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 50:
            raise ValueError("Select between 1 and 50 unique opportunities")
        batch_id = str(uuid4())
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6243))",
                (p.tenant_id,),
            )
            self.expire_priority(db, p)
            rows = db.execute(
                "SELECT * FROM opportunities WHERE workspace_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                (p.tenant_id, ids),
            ).fetchall()
            if len(rows) != len(ids):
                return None
            active = db.execute(
                "SELECT count(DISTINCT COALESCE(analysis->>'batch_id',id::text)) AS n FROM priority_jobs WHERE workspace_id=%s AND status='running'",
                (p.tenant_id,),
            ).fetchone()["n"]
            if active >= 2:
                raise ValueError(
                    "Workspace assessment capacity is busy. Try again shortly."
                )
            busy = db.execute(
                "SELECT id FROM priority_jobs WHERE workspace_id=%s AND opportunity_id=ANY(%s) AND status IN ('running','queued') LIMIT 1",
                (p.tenant_id, ids),
            ).fetchone()
            if busy:
                raise ValueError(
                    "A selected opportunity already has a queued or running assessment. Wait before retrying."
                )
            now = datetime.now(UTC)
            for index, row in enumerate(rows):
                analysis = dict(
                    id=str(uuid4()),
                    batch_id=batch_id,
                    status="running",
                    automatic=False,
                    budget_ceiling_usd=budget,
                    evidence_limit_per_opportunity=10,
                    evidence_description_limit=1500,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    product_context=priority_context(),
                    requested_by=p.subject,
                    created_at=now.isoformat(),
                    deadline_at=(now + timedelta(seconds=timeout)).isoformat(),
                    based_on_revision=row["priority_revision"],
                    based_on_evidence_revision=row["evidence_revision"],
                    batch_snapshot=dict(
                        opportunity_id=str(row["id"]),
                        name=row["name"],
                        current_priority=row["priority"],
                        expected_revision=row["priority_revision"],
                        expected_evidence_revision=row["evidence_revision"],
                        effort=row["effort"],
                        dependencies=row["dependencies"],
                    ),
                )
                db.execute(
                    "INSERT INTO priority_jobs(id,workspace_id,opportunity_id,requested_by,status,analysis,deadline_at,reserved_budget,budget_reserved_at) VALUES(%s,%s,%s,%s,'running',%s,%s,%s,now())",
                    (
                        analysis["id"],
                        p.tenant_id,
                        row["id"],
                        p.subject,
                        Jsonb(analysis),
                        analysis["deadline_at"],
                        budget if index == 0 else 0,
                    ),
                )
                db.execute(
                    "UPDATE opportunities SET priority_analysis=%s WHERE workspace_id=%s AND id=%s",
                    (Jsonb(analysis), p.tenant_id, row["id"]),
                )
            self._audit(
                db,
                p.tenant_id,
                p.subject,
                "opportunity.batch_priority_assessment_requested",
            )
        return self.batch_priority(p, batch_id)

    def batch_priority(self, p, batch_id):
        with self.connection(p) as db:
            if p.role in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
                self.expire_priority(db, p)
            rows = db.execute(
                "SELECT analysis FROM priority_jobs WHERE workspace_id=%s AND analysis->>'batch_id'=%s ORDER BY opportunity_id",
                (p.tenant_id, str(batch_id)),
            ).fetchall()
        if not rows:
            return None
        statuses = {row["analysis"]["status"] for row in rows}
        status = (
            "running"
            if "running" in statuses
            else "failed"
            if "failed" in statuses
            else "complete"
        )
        return dict(
            id=str(batch_id),
            status=status,
            items=[
                dict(**row["analysis"]["batch_snapshot"], analysis=row["analysis"])
                for row in rows
            ],
        )

    def save_batch_priority(self, p, decisions):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        ids = [item.opportunity_id for item in decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("Select each opportunity only once")
        with self.connection(p) as db:
            rows = db.execute(
                "SELECT id FROM opportunities WHERE workspace_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                (p.tenant_id, ids),
            ).fetchall()
            if len(rows) != len(ids):
                return None
            for decision in sorted(
                decisions, key=lambda item: str(item.opportunity_id)
            ):
                self._save_priority(db, p, decision.opportunity_id, decision)
        return {"items": [self.opportunity(p, oid) for oid in ids]}
