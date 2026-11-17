"""Workspace-scoped triage persistence. No owner connection or RLS bypass."""

from datetime import UTC, datetime
from uuid import uuid4
from psycopg.types.json import Jsonb
from app_core.domain.models import WorkspaceRole
from app_core.priority_context import priority_context


class TriageStore:
    def feedback(self, p, feedback_id):
        with self.connection(p) as db:
            return db.execute(
                "SELECT id,title,description FROM feedback WHERE id=%s AND workspace_id=%s",
                (feedback_id, p.tenant_id),
            ).fetchone()

    def opportunities(
        self, p, query="", limit=30, status="all", include_archived=False, offset=0
    ):
        if status not in {
            "all",
            "considering",
            "planned",
            "in_progress",
            "shipped",
            "not_pursuing",
        }:
            raise ValueError("Invalid opportunity status")
        with self.connection(p) as db:
            rows = db.execute(
                """SELECT o.id,o.name,o.problem,o.status,o.priority,o.priority_rationale,o.archived,o.board_order,o.created_by,o.created_at,
            (SELECT count(*) FROM feedback_opportunity_links l WHERE l.opportunity_id=o.id AND l.workspace_id=o.workspace_id) AS feedback_count
            FROM opportunities o WHERE o.workspace_id=%s
            AND (%s='all' OR o.status=%s) AND (%s OR NOT o.archived)
            AND (strpos(lower(name),lower(%s))>0 OR strpos(lower(problem),lower(%s))>0)
            ORDER BY created_at DESC,id LIMIT %s OFFSET %s""",
                (
                    p.tenant_id,
                    status,
                    status,
                    include_archived,
                    query,
                    query,
                    limit + 1,
                    offset,
                ),
            ).fetchall()
            return {"items": rows[:limit], "has_more": len(rows) > limit}

    def opportunity(self, p, opportunity_id):
        with self.connection(p) as db:
            opportunity = db.execute(
                """SELECT id,name,problem,description_markdown,description_revision,status,archived,board_order,priority,priority_rationale,effort,dependencies,priority_revision,evidence_revision,priority_updated_by,priority_updated_at,priority_analysis,created_by,created_at,outcome_status,outcome_evidence,outcome_revision FROM opportunities
                WHERE id=%s AND workspace_id=%s""",
                (opportunity_id, p.tenant_id),
            ).fetchone()
            if not opportunity:
                return None
            feedback = db.execute(
                """SELECT f.id,f.title,f.description,f.submitted_by,f.created_at,
                (SELECT count(*) FROM feedback_support s WHERE s.feedback_id=f.id AND s.workspace_id=f.workspace_id) AS support_count
                FROM feedback_opportunity_links l JOIN feedback f
                  ON f.id=l.feedback_id AND f.workspace_id=l.workspace_id
                WHERE l.opportunity_id=%s AND l.workspace_id=%s
                ORDER BY f.created_at DESC,f.id""",
                (opportunity_id, p.tenant_id),
            ).fetchall()
            analysis = db.execute(
                """SELECT r.result,r.model,r.prompt_version,r.completed_at,r.requested_by,l.confirmation,l.linked_by,l.linked_at
                FROM feedback_opportunity_links l JOIN triage_runs r
                  ON r.id=l.confirmed_run_id AND r.workspace_id=l.workspace_id
                WHERE l.opportunity_id=%s AND l.workspace_id=%s
                ORDER BY r.completed_at DESC,r.id DESC LIMIT 1""",
                (opportunity_id, p.tenant_id),
            ).fetchone()
            return {
                **opportunity,
                "priority_context": priority_context(),
                "feedback": feedback,
                "analysis": analysis,
                "can_edit": p.role in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR},
                "decisions": db.execute(
                    "SELECT id,actor_id,created_at,previous_status,new_status,note FROM opportunity_decisions WHERE opportunity_id=%s AND workspace_id=%s ORDER BY created_at DESC,id DESC",
                    (opportunity_id, p.tenant_id),
                ).fetchall(),
            }

    def save_opportunity_description(self, p, opportunity_id, payload):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            updated = db.execute(
                """UPDATE opportunities
                SET description_markdown=%s,description_revision=description_revision+1
                WHERE id=%s AND workspace_id=%s AND description_revision=%s
                RETURNING description_markdown,description_revision""",
                (
                    payload.markdown,
                    opportunity_id,
                    p.tenant_id,
                    payload.expected_revision,
                ),
            ).fetchone()
            if updated is None:
                if db.execute(
                    "SELECT 1 FROM opportunities WHERE id=%s AND workspace_id=%s",
                    (opportunity_id, p.tenant_id),
                ).fetchone():
                    raise ValueError(
                        "Description changed. Copy your draft and reopen the opportunity before saving."
                    )
                return None
            self._audit(db, p.tenant_id, p.subject, "opportunity.description_updated")
            return updated

    def decide_opportunity(self, p, opportunity_id, decision):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            if not self._decide_opportunity(db, p, opportunity_id, decision):
                return None
        return self.opportunity(p, opportunity_id)

    def _decide_opportunity(self, db, p, opportunity_id, decision):
        current = db.execute(
            "SELECT status,archived FROM opportunities WHERE id=%s AND workspace_id=%s FOR UPDATE",
            (opportunity_id, p.tenant_id),
        ).fetchone()
        if current is None:
            return None
        if current["status"] != decision.expected_status:
            raise ValueError(
                "Status changed. Refresh and review before saving your decision."
            )
        db.execute(
            "INSERT INTO opportunity_decisions(id,workspace_id,opportunity_id,actor_id,previous_status,new_status,note) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                p.tenant_id,
                opportunity_id,
                p.subject,
                current["status"],
                decision.status,
                decision.note,
            ),
        )
        db.execute(
            "UPDATE opportunities SET status=%s WHERE id=%s AND workspace_id=%s",
            (decision.status, opportunity_id, p.tenant_id),
        )
        if current["status"] != decision.status and not current["archived"]:
            self._notify_opportunity_status(db, p, opportunity_id, decision.status)
        self._audit(db, p.tenant_id, p.subject, "opportunity.decision_recorded")
        return True

    def _expire_triage(self, db, p):
        db.execute(
            """UPDATE triage_runs SET status='failed',error='Analysis expired or was interrupted. Retry when ready.',completed_at=now()
        WHERE workspace_id=%s AND status='running' AND deadline_at<now()""",
            (p.tenant_id,),
        )

    def triage_state(self, p, feedback_id):
        with self.connection(p) as db:
            if not db.execute(
                "SELECT id FROM feedback WHERE id=%s AND workspace_id=%s",
                (feedback_id, p.tenant_id),
            ).fetchone():
                return None
            if p.role in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
                self._expire_triage(db, p)
            run = db.execute(
                "SELECT * FROM triage_runs WHERE feedback_id=%s AND workspace_id=%s ORDER BY created_at DESC,id DESC LIMIT 1",
                (feedback_id, p.tenant_id),
            ).fetchone()
            if (
                run
                and run["status"] == "running"
                and run["deadline_at"] < datetime.now(UTC)
            ):
                run = {
                    **run,
                    "status": "failed",
                    "error": "Analysis expired or was interrupted. An editor can retry.",
                }
            links = db.execute(
                """SELECT o.id,o.name,o.problem,l.confirmation,l.linked_by,l.linked_at,r.result AS original_suggestion FROM feedback_opportunity_links l JOIN opportunities o ON o.id=l.opportunity_id AND o.workspace_id=l.workspace_id LEFT JOIN triage_runs r ON r.id=l.confirmed_run_id AND r.workspace_id=l.workspace_id
                WHERE l.feedback_id=%s AND l.workspace_id=%s ORDER BY l.linked_at,o.id""",
                (feedback_id, p.tenant_id),
            ).fetchall()
            return {
                "run": run,
                "linked_opportunity": links[0] if links else None,
                "linked_opportunities": links,
            }

    def start_triage(
        self, p, feedback_id, model, version, timeout, budget=0.05, approval_id=None
    ):
        with self.connection(p) as db:
            # Same lock order for capture/manual/automatic dispatch, across API processes.
            db.execute("SELECT pg_advisory_xact_lock(83142001)")
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6243))",
                (p.tenant_id,),
            )
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6242))",
                (str(feedback_id),),
            )
            if approval_id:
                job = db.execute(
                    "SELECT * FROM request_approvals WHERE id=%s AND workspace_id=%s FOR UPDATE",
                    (approval_id, p.tenant_id),
                ).fetchone()
                if not job or job["status"] not in ("queued", "running"):
                    return None, False
                if job["run_id"]:
                    return db.execute(
                        "SELECT * FROM triage_runs WHERE id=%s", (job["run_id"],)
                    ).fetchone(), False
            self._expire_triage(db, p)
            if not db.execute(
                "SELECT id FROM feedback WHERE id=%s AND workspace_id=%s",
                (feedback_id, p.tenant_id),
            ).fetchone():
                return None, False
            existing = db.execute(
                "SELECT * FROM triage_runs WHERE feedback_id=%s AND workspace_id=%s AND status IN ('queued','running')",
                (feedback_id, p.tenant_id),
            ).fetchone()
            if approval_id and existing and existing["status"] == "queued":
                db.execute(
                    "UPDATE triage_runs SET status='failed',error='Superseded by explicit approval',completed_at=now() WHERE id=%s",
                    (existing["id"],),
                )
                existing = None
            if approval_id and existing:
                return existing, False
            if existing and existing["status"] == "running":
                return existing, False
            # RLS scopes this running count to the workspace; each service also has a process-wide cap.
            active = db.execute(
                "SELECT count(*) AS n FROM triage_runs WHERE workspace_id=%s AND status='running'",
                (p.tenant_id,),
            ).fetchone()["n"]
            if active >= 2:
                if existing:
                    return existing, False
                raise ValueError(
                    "Workspace analysis capacity is busy. Try again shortly."
                )
            if existing:
                config = db.execute(
                    "SELECT * FROM auto_triage_settings WHERE workspace_id=%s",
                    (p.tenant_id,),
                ).fetchone()
                reason = None
                if not config or not config["enabled"]:
                    reason = "Automatic triage is paused for this workspace. Enable it to resume queued work."
                used = self.automatic_allocation_used(db, p)
                from decimal import Decimal

                if config and used + Decimal(str(budget)) > config["daily_budget_usd"]:
                    reason = "Automatic daily allocation reached. Queued work resumes after UTC midnight or a budget change."
                if reason:
                    row = db.execute(
                        "UPDATE triage_runs SET error=%s WHERE id=%s RETURNING *",
                        (reason, existing["id"]),
                    ).fetchone()
                    return row, False
                row = db.execute(
                    """UPDATE triage_runs SET status='running',model=%s,prompt_version=%s,error=NULL,
                  deadline_at=now()+%s*interval '1 second',reserved_budget=%s,budget_reserved_at=now() WHERE id=%s RETURNING *""",
                    (model, version, timeout, budget, existing["id"]),
                ).fetchone()
            else:
                row = db.execute(
                    """INSERT INTO triage_runs(id,workspace_id,feedback_id,requested_by,status,model,prompt_version,deadline_at)
                  VALUES(%s,%s,%s,%s,'running',%s,%s,now()+%s*interval '1 second') RETURNING *""",
                    (
                        uuid4(),
                        p.tenant_id,
                        feedback_id,
                        p.subject,
                        model,
                        version,
                        timeout,
                    ),
                ).fetchone()
            if approval_id:
                db.execute(
                    "UPDATE request_approvals SET run_id=%s,status='running',updated_at=now() WHERE id=%s",
                    (row["id"], approval_id),
                )
            self._audit(db, p.tenant_id, p.subject, "feedback.analysis_started")
            return row, True

    def finish_triage(self, p, run_id, result=None, error=None, cost=None):
        with self.connection(p) as db:
            row = db.execute(
                """UPDATE triage_runs SET status=%s,result=%s,error=%s,cost_usd=%s,completed_at=now()
            WHERE id=%s AND workspace_id=%s AND status='running' AND deadline_at>now() RETURNING id""",
                (
                    "complete" if result is not None else "failed",
                    Jsonb(result) if result is not None else None,
                    error,
                    cost,
                    run_id,
                    p.tenant_id,
                ),
            ).fetchone()
            if row:
                self._audit(
                    db,
                    p.tenant_id,
                    p.subject,
                    "feedback.analysis_completed"
                    if result is not None
                    else "feedback.analysis_failed",
                )

    def confirm_triage(self, p, feedback_id, run_id, payload=None):
        from app_core.triage_models import TriageConfirmation

        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                (p.tenant_id,),
            )
            return self._confirm_triage(
                db, p, feedback_id, run_id, payload or TriageConfirmation()
            )

    def confirm_triage_batch(self, p, payload):
        from app_core.triage_models import TriageConfirmation

        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise PermissionError("Read-only membership")
        with self.connection(p) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                (p.tenant_id,),
            )
            # Lock every request before any targets, in stable order across batches.
            for item in sorted(payload.items, key=lambda item: str(item.feedback_id)):
                self._lock_triage_feedback(db, p, item.feedback_id)
            db.execute(
                """SELECT id FROM opportunities WHERE workspace_id=%s AND id IN (
                    SELECT (result->>'opportunity_id')::uuid FROM triage_runs
                    WHERE workspace_id=%s AND id=ANY(%s)
                    AND result->>'outcome'='existing_opportunity'
                ) ORDER BY id FOR UPDATE""",
                (p.tenant_id, p.tenant_id, [item.run_id for item in payload.items]),
            ).fetchall()
            results = []
            for item in payload.items:
                result = self._confirm_triage(
                    db, p, item.feedback_id, item.run_id, TriageConfirmation()
                )
                if result is None:
                    # Raise inside the transaction to roll back earlier items too.
                    raise LookupError("One or more selected analyses were not found")
                results.append(
                    {"feedback_id": item.feedback_id, "run_id": item.run_id, **result}
                )
            return {"items": results}

    def _lock_triage_feedback(self, db, p, feedback_id):
        db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,6242))",
            (str(feedback_id),),
        )
        return db.execute(
            "SELECT status FROM feedback WHERE id=%s AND workspace_id=%s FOR UPDATE",
            (feedback_id, p.tenant_id),
        ).fetchone()

    def _confirm_triage(self, db, p, feedback_id, run_id, choice):
        submitted = choice.model_dump(mode="json", exclude_none=True)
        feedback = self._lock_triage_feedback(db, p, feedback_id)
        if feedback is None:
            return None
        if feedback["status"] == "archived":
            raise ValueError("Restore archived requests before confirming")
        if feedback[
            "status"
        ] == "needs_clarification" and self._waiting_for_clarification(
            db, p, feedback_id
        ):
            raise ValueError("Wait for the submitter’s clarification before approving.")
        run = db.execute(
            "SELECT * FROM triage_runs WHERE id=%s AND feedback_id=%s AND workspace_id=%s FOR UPDATE",
            (run_id, feedback_id, p.tenant_id),
        ).fetchone()
        if not run:
            return None
        if (
            run["status"] != "complete"
            or run["result"]["outcome"] == "insufficient_context"
        ):
            raise ValueError("No opportunity suggestion to confirm")
        if (
            feedback["status"] != "triaged"
            and db.execute(
                """SELECT 1 FROM clarification_replies r JOIN submitter_messages m
              ON m.id=r.message_id AND m.workspace_id=r.workspace_id
              WHERE m.workspace_id=%s AND m.feedback_id=%s AND r.created_at>%s LIMIT 1""",
                (p.tenant_id, feedback_id, run["created_at"]),
            ).fetchone()
        ):
            raise ValueError(
                "A clarification reply was added. Review it and run triage again."
            )
        existing_links = db.execute(
            "SELECT opportunity_id,confirmed_run_id,confirmation FROM feedback_opportunity_links WHERE feedback_id=%s AND workspace_id=%s",
            (feedback_id, p.tenant_id),
        ).fetchall()
        linked = next(
            (link for link in existing_links if link["confirmed_run_id"] == run_id),
            existing_links[0] if existing_links else None,
        )
        if linked:
            if linked["confirmed_run_id"] == run_id:
                saved = linked["confirmation"]
                prior = saved["choice"] if saved else {"mode": "accept"}
                if prior == submitted:
                    return {"opportunity_id": linked["opportunity_id"]}
                raise ValueError(
                    "A different decision was already confirmed. Refresh to review it."
                )
            raise ValueError("Request already linked; changing links is not available")
        latest = db.execute(
            "SELECT id FROM triage_runs WHERE feedback_id=%s AND workspace_id=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (feedback_id, p.tenant_id),
        ).fetchone()
        if latest["id"] != run_id:
            raise ValueError("Review the latest analysis before confirming")
        result = run["result"]
        if choice.mode == "edit_new" and result["outcome"] != "new_opportunity":
            raise ValueError("Only a proposed new opportunity can be edited")
        if choice.mode == "existing" or result["outcome"] == "existing_opportunity":
            opportunity_id = (
                choice.opportunity_id
                if choice.mode == "existing"
                else result["opportunity_id"]
            )
            target = db.execute(
                "SELECT id,name,problem FROM opportunities WHERE id=%s AND workspace_id=%s AND NOT archived FOR UPDATE",
                (opportunity_id, p.tenant_id),
            ).fetchone()
            if not target:
                raise ValueError("Opportunity is no longer available in this workspace")
        else:
            target = {
                "name": choice.name
                if choice.mode == "edit_new"
                else result["proposed_name"],
                "problem": choice.problem
                if choice.mode == "edit_new"
                else result["proposed_problem"],
            }
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,6249))",
                (p.tenant_id,),
            )
            duplicate = db.execute(
                """SELECT id,name,problem FROM opportunities WHERE workspace_id=%s AND NOT archived AND
                (lower(regexp_replace(btrim(name),'[^[:alnum:]]+','','g'))=lower(regexp_replace(btrim(%s),'[^[:alnum:]]+','','g'))
                 OR lower(regexp_replace(btrim(problem),'[^[:alnum:]]+','','g'))=lower(regexp_replace(btrim(%s),'[^[:alnum:]]+','','g')))
                ORDER BY created_at,id LIMIT 1 FOR UPDATE""",
                (p.tenant_id, target["name"], target["problem"]),
            ).fetchone()
            opportunity_id = duplicate["id"] if duplicate else uuid4()
            if duplicate:
                target = duplicate
            db.execute(
                "INSERT INTO opportunities(id,workspace_id,name,problem,created_by) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (
                    opportunity_id,
                    p.tenant_id,
                    target["name"],
                    target["problem"],
                    p.subject,
                ),
            )
            if not duplicate:
                self._audit(db, p.tenant_id, p.subject, "opportunity.created")
        db.execute(
            "INSERT INTO feedback_opportunity_links(feedback_id,workspace_id,opportunity_id,confirmed_run_id,linked_by,confirmation) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                feedback_id,
                p.tenant_id,
                opportunity_id,
                run_id,
                p.subject,
                Jsonb(
                    {
                        "choice": submitted,
                        "target": {
                            "id": str(opportunity_id),
                            "name": target["name"],
                            "problem": target["problem"],
                        },
                    }
                ),
            ),
        )
        db.execute(
            "UPDATE triage_runs SET confirmed_opportunity_id=%s WHERE id=%s AND workspace_id=%s",
            (opportunity_id, run_id, p.tenant_id),
        )
        self._record_request_decision(
            db, p, feedback_id, feedback["status"], "triaged"
        )
        self.enqueue_priority_after_link(db, p, opportunity_id)
        self._audit(db, p.tenant_id, p.subject, "feedback.opportunity_linked")
        if choice.mode != "accept":
            self._audit(db, p.tenant_id, p.subject, "feedback.grouping_corrected")
        return {"opportunity_id": opportunity_id}
