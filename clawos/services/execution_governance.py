"""Composable enforcement primitives for agent execution governance."""

from __future__ import annotations

import fnmatch
import ipaddress
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse


@dataclass(frozen=True)
class IdentityContext:
    actor_id: str
    workspace_id: str
    roles: tuple[str, ...] = ()
    authenticated: bool = False

    def require(self, *allowed_roles: str) -> None:
        if not self.authenticated:
            raise PermissionError("authenticated identity is required")
        if allowed_roles and not set(self.roles) & set(allowed_roles):
            raise PermissionError("identity does not have a required role")


class NetworkEgressPolicy:
    """Deny private networks and enforce explicit host allow/deny patterns."""

    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        denied_hosts: list[str] | None = None,
        allowed_ports: list[int] | None = None,
    ):
        self.allowed_hosts = tuple(allowed_hosts or ())
        self.denied_hosts = tuple(denied_hosts or ())
        self.allowed_ports = {
            int(port) for port in (allowed_ports or [80, 443])
        }

    def evaluate(self, url: str) -> dict[str, Any]:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        reason = ""
        allowed = parsed.scheme in {"http", "https"} and bool(host)
        if not allowed:
            reason = "only absolute http(s) URLs are allowed"
        if allowed:
            try:
                address = ipaddress.ip_address(host)
                if (
                    address.is_private or address.is_loopback
                    or address.is_link_local or address.is_reserved
                ):
                    allowed = False
                    reason = "private, local, link-local, or reserved networks are denied"
            except ValueError:
                pass
        if allowed and any(fnmatch.fnmatch(host, pattern) for pattern in self.denied_hosts):
            allowed = False
            reason = "host matched deny policy"
        if allowed and self.allowed_hosts and not any(
            fnmatch.fnmatch(host, pattern) for pattern in self.allowed_hosts
        ):
            allowed = False
            reason = "host is not allowlisted"
        if allowed and port not in self.allowed_ports:
            allowed = False
            reason = "port is not allowlisted"
        return {
            "allowed": allowed,
            "decision": "confirm" if allowed else "deny",
            "host": host,
            "port": port,
            "reason": reason or "egress policy passed",
        }


@dataclass
class ExecutionBudget:
    """Monotonic resource accounting with hard limits."""

    max_model_calls: int = 20
    max_tool_calls: int = 100
    max_tokens: int = 200_000
    max_wall_seconds: float = 1800.0
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def consume(
        self, *, model_calls: int = 0, tool_calls: int = 0, tokens: int = 0
    ) -> dict[str, Any]:
        projected = {
            "model_calls": self.model_calls + max(0, int(model_calls)),
            "tool_calls": self.tool_calls + max(0, int(tool_calls)),
            "tokens": self.tokens + max(0, int(tokens)),
            "wall_seconds": time.monotonic() - self.started_at,
        }
        violations = []
        for key, limit in (
            ("model_calls", self.max_model_calls),
            ("tool_calls", self.max_tool_calls),
            ("tokens", self.max_tokens),
            ("wall_seconds", self.max_wall_seconds),
        ):
            if projected[key] > limit:
                violations.append(key)
        if violations:
            raise RuntimeError(
                "execution budget exceeded: " + ", ".join(violations)
            )
        self.model_calls = projected["model_calls"]
        self.tool_calls = projected["tool_calls"]
        self.tokens = projected["tokens"]
        return {**projected, "remaining": {
            "model_calls": self.max_model_calls - self.model_calls,
            "tool_calls": self.max_tool_calls - self.tool_calls,
            "tokens": self.max_tokens - self.tokens,
            "wall_seconds": max(0.0, self.max_wall_seconds - projected["wall_seconds"]),
        }}


class PolicyHookRegistry:
    """Run deterministic lifecycle hooks that may observe, deny, or annotate."""

    EVENTS = {
        "before_context", "after_context", "before_model", "after_model",
        "before_tool", "after_tool", "before_write", "after_write",
        "before_publish", "after_publish", "on_failure",
    }

    def __init__(self):
        self._hooks: dict[str, list[tuple[int, str, Callable]]] = {
            event: [] for event in self.EVENTS
        }

    def register(
        self, event: str, name: str, callback: Callable[[dict[str, Any]], dict[str, Any] | None],
        *, priority: int = 100
    ) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"unsupported hook event: {event}")
        self._hooks[event].append((int(priority), str(name), callback))
        self._hooks[event].sort(key=lambda item: (item[0], item[1]))

    def run(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event not in self.EVENTS:
            raise ValueError(f"unsupported hook event: {event}")
        current = dict(payload or {})
        evidence = []
        for _, name, callback in self._hooks[event]:
            result = callback(dict(current)) or {}
            decision = str(result.get("decision") or "allow")
            evidence.append({
                "hook": name,
                "decision": decision,
                "reason": str(result.get("reason") or ""),
            })
            if decision == "deny":
                return {
                    "allowed": False,
                    "event": event,
                    "payload": current,
                    "evidence": evidence,
                    "denied_by": name,
                }
            current.update(result.get("annotations") or {})
        return {
            "allowed": True,
            "event": event,
            "payload": current,
            "evidence": evidence,
        }


@dataclass
class GovernedExecutionContext:
    """One identity, policy, budget, and hook context for a complete run."""

    identity: IdentityContext
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    hooks: PolicyHookRegistry = field(default_factory=PolicyHookRegistry)
    egress: NetworkEgressPolicy = field(default_factory=NetworkEgressPolicy)

    @classmethod
    def local(
        cls, actor_id: str = "local-user", workspace_id: str = "default"
    ) -> "GovernedExecutionContext":
        return cls(IdentityContext(
            actor_id=actor_id, workspace_id=workspace_id,
            roles=("developer",), authenticated=True,
        ))

    def gate(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.identity.require("developer", "operator", "admin")
        result = self.hooks.run(event, {
            **dict(payload or {}),
            "actor_id": self.identity.actor_id,
            "workspace_id": self.identity.workspace_id,
        })
        if not result["allowed"]:
            raise PermissionError(
                f"{event} denied by {result.get('denied_by') or 'policy'}"
            )
        return result

    def authorize_egress(self, value: Any) -> list[dict[str, Any]]:
        urls: list[str] = []

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for child in item.values():
                    visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
            elif isinstance(item, str) and item.startswith(("http://", "https://")):
                urls.append(item)

        visit(value)
        decisions = [self.egress.evaluate(url) for url in urls]
        denied = [item for item in decisions if not item["allowed"]]
        if denied:
            raise PermissionError(
                "network egress denied: " + ", ".join(
                    item.get("host") or "invalid-url" for item in denied
                )
            )
        return decisions


class CodingAgentReadiness:
    """Evidence-only product gate spanning P0-P2 software capabilities."""

    REQUIRED = {
        "p0": (
            "causal_policy_benchmark",
            "counterfactual_trace_audit",
            "robust_ope",
            "coding_context_kernel",
            "network_egress_policy",
            "production_trace_wiring",
            "signed_review_evidence",
            "evaluator_feedback_provenance",
        ),
        "p1": (
            "structured_patch_loop",
            "syntax_test_review",
            "worktree_isolation",
            "human_confirmed_commit",
            "router_shadow_gate",
            "agentic_action_loop",
            "persistent_lsp",
            "headless_ide_entry",
            "path_scoped_context",
            "recoverable_model_patch_errors",
        ),
        "p2": (
            "trajectory_ranker",
            "offline_policy_sandbox",
            "identity_boundary",
            "resource_budget",
            "lifecycle_hooks",
            "group_disjoint_policy_evaluation",
            "paired_canary_control",
            "unknown_propensity_exclusion",
        ),
    }

    @classmethod
    def report(cls, evidence: dict[str, Any]) -> dict[str, Any]:
        phases = {}
        for phase, requirements in cls.REQUIRED.items():
            checks = {
                name: bool((evidence.get(name) or {}).get("verified"))
                for name in requirements
            }
            phases[phase] = {
                "software_closed": all(checks.values()),
                "checks": checks,
            }
        return {
            "schema": "clawos.coding-agent-readiness.v1",
            "phases": phases,
            "software_p0_p2_closed": all(
                item["software_closed"] for item in phases.values()
            ),
            "production_learning_ready": bool(
                (evidence.get("real_data_thresholds") or {}).get("verified")
            ),
            "online_rl_claimed": False,
            "hardware_validated": bool(
                (evidence.get("target_hardware") or {}).get("verified")
            ),
        }
