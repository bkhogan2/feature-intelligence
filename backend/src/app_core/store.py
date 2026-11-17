"""PostgreSQL adapter for the extracted repository contracts.

Every domain read requires a tenant scope derived from authenticated membership.
Replace this adapter for a different database; keep service contracts and policies.
"""

from __future__ import annotations

import hashlib
import secrets
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app_core.auth.identity import InvalidAuthenticationError, VerifiedIdentity
from app_core.auth.onboarding import InvitationRecord
from app_core.auth.workspace_admin import (
    LastWorkspaceAdminError,
    SelfRemovalError,
    WorkspaceAdminConflictError,
    WorkspaceAdminForbiddenError,
    WorkspaceAdminNotFoundError,
)
from app_core.domain.models import (
    UserPreferences,
    Workspace,
    WorkspaceAccess,
    WorkspaceInvitationAdminSummary,
    WorkspaceMemberSummary,
    WorkspaceRole,
)
from app_core.services.workspace import WorkspaceRecord
from app_core.triage_store import TriageStore
from app_core.priority_store import PriorityStore
from app_core.batch_priority_store import BatchPriorityStore
from app_core.auto_triage_store import AutoTriageStore
from app_core.bulk import BulkStore
from app_core.comments import CommentStore
from app_core.tasks import TaskStore
from app_core.request_links import RequestLinkStore
from app_core.request_approvals import ApprovalStore
from app_core.submitter_updates import SubmitterUpdatesStore


def now_iso():
    return datetime.now(UTC).isoformat()


class PostgresStore(
    TriageStore,
    PriorityStore,
    BatchPriorityStore,
    AutoTriageStore,
    BulkStore,
    CommentStore,
    TaskStore,
    RequestLinkStore,
    ApprovalStore,
    SubmitterUpdatesStore,
):
    def __init__(self, database_url: str):
        if not database_url.strip():
            raise RuntimeError(
                "DATABASE_URL is required; PostgreSQL is the only database backend"
            )
        self.database_url = database_url
        self.pool = ConnectionPool(
            database_url,
            min_size=0,
            max_size=int(os.getenv("DB_POOL_MAX_SIZE", "4")),
            timeout=10,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            open=True,
        )
        try:
            with self.pool.connection() as db:
                role = db.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user OR rolname='app_runtime'"
                ).fetchall()
                owner = db.execute(
                    "SELECT pg_get_userbyid(nspowner)=current_user AS owns_schema FROM pg_namespace WHERE nspname='app_core'"
                ).fetchone()
                if any(r["rolsuper"] or r["rolbypassrls"] for r in role) or (
                    owner and owner["owns_schema"]
                ):
                    raise RuntimeError(
                        "DATABASE_URL must use a non-owner login without superuser or BYPASSRLS privileges"
                    )
            with self.connection() as db:
                version = db.execute(
                    "SELECT max(version) AS version FROM schema_migrations"
                ).fetchone()
                if version["version"] != 25:
                    raise RuntimeError(
                        "Database schema is not current; run the migration command"
                    )
        except Exception:
            self.pool.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.pool.close()

    def workspace_entitlements(self, principal, stripe_enabled=False, livemode=False):
        with self.connection(principal) as db:
            rows = db.execute(
                """WITH effective AS (
                  SELECT plan_key FROM workspace_plans WHERE workspace_id=%(workspace)s
                  UNION ALL
                  SELECT bp.plan_key FROM billing_subscriptions s
                  JOIN billing_prices bp ON bp.price_id=s.price_id AND bp.livemode=s.livemode
                  WHERE %(enabled)s AND s.workspace_id=%(workspace)s AND s.livemode=%(live)s
                  AND s.status IN ('active','trialing') AND s.period_end>now() AND NOT s.collection_paused AND s.payment_confirmed
                  AND NOT EXISTS(SELECT 1 FROM workspace_plans WHERE workspace_id=%(workspace)s)
                  AND (SELECT count(*) FROM billing_subscriptions bs WHERE bs.workspace_id=s.workspace_id
                    AND bs.livemode=s.livemode AND bs.status NOT IN ('canceled','incomplete_expired'))=1
                ) SELECT p.key,a.feature_key FROM effective w
                JOIN plans p ON p.key=w.plan_key AND p.active
                LEFT JOIN plan_feature_assignments a ON a.plan_key=p.key
                """,
                {
                    "workspace": principal.tenant_id,
                    "enabled": stripe_enabled,
                    "live": livemode,
                },
            ).fetchall()
            return (
                rows[0]["key"] if rows else None,
                [row["feature_key"] for row in rows if row["feature_key"]],
            )

    def billing_summary(self, principal, livemode):
        with self.connection(principal) as db:
            manual = db.execute(
                "SELECT plan_key FROM workspace_plans WHERE workspace_id=%s",
                (principal.tenant_id,),
            ).fetchone()
            account = db.execute(
                "SELECT customer_id IS NOT NULL AS exists FROM billing_accounts WHERE workspace_id=%s AND livemode=%s",
                (principal.tenant_id, livemode),
            ).fetchone()
            subscriptions = db.execute(
                """SELECT s.status,s.period_end,s.cancel_at_period_end,s.collection_paused,s.payment_confirmed,s.synced_at,b.plan_key
                FROM billing_subscriptions s LEFT JOIN billing_prices b ON b.price_id=s.price_id AND b.livemode=s.livemode
                WHERE s.workspace_id=%s AND s.livemode=%s ORDER BY s.synced_at DESC,s.subscription_id""",
                (principal.tenant_id, livemode),
            ).fetchall()
            plans = db.execute(
                """SELECT p.key,p.name,b.currency,b.unit_amount,b.interval,b.interval_count
                FROM plans p JOIN billing_prices b ON b.plan_key=p.key
                WHERE p.active AND b.checkout_enabled AND b.livemode=%s ORDER BY b.unit_amount,p.key""",
                (livemode,),
            ).fetchall()
            return {
                "manual_plan": manual["plan_key"] if manual else None,
                "has_customer": bool(account and account["exists"]),
                "subscriptions": subscriptions,
                "plans": plans,
            }

    @contextmanager
    def connection(self, principal=None):
        with self.pool.connection() as db:
            with db.transaction():
                db.execute("SET LOCAL ROLE app_runtime")
                db.execute("SET LOCAL search_path = pg_catalog, app_core")
                # Overwrite transaction context on every pool checkout; never leak it.
                db.execute(
                    "SELECT set_config('app.subject', %s, true), set_config('app.workspace_id', %s, true)",
                    (
                        principal.subject if principal else "",
                        principal.tenant_id if principal else "",
                    ),
                )
                yield db

    @staticmethod
    def _lock_workspace(db, tenant_id):
        db.execute("SELECT id FROM workspaces WHERE id=%s FOR UPDATE", (tenant_id,))

    def provision(
        self,
        email,
        password_hash,
        workspace_slug,
        workspace_name,
        role="admin",
        subject=None,
    ):
        """Operator-only provisioning, never exposed as a public API."""
        with self.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(83142001)")

            user = db.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            uid = user["id"] if user else (subject or str(uuid4()))
            if not user:
                db.execute(
                    "INSERT INTO users VALUES(%s,%s,%s,1)", (uid, email, password_hash)
                )
            elif subject and subject != uid:
                raise ValueError("Email already belongs to a different identity")
            workspace = db.execute(
                "SELECT id FROM workspaces WHERE slug=%s", (workspace_slug,)
            ).fetchone()
            wid = workspace["id"] if workspace else str(uuid4())
            if not workspace:
                db.execute(
                    "INSERT INTO workspaces(id,slug,name) VALUES(%s,%s,%s)",
                    (wid, workspace_slug, workspace_name),
                )
            stamp = now_iso()
            db.execute(
                "INSERT INTO memberships VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,user_id) DO NOTHING",
                (str(uuid4()), wid, uid, role, "active", stamp, stamp),
            )
            return uid

    def user_by_email(self, email):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            return dict(row) if row else None

    def ensure_external_user(self, identity):
        email = identity.email.strip().casefold()
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM users WHERE id=%s", (identity.subject,)
            ).fetchone()
            if row and row["email"] != email:
                raise InvalidAuthenticationError
            if not row:
                try:
                    db.execute(
                        "INSERT INTO users VALUES(%s,%s,NULL,%s)",
                        (
                            identity.subject,
                            email,
                            int(identity.email_verified),
                        ),
                    )
                except psycopg.IntegrityError as error:
                    # Never link identities merely because their email strings match.
                    raise InvalidAuthenticationError from error

    def identity_for_session(self, token):
        with self.connection() as db:
            row = db.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.digest=%s AND s.expires_at>%s",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    datetime.now(UTC).timestamp(),
                ),
            ).fetchone()
            if not row:
                raise InvalidAuthenticationError
            return VerifiedIdentity(
                subject=row["id"],
                email=row["email"],
                email_verified=bool(row["email_verified"]),
            )

    def new_session(self, uid):
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE expires_at<=%s",
                (datetime.now(UTC).timestamp(),),
            )
            db.execute(
                "INSERT INTO sessions VALUES(%s,%s,%s)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    uid,
                    datetime.now(UTC).timestamp() + 28800,
                ),
            )
        return token

    def revoke_session(self, token):
        with self.connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE digest=%s",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def allow_login(self, bucket):
        stamp = datetime.now(UTC).timestamp()
        bucket = hashlib.sha256(bucket.encode()).hexdigest()
        with self.connection() as db:
            db.execute("DELETE FROM login_attempts WHERE started<%s", (stamp - 300,))
            db.execute(
                "INSERT INTO login_attempts VALUES(%s,%s,1) ON CONFLICT(bucket) DO UPDATE SET count=login_attempts.count+1",
                (bucket, stamp),
            )
            return (
                db.execute(
                    "SELECT count FROM login_attempts WHERE bucket=%s", (bucket,)
                ).fetchone()["count"]
                <= 20
            )

    def list_active_global_access(self, subject):
        with self.connection() as db:
            rows = db.execute(
                "SELECT w.*,m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=%s AND m.status='active' AND w.status='active' ORDER BY w.name",
                (subject,),
            ).fetchall()
            return tuple(
                WorkspaceAccess(
                    workspace=Workspace(id=r["id"], display_name=r["name"]),
                    user_id=subject,
                    role=r["role"],
                    workspace_slug=r["slug"],
                    theme_color=r["theme_color"],
                )
                for r in rows
            )

    def get_active_global_access(self, subject, workspace_slug):
        memberships = self.list_active_global_access(subject)
        if workspace_slug is not None:
            memberships = tuple(
                m
                for m in memberships
                if m.workspace_slug == workspace_slug.strip().lower()
            )
        return memberships[0] if len(memberships) == 1 else None

    def get_active_access(self, identity_tenant_id, subject):
        # External provider tenant claims never grant access on their own.
        matches = tuple(
            m
            for m in self.list_active_global_access(subject)
            if m.workspace.id == identity_tenant_id
        )
        return matches[0] if len(matches) == 1 else None

    def resolve_workspace(self, slug):
        with self.connection() as db:
            r = db.execute(
                "SELECT * FROM workspaces WHERE slug=%s AND status='active'", (slug,)
            ).fetchone()
            return (
                WorkspaceRecord(
                    workspace_id=UUID(r["id"]),
                    workspace_slug=r["slug"],
                    identity_tenant_id=r["id"],
                    workspace_name=r["name"],
                    logo_url=None,
                    theme_color=r["theme_color"],
                )
                if r
                else None
            )

    def _admin(self, db, uid, tenant):
        if not db.execute(
            "SELECT 1 FROM memberships m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=%s AND m.workspace_id=%s AND m.role='admin' AND m.status='active' AND w.status='active'",
            (uid, tenant),
        ).fetchone():
            raise WorkspaceAdminForbiddenError

    def _member(self, row, actor):
        return WorkspaceMemberSummary(
            membership_id=row["id"],
            email=row["email"],
            role=row["role"],
            status=row["status"],
            is_current_user=row["user_id"] == actor,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_members(self, actor_uid, tenant_id):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            return tuple(
                self._member(r, actor_uid)
                for r in db.execute(
                    "SELECT m.*,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s ORDER BY m.created_at",
                    (tenant_id,),
                )
            )

    def _invitation(self, row):
        status = row["status"]
        if status == "pending" and row["expires_at"] <= datetime.now(UTC):
            status = "expired"
        return WorkspaceInvitationAdminSummary(
            invitation_id=row["id"],
            invited_email=row["email"],
            role=row["role"],
            status=status,
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            accepted_at=row["accepted_at"],
            revoked_at=row["revoked_at"],
        )

    def list_invitations(self, actor_uid, tenant_id):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            return tuple(
                self._invitation(r)
                for r in db.execute(
                    "SELECT * FROM invitations WHERE workspace_id=%s ORDER BY created_at DESC",
                    (tenant_id,),
                )
            )

    def create_invitation(
        self, *, actor_uid, tenant_id, invited_email, role, token_digest, expires_at
    ):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            if (
                db.execute(
                    "SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s AND u.email=%s",
                    (tenant_id, invited_email),
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM invitations WHERE workspace_id=%s AND email=%s AND status='pending' AND expires_at>%s",
                    (tenant_id, invited_email, now_iso()),
                ).fetchone()
            ):
                raise WorkspaceAdminConflictError
            iid = str(uuid4())
            db.execute(
                "INSERT INTO invitations(id,workspace_id,email,role,token_digest,expires_at,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    iid,
                    tenant_id,
                    invited_email,
                    role,
                    token_digest,
                    expires_at.isoformat(),
                    now_iso(),
                ),
            )
            self._audit(db, tenant_id, actor_uid, "invitation.created")
            return self._invitation(
                db.execute("SELECT * FROM invitations WHERE id=%s", (iid,)).fetchone()
            )

    def revoke_invitation(self, *, actor_uid, tenant_id, invitation_id):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            changed = db.execute(
                "UPDATE invitations SET status='revoked',revoked_at=%s WHERE id=%s AND workspace_id=%s AND status='pending'",
                (now_iso(), str(invitation_id), tenant_id),
            ).rowcount
            if not changed:
                raise WorkspaceAdminNotFoundError
            self._audit(db, tenant_id, actor_uid, "invitation.revoked")
            return self._invitation(
                db.execute(
                    "SELECT * FROM invitations WHERE id=%s AND workspace_id=%s",
                    (str(invitation_id), tenant_id),
                ).fetchone()
            )

    def resolve(self, token_digest, now):
        with self.connection() as db:
            r = db.execute(
                "SELECT i.*,w.name FROM invitations i JOIN workspaces w ON w.id=i.workspace_id WHERE token_digest=%s AND i.status='pending' AND i.expires_at>%s AND w.status='active'",
                (token_digest, now.isoformat()),
            ).fetchone()
            return (
                InvitationRecord(
                    id=UUID(r["id"]),
                    workspace_id=UUID(r["workspace_id"]),
                    identity_tenant_id=r["workspace_id"],
                    workspace_name=r["name"],
                    invited_email=r["email"],
                    role=WorkspaceRole(r["role"]),
                    expires_at=r["expires_at"],
                    token_digest=r["token_digest"],
                )
                if r
                else None
            )

    def accept(
        self, *, invitation, identity, terms_version, privacy_version, accepted_at
    ):
        with self.connection() as db:
            self._lock_workspace(db, str(invitation.workspace_id))

            changed = db.execute(
                "UPDATE invitations SET status='accepted',accepted_by=%s,accepted_at=%s WHERE id=%s AND workspace_id=%s AND token_digest=%s AND status='pending' AND expires_at>%s AND EXISTS(SELECT 1 FROM workspaces WHERE id=%s AND status='active')",
                (
                    identity.subject,
                    accepted_at.isoformat(),
                    str(invitation.id),
                    str(invitation.workspace_id),
                    invitation.token_digest,
                    accepted_at.isoformat(),
                    str(invitation.workspace_id),
                ),
            ).rowcount
            if not changed:
                return False
            stamp = accepted_at.isoformat()
            # Replayed/disabled membership cannot be silently reactivated by a stale invite.
            if db.execute(
                "SELECT 1 FROM memberships WHERE workspace_id=%s AND user_id=%s",
                (str(invitation.workspace_id), identity.subject),
            ).fetchone():
                raise WorkspaceAdminConflictError
            db.execute(
                "INSERT INTO memberships VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    str(uuid4()),
                    str(invitation.workspace_id),
                    identity.subject,
                    invitation.role,
                    "active",
                    stamp,
                    stamp,
                ),
            )
            db.execute(
                "INSERT INTO legal_acceptances VALUES(%s,%s,%s,%s,%s)",
                (
                    str(invitation.id),
                    identity.subject,
                    terms_version,
                    privacy_version,
                    stamp,
                ),
            )
            self._audit(
                db,
                str(invitation.workspace_id),
                identity.subject,
                "invitation.accepted",
            )
            return True

    def update_member(self, *, actor_uid, tenant_id, membership_id, role, status):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            r = db.execute(
                "SELECT m.*,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.id=%s AND m.workspace_id=%s",
                (str(membership_id), tenant_id),
            ).fetchone()
            if not r:
                raise WorkspaceAdminNotFoundError
            role = role or r["role"]
            status = status or r["status"]
            if (
                r["role"] == "admin"
                and r["status"] == "active"
                and (role != "admin" or status != "active")
                and not db.execute(
                    "SELECT 1 FROM memberships WHERE workspace_id=%s AND id<>%s AND role='admin' AND status='active'",
                    (tenant_id, str(membership_id)),
                ).fetchone()
            ):
                raise LastWorkspaceAdminError
            db.execute(
                "UPDATE memberships SET role=%s,status=%s,updated_at=%s WHERE id=%s AND workspace_id=%s",
                (role, status, now_iso(), str(membership_id), tenant_id),
            )
            self._audit(db, tenant_id, actor_uid, "membership.updated")
            return self._member(
                db.execute(
                    "SELECT m.*,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.id=%s AND m.workspace_id=%s",
                    (str(membership_id), tenant_id),
                ).fetchone(),
                actor_uid,
            )

    def remove_member(self, *, actor_uid, tenant_id, membership_id):
        with self.connection() as db:
            self._lock_workspace(db, tenant_id)
            self._admin(db, actor_uid, tenant_id)
            r = db.execute(
                "SELECT * FROM memberships WHERE id=%s AND workspace_id=%s",
                (str(membership_id), tenant_id),
            ).fetchone()
            if not r:
                raise WorkspaceAdminNotFoundError
            if r["user_id"] == actor_uid:
                raise SelfRemovalError
            if (
                r["role"] == "admin"
                and r["status"] == "active"
                and not db.execute(
                    "SELECT 1 FROM memberships WHERE workspace_id=%s AND id<>%s AND role='admin' AND status='active'",
                    (tenant_id, str(membership_id)),
                ).fetchone()
            ):
                raise LastWorkspaceAdminError
            db.execute(
                "DELETE FROM memberships WHERE id=%s AND workspace_id=%s",
                (str(membership_id), tenant_id),
            )
            self._audit(db, tenant_id, actor_uid, "membership.removed")

    def get_preferences(self, subject):
        with self.connection() as db:
            r = db.execute(
                "SELECT payload FROM preferences WHERE user_id=%s", (subject,)
            ).fetchone()
            return (
                UserPreferences.model_validate(r["payload"]) if r else UserPreferences()
            )

    def update_preferences(self, subject, patch):
        with self.connection() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (subject,)
            )

            r = db.execute(
                "SELECT payload FROM preferences WHERE user_id=%s", (subject,)
            ).fetchone()
            current = (
                UserPreferences.model_validate(r["payload"]) if r else UserPreferences()
            )
            result = UserPreferences.model_validate(
                current.model_dump() | patch.model_dump(exclude_none=True)
            )
            db.execute(
                "INSERT INTO preferences VALUES(%s,%s) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload",
                (subject, Jsonb(result.model_dump(mode="json"))),
            )
            return result

    def _audit(self, db, tenant, subject, action):
        db.execute(
            "SELECT set_config('app.subject', %s, true), set_config('app.workspace_id', %s, true)",
            (subject, tenant),
        )
        db.execute(
            "INSERT INTO audit VALUES(%s,%s,%s,%s,%s)",
            (str(uuid4()), tenant, subject, action, now_iso()),
        )

    def list_feedback(
        self, principal, search="", limit=25, offset=0, status="all", feedback_id=None
    ):
        with self.connection(principal) as db:
            # Literal substring search: user input is never a SQL pattern or expression.
            rows = db.execute(
                """SELECT f.*,
                  (SELECT split_part(u.email, '@', 1) FROM users u WHERE u.id=f.submitted_by) AS submitter_name,
                  (SELECT status FROM request_approvals a WHERE a.feedback_id=f.id AND a.workspace_id=f.workspace_id) AS approval_status,
                  (SELECT error FROM request_approvals a WHERE a.feedback_id=f.id AND a.workspace_id=f.workspace_id) AS approval_error,
                  (SELECT count(*) FROM feedback_support s
                   WHERE s.feedback_id=f.id AND s.workspace_id=f.workspace_id) AS support_count,
                  EXISTS(SELECT 1 FROM feedback_support s
                   WHERE s.feedback_id=f.id AND s.workspace_id=f.workspace_id
                   AND s.user_id=current_setting('app.subject',true)) AS supported_by_me
                FROM feedback f WHERE f.workspace_id=%s
                AND (%s='all' OR f.status=%s)
                AND (%s::uuid IS NULL OR f.id=%s::uuid)
                AND (strpos(lower(f.title), lower(%s)) > 0
                     OR strpos(lower(f.description), lower(%s)) > 0)
                ORDER BY f.created_at DESC, f.id DESC LIMIT %s OFFSET %s""",
                (
                    principal.tenant_id,
                    status,
                    status,
                    feedback_id,
                    feedback_id,
                    search,
                    search,
                    limit + 1,
                    offset,
                ),
            ).fetchall()
            return {"items": rows[:limit], "has_more": len(rows) > limit}

    def create_feedback(self, principal, title, description, submission_key=None):
        with self.connection(principal) as db:
            row = db.execute(
                """INSERT INTO feedback(id,workspace_id,title,description,submitted_by,submission_key)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,submitted_by,submission_key) DO NOTHING RETURNING *""",
                (
                    uuid4(),
                    principal.tenant_id,
                    title,
                    description,
                    principal.subject,
                    submission_key,
                ),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT * FROM feedback WHERE workspace_id=%s AND submitted_by=%s AND submission_key=%s",
                    (principal.tenant_id, principal.subject, submission_key),
                ).fetchone()
                if row["title"] != title or row["description"] != description:
                    raise ValueError(
                        "Submission key was already used with different feedback. Start a new submission."
                    )
                return row
            self._notify_submitter(
                db, principal, row["id"], "receipt",
                "Thanks for submitting feedback. We received your request and it’s ready for review.",
            )
            self.enqueue_automatic_triage(db, principal, row["id"])
            self._audit(db, principal.tenant_id, principal.subject, "feedback.created")
            return row

    def set_feedback_support(self, principal, feedback_id, supported):
        with self.connection(principal) as db:
            request = db.execute(
                "SELECT id FROM feedback WHERE id=%s AND workspace_id=%s",
                (feedback_id, principal.tenant_id),
            ).fetchone()
            if not request:
                return None
            # Serialize toggles for this request, including concurrent retries.
            # The unique key remains the final database-level duplicate guard.
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 6241))",
                (str(feedback_id),),
            )
            if supported:
                changed = db.execute(
                    """INSERT INTO feedback_support(feedback_id,workspace_id,user_id)
                    VALUES(%s,%s,%s) ON CONFLICT(feedback_id,user_id) DO NOTHING
                    RETURNING feedback_id""",
                    (feedback_id, principal.tenant_id, principal.subject),
                ).fetchone()
            else:
                changed = db.execute(
                    """DELETE FROM feedback_support WHERE feedback_id=%s
                    AND workspace_id=%s AND user_id=%s RETURNING feedback_id""",
                    (feedback_id, principal.tenant_id, principal.subject),
                ).fetchone()
            if changed:
                self._audit(
                    db,
                    principal.tenant_id,
                    principal.subject,
                    "feedback.supported" if supported else "feedback.support_withdrawn",
                )
            return db.execute(
                """SELECT count(*) AS support_count,
                coalesce(bool_or(user_id=%s),false) AS supported_by_me
                FROM feedback_support WHERE feedback_id=%s AND workspace_id=%s""",
                (principal.subject, feedback_id, principal.tenant_id),
            ).fetchone()

    def scoped_records(self, principal, record_id=None):
        with self.connection(principal) as db:
            query = "SELECT * FROM records WHERE workspace_id=%s"
            args = [principal.tenant_id]
            if record_id:
                query += " AND id=%s"
                args.append(record_id)
            return [
                dict(r) for r in db.execute(query + " ORDER BY created_at DESC", args)
            ]

    def create_record(self, principal, title, payload):
        rid = str(uuid4())
        with self.connection(principal) as db:
            db.execute(
                "INSERT INTO records VALUES(%s,%s,%s,%s,%s)",
                (rid, principal.tenant_id, title, Jsonb(payload), now_iso()),
            )
            self._audit(db, principal.tenant_id, principal.subject, "record.created")
        return self.scoped_records(principal, rid)[0]

    def delete_record(self, principal, record_id):
        with self.connection(principal) as db:
            changed = db.execute(
                "DELETE FROM records WHERE id=%s AND workspace_id=%s",
                (record_id, principal.tenant_id),
            ).rowcount
            if changed:
                self._audit(
                    db, principal.tenant_id, principal.subject, "record.deleted"
                )
            return bool(changed)

    def activity(self, principal):
        with self.connection(principal) as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,actor_id,action,created_at FROM audit WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 100",
                    (principal.tenant_id,),
                )
            ]
