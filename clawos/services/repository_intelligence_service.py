"""Persistent repository intelligence graph and bounded task slices.

The graph is intentionally repository-wide: retrieval ranks a task slice from a
stable model instead of pretending that the first few matching files are the
repository model. Tree-sitter supplies syntax facts, LSP supplies semantic
evidence, and deterministic resolvers connect files, symbols, tests and build
configuration without requiring a model call.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


GRAPH_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".cs", ".java", ".kt", ".rb", ".php",
    ".json", ".toml", ".yaml", ".yml", ".ini", ".xml", ".md",
}
SPECIAL_FILES = {
    "Dockerfile", "Makefile", "CMakeLists.txt", "go.mod", "go.work",
    "Cargo.toml", "Cargo.lock", "package.json", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock", "pyproject.toml", "requirements.txt",
    "Pipfile", "poetry.lock", "build.gradle", "settings.gradle",
    "pom.xml", "Directory.Build.props", "Directory.Build.targets",
}
TEST_MARKERS = ("/tests/", "/test/", "__tests__", ".spec.", ".test.", "test_")
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]+")

LANGUAGES: dict[str, tuple[str, str]] = {
    ".py": ("tree_sitter_python", "language"),
    ".js": ("tree_sitter_javascript", "language"),
    ".jsx": ("tree_sitter_javascript", "language"),
    ".ts": ("tree_sitter_typescript", "language_typescript"),
    ".tsx": ("tree_sitter_typescript", "language_tsx"),
    ".go": ("tree_sitter_go", "language"),
    ".rs": ("tree_sitter_rust", "language"),
    ".c": ("tree_sitter_c", "language"),
    ".h": ("tree_sitter_c", "language"),
    ".cc": ("tree_sitter_cpp", "language"),
    ".cpp": ("tree_sitter_cpp", "language"),
    ".hpp": ("tree_sitter_cpp", "language"),
    ".cs": ("tree_sitter_c_sharp", "language"),
}
DEFINITION_TYPES = {
    "function_definition": "function", "function_declaration": "function",
    "method_definition": "method", "method_declaration": "method",
    "function_item": "function", "local_function_statement": "function",
    "class_definition": "class", "class_declaration": "class",
    "interface_declaration": "interface", "struct_item": "struct",
    "struct_specifier": "struct", "enum_item": "enum",
    "enum_declaration": "enum", "trait_item": "trait",
    "type_declaration": "type", "namespace_declaration": "namespace",
}
CALL_TYPES = {"call", "call_expression", "invocation_expression"}
IMPORT_TYPES = {
    "import_statement", "import_from_statement", "lexical_declaration",
    "use_declaration", "use_item", "using_directive", "preproc_include",
}
IMPACT_EDGE_TYPES = {
    "imports", "calls", "references", "covers", "inherits_config",
    "depends_on", "entrypoint",
}
CANDIDATE_TEST_EDGE_TYPES = {"may_test", "may_cover"}
CONTEXT_EDGE_CONFIDENCE = 0.60
IMPACT_PATH_CONFIDENCE = 0.60


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return {item.lower() for item in TOKEN_RE.findall(value or "") if len(item) > 1}


def _node_id(kind: str, *parts: object) -> str:
    return f"{kind}:" + ":".join(str(item).replace("\\", "/") for item in parts)


def _edge_row(
    source: str, target: str, edge_type: str, *, evidence_tier: str,
    verification: str, confidence: float, basis: str = "",
    impact: bool = False, **metadata: Any,
) -> dict[str, Any]:
    return {
        "source": source, "target": target, "type": edge_type,
        "evidence": evidence_tier, "evidence_tier": evidence_tier,
        "verification": verification,
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 4),
        "basis": basis, "impact_eligible": bool(impact), **metadata,
    }


class RepositoryIntelligenceService:
    """Build and incrementally cache a layered repository knowledge graph."""

    SCHEMA = "clawos.repository-intelligence.v1"

    def __init__(self, cache_root: str | Path | None = None):
        self.cache_root = Path(cache_root).expanduser().resolve() if cache_root else None
        self._lock = threading.RLock()
        self._parsers: dict[str, Any] = {}

    def build(
        self,
        repo_path: str | Path,
        *,
        semantic_graph: dict[str, Any] | None = None,
        execution_coverage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = self._repo(repo_path)
        files = self._tracked_files(repo)
        cache_path = self._cache_path(repo)
        previous = self._read_cache(cache_path)
        old_facts = dict(previous.get("file_facts") or {})
        facts: dict[str, dict[str, Any]] = {}
        changed: list[str] = []
        hits = 0
        misses = 0
        for rel in files:
            path = repo / rel
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            digest = hashlib.sha256(raw).hexdigest()
            cached = old_facts.get(rel)
            if cached and cached.get("digest") == digest:
                facts[rel] = cached
                hits += 1
                continue
            text = raw.decode("utf-8", errors="replace")
            facts[rel] = self._analyze_file(path, rel, text, digest)
            changed.append(rel)
            misses += 1
        removed = sorted(set(old_facts) - set(facts))
        graph = self._assemble(repo, facts, semantic_graph or {}, execution_coverage or {})
        graph["incremental"] = {
            "cache_enabled": bool(cache_path), "cache_hits": hits,
            "cache_misses": misses, "changed_files": changed,
            "removed_files": removed, "git_head": self._git(repo, "rev-parse", "HEAD").strip(),
        }
        graph["digest"] = _digest({"nodes": graph["nodes"], "edges": graph["edges"]})
        self._write_cache(cache_path, {"schema": self.SCHEMA, "file_facts": facts})
        return graph

    def task_slice(
        self,
        graph: dict[str, Any],
        objective: str,
        *,
        focus_paths: list[str] | None = None,
        max_files: int = 24,
        max_nodes: int = 240,
        depth: int = 2,
    ) -> dict[str, Any]:
        nodes = {row["id"]: row for row in graph.get("nodes") or []}
        edges = graph.get("edges") or []
        objective_tokens = _tokens(objective)
        focus = {str(item).replace("\\", "/").strip("/") for item in focus_paths or []}
        scores: dict[str, float] = defaultdict(float)
        for node_id, node in nodes.items():
            path = str(node.get("path") or "")
            overlap = _tokens(f"{path} {node.get('name', '')}") & objective_tokens
            scores[node_id] += len(overlap) * 12.0
            if path in focus or any(path.startswith(item.rstrip("/") + "/") for item in focus):
                scores[node_id] += 100.0
            if overlap and node.get("kind") in {"entrypoint", "test", "module"}:
                scores[node_id] += 2.0
        seeds = [item for item, score in sorted(scores.items(), key=lambda row: (-row[1], row[0])) if score > 0][:40]
        if not seeds:
            seeds = [row["id"] for row in graph.get("nodes") or [] if row.get("kind") == "entrypoint"][:10]
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for edge in edges:
            if not self._context_edge(edge):
                continue
            adjacency[edge["source"]].append((edge["target"], edge))
            adjacency[edge["target"]].append((edge["source"], edge))
        selected = set(seeds)
        queue = deque((seed, 0) for seed in seeds)
        while queue and len(selected) < max_nodes:
            current, level = queue.popleft()
            if level >= max(1, depth):
                continue
            neighbours = sorted(
                adjacency.get(current, []),
                key=lambda row: (
                    row[1].get("type") not in IMPACT_EDGE_TYPES,
                    -float(row[1].get("confidence") or 0), row[0],
                ),
            )
            for target, _edge in neighbours:
                if target not in nodes or target in selected:
                    continue
                selected.add(target)
                queue.append((target, level + 1))
                if len(selected) >= max_nodes:
                    break
        relevant_nodes = [nodes[item] for item in selected if item in nodes]
        file_scores: dict[str, float] = defaultdict(float)
        for node in relevant_nodes:
            path = str(node.get("path") or "")
            if path and node.get("kind") not in {"module", "layer"}:
                structural = 5.0 if node.get("kind") in {"symbol", "lsp_symbol"} else 2.0 if node.get("kind") in {"source", "test"} else 0.5
                file_scores[path] += scores.get(node["id"], 0.0) + structural
        for edge in edges:
            if edge.get("type") not in IMPACT_EDGE_TYPES:
                continue
            if not self._context_edge(edge):
                continue
            if edge.get("source") not in selected or edge.get("target") not in selected:
                continue
            for endpoint in (edge.get("source"), edge.get("target")):
                path = str(nodes.get(str(endpoint), {}).get("path") or "")
                if path:
                    file_scores[path] += 3.0 * float(edge.get("confidence") or 0)
        selected_files = [row[0] for row in sorted(file_scores.items(), key=lambda row: (-row[1], row[0]))[:max_files]]
        selected_set = set(selected_files)
        selected_ids = {row["id"] for row in relevant_nodes if not row.get("path") or row.get("path") in selected_set}
        compact_nodes = [row for row in relevant_nodes if row["id"] in selected_ids]
        compact_edges = [row for row in edges if row["source"] in selected_ids and row["target"] in selected_ids]
        source_map = graph.get("repo_map") or {}
        layered_map: dict[str, Any] = {}
        for key, value in source_map.items():
            if not isinstance(value, list):
                layered_map[key] = value
                continue
            if key == "modules":
                selected_modules = {item.split("/", 1)[0] if "/" in item else "root" for item in selected_set}
                relevant = [item for item in value if item in selected_modules]
            elif key == "dependencies":
                relevant = value[:24]
            else:
                relevant = [item for item in value if item in selected_set]
            if key in {"entrypoints", "build_systems", "configuration", "ci"}:
                relevant = list(dict.fromkeys(relevant + value[:12]))
            layered_map[key] = {"count": len(value), "relevant": relevant[:24]}
        return {
            "schema": "clawos.task-context-slice.v1", "objective": objective,
            "seed_nodes": seeds, "selected_files": selected_files,
            "nodes": compact_nodes[:max_nodes], "edges": compact_edges[:max_nodes * 3],
            "layered_repo_map": layered_map,
            "evidence_policy": {
                "minimum_context_confidence": CONTEXT_EDGE_CONFIDENCE,
                "inferred_test_edges_select_context": False,
                "broad_configuration_edges_select_context": False,
                "covers_requires": "digest-bound execution context",
            },
            "bounded": True, "digest": _digest([objective, selected_files, compact_edges]),
        }

    def impact_analysis(
        self,
        graph: dict[str, Any],
        changed_paths: list[str],
        *,
        depth: int = 3,
    ) -> dict[str, Any]:
        nodes = {row["id"]: row for row in graph.get("nodes") or []}
        normalized = {str(item).replace("\\", "/").strip("/") for item in changed_paths}
        seeds = {node_id for node_id, node in nodes.items() if node.get("path") in normalized}
        reverse: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        candidate_reverse: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for edge in graph.get("edges") or []:
            if edge.get("type") in IMPACT_EDGE_TYPES and self._context_edge(edge):
                reverse[edge["target"]].append((edge["source"], edge))
            elif edge.get("type") in CANDIDATE_TEST_EDGE_TYPES:
                candidate_reverse[edge["target"]].append((edge["source"], edge))
        impacted: dict[str, dict[str, Any]] = {}
        queue = deque((seed, 0, [], 1.0) for seed in seeds)
        best_confidence = {seed: 1.0 for seed in seeds}
        while queue:
            current, level, path_edges, path_confidence = queue.popleft()
            if level >= max(1, depth):
                continue
            for consumer, edge in reverse.get(current, []):
                cumulative_confidence = path_confidence * float(edge.get("confidence") or 0)
                if cumulative_confidence < IMPACT_PATH_CONFIDENCE:
                    continue
                if cumulative_confidence <= best_confidence.get(consumer, -1.0):
                    continue
                best_confidence[consumer] = cumulative_confidence
                node = nodes.get(consumer, {})
                edge_fact = {
                    "type": edge.get("type"), "evidence_tier": edge.get("evidence_tier"),
                    "verification": edge.get("verification"), "confidence": edge.get("confidence"),
                }
                trail = path_edges + [edge_fact]
                impacted[consumer] = {
                    "id": consumer, "kind": node.get("kind"),
                    "path": node.get("path"), "name": node.get("name"),
                    "distance": level + 1, "via": trail,
                    "verification": "confirmed" if all(
                        item.get("verification") in {"confirmed", "verified"} for item in trail
                    ) else "inferred",
                    "confidence": round(cumulative_confidence, 4),
                }
                queue.append((consumer, level + 1, trail, cumulative_confidence))
        rows = sorted(impacted.values(), key=lambda row: (row["distance"], str(row.get("path")), row["id"]))
        impacted_files = sorted({
            str(row["path"]) for row in rows
            if row.get("path") and row.get("path") not in normalized
            and not self._is_test(str(row.get("path") or ""))
        })
        confirmed_impacted = sorted({
            str(row["path"]) for row in rows
            if row.get("path") and row.get("verification") == "confirmed" and row.get("path") not in normalized
            and not self._is_test(str(row.get("path") or ""))
        })
        inferred_impacted = sorted(set(impacted_files) - set(confirmed_impacted))
        verified_test_paths = {
            str(row["path"]) for row in rows
            if (row.get("kind") == "test" or self._is_test(str(row.get("path") or "")))
            and row.get("verification") == "confirmed"
            and any(item.get("type") == "covers" and item.get("verification") == "verified" for item in row.get("via") or [])
        }
        verified_test_paths.update(
            str(nodes.get(str(edge.get("source")), {}).get("path"))
            for edge in graph.get("edges") or []
            if edge.get("type") == "covers"
            and edge.get("verification") == "verified"
            and nodes.get(str(edge.get("target")), {}).get("path") in normalized
            and self._is_test(str(nodes.get(str(edge.get("source")), {}).get("path") or ""))
        )
        verified_tests = sorted(path for path in verified_test_paths if path and path != "None")
        candidate_ids: set[str] = set()
        candidate_targets = set(seeds)
        for current in seeds:
            candidate_targets.update(consumer for consumer, _edge in reverse.get(current, []))
        for current in candidate_targets:
            candidate_ids.update(consumer for consumer, _edge in candidate_reverse.get(current, []))
        candidate_tests = sorted({
            str(nodes[item].get("path")) for item in candidate_ids if item in nodes
            and self._is_test(str(nodes[item].get("path") or ""))
        })
        coverage_gap = bool(candidate_tests) and not bool(verified_tests)
        risk = "unknown" if coverage_gap else "high" if len(impacted_files) > 12 else "medium" if len(impacted_files) > 4 else "low"
        return {
            "schema": "clawos.repository-impact.v1", "changed_paths": sorted(normalized),
            "impacted_files": impacted_files, "confirmed_impacted_files": confirmed_impacted,
            "inferred_impacted_files": inferred_impacted,
            "tests": verified_tests, "verified_tests": verified_tests,
            "candidate_tests": sorted(set(candidate_tests) - set(verified_tests)),
            "coverage_gap": coverage_gap,
            "evidence_policy": {
                "confirmed": ["lsp", "execution"],
                "inferred": ["syntax", "metadata"],
                "tests_alias": "verified_tests",
                "minimum_cumulative_impact_confidence": IMPACT_PATH_CONFIDENCE,
            },
            "consumers": rows[:500], "risk": risk, "depth": depth,
        }

    def _assemble(
        self, repo: Path, facts: dict[str, dict[str, Any]], semantic_graph: dict[str, Any],
        execution_coverage: dict[str, Any],
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(row: dict[str, Any]) -> None:
            nodes[row["id"]] = {**nodes.get(row["id"], {}), **row}

        def add_edge(
            source: str, target: str, edge_type: str, evidence: str = "metadata",
            *, verification: str = "declared", confidence: float = 1.0,
            basis: str = "", impact: bool = False, **metadata: Any,
        ) -> None:
            if source in nodes and target in nodes and source != target:
                edges[(source, target, edge_type)] = _edge_row(
                    source, target, edge_type, evidence_tier=evidence,
                    verification=verification, confidence=confidence,
                    basis=basis, impact=impact, **metadata,
                )

        root_id = _node_id("repository", repo.name)
        add_node({"id": root_id, "kind": "repository", "name": repo.name})
        layers: dict[str, str] = {}
        modules: dict[str, str] = {}
        path_to_id: dict[str, str] = {}
        symbol_by_name: dict[str, list[str]] = defaultdict(list)
        symbol_by_file_name: dict[tuple[str, str], str] = {}
        for rel, fact in facts.items():
            layer = fact["layer"]
            layer_id = layers.setdefault(layer, _node_id("layer", layer))
            add_node({"id": layer_id, "kind": "layer", "name": layer})
            add_edge(root_id, layer_id, "contains")
            module = fact["module"]
            module_id = modules.setdefault(module, _node_id("module", module))
            add_node({"id": module_id, "kind": "module", "name": module, "path": fact["module_path"]})
            add_edge(layer_id, module_id, "contains")
            file_kind = "test" if fact["is_test"] else fact["kind"]
            file_id = _node_id("file", rel)
            path_to_id[rel] = file_id
            add_node({
                "id": file_id, "kind": file_kind, "name": Path(rel).name,
                "path": rel, "language": fact.get("language"),
                "parser": fact.get("parser"), "digest": fact.get("digest"),
            })
            add_edge(module_id, file_id, "contains")
            for symbol in fact.get("symbols") or []:
                symbol_id = _node_id("symbol", rel, symbol["name"], symbol["line"])
                add_node({
                    "id": symbol_id, "kind": "symbol", "name": symbol["name"],
                    "symbol_kind": symbol["kind"], "path": rel,
                    "line": symbol["line"], "end_line": symbol.get("end_line", symbol["line"]),
                    "parser": fact.get("parser"),
                })
                add_edge(
                    file_id, symbol_id, "defines", "syntax",
                    verification="observed", confidence=0.98,
                    basis=fact.get("parser", "fallback"),
                )
                symbol_by_name[symbol["name"]].append(symbol_id)
                symbol_by_file_name[(rel, symbol["name"])] = symbol_id
        resolver = self._path_resolver(path_to_id)
        for rel, fact in facts.items():
            file_id = path_to_id[rel]
            for dependency in fact.get("imports") or []:
                target_path = self._resolve_import(rel, dependency, resolver)
                if target_path:
                    add_edge(
                        file_id, path_to_id[target_path], "imports", "syntax",
                        verification="inferred", confidence=0.75,
                        basis=fact.get("parser", "fallback"),
                        impact=not fact["is_test"], test_candidate=bool(fact["is_test"]),
                    )
                    if fact["is_test"] and not facts[target_path]["is_test"]:
                        add_edge(
                            file_id, path_to_id[target_path], "may_test", "syntax",
                            verification="inferred", confidence=0.5,
                            basis="test imports source; execution not observed",
                        )
            for call in fact.get("calls") or []:
                candidates = symbol_by_name.get(call["name"], [])
                target = next((item for item in candidates if nodes[item].get("path") == rel), None)
                resolution = "same_file" if target else ""
                if target is None and len(candidates) == 1:
                    target = candidates[0]
                    resolution = "unique_repository_name"
                source = symbol_by_file_name.get((rel, call.get("container", "")), file_id)
                if target:
                    call_confidence = 0.7 if resolution == "same_file" else 0.45
                    add_edge(
                        source, target, "calls", "syntax",
                        verification="inferred", confidence=call_confidence,
                        basis="name-resolved syntax call", impact=True,
                        resolution=resolution,
                    )
                    if fact["is_test"] and nodes[target].get("path") != rel:
                        add_edge(
                            file_id, target, "may_cover", "syntax",
                            verification="inferred", confidence=0.45,
                            basis="test contains a name-resolved call; execution not observed",
                        )
            if fact.get("entrypoint"):
                entry_id = _node_id("entrypoint", rel)
                add_node({"id": entry_id, "kind": "entrypoint", "name": rel, "path": rel})
                add_edge(entry_id, file_id, "entrypoint")
            for inherited in fact.get("config_extends") or []:
                target_path = self._resolve_relative(rel, inherited, path_to_id)
                if target_path:
                    add_edge(
                        file_id, path_to_id[target_path], "inherits_config", "metadata",
                        verification="declared", confidence=0.95,
                        basis="explicit extends path", impact=True,
                    )
            for dependency in fact.get("packages") or []:
                dep_id = _node_id("dependency", dependency)
                add_node({"id": dep_id, "kind": "dependency", "name": dependency})
                add_edge(file_id, dep_id, "depends_on")
        for rel, fact in facts.items():
            source_id = path_to_id[rel]
            scope = fact.get("module") or "root"
            if fact["kind"] in {"build", "config"}:
                nodes[source_id]["scope_hint"] = scope
                nodes[source_id]["scope_verification"] = "unresolved"
            elif fact["kind"] == "ci":
                nodes[source_id]["scope_hint"] = scope
                nodes[source_id]["scope_verification"] = "unresolved"
        self._merge_lsp(nodes, edges, semantic_graph)
        coverage_status = self._merge_execution_coverage(
            repo, facts, nodes, edges, execution_coverage
        )
        node_rows = sorted(nodes.values(), key=lambda row: row["id"])
        edge_rows = sorted(edges.values(), key=lambda row: (row["source"], row["target"], row["type"]))
        repo_map = self._layered_map(facts, node_rows, edge_rows)
        evidence_summary = self._evidence_summary(edge_rows)
        return {
            "schema": self.SCHEMA, "repo": str(repo), "nodes": node_rows,
            "edges": edge_rows, "repo_map": repo_map,
            "schema_version": 2, "evidence_summary": evidence_summary,
            "execution_coverage": coverage_status,
            "metrics": {
                "files": len(facts), "nodes": len(node_rows), "edges": len(edge_rows),
                "symbols": sum(1 for row in node_rows if row["kind"] == "symbol"),
                "tree_sitter_files": sum(1 for row in facts.values() if row.get("parser") == "tree-sitter"),
                "lsp_available": bool(semantic_graph),
                "verified_coverage_edges": evidence_summary["verified_coverage_edges"],
            },
        }

    @staticmethod
    def _context_edge(edge: dict[str, Any]) -> bool:
        return bool(
            edge.get("impact_eligible")
            and (
                edge.get("verification") in {"confirmed", "verified"}
                or float(edge.get("confidence") or 0) >= CONTEXT_EDGE_CONFIDENCE
            )
        )

    @staticmethod
    def _evidence_summary(edges: list[dict[str, Any]]) -> dict[str, Any]:
        tiers: dict[str, int] = defaultdict(int)
        verification: dict[str, int] = defaultdict(int)
        for edge in edges:
            tiers[str(edge.get("evidence_tier") or "unknown")] += 1
            verification[str(edge.get("verification") or "unknown")] += 1
        return {
            "edge_counts_by_tier": dict(sorted(tiers.items())),
            "edge_counts_by_verification": dict(sorted(verification.items())),
            "verified_coverage_edges": sum(
                edge.get("type") == "covers"
                and edge.get("evidence_tier") == "execution"
                and edge.get("verification") == "verified"
                for edge in edges
            ),
            "inferred_edges": verification.get("inferred", 0),
            "truth_boundary": (
                "Syntax edges are inferred, LSP edges are confirmed semantic observations, "
                "and covers is reserved for digest-bound execution contexts."
            ),
        }

    def bind_coverage_py_report(
        self, repo_path: str | Path, report: dict[str, Any], *, run_id: str,
        command: list[str] | None = None, tests_passed: bool,
    ) -> dict[str, Any]:
        """Bind coverage.py JSON to current Git/file identities before graph ingestion."""
        repo = self._repo(repo_path)
        if not run_id.strip():
            raise ValueError("run_id is required")
        meta = report.get("meta") or {}
        if not isinstance(report.get("files"), dict) or not str(meta.get("version") or ""):
            raise ValueError("a coverage.py JSON report with meta.version and files is required")
        if meta.get("show_contexts") is not True:
            raise ValueError("coverage.py report must be generated with per-test contexts")
        rows = []
        for raw_path, raw in (report.get("files") or {}).items():
            candidate = Path(str(raw_path))
            path = candidate if candidate.is_absolute() else repo / candidate
            try:
                resolved = path.resolve()
                rel = resolved.relative_to(repo).as_posix()
            except (OSError, ValueError):
                continue
            if not resolved.is_file():
                continue
            contexts = {
                str(line): [str(item) for item in values if str(item).strip()]
                for line, values in (raw.get("contexts") or {}).items()
                if isinstance(values, list)
            }
            rows.append({
                "path": rel, "digest": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                "covered_lines": [int(item) for item in raw.get("executed_lines") or [] if str(item).isdigit()],
                "contexts": contexts,
            })
        return {
            "schema": "clawos.execution-coverage.v1",
            "producer": "coverage.py-json", "producer_version": str(meta.get("version")),
            "run_id": run_id.strip(),
            "command": list(command or []), "tests_passed": tests_passed is True,
            "git_head": self._git(repo, "rev-parse", "HEAD").strip(),
            "coverage_report_digest": _digest(report), "files": rows,
        }

    def _merge_execution_coverage(
        self, repo: Path, facts: dict[str, dict[str, Any]],
        nodes: dict[str, dict[str, Any]],
        edges: dict[tuple[str, str, str], dict[str, Any]],
        coverage: dict[str, Any],
    ) -> dict[str, Any]:
        if not coverage:
            return {
                "status": "absent", "verified": False, "accepted_files": [],
                "rejected_files": [], "verified_edges": 0,
            }
        run_id = str(coverage.get("run_id") or "").strip()
        current_head = self._git(repo, "rev-parse", "HEAD").strip()
        valid_contract = bool(
            coverage.get("schema") == "clawos.execution-coverage.v1"
            and coverage.get("tests_passed") is True
            and run_id
            and str(coverage.get("coverage_report_digest") or "")
            and str(coverage.get("git_head") or "").strip() == current_head
        )
        coverage_files = coverage.get("files") or []
        if not valid_contract:
            return {
                "status": "rejected_contract", "verified": False,
                "accepted_files": [],
                "rejected_files": sorted({
                    str(item.get("path") or "") for item in coverage_files if item.get("path")
                }),
                "verified_edges": 0,
                "reason": "coverage requires a bound report digest, passed tests, run_id and current git_head",
            }
        run_node = _node_id("coverage_run", run_id)
        nodes[run_node] = {
            "id": run_node, "kind": "coverage_run", "name": run_id,
            "command": list(coverage.get("command") or []), "git_head": current_head,
            "evidence_tier": "execution", "verification": "verified",
        }
        file_nodes = {
            str(row.get("path")): node_id for node_id, row in nodes.items()
            if node_id.startswith("file:") and row.get("path")
        }
        symbols_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in nodes.values():
            if row.get("kind") == "symbol" and row.get("path"):
                symbols_by_path[str(row["path"])].append(row)
        accepted: list[str] = []
        rejected: list[str] = []
        verified_edges = 0
        for item in coverage_files:
            rel = str(item.get("path") or "").replace("\\", "/").strip("/")
            fact = facts.get(rel)
            if not fact or str(item.get("digest") or "") != str(fact.get("digest") or ""):
                if rel:
                    rejected.append(rel)
                continue
            accepted.append(rel)
            file_id = file_nodes.get(rel)
            if not file_id:
                continue
            edges[(run_node, file_id, "executes")] = _edge_row(
                run_node, file_id, "executes", evidence_tier="execution",
                verification="verified", confidence=1.0,
                basis="digest-bound runtime coverage file", run_id=run_id,
                impact=False,
            )
            contexts = item.get("contexts") or {}
            for raw_line, raw_contexts in contexts.items():
                try:
                    line = max(1, int(raw_line))
                except (TypeError, ValueError):
                    continue
                targets = [
                    row for row in symbols_by_path.get(rel, [])
                    if int(row.get("line") or 1) <= line <= int(row.get("end_line") or row.get("line") or 1)
                ]
                target = max(targets, key=lambda row: int(row.get("line") or 1))["id"] if targets else file_id
                values = raw_contexts if isinstance(raw_contexts, list) else []
                for raw_context in values:
                    test_path = str(raw_context or "").split("::", 1)[0].replace("\\", "/").strip("/")
                    if test_path not in facts or not facts[test_path].get("is_test"):
                        continue
                    test_id = file_nodes.get(test_path)
                    if not test_id:
                        continue
                    edges[(test_id, target, "covers")] = _edge_row(
                        test_id, target, "covers", evidence_tier="execution",
                        verification="verified", confidence=1.0,
                        basis="digest-bound executed line with test context",
                        run_id=run_id, source_line=line,
                        test_context=str(raw_context), impact=True,
                    )
                    verified_edges += 1
        return {
            "status": "verified" if accepted else "rejected_files",
            "verified": bool(accepted), "run_id": run_id, "git_head": current_head,
            "coverage_report_digest": str(coverage.get("coverage_report_digest") or ""),
            "accepted_files": sorted(set(accepted)),
            "rejected_files": sorted(set(rejected)),
            "verified_edges": verified_edges,
        }

    def _analyze_file(self, path: Path, rel: str, text: str, digest: str) -> dict[str, Any]:
        kind, layer = self._classify(rel)
        language = path.suffix.lower().lstrip(".") or path.name.lower()
        symbols: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []
        imports: list[str] = []
        parser_name = "metadata"
        parser = self._parser(path.suffix.lower())
        if parser is not None and len(text) <= 1_500_000:
            try:
                tree = parser.parse(text.encode("utf-8"))
                symbols, calls, imports = self._syntax_facts(tree.root_node, text.encode("utf-8"))
                parser_name = "tree-sitter"
            except (ValueError, TypeError, RuntimeError):
                parser = None
        if parser is None and path.suffix.lower() in LANGUAGES:
            symbols, calls, imports = self._fallback_facts(text)
            parser_name = "fallback"
        config_extends, packages = self._metadata_facts(path.name, text)
        entrypoint = self._entrypoint(rel, text)
        module_path = str(Path(rel).parent).replace("\\", "/")
        if module_path == ".":
            module_path = "."
        module = rel.split("/", 1)[0] if "/" in rel else "root"
        return {
            "digest": digest, "path": rel, "kind": kind, "layer": layer,
            "module": module, "module_path": module_path, "language": language,
            "parser": parser_name, "symbols": symbols[:1000], "calls": calls[:3000],
            "imports": sorted(set(imports))[:1000], "config_extends": config_extends,
            "packages": packages[:2000], "entrypoint": entrypoint,
            "is_test": self._is_test(rel),
        }

    def _parser(self, suffix: str) -> Any | None:
        if suffix not in LANGUAGES:
            return None
        if suffix in self._parsers:
            return self._parsers[suffix]
        try:
            from tree_sitter import Language, Parser
            module_name, factory = LANGUAGES[suffix]
            module = importlib.import_module(module_name)
            parser = Parser(Language(getattr(module, factory)()))
        except (ImportError, AttributeError, TypeError, ValueError):
            parser = None
        self._parsers[suffix] = parser
        return parser

    @staticmethod
    def _syntax_facts(root: Any, source: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        symbols: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []
        import_chunks: list[str] = []

        def text(node: Any) -> str:
            return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

        def visit(node: Any, container: str = "") -> None:
            next_container = container
            if node.type in DEFINITION_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    declarator = node.child_by_field_name("declarator")
                    name_node = declarator.child_by_field_name("declarator") if declarator is not None else None
                if name_node is not None:
                    name = text(name_node).strip()
                    name_match = re.search(r"([A-Za-z_$][\w$]*)\s*$", name)
                    name = name_match.group(1) if name_match else name
                    if name:
                        symbols.append({
                            "name": name, "kind": DEFINITION_TYPES[node.type],
                            "line": node.start_point.row + 1,
                            "end_line": node.end_point.row + 1,
                        })
                        next_container = name
            if node.type in CALL_TYPES:
                callee = node.child_by_field_name("function") or node.child_by_field_name("name")
                raw = text(callee).strip() if callee is not None else ""
                match = re.search(r"([A-Za-z_$][\w$]*)\s*$", raw)
                if match:
                    calls.append({"name": match.group(1), "line": node.start_point.row + 1, "container": container})
            if node.type in IMPORT_TYPES:
                import_chunks.append(text(node))
            child = node.child(0) if node.child_count else None
            index = 0
            while child is not None:
                visit(child, next_container)
                index += 1
                child = node.child(index) if index < node.child_count else None

        visit(root)
        imports: list[str] = []
        for chunk in import_chunks:
            imports.extend(RepositoryIntelligenceService._extract_imports(chunk))
        return symbols, calls, imports

    @staticmethod
    def _extract_imports(text: str) -> list[str]:
        values: list[str] = []
        patterns = (
            r"\bfrom\s+([.\w/\-@]+)\s+import\b", r"\bimport\s+['\"]([^'\"]+)['\"]",
            r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\brequire\s*\(\s*['\"]([^'\"]+)",
            r"\buse\s+([:\w]+)", r"\busing\s+([.\w]+)", r"#include\s*[<\"]([^>\"]+)",
        )
        for pattern in patterns:
            values.extend(match.group(1) for match in re.finditer(pattern, text))
        if re.match(r"\s*import\s+[\w., ]+\s*$", text):
            raw = re.sub(r"^\s*import\s+", "", text).strip()
            values.extend(item.strip().split(" as ")[0] for item in raw.split(","))
        return [item for item in values if item]

    @staticmethod
    def _fallback_facts(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        symbols = []
        for match in re.finditer(r"\b(class|def|function|fn|struct|interface)\s+([A-Za-z_$][\w$]*)", text):
            symbols.append({"name": match.group(2), "kind": match.group(1), "line": text.count("\n", 0, match.start()) + 1})
        calls = [{"name": match.group(1), "line": text.count("\n", 0, match.start()) + 1, "container": ""}
                 for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", text)]
        return symbols, calls, RepositoryIntelligenceService._extract_imports(text)

    @staticmethod
    def _metadata_facts(name: str, text: str) -> tuple[list[str], list[str]]:
        extends: list[str] = []
        packages: list[str] = []
        if name.endswith(".json") or name == "package.json":
            try:
                value = json.loads(text)
                raw_extends = value.get("extends") if isinstance(value, dict) else None
                if isinstance(raw_extends, str):
                    extends.append(raw_extends)
                if name == "package.json" and isinstance(value, dict):
                    for key in ("dependencies", "devDependencies", "peerDependencies"):
                        if isinstance(value.get(key), dict):
                            packages.extend(value[key].keys())
            except json.JSONDecodeError:
                pass
        if name in {"pyproject.toml", "Cargo.toml"}:
            packages.extend(re.findall(r"(?m)^([A-Za-z0-9_.-]+)\s*=\s*(?:[\"'{\[])", text))
        elif name.startswith("requirements"):
            packages.extend(match.group(1) for match in re.finditer(r"(?m)^\s*([A-Za-z0-9_.-]+)(?:[<>=!~]|\s|$)", text))
        elif name in {"go.mod", "go.work"}:
            packages.extend(match.group(1) for match in re.finditer(r"(?m)^\s*([\w.-]+/[\w./-]+)\s+v\d", text))
        return sorted(set(extends)), sorted(set(packages))

    @staticmethod
    def _classify(rel: str) -> tuple[str, str]:
        lower = rel.lower()
        name = Path(rel).name
        if lower.startswith(".github/workflows/") or lower.startswith(".gitlab-ci") or "jenkins" in lower:
            return "ci", "automation"
        if name.lower().startswith("readme") or lower.startswith("docs/") or Path(rel).suffix.lower() == ".md":
            return "documentation", "documentation"
        if name in SPECIAL_FILES or name.endswith((".csproj", ".sln", ".gradle")):
            return "build", "build"
        if name.startswith(("tsconfig", "eslint", "webpack", "vite.config")) or Path(rel).suffix.lower() in {".json", ".toml", ".yaml", ".yml", ".ini"}:
            return "config", "configuration"
        if RepositoryIntelligenceService._is_test(rel):
            return "test", "test"
        return "source", "source"

    @staticmethod
    def _entrypoint(rel: str, text: str) -> bool:
        name = Path(rel).name.lower()
        return bool(
            name in {"main.py", "main.go", "main.rs", "program.cs", "index.js", "index.ts", "app.py", "server.py"}
            or "if __name__ == \"__main__\"" in text or "if __name__ == '__main__'" in text
            or re.search(r"\bfn\s+main\s*\(|\bfunc\s+main\s*\(|\bstatic\s+void\s+Main\s*\(", text)
        )

    @staticmethod
    def _is_test(rel: str) -> bool:
        value = "/" + rel.lower().replace("\\", "/")
        return any(marker in value for marker in TEST_MARKERS)

    @staticmethod
    def _path_resolver(path_to_id: dict[str, str]) -> dict[str, str]:
        resolver: dict[str, str] = {}
        for rel in path_to_id:
            path = Path(rel)
            without = str(path.with_suffix("")).replace("\\", "/")
            resolver[without] = rel
            resolver[without.replace("/", ".")] = rel
            if path.stem in {"__init__", "index", "mod"}:
                parent = str(path.parent).replace("\\", "/")
                resolver[parent] = rel
                resolver[parent.replace("/", ".")] = rel
        return resolver

    @staticmethod
    def _resolve_import(source: str, dependency: str, resolver: dict[str, str]) -> str | None:
        dep = dependency.strip().strip("'\"").replace("::", "/")
        source_parent = str(Path(source).parent).replace("\\", "/")
        candidates = [dep, dep.replace(".", "/")]
        if dep.startswith("."):
            candidates.insert(0, str((Path(source_parent) / dep).as_posix()))
        else:
            candidates.extend([f"{source_parent}/{dep}", f"{source_parent}/{dep.replace('.', '/')}"])
        for candidate in candidates:
            normalized = str(Path(candidate)).replace("\\", "/").lstrip("./")
            if normalized in resolver:
                return resolver[normalized]
        suffix_matches = [value for key, value in resolver.items() if key.endswith("/" + dep.replace(".", "/"))]
        return suffix_matches[0] if len(set(suffix_matches)) == 1 else None

    @staticmethod
    def _resolve_relative(source: str, target: str, path_to_id: dict[str, str]) -> str | None:
        candidate = (Path(source).parent / target).as_posix()
        options = [candidate, candidate + ".json", candidate + ".yaml", candidate + ".yml"]
        return next((item for item in options if item in path_to_id), None)

    @staticmethod
    def _layered_map(facts: dict[str, dict[str, Any]], nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        def paths(kind: str) -> list[str]:
            return sorted(rel for rel, fact in facts.items() if fact["kind"] == kind)
        modules = sorted({fact["module"] for fact in facts.values()})
        relationship_counts: dict[str, int] = defaultdict(int)
        for edge in edges:
            relationship_counts[str(edge["type"])] += 1
        return {
            "entrypoints": sorted(rel for rel, fact in facts.items() if fact.get("entrypoint")),
            "modules": modules, "source": paths("source"), "tests": paths("test"),
            "build_systems": paths("build"), "configuration": paths("config"),
            "ci": paths("ci"), "documentation": paths("documentation"),
            "dependencies": sorted({node["name"] for node in nodes if node["kind"] == "dependency"}),
            "relationship_counts": dict(sorted(relationship_counts.items())),
        }

    @staticmethod
    def _merge_lsp(nodes: dict[str, dict[str, Any]], edges: dict[tuple[str, str, str], dict[str, Any]], graph: dict[str, Any]) -> None:
        repository_files = {
            str(row.get("path")): node_id for node_id, row in nodes.items()
            if node_id.startswith("file:") and row.get("path")
        }
        repository_symbols = defaultdict(list)
        for node_id, row in nodes.items():
            if row.get("kind") == "symbol":
                repository_symbols[(str(row.get("path")), str(row.get("name")))].append(node_id)
        for language_graph in graph.get("graphs") or []:
            id_map: dict[str, str] = {}
            counterpart_map: dict[str, str] = {}
            for row in language_graph.get("nodes") or []:
                new_id = "lsp:" + str(row.get("id"))
                id_map[str(row.get("id"))] = new_id
                nodes[new_id] = {
                    **row, "id": new_id, "evidence": "lsp",
                    "evidence_tier": "lsp", "verification": "confirmed",
                    "kind": "lsp_" + str(row.get("kind") or "node"),
                }
                repo_file = repository_files.get(str(row.get("path") or ""))
                symbol_matches = repository_symbols.get(
                    (str(row.get("path") or ""), str(row.get("name") or "")), []
                )
                counterpart = ""
                if symbol_matches:
                    line = int(row.get("line") or 1)
                    counterpart = min(
                        symbol_matches,
                        key=lambda item: abs(int(nodes[item].get("line") or 1) - line),
                    )
                elif repo_file:
                    counterpart = repo_file
                if counterpart:
                    counterpart_map[str(row.get("id"))] = counterpart
                if repo_file:
                    edges[(repo_file, new_id, "semantic_evidence")] = _edge_row(
                        repo_file, new_id, "semantic_evidence", evidence_tier="lsp",
                        verification="confirmed", confidence=0.9,
                        basis="LSP node located in repository file",
                    )
                for repo_symbol in symbol_matches:
                    edges[(repo_symbol, new_id, "corroborates")] = _edge_row(
                        repo_symbol, new_id, "corroborates", evidence_tier="lsp",
                        verification="confirmed", confidence=0.95,
                        basis="path/name LSP symbol match",
                    )
            for row in language_graph.get("edges") or []:
                source = id_map.get(str(row.get("source")))
                target = id_map.get(str(row.get("target")))
                if source in nodes and target in nodes:
                    raw_type = str(row.get("type") or row.get("kind") or "related")
                    edge_type = "lsp_" + raw_type
                    edges[(source, target, edge_type)] = _edge_row(
                        source, target, edge_type, evidence_tier="lsp",
                        verification="confirmed", confidence=0.95,
                        basis=f"language-server {raw_type}",
                    )
                    repo_source = counterpart_map.get(str(row.get("source")))
                    repo_target = counterpart_map.get(str(row.get("target")))
                    if not repo_source or not repo_target or repo_source == repo_target:
                        continue
                    projected_source, projected_target, projected_type = repo_source, repo_target, ""
                    if raw_type == "calls":
                        projected_type = "calls"
                    elif raw_type == "referenced_at":
                        projected_source, projected_target = repo_target, repo_source
                        projected_type = "references"
                    if projected_type:
                        edges[(projected_source, projected_target, projected_type)] = _edge_row(
                            projected_source, projected_target, projected_type,
                            evidence_tier="lsp", verification="confirmed",
                            confidence=0.95, basis=f"projected LSP {raw_type}",
                            impact=True,
                        )

    def _tracked_files(self, repo: Path) -> list[str]:
        values = self._git(repo, "ls-files").splitlines()
        values.extend(self._git(repo, "ls-files", "--others", "--exclude-standard").splitlines())
        rows = []
        for raw in values:
            rel = raw.replace("\\", "/")
            path = repo / rel
            if path.is_file() and (path.suffix.lower() in GRAPH_SUFFIXES or path.name in SPECIAL_FILES or path.name.endswith((".csproj", ".sln"))):
                rows.append(rel)
        return sorted(set(rows))

    def _cache_path(self, repo: Path) -> Path | None:
        if not self.cache_root:
            return None
        key = hashlib.sha256(str(repo).lower().encode("utf-8")).hexdigest()[:16]
        return self.cache_root / f"{repo.name}-{key}.json"

    @staticmethod
    def _read_cache(path: Path | None) -> dict[str, Any]:
        if not path or not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_cache(self, path: Path | None, value: dict[str, Any]) -> None:
        if not path:
            return
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)

    @staticmethod
    def _repo(value: str | Path) -> Path:
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("repo_path must be a Git repository")
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise ValueError("repo_path must be a Git repository")
        return path

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""
