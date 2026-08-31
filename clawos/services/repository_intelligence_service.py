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
    "imports", "calls", "tests", "covers", "configured_by",
    "inherits_config", "builds", "depends_on", "entrypoint",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return {item.lower() for item in TOKEN_RE.findall(value or "") if len(item) > 1}


def _node_id(kind: str, *parts: object) -> str:
    return f"{kind}:" + ":".join(str(item).replace("\\", "/") for item in parts)


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
        graph = self._assemble(repo, facts, semantic_graph or {})
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
            if node.get("kind") in {"entrypoint", "test", "module"}:
                scores[node_id] += 2.0
        seeds = [item for item, score in sorted(scores.items(), key=lambda row: (-row[1], row[0])) if score > 0][:40]
        if not seeds:
            seeds = [row["id"] for row in graph.get("nodes") or [] if row.get("kind") == "entrypoint"][:10]
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for edge in edges:
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
                key=lambda row: (row[1].get("type") not in IMPACT_EDGE_TYPES, row[0]),
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
            if edge.get("source") not in selected or edge.get("target") not in selected:
                continue
            for endpoint in (edge.get("source"), edge.get("target")):
                path = str(nodes.get(str(endpoint), {}).get("path") or "")
                if path:
                    file_scores[path] += 3.0
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
        reverse: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for edge in graph.get("edges") or []:
            if edge.get("type") in IMPACT_EDGE_TYPES:
                reverse[edge["target"]].append((edge["source"], edge["type"]))
        impacted: dict[str, dict[str, Any]] = {}
        queue = deque((seed, 0, []) for seed in seeds)
        visited = set(seeds)
        while queue:
            current, level, path_edges = queue.popleft()
            if level >= max(1, depth):
                continue
            for consumer, edge_type in reverse.get(current, []):
                if consumer in visited:
                    continue
                visited.add(consumer)
                node = nodes.get(consumer, {})
                trail = path_edges + [edge_type]
                impacted[consumer] = {
                    "id": consumer, "kind": node.get("kind"),
                    "path": node.get("path"), "name": node.get("name"),
                    "distance": level + 1, "via": trail,
                }
                queue.append((consumer, level + 1, trail))
        rows = sorted(impacted.values(), key=lambda row: (row["distance"], str(row.get("path")), row["id"]))
        impacted_files = sorted({str(row["path"]) for row in rows if row.get("path") and row.get("path") not in normalized})
        tests = sorted({str(row["path"]) for row in rows if row.get("kind") == "test" or self._is_test(str(row.get("path") or ""))})
        risk = "high" if len(impacted_files) > 12 or not tests else "medium" if len(impacted_files) > 4 else "low"
        return {
            "schema": "clawos.repository-impact.v1", "changed_paths": sorted(normalized),
            "impacted_files": impacted_files, "tests": tests,
            "consumers": rows[:500], "risk": risk, "depth": depth,
        }

    def _assemble(
        self, repo: Path, facts: dict[str, dict[str, Any]], semantic_graph: dict[str, Any]
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(row: dict[str, Any]) -> None:
            nodes[row["id"]] = {**nodes.get(row["id"], {}), **row}

        def add_edge(source: str, target: str, edge_type: str, evidence: str = "repository") -> None:
            if source in nodes and target in nodes and source != target:
                edges[(source, target, edge_type)] = {
                    "source": source, "target": target, "type": edge_type,
                    "evidence": evidence,
                }

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
                add_edge(file_id, symbol_id, "defines", fact.get("parser", "fallback"))
                symbol_by_name[symbol["name"]].append(symbol_id)
                symbol_by_file_name[(rel, symbol["name"])] = symbol_id
        resolver = self._path_resolver(path_to_id)
        for rel, fact in facts.items():
            file_id = path_to_id[rel]
            for dependency in fact.get("imports") or []:
                target_path = self._resolve_import(rel, dependency, resolver)
                if target_path:
                    add_edge(file_id, path_to_id[target_path], "imports", fact.get("parser", "fallback"))
                    if fact["is_test"] and not facts[target_path]["is_test"]:
                        add_edge(file_id, path_to_id[target_path], "tests")
                        add_edge(file_id, path_to_id[target_path], "covers")
            for call in fact.get("calls") or []:
                candidates = symbol_by_name.get(call["name"], [])
                target = next((item for item in candidates if nodes[item].get("path") == rel), None)
                if target is None and len(candidates) == 1:
                    target = candidates[0]
                source = symbol_by_file_name.get((rel, call.get("container", "")), file_id)
                if target:
                    add_edge(source, target, "calls", fact.get("parser", "fallback"))
                    if fact["is_test"] and nodes[target].get("path") != rel:
                        add_edge(file_id, target, "covers", fact.get("parser", "fallback"))
            if fact.get("entrypoint"):
                entry_id = _node_id("entrypoint", rel)
                add_node({"id": entry_id, "kind": "entrypoint", "name": rel, "path": rel})
                add_edge(entry_id, file_id, "entrypoint")
            for inherited in fact.get("config_extends") or []:
                target_path = self._resolve_relative(rel, inherited, path_to_id)
                if target_path:
                    add_edge(file_id, path_to_id[target_path], "inherits_config")
            for dependency in fact.get("packages") or []:
                dep_id = _node_id("dependency", dependency)
                add_node({"id": dep_id, "kind": "dependency", "name": dependency})
                add_edge(file_id, dep_id, "depends_on")
        build_files = [rel for rel, fact in facts.items() if fact["kind"] == "build"]
        test_files = [rel for rel, fact in facts.items() if fact["is_test"]]
        for rel, fact in facts.items():
            source_id = path_to_id[rel]
            scope = fact.get("module") or "root"
            module_id = modules.get(scope)
            if fact["kind"] in {"build", "config"}:
                edge_type = "builds" if fact["kind"] == "build" else "configured_by"
                for target_rel, target_fact in facts.items():
                    if target_fact["kind"] in {"source", "test"}:
                        add_edge(path_to_id[target_rel], source_id, edge_type)
            elif fact["kind"] == "ci":
                for target_rel in (build_files + test_files)[:100]:
                    add_edge(source_id, path_to_id[target_rel], "builds")
                    add_edge(path_to_id[target_rel], source_id, "configured_by")
        self._merge_lsp(nodes, edges, semantic_graph)
        node_rows = sorted(nodes.values(), key=lambda row: row["id"])
        edge_rows = sorted(edges.values(), key=lambda row: (row["source"], row["target"], row["type"]))
        repo_map = self._layered_map(facts, node_rows, edge_rows)
        return {
            "schema": self.SCHEMA, "repo": str(repo), "nodes": node_rows,
            "edges": edge_rows, "repo_map": repo_map,
            "metrics": {
                "files": len(facts), "nodes": len(node_rows), "edges": len(edge_rows),
                "symbols": sum(1 for row in node_rows if row["kind"] == "symbol"),
                "tree_sitter_files": sum(1 for row in facts.values() if row.get("parser") == "tree-sitter"),
                "lsp_available": bool(semantic_graph),
            },
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
            for row in language_graph.get("nodes") or []:
                new_id = "lsp:" + str(row.get("id"))
                id_map[str(row.get("id"))] = new_id
                nodes[new_id] = {**row, "id": new_id, "evidence": "lsp", "kind": "lsp_" + str(row.get("kind") or "node")}
                repo_file = repository_files.get(str(row.get("path") or ""))
                if repo_file:
                    edges[(repo_file, new_id, "semantic_evidence")] = {
                        "source": repo_file, "target": new_id,
                        "type": "semantic_evidence", "evidence": "lsp",
                    }
                for repo_symbol in repository_symbols.get((str(row.get("path") or ""), str(row.get("name") or "")), []):
                    edges[(repo_symbol, new_id, "corroborates")] = {
                        "source": repo_symbol, "target": new_id,
                        "type": "corroborates", "evidence": "lsp",
                    }
            for row in language_graph.get("edges") or []:
                source = id_map.get(str(row.get("source")))
                target = id_map.get(str(row.get("target")))
                if source in nodes and target in nodes:
                    edge_type = "lsp_" + str(row.get("type") or "related")
                    edges[(source, target, edge_type)] = {"source": source, "target": target, "type": edge_type, "evidence": "lsp"}

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
