"""Small, capability-aware SDK surface for ClawOS extensions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .agent_product_kernel import AgentProductKernel


@dataclass(frozen=True)
class ExtensionSpec:
    name: str
    kind: str
    handler: Callable[..., Any]
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentSDKRegistry:
    """Register typed extensions only when all capabilities were granted."""

    KINDS = {"agent", "tool", "context_provider", "evaluator", "hook"}

    def __init__(self, granted_capabilities: list[str] | None = None):
        self.granted = set(granted_capabilities or [])
        self._extensions: dict[tuple[str, str], ExtensionSpec] = {}

    def register(self, spec: ExtensionSpec) -> ExtensionSpec:
        if spec.kind not in self.KINDS:
            raise ValueError(f"unsupported extension kind: {spec.kind}")
        if not spec.name or (spec.kind, spec.name) in self._extensions:
            raise ValueError("extension name must be present and unique per kind")
        requested = set(spec.capabilities)
        unknown = requested - AgentProductKernel.PLUGIN_CAPABILITIES
        if unknown:
            raise ValueError("unknown capabilities: " + ", ".join(sorted(unknown)))
        denied = requested - self.granted
        if denied:
            raise PermissionError(
                "extension capabilities were not granted: "
                + ", ".join(sorted(denied))
            )
        self._extensions[(spec.kind, spec.name)] = spec
        return spec

    def resolve(self, kind: str, name: str) -> ExtensionSpec:
        try:
            return self._extensions[(str(kind), str(name))]
        except KeyError as exc:
            raise KeyError(f"extension not registered: {kind}/{name}") from exc

    def describe(self) -> dict[str, Any]:
        return {
            "schema": "clawos.agent-sdk.v1",
            "granted_capabilities": sorted(self.granted),
            "extensions": [
                {
                    "kind": spec.kind,
                    "name": spec.name,
                    "capabilities": list(spec.capabilities),
                    "metadata": spec.metadata,
                }
                for spec in sorted(
                    self._extensions.values(),
                    key=lambda item: (item.kind, item.name),
                )
            ],
        }
