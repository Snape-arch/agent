"""Persistent, incremental semantic graph built from real LSP evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .coding_diagnostics_service import CodingDiagnosticsService
from .lsp_bridge_service import LanguageServerBridge, LanguageServerManager, DEFAULT_LANGUAGE_SERVER_MANAGER


LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".jsx": "javascriptreact",
    ".ts": "typescript", ".tsx": "typescriptreact", ".go": "go",
    ".rs": "rust", ".cs": "csharp", ".c": "c", ".cc": "cpp",
    ".cpp": "cpp", ".h": "cpp", ".hpp": "cpp", ".java": "java",
}
SYMBOL_KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter",
}


class LanguageServerDiscovery:
    """Discover only known language-server commands; never execute project config."""

    CANDIDATES = {
        "python": [["pylsp"], ["pyright-langserver", "--stdio"]],
        "typescript": [["typescript-language-server", "--stdio"]],
        "javascript": [["typescript-language-server", "--stdio"]],
        "go": [["gopls"]], "rust": [["rust-analyzer"]],
        "c": [["clangd", "--background-index=false"]],
        "cpp": [["clangd", "--background-index=false"]],
        "csharp": [["csharp-ls"]], "java": [["jdtls"]],
    }

    STANDARD_EXECUTABLES = {
        "typescript-language-server": [
            Path.home() / "AppData/Roaming/npm/typescript-language-server.cmd",
        ],
        "gopls": [Path.home() / "go/bin/gopls.exe"],
        "rust-analyzer": [Path.home() / ".cargo/bin/rust-analyzer.exe"],
        "clangd": [Path("C:/Program Files/LLVM/bin/clangd.exe")],
        "csharp-ls": [Path.home() / "AppData/Local/ClawOS/lsp-tools/csharp-ls.exe"],
    }

    @classmethod
    def _resolve(cls, executable: str) -> str:
        found = shutil.which(executable)
        if found:
            return found
        return next((str(path) for path in cls.STANDARD_EXECUTABLES.get(executable, []) if path.is_file()), "")

    def discover(self) -> dict[str, Any]:
        rows = {}
        for language, candidates in self.CANDIDATES.items():
            found, executable = [], ""
            for command in candidates:
                executable = self._resolve(command[0])
                if executable:
                    found = [executable, *command[1:]]
                    break
            rows[language] = {
                "available": bool(found), "command": found,
                "executable": executable if found else "",
            }
        return {"schema": "clawos.lsp-discovery.v1", "languages": rows}

    def command_for(self, language: str) -> list[str]:
        row = self.discover()["languages"].get(str(language).lower()) or {}
        return list(row.get("command") or [])


class LSPSemanticGraphService:
    """Create a graph of files, symbols, definitions, references, calls and diagnostics."""

    SCHEMA = "clawos.lsp-semantic-graph.v1"

    def __init__(
        self, *, manager: LanguageServerManager | None = None,
        cache_root: str | Path | None = None,
    ):
        self.manager = manager or DEFAULT_LANGUAGE_SERVER_MANAGER
        self.cache_root = Path(cache_root).expanduser().resolve() if cache_root else None
        self.diagnostics = CodingDiagnosticsService()

    def build(
        self, repo_path: str | Path, *, language: str,
        command: list[str] | None = None, files: list[str] | None = None,
        max_symbols: int = 500, include_calls: bool = True,
        timeout_seconds: float = 15,
    ) -> dict[str, Any]:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir() or not (repo / ".git").exists():
            raise ValueError("repo_path must be a Git repository")
        selected_command = list(command or LanguageServerDiscovery().command_for(language))
        if not selected_command:
            raise RuntimeError(f"no configured language server is available for {language}")
        bridge = self.manager.get(repo, selected_command, timeout_seconds=timeout_seconds)
        selected = self._files(repo, language, files)
        previous = self._load(repo, language)
        previous_files = dict(previous.get("file_digests") or {})
        digests = {rel: self._sha(repo / rel) for rel in selected}
        changed = {rel for rel, digest in digests.items() if previous_files.get(rel) != digest}
        removed = set(previous_files) - set(digests)
        keep_nodes = [node for node in previous.get("nodes") or [] if node.get("path") not in changed | removed]
        keep_ids = {node.get("id") for node in keep_nodes}
        keep_edges = [edge for edge in previous.get("edges") or [] if edge.get("source") in keep_ids and edge.get("target") in keep_ids]
        nodes, edges = list(keep_nodes), list(keep_edges)
        diagnostics = [item for item in previous.get("diagnostics") or [] if item.get("path") not in changed | removed]
        file_nodes = {node.get("path"): node.get("id") for node in nodes if node.get("kind") == "file"}
        symbol_nodes: dict[tuple[str, str, int], str] = {
            (str(node.get("path")), str(node.get("name")), int(node.get("line") or 1)): str(node.get("id"))
            for node in nodes if node.get("kind") == "symbol"
        }
        for rel in sorted(changed):
            path = repo / rel
            language_id = LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), language)
            file_id = self._node_id("file", rel, "", 1, 1)
            file_nodes[rel] = file_id
            nodes.append({"id": file_id, "kind": "file", "path": rel, "language": language_id, "digest": digests[rel]})
            try:
                raw_symbols = bridge.document_symbols(path, language_id=language_id)
            except (OSError, RuntimeError, TimeoutError, ValueError):
                raw_symbols = []
            flattened = self._flatten_symbols(raw_symbols)[: max(1, min(max_symbols, 2000))]
            for raw in flattened:
                location = raw.get("location") or {}
                start = self._start(
                    raw.get("selectionRange") or raw.get("range")
                    or location.get("range") or {}
                )
                symbol_id = self._node_id("symbol", rel, str(raw.get("name") or ""), start[0], start[1])
                symbol_nodes[(rel, str(raw.get("name") or ""), start[0])] = symbol_id
                nodes.append({
                    "id": symbol_id, "kind": "symbol", "path": rel,
                    "name": str(raw.get("name") or ""),
                    "symbol_kind": SYMBOL_KINDS.get(int(raw.get("kind") or 0), str(raw.get("kind") or "unknown")),
                    "line": start[0], "column": start[1],
                    "range": raw.get("range") or location.get("range") or {},
                    "language": language_id, "source": "lsp",
                })
                edges.append(self._edge(file_id, symbol_id, "contains", "lsp"))
            try:
                raw_diagnostics = bridge.diagnostics(path, language_id=language_id)
            except (OSError, RuntimeError, TimeoutError, ValueError):
                raw_diagnostics = []
            diagnostics.extend(self._normalize_lsp_diagnostics(repo, rel, raw_diagnostics))
        # Definitions/references use all current symbols so unchanged nodes can link to changed targets.
        current_symbols = [node for node in nodes if node.get("kind") == "symbol"][: max(1, min(max_symbols, 2000))]
        for node in current_symbols:
            path = repo / str(node["path"])
            language_id = str(node.get("language") or language)
            line = int(node.get("line") or 1) - 1
            column = self._symbol_column(
                path, line, str(node.get("name") or ""),
                int(node.get("column") or 1) - 1,
            )
            try:
                definitions = self._locations(bridge.definition(path, line, column, language_id=language_id))
                references = bridge.references(path, line, column, language_id=language_id)
            except (RuntimeError, TimeoutError, ValueError, OSError):
                definitions, references = [], []
            for location in definitions:
                target = self._location_node(repo, nodes, file_nodes, location)
                if target:
                    edges.append(self._edge(node["id"], target, "defines_at", "lsp"))
            for location in references[:500]:
                target = self._location_node(repo, nodes, file_nodes, location)
                if target:
                    edges.append(self._edge(node["id"], target, "referenced_at", "lsp"))
            if include_calls:
                try:
                    hierarchy = bridge.prepare_call_hierarchy(path, line, column, language_id=language_id)
                    for item in hierarchy[:10]:
                        for incoming in bridge.incoming_calls(item)[:100]:
                            caller = self._location_node(repo, nodes, file_nodes, incoming.get("from") or {})
                            if caller: edges.append(self._edge(caller, node["id"], "calls", "lsp"))
                        for outgoing in bridge.outgoing_calls(item)[:100]:
                            callee = self._location_node(repo, nodes, file_nodes, outgoing.get("to") or {})
                            if callee: edges.append(self._edge(node["id"], callee, "calls", "lsp"))
                except (RuntimeError, TimeoutError, ValueError, OSError):
                    pass
        diagnostics = self._link_diagnostics(repo, diagnostics, nodes)
        for item in diagnostics:
            diag_id = self._node_id("diagnostic", item["path"], item.get("code") or item.get("message") or "", item["line"], item["column"])
            nodes.append({"id": diag_id, "kind": "diagnostic", **item})
            target = str((item.get("related_symbol") or {}).get("id") or file_nodes.get(item["path"]) or "")
            if target: edges.append(self._edge(diag_id, target, "diagnoses", "lsp"))
        nodes = self._dedupe(nodes, "id")
        edges = self._dedupe(edges, "id")
        graph = {
            "schema": self.SCHEMA, "repo": str(repo), "language": language,
            "server": {**bridge.status(), "command": selected_command},
            "file_digests": digests, "changed_files": sorted(changed), "removed_files": sorted(removed),
            "incremental": bool(previous), "nodes": nodes, "edges": edges,
            "diagnostics": diagnostics,
            "metrics": self._metrics(nodes, edges, diagnostics, len(selected)),
        }
        graph["digest"] = hashlib.sha256(json.dumps(graph, sort_keys=True, default=str).encode()).hexdigest()
        self._persist(repo, language, graph)
        return graph

    def build_available(
        self, repo_path: str | Path, *, max_languages: int = 3,
        max_files: int = 40, max_symbols: int = 300, include_calls: bool = True,
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        repo = Path(repo_path).expanduser().resolve()
        discovery = LanguageServerDiscovery().discover()
        present = []
        if files:
            scan_paths = [(repo / str(item)).resolve() for item in files]
        else:
            listed = subprocess.run(
                ["git", "ls-files"], cwd=repo, capture_output=True,
                text=True, check=True,
            ).stdout.splitlines()
            scan_paths = [(repo / item).resolve() for item in listed[: max(1, int(max_files))]]
        selected_by_language: dict[str, list[str]] = {}
        for path in scan_paths:
            if path.is_file() and ".git" not in path.parts:
                language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "")
                base = "typescript" if language in {"typescriptreact"} else "javascript" if language == "javascriptreact" else language
                if base and base not in present:
                    present.append(base)
                if base:
                    try:
                        selected_by_language.setdefault(base, []).append(path.relative_to(repo).as_posix())
                    except ValueError:
                        pass
        graphs, errors = [], []
        for language in present:
            row = discovery["languages"].get(language) or {}
            if not row.get("available"):
                continue
            try:
                graphs.append(self.build(
                    repo, language=language, command=row["command"],
                    files=selected_by_language.get(language), max_symbols=max_symbols,
                    include_calls=include_calls,
                ))
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                errors.append({"language": language, "error": f"{type(exc).__name__}: {exc}"})
            if len(graphs) >= max(1, min(int(max_languages), 8)):
                break
        return {
            "schema": "clawos.lsp-semantic-workspace.v1", "repo": str(repo),
            "discovery": discovery, "graphs": graphs, "errors": errors,
            "metrics": {
                "languages": len(graphs),
                "nodes": sum(item["metrics"]["nodes"] for item in graphs),
                "edges": sum(item["metrics"]["edges"] for item in graphs),
                "diagnostics": sum(item["metrics"]["diagnostics"] for item in graphs),
            },
        }

    def query(
        self, graph: dict[str, Any], *, path: str = "", symbol: str = "",
        depth: int = 2, limit: int = 100,
    ) -> dict[str, Any]:
        nodes = {str(node["id"]): node for node in graph.get("nodes") or []}
        seeds = {
            node_id for node_id, node in nodes.items()
            if (not path or node.get("path") == path) and (not symbol or str(node.get("name") or "").lower() == symbol.lower())
        }
        selected = set(seeds)
        chosen_edges = []
        frontier = set(seeds)
        for _ in range(max(0, min(int(depth), 5))):
            next_frontier = set()
            for edge in graph.get("edges") or []:
                if edge.get("source") in frontier or edge.get("target") in frontier:
                    chosen_edges.append(edge)
                    next_frontier |= {str(edge.get("source")), str(edge.get("target"))}
            next_frontier -= selected
            selected |= next_frontier
            frontier = next_frontier
            if not frontier or len(selected) >= limit: break
        return {
            "schema": "clawos.lsp-semantic-query.v1",
            "seed_ids": sorted(seeds),
            "nodes": [nodes[node_id] for node_id in list(selected)[:limit] if node_id in nodes],
            "edges": self._dedupe(chosen_edges, "id")[: limit * 3],
        }

    def _normalize_lsp_diagnostics(self, repo: Path, rel: str, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        severities = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        for item in raw[:500]:
            start = self._start(item.get("range") or {})
            rows.append({
                "path": rel, "line": start[0], "column": start[1],
                "severity": severities.get(int(item.get("severity") or 1), "error"),
                "code": str(item.get("code") or "")[:100],
                "message": str(item.get("message") or "")[:1000],
                "source": f"lsp:{item.get('source') or 'server'}", "trust": "tool_evidence",
                "tags": list(item.get("tags") or []), "related_information": list(item.get("relatedInformation") or [])[:50],
            })
        return rows

    def _link_diagnostics(self, repo: Path, diagnostics: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        repo_map = {"files": []}
        for rel in sorted({str(item.get("path")) for item in nodes if item.get("path")}):
            repo_map["files"].append({
                "path": rel,
                "symbols": [{"name": item.get("name"), "line": item.get("line"), "id": item.get("id")} for item in nodes if item.get("kind") == "symbol" and item.get("path") == rel],
            })
        linked = self.diagnostics.link_symbols(repo, diagnostics, repo_map)
        index = {(node.get("path"), node.get("name"), node.get("line")): node.get("id") for node in nodes if node.get("kind") == "symbol"}
        for item in linked:
            symbol = item.get("related_symbol") or {}
            symbol["id"] = index.get((symbol.get("path"), symbol.get("name"), symbol.get("definition_line")), "")
        return linked

    @staticmethod
    def _files(repo: Path, language: str, files: list[str] | None) -> list[str]:
        if files:
            candidates = [str(item).replace("\\", "/").strip("/") for item in files]
        else:
            result = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True)
            candidates = result.stdout.splitlines()
        selected = []
        for rel in candidates:
            path = (repo / rel).resolve()
            try: path.relative_to(repo)
            except ValueError: continue
            lang = LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "")
            if path.is_file() and (lang == language or language in {"typescript", "javascript"} and lang in {"typescript", "typescriptreact", "javascript", "javascriptreact"}):
                selected.append(rel)
        return selected[:500]

    @classmethod
    def _location_node(cls, repo: Path, nodes: list[dict[str, Any]], file_nodes: dict[str, str], location: dict[str, Any]) -> str:
        uri = str(location.get("uri") or location.get("targetUri") or "")
        rel = cls._uri_relative(repo, uri)
        if not rel: return ""
        range_value = location.get("range") or location.get("targetSelectionRange") or {}
        line, _ = cls._start(range_value)
        candidates = [node for node in nodes if node.get("kind") == "symbol" and node.get("path") == rel and int(node.get("line") or 1) <= line]
        if candidates:
            return str(max(candidates, key=lambda item: int(item.get("line") or 1))["id"])
        return str(file_nodes.get(rel) or "")

    @staticmethod
    def _locations(value: Any) -> list[dict[str, Any]]:
        if not value: return []
        return value if isinstance(value, list) else [value] if isinstance(value, dict) else []

    @classmethod
    def _flatten_symbols(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            result.append({key: value for key, value in row.items() if key != "children"})
            result.extend(cls._flatten_symbols(list(row.get("children") or [])))
        return result

    @staticmethod
    def _start(range_value: dict[str, Any]) -> tuple[int, int]:
        start = range_value.get("start") or {}
        return max(1, int(start.get("line") or 0) + 1), max(1, int(start.get("character") or 0) + 1)

    @staticmethod
    def _symbol_column(path: Path, zero_line: int, name: str, fallback: int) -> int:
        """Place semantic queries on the identifier, not a declaration keyword."""
        try:
            line = path.read_text(encoding="utf-8", errors="replace").splitlines()[zero_line]
        except (OSError, IndexError):
            return max(0, fallback)
        position = line.find(name, max(0, fallback))
        if position < 0:
            position = line.find(name)
        return position if position >= 0 else max(0, fallback)

    @staticmethod
    def _uri_relative(repo: Path, uri: str) -> str:
        try:
            path = Path(unquote(urlparse(uri).path.lstrip("/") if os.name == "nt" else unquote(urlparse(uri).path))).resolve()
            return path.relative_to(repo).as_posix()
        except (ValueError, OSError):
            return ""

    @staticmethod
    def _node_id(kind: str, path: str, name: str, line: int, column: int) -> str:
        return "n-" + hashlib.sha256(f"{kind}\0{path}\0{name}\0{line}\0{column}".encode()).hexdigest()[:24]

    @staticmethod
    def _edge(source: str, target: str, kind: str, evidence: str) -> dict[str, Any]:
        value = f"{source}\0{target}\0{kind}"
        return {"id": "e-" + hashlib.sha256(value.encode()).hexdigest()[:24], "source": source, "target": target, "kind": kind, "evidence": evidence}

    @staticmethod
    def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        return list({str(item.get(key)): item for item in rows if item.get(key)}.values())

    @staticmethod
    def _metrics(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], diagnostics: list[dict[str, Any]], files: int) -> dict[str, Any]:
        return {
            "files": files, "nodes": len(nodes), "symbols": sum(item.get("kind") == "symbol" for item in nodes),
            "edges": len(edges), "definitions": sum(item.get("kind") == "defines_at" for item in edges),
            "references": sum(item.get("kind") == "referenced_at" for item in edges),
            "calls": sum(item.get("kind") == "calls" for item in edges), "diagnostics": len(diagnostics),
        }

    def _cache_path(self, repo: Path, language: str) -> Path | None:
        if self.cache_root is None: return None
        key = hashlib.sha256(str(repo).lower().encode()).hexdigest()[:16]
        return self.cache_root / key / f"{language}.json"

    def _load(self, repo: Path, language: str) -> dict[str, Any]:
        path = self._cache_path(repo, language)
        if not path or not path.is_file(): return {}
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {}

    def _persist(self, repo: Path, language: str, graph: dict[str, Any]) -> None:
        path = self._cache_path(repo, language)
        if not path: return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
