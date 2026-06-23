from __future__ import annotations

from typing import Any


class SecurityService:
    """Permission policy, grants, secrets, and audit route boundary."""

    def __init__(self, policy: Any, secret_manager: Any, store: Any):
        self.policy = policy
        self.secret_manager = secret_manager
        self.store = store

    def audit(self, action: str = "", decision: str = "", limit: int = 100):
        if not self.store:
            raise RuntimeError("Audit store not initialized")
        return self.store.list_audit_events(action, decision, limit)

    def list_secrets(self):
        if not self.secret_manager:
            raise RuntimeError("Secret Manager not initialized")
        return self.secret_manager.list()

    def register_secret(self, data: dict[str, Any]):
        if not self.secret_manager:
            raise RuntimeError("Secret Manager not initialized")
        return self.secret_manager.register(
            data.get("name", ""),
            data.get("env_var", ""),
            purpose=data.get("purpose", ""),
            allowed_tools=data.get("allowed_tools", []),
            actor_id=data.get("actor_id", "system"),
        )

    def check_policy(self, tool: str, arguments: dict[str, Any]):
        if not self.policy:
            raise RuntimeError("Security Policy not initialized")
        return self.policy.evaluate(str(tool or ""), arguments or {})

    def list_grants(self, include_expired: bool = False):
        if not self.policy:
            raise RuntimeError("Security Policy not initialized")
        return self.policy.list_grants(include_expired)

    def create_grant(self, data: dict[str, Any]):
        if not self.policy:
            raise RuntimeError("Security Policy not initialized")
        grant = self.policy.add_grant(data)
        if self.store:
            self.store.record_audit_event(
                actor_id=str(data.get("created_by") or "system"),
                action="security.grant.create",
                resource_type="security_policy",
                resource_id=str(grant.get("id") or ""),
                decision=str(grant.get("decision") or ""),
                reason=str(grant.get("reason") or ""),
                details=grant,
            )
        return grant

    def revoke_grant(self, grant_id: str):
        if not self.policy:
            raise RuntimeError("Security Policy not initialized")
        revoked = self.policy.revoke_grant(grant_id)
        if self.store:
            self.store.record_audit_event(
                actor_id="system",
                action="security.grant.revoke",
                resource_type="security_policy",
                resource_id=str(grant_id),
                decision="allow" if revoked else "not_found",
                reason="manual permission grant revoked",
                details={"grant_id": grant_id},
            )
        return bool(revoked)
