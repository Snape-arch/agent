"""Environment-backed secret references with audited access."""

from __future__ import annotations

import os


class SecretManager:
    """Keep secret values outside SQLite and expose only availability metadata."""

    def __init__(self, store):
        self._store = store

    def register(self, name, env_var, purpose="", allowed_tools=None, actor_id="system"):
        if not name or not env_var:
            raise ValueError("name and env_var are required")
        item = self._store.register_secret_ref(
            name, env_var, purpose, allowed_tools or [], created_by=actor_id
        )
        self._store.record_audit_event(
            "secret.register",
            actor_id=actor_id,
            resource_type="secret_ref",
            resource_id=name,
            details={"env_var": env_var, "allowed_tools": allowed_tools or []},
        )
        return self._public(item)

    def resolve(self, name, tool_name="", actor_id="system", session_id=""):
        item = self._store.get_secret_ref(name)
        if not item or not item["enabled"]:
            self._audit(name, tool_name, actor_id, session_id, "deny", "secret reference not found or disabled")
            raise ValueError("secret reference not found or disabled")
        allowed = item.get("allowed_tools", [])
        if allowed and tool_name not in allowed:
            self._audit(name, tool_name, actor_id, session_id, "deny", "tool is not allowed to use secret")
            raise PermissionError("tool is not allowed to use secret")
        value = os.environ.get(item["env_var"], "")
        if not value:
            self._audit(name, tool_name, actor_id, session_id, "deny", "environment secret is not configured")
            raise ValueError("secret is not configured")
        self._audit(name, tool_name, actor_id, session_id, "allow", "secret resolved")
        return value

    def list(self):
        return [self._public(item) for item in self._store.list_secret_refs()]

    def _audit(self, name, tool_name, actor_id, session_id, decision, reason):
        self._store.record_audit_event(
            "secret.resolve",
            decision=decision,
            actor_id=actor_id,
            session_id=session_id,
            resource_type="secret_ref",
            resource_id=name,
            reason=reason,
            details={"tool_name": tool_name},
        )

    @staticmethod
    def _public(item):
        return {
            "name": item["name"],
            "env_var": item["env_var"],
            "purpose": item.get("purpose", ""),
            "allowed_tools": item.get("allowed_tools", []),
            "enabled": bool(item.get("enabled")),
            "configured": bool(os.environ.get(item["env_var"], "")),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
        }
