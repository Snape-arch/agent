"""Unified product contracts for task runs, extensions, safety, and explainability."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from pathlib import Path
from typing import Any

from .execution_governance import PolicyHookRegistry


class TaskRunContract:
    """Canonical state/event contract shared by CLI, IDE, web, and workers."""

    SCHEMA = "clawos.task-run.v2"
    TERMINAL = {"succeeded", "failed", "canceled"}
    TRANSITIONS = {
        "created": {"pending", "running", "canceled"},
        "pending": {"running", "canceled"},
        "pending_retry": {"running", "canceled"},
        "running": {
            "waiting_confirmation", "paused", "cancel_requested",
            "succeeded", "failed", "interrupted",
        },
        "waiting_confirmation": {"running", "canceled", "cancel_requested"},
        "paused": {"running", "canceled"},
        "interrupted": {"running", "pending_retry", "canceled"},
        "cancel_requested": {"canceled", "running"},
    }
    EVENT_TYPES = {
        "run.created", "run.transitioned", "run.progress", "run.approval",
        "run.tool", "run.diff", "run.test", "run.checkpoint",
        "run.context", "run.review", "run.policy", "run.failure",
        "run.completed",
    }

    @classmethod
    def validate_transition(cls, current: str, target: str) -> None:
        current, target = str(current), str(target)
        if target == current:
            return
        if current in cls.TERMINAL:
            raise ValueError(f"terminal task run cannot transition from {current}")
        if target not in cls.TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid task run transition: {current} -> {target}")

    @classmethod
    def envelope(cls, detail: dict[str, Any]) -> dict[str, Any]:
        task = dict(detail.get("task") or detail)
        events = list(detail.get("events") or [])
        checkpoints = [
            event for event in events
            if event.get("event_type") in {"run.checkpoint", "checkpoint_created"}
        ]
        return {
            "schema": cls.SCHEMA,
            "run_id": str(task.get("id") or ""),
            "session_id": str(task.get("session_id") or ""),
            "title": str(task.get("title") or ""),
            "status": str(task.get("status") or "unknown"),
            "source": str(task.get("source") or ""),
            "attempt": int(task.get("attempt") or 1),
            "cancellation_requested": bool(task.get("cancellation_requested")),
            "resume_state": str(task.get("resume_state") or ""),
            "metadata": dict(task.get("metadata") or {}),
            "steps": list(detail.get("steps") or []),
            "events": events,
            "checkpoint_graph": {
                "schema": "clawos.checkpoint-graph.v1",
                "nodes": checkpoints,
                "latest": checkpoints[-1] if checkpoints else None,
            },
            "links": {
                "events": f"/api/agent-product/task-runs/{task.get('id')}/events",
                "stream": f"/api/tasks/stream?session_id={task.get('session_id', '')}",
            },
        }


class AgentProductKernel:
    """Read-only validators and explainers around the executable runtime."""

    PLUGIN_CAPABILITIES = {
        "context.read", "memory.read", "memory.propose", "task.read",
        "task.create", "tool.invoke", "network.egress", "workspace.read",
        "workspace.write", "agent.spawn", "hook.register",
    }

    @classmethod
    def contracts(cls) -> dict[str, Any]:
        hooks = PolicyHookRegistry().describe()
        return {
            "schema": "clawos.agent-product-contracts.v1",
            "task_run": {
                "schema": TaskRunContract.SCHEMA,
                "states": sorted(set(TaskRunContract.TRANSITIONS) | TaskRunContract.TERMINAL),
                "terminal_states": sorted(TaskRunContract.TERMINAL),
                "event_types": sorted(TaskRunContract.EVENT_TYPES),
                "supports": ["stream", "cancel", "resume", "approval", "checkpoint", "replay"],
            },
            "hooks": hooks,
            "multi_agent": {
                "schema": "clawos.agent-graph.v1",
                "isolation": "worktree-per-writing-agent",
                "requires": ["typed_role", "dependencies", "budget", "permissions"],
            },
            "plugins": {
                "schema": "clawos.plugin-manifest.v1",
                "capabilities": sorted(cls.PLUGIN_CAPABILITIES),
                "default": "deny",
            },
            "sandbox": {
                "schema": "clawos.sandbox-plan.v1",
                "application_policy": True,
                "os_enforcement_claimed": False,
            },
            "personalization": {
                "memory_explanation": True,
                "confirmed_enable_disable": True,
                "online_rl_claimed": False,
            },
            "evidence_ledger": {
                "context_snapshots": True,
                "coding_reviews": True,
                "digest_bound": True,
            },
            "education": {
                "mastery_truth_source": "persisted-evidence-only",
                "learner_model": "bkt-fsrs-lite.v1",
                "project_evidence": True,
                "online_rl_claimed": False,
            },
        }

    @staticmethod
    def explain_context(manifest: dict[str, Any]) -> dict[str, Any]:
        sources = []
        for source in manifest.get("sources") or []:
            kind = str(source.get("kind") or "unknown")
            sources.append({
                **source,
                "reason": (
                    "applicable instruction by precedence and path scope"
                    if kind == "instruction"
                    else "ranked repository evidence within the token budget"
                ),
            })
        budget = dict(manifest.get("budget") or {})
        return {
            "schema": "clawos.context-explanation.v1",
            "context_digest": manifest.get("context_digest", ""),
            "objective": manifest.get("objective", ""),
            "budget": budget,
            "selection_policy": {
                "instruction_precedence": (
                    (manifest.get("trust_policy") or {}).get("instruction_precedence") or []
                ),
                "truncated": bool(budget.get("truncated")),
                "source_count": len(sources),
            },
            "sources": sources,
            "diagnostics_count": len(manifest.get("diagnostics") or []),
            "repo_map_digest": (manifest.get("repo_map") or {}).get("digest", ""),
        }

    @staticmethod
    def explain_memory(store: Any, memory_id: int) -> dict[str, Any]:
        memory = store.get_memory(int(memory_id))
        if not memory:
            raise KeyError("memory not found")
        versions = store.list_memory_versions(int(memory_id), limit=20)
        evidence = store.list_memory_evidence(int(memory_id), limit=50)
        return {
            "schema": "clawos.memory-explanation.v1",
            "memory": memory,
            "why_available": {
                "enabled": bool(memory.get("enabled")),
                "confidence": float(memory.get("confidence") or 0),
                "source": memory.get("source") or "unknown",
                "evidence_count": len(evidence),
                "current_version": memory.get("current_version"),
            },
            "versions": versions,
            "evidence": evidence,
            "controls": ["enable", "disable", "review", "inspect_versions"],
        }

    @classmethod
    def validate_plugin(
        cls, manifest: dict[str, Any], granted_capabilities: list[str] | None = None
    ) -> dict[str, Any]:
        required = {"name", "version", "entrypoint", "capabilities"}
        missing = sorted(required - set(manifest))
        name = str(manifest.get("name") or "")
        version = str(manifest.get("version") or "")
        capabilities = set(manifest.get("capabilities") or [])
        unknown = sorted(capabilities - cls.PLUGIN_CAPABILITIES)
        granted = set(granted_capabilities or [])
        ungranted = sorted(capabilities - granted)
        checks = {
            "required_fields": not missing,
            "safe_name": bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", name)),
            "semantic_version": bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version)),
            "known_capabilities": not unknown,
            "explicit_grants": not ungranted,
            "entrypoint_relative": bool(manifest.get("entrypoint"))
            and not Path(str(manifest.get("entrypoint"))).is_absolute()
            and ".." not in Path(str(manifest.get("entrypoint"))).parts,
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "schema": "clawos.plugin-validation.v1",
            "valid": all(checks.values()),
            "checks": checks,
            "missing": missing,
            "unknown_capabilities": unknown,
            "ungranted_capabilities": ungranted,
            "manifest_digest": digest,
        }

    @staticmethod
    def validate_agent_graph(graph: dict[str, Any]) -> dict[str, Any]:
        nodes = list(graph.get("agents") or [])
        ids = [str(node.get("id") or "") for node in nodes]
        known = set(ids)
        errors = []
        if not ids or len(known) != len(ids) or "" in known:
            errors.append("agent ids must be present and unique")
        edges: dict[str, list[str]] = {}
        for node in nodes:
            node_id = str(node.get("id") or "")
            dependencies = [str(item) for item in node.get("depends_on") or []]
            edges[node_id] = dependencies
            if any(item not in known for item in dependencies):
                errors.append(f"{node_id} has an unknown dependency")
            if not node.get("role"):
                errors.append(f"{node_id} requires a typed role")
            if not isinstance(node.get("permissions"), list):
                errors.append(f"{node_id} requires explicit permissions")
            if not isinstance(node.get("budget"), dict):
                errors.append(f"{node_id} requires an explicit budget")
            if "workspace.write" in (node.get("permissions") or []) and not node.get("worktree"):
                errors.append(f"{node_id} requires worktree isolation for writes")
        visiting, visited, execution_order = set(), set(), []

        def visit(node_id: str) -> None:
            if node_id in visiting:
                errors.append("agent dependency graph contains a cycle")
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in edges.get(node_id, []):
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)
            execution_order.append(node_id)

        for node_id in ids:
            visit(node_id)
        return {
            "schema": "clawos.agent-graph-validation.v1",
            "valid": not errors,
            "errors": sorted(set(errors)),
            "agent_count": len(nodes),
            "execution_order": execution_order,
        }

    @staticmethod
    def sandbox_plan(requested: dict[str, Any]) -> dict[str, Any]:
        system = platform.system().lower()
        backend = {
            "windows": "restricted-token-job-object",
            "linux": "namespace-seccomp",
            "darwin": "sandbox-exec-profile",
        }.get(system, "unsupported")
        checks = {
            "workspace_roots_declared": bool(requested.get("workspace_roots")),
            "network_default_deny": requested.get("network_default") == "deny",
            "secrets_brokered": bool(requested.get("secret_refs")) and not bool(
                requested.get("plaintext_secrets")
            ),
            "resource_limits": all(
                int((requested.get("limits") or {}).get(key) or 0) > 0
                for key in ("wall_seconds", "processes", "memory_mb")
            ),
        }
        return {
            "schema": "clawos.sandbox-plan.v1",
            "platform": system,
            "backend": backend,
            "plan_valid": all(checks.values()) and backend != "unsupported",
            "checks": checks,
            "os_enforced": False,
            "truth_boundary": (
                "This validates a least-privilege execution plan. OS isolation "
                "remains unclaimed until a backend probe artifact passes."
            ),
            "environment_policy": "explicit allowlist with secret-shaped values removed",
        }
