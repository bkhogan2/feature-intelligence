"""Owner-configured platform access, independent of customer workspace roles.

No HTTP endpoint can grant platform roles.
The runtime keeps its existing read-only grants on plan configuration tables.
"""

import os
import hashlib
import json

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from app_core.entitlements import FEATURES


def _subjects(name):
    values = frozenset(
        value.strip() for value in os.getenv(name, "").split(",") if value.strip()
    )
    if "*" in values:
        raise RuntimeError(
            f"{name} requires explicit verified subject IDs; wildcards are forbidden"
        )
    return values


@dataclass(frozen=True)
class PlatformAccess:
    owners: frozenset[str]
    admins: frozenset[str]

    @classmethod
    def from_env(cls):
        owners = _subjects("PLATFORM_OWNER_SUBJECTS")
        admins = _subjects("PLATFORM_ADMIN_SUBJECTS")
        if admins and not owners:
            raise RuntimeError(
                "Configure an app owner before granting platform-admin access"
            )
        return cls(owners, admins)

    def role(self, subject):
        if subject in self.owners:
            return "owner"
        if subject in self.admins:
            return "admin"
        return None


def _revision(row):
    return hashlib.sha256(
        json.dumps(
            [row["key"], row["name"], row["active"], sorted(row["features"])],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _public_plan(row):
    return {
        **row,
        "features": sorted(set(row["features"]) & FEATURES.keys()),
        "revision": _revision(row),
    }


CATALOG_SQL = """
    SELECT p.key, p.name, p.active,
           COALESCE(array_agg(a.feature_key ORDER BY a.feature_key)
               FILTER (WHERE a.feature_key IS NOT NULL), ARRAY[]::text[]) AS features
    FROM plans p LEFT JOIN plan_feature_assignments a ON a.plan_key=p.key
    GROUP BY p.key, p.name, p.active ORDER BY p.key
"""


class PlanFeatureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: list[str] = Field(max_length=256)
    revision: str = Field(min_length=64, max_length=64)


class PlanFeatureEditor:
    """Separate credential with assignment and audit privileges only."""

    def __init__(self, dsn):
        self.dsn = dsn
        with psycopg.connect(dsn) as db:
            unsafe = db.execute("""
                SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb
                    OR pg_has_role(current_user, 'app_runtime', 'MEMBER')
                    OR pg_has_role(current_user, 'app_plan_operator', 'MEMBER')
                    OR pg_has_role(current_user, 'app_billing_service', 'MEMBER')
                    OR EXISTS (SELECT 1 FROM pg_namespace
                        WHERE nspname='app_core' AND nspowner=pg_roles.oid)
                FROM pg_roles WHERE rolname=current_user
            """).fetchone()[0]
            if unsafe:
                raise RuntimeError(
                    "PLATFORM_DATABASE_URL must use a dedicated restricted plan editor login"
                )
            db.execute("SET LOCAL ROLE app_plan_editor")

    def update(self, key, change, subject, role):
        requested = set(change.features)
        if requested - FEATURES.keys():
            raise HTTPException(422, "Unknown feature key")
        with psycopg.connect(self.dsn, row_factory=dict_row) as db:
            db.execute("SET LOCAL ROLE app_plan_editor")
            db.execute("SET LOCAL search_path=pg_catalog,app_core")
            # Shared with the operator CLI so saves cannot race configuration changes.
            db.execute("SELECT pg_advisory_xact_lock(83142002)")
            before = next(
                (
                    row
                    for row in db.execute(CATALOG_SQL).fetchall()
                    if row["key"] == key
                ),
                None,
            )
            if before is None:
                raise HTTPException(404, "Plan not found")
            if _revision(before) != change.revision:
                raise HTTPException(
                    409, "This plan changed. Reload the plan before saving again."
                )
            previous = set(before["features"]) & FEATURES.keys()
            if requested != previous:
                # Preserve assignments belonging to newer versions of the application.
                db.execute(
                    "DELETE FROM plan_feature_assignments WHERE plan_key=%s AND feature_key=ANY(%s)",
                    (key, list(FEATURES)),
                )
                for feature in sorted(requested):
                    db.execute(
                        "INSERT INTO plan_feature_assignments(plan_key,feature_key) VALUES (%s,%s)",
                        (key, feature),
                    )
                db.execute(
                    "INSERT INTO plan_configuration_audit(action,details) VALUES (%s,%s)",
                    (
                        "platform.update_features",
                        Jsonb(
                            {
                                "plan": key,
                                "subject": subject,
                                "platform_role": role,
                                "before": sorted(previous),
                                "after": sorted(requested),
                            }
                        ),
                    ),
                )
            after = {
                **before,
                "features": sorted(
                    (set(before["features"]) - FEATURES.keys()) | requested
                ),
            }
            return _public_plan(after)


def register_platform_routes(app, store, identity_dependency, access, entitlements):
    Identity = Annotated[Any, Depends(identity_dependency)]
    dsn = os.getenv("PLATFORM_DATABASE_URL", "").strip()
    editor = PlanFeatureEditor(dsn) if dsn else None

    @app.get("/api/v1/platform/plans")
    def plans(ident: Identity):
        role = access.role(ident.subject)
        if role is None:
            raise HTTPException(403, "Platform administrator access is required")
        # This query uses the existing restricted app_runtime role, not operator credentials.
        with store.connection() as db:
            rows = db.execute(CATALOG_SQL).fetchall()
        return {
            "role": role,
            "can_edit": editor is not None,
            "billing_enabled": entitlements.enabled,
            "features": [
                {"key": key, "description": description}
                for key, description in sorted(FEATURES.items())
            ],
            "plans": [_public_plan(row) for row in rows],
        }

    @app.patch("/api/v1/platform/plans/{plan_key}/features")
    def update_plan(plan_key: str, change: PlanFeatureUpdate, ident: Identity):
        role = access.role(ident.subject)
        if role is None:
            raise HTTPException(403, "Platform administrator access is required")
        if editor is None:
            raise HTTPException(503, "Plan editing is not configured")
        return editor.update(plan_key, change, ident.subject, role)
