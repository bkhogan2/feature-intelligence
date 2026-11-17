"""Plan policy is independent of membership authorization; never replaces it."""

import os
from fastapi import HTTPException
from app_core.stripe_gateway import boolean

# New capabilities must be implemented and registered by developers, then migrated.
FEATURES = {"records.write": "Create and delete example records"}


class Entitlements:
    def __init__(self, store):
        setting = os.getenv("BILLING_ENABLED", "false").lower()
        if setting not in {"true", "false"}:
            raise RuntimeError("BILLING_ENABLED must be true or false")
        self.enabled = setting == "true"
        self.stripe_enabled = boolean("STRIPE_ENABLED")
        self.livemode = os.getenv("STRIPE_MODE", "test") == "live"
        self.store = store

    def snapshot(self, principal):
        if not self.enabled:
            return {
                "billing_enabled": False,
                "plan": None,
                "features": sorted(FEATURES),
            }
        plan, features = self.store.workspace_entitlements(
            principal, self.stripe_enabled, self.livemode
        )
        return {
            "billing_enabled": True,
            "plan": plan,
            "features": sorted(set(features) & FEATURES.keys()),
        }

    def require(self, principal, feature):
        if feature not in FEATURES:
            raise ValueError(f"Unregistered feature: {feature}")
        if feature not in self.snapshot(principal)["features"]:
            raise HTTPException(
                403, "Your workspace plan does not include this feature"
            )
