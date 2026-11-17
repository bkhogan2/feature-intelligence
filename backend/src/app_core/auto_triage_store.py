"""Durable pending work and automatic-run allocation limits, always under tenant RLS."""

from uuid import uuid4
from app_core.domain.models import WorkspaceRole


class AutoTriageStore:
    def auto_triage_config(self, p):
        with self.connection(p) as db:
            row = db.execute(
                "SELECT enabled,priority_enabled,daily_budget_usd,updated_by,updated_at FROM auto_triage_settings WHERE workspace_id=%s",
                (p.tenant_id,),
            ).fetchone()
            used = self.automatic_allocation_used(db, p)
            return {
                **(
                    row
                    or {
                        "enabled": False,
                        "priority_enabled": False,
                        "daily_budget_usd": 0.25,
                        "updated_by": None,
                        "updated_at": None,
                    }
                ),
                "reserved_today_usd": used,
                "can_edit": p.role in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR},
            }

    def save_auto_triage_config(self, p, payload):
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6243))",
                (p.tenant_id,),
            )
            db.execute(
                """INSERT INTO auto_triage_settings(workspace_id,enabled,daily_budget_usd,updated_by,priority_enabled)
            VALUES(%s,%s,%s,%s,COALESCE(%s,false)) ON CONFLICT(workspace_id) DO UPDATE SET enabled=excluded.enabled,daily_budget_usd=excluded.daily_budget_usd,updated_by=excluded.updated_by,priority_enabled=COALESCE(%s,auto_triage_settings.priority_enabled),updated_at=now()""",
                (
                    p.tenant_id,
                    payload.enabled,
                    payload.daily_budget_usd,
                    p.subject,
                    payload.priority_enabled,
                    payload.priority_enabled,
                ),
            )
            self._audit(
                db, p.tenant_id, p.subject, "triage.automation_settings_changed"
            )
        return self.auto_triage_config(p)

    def enqueue_automatic_triage(self, db, p, feedback_id):
        # Called inside capture's transaction, so feedback and pending work commit together.
        config = db.execute(
            "SELECT enabled FROM auto_triage_settings WHERE workspace_id=%s",
            (p.tenant_id,),
        ).fetchone()
        if config and config["enabled"]:
            db.execute(
                """INSERT INTO triage_runs(id,workspace_id,feedback_id,requested_by,status,model,prompt_version,deadline_at,automatic)
            VALUES(%s,%s,%s,%s,'queued','pending','triage-v1',now()+interval '1 day',true)
            ON CONFLICT(workspace_id,feedback_id) WHERE status IN ('queued','running') DO NOTHING""",
                (uuid4(), p.tenant_id, feedback_id, p.subject),
            )

    def auto_triage_workspaces(self, after=""):
        # Only routing metadata from the pre-existing identity tables; no unscoped evidence reads.
        with self.connection() as db:
            return db.execute(
                """SELECT DISTINCT ON(w.id) w.id,w.name,m.user_id FROM workspaces w JOIN memberships m ON m.workspace_id=w.id
            WHERE w.status='active' AND m.status='active' AND m.role IN ('admin','editor') AND w.id>%s ORDER BY w.id,m.user_id LIMIT 50""",
                (after,),
            ).fetchall()

    def queued_triage(self, p):
        with self.connection(p) as db:
            self._expire_triage(db, p)
            return db.execute(
                "SELECT id,feedback_id,requested_by FROM triage_runs WHERE workspace_id=%s AND status='queued' ORDER BY created_at,id LIMIT 5",
                (p.tenant_id,),
            ).fetchall()

    def automatic_allocation_used(self, db, p):
        return db.execute(
            """SELECT COALESCE(sum(used),0) AS used FROM (
          SELECT GREATEST(reserved_budget,COALESCE(cost_usd,0)) AS used FROM triage_runs
          WHERE workspace_id=%s AND automatic AND budget_reserved_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
          UNION ALL
          SELECT GREATEST(reserved_budget,COALESCE(cost_usd,0)) AS used FROM priority_jobs
          WHERE workspace_id=%s AND automatic AND budget_reserved_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
        ) allocations""",
            (p.tenant_id, p.tenant_id),
        ).fetchone()["used"]
