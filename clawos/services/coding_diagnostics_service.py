"""Normalize build/test/lint output into evidence for coding-agent decisions."""

from __future__ import annotations

import re
import ast
from pathlib import Path
from typing import Any


class CodingDiagnosticsService:
    """Parse common diagnostics, link stack frames to symbols, classify failures."""

    PATTERNS = (
        ("python", re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<symbol>[\w.<>]+))?')),
        ("pytest", re.compile(r"^(?P<path>[^:\s]+\.py):(?P<line>\d+):\s*(?P<message>.+)$", re.M)),
        ("typescript", re.compile(r"^(?P<path>[^\r\n()]+\.(?:ts|tsx|js|jsx))\((?P<line>\d+),(?P<column>\d+)\):\s*(?P<severity>error|warning)\s*(?P<code>TS\d+):\s*(?P<message>.+)$", re.M | re.I)),
        ("eslint", re.compile(r"^(?P<path>[^:\r\n]+\.(?:js|jsx|ts|tsx)):(?P<line>\d+):(?P<column>\d+)\s+(?P<severity>error|warning)\s+(?P<message>.+?)(?:\s{2,}(?P<code>[\w@/-]+))?$", re.M | re.I)),
        ("rust", re.compile(r"^\s*-->\s+(?P<path>[^:\r\n]+):(?P<line>\d+):(?P<column>\d+)", re.M)),
        ("go", re.compile(r"^(?P<path>[^:\r\n]+\.go):(?P<line>\d+):(?P<column>\d+):\s*(?P<message>.+)$", re.M)),
        ("generic", re.compile(r"^(?P<path>[^:\r\n]+\.(?:py|go|rs|java|kt|cs|c|cc|cpp|h|hpp)):(?P<line>\d+)(?::(?P<column>\d+))?:\s*(?P<message>.+)$", re.M)),
    )

    ENVIRONMENT_MARKERS = (
        "command not found", "is not recognized", "no such file or directory",
        "modulenotfounderror", "cannot find module", "permission denied",
        "access is denied", "connection refused", "network is unreachable",
        "could not resolve host", "failed to download", "timed out",
        "appcontainer launch failed", "sandbox orchestration failed",
    )
    REQUIREMENT_MARKERS = (
        "ambiguous requirement", "expected behavior unspecified",
        "acceptance criteria missing", "requirements mismatch",
    )
    ASSERTION_MARKERS = (
        "assertionerror", "assert ", "expected:", "actual:",
        "tests failed", "test failed", "panic:",
    )

    def analyze(
        self, repo: str | Path, executions: list[dict[str, Any]],
        repo_map: dict[str, Any] | None = None,
        lsp_diagnostics: list[dict[str, Any]] | None = None,
        semantic_graph: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = Path(repo).resolve()
        diagnostics: list[dict[str, Any]] = []
        combined = []
        timed_out = False
        nonzero = False
        for execution in executions:
            output = f"{execution.get('stdout') or ''}\n{execution.get('stderr') or ''}"
            combined.append(output)
            timed_out = timed_out or bool(execution.get("timed_out"))
            nonzero = nonzero or int(execution.get("exit_code") or 0) != 0
            diagnostics.extend(self.parse(root, output, execution.get("command") or []))
        text = "\n".join(combined)
        diagnostics.extend(self._normalize_lsp(repo=root, diagnostics=lsp_diagnostics or []))
        category, confidence, reason = self.classify(text, nonzero=nonzero, timed_out=timed_out)
        graph_map = self._semantic_repo_map(semantic_graph or {})
        linked = self.link_symbols(root, diagnostics, graph_map or repo_map or {})
        return {
            "schema": "clawos.coding-diagnostics.v1",
            "failure_category": category,
            "classification_confidence": confidence,
            "classification_reason": reason,
            "diagnostics": linked[:200],
            "error_count": sum(item["severity"] == "error" for item in linked),
            "related_symbols": self._related_symbols(linked),
            "semantic_graph_used": bool(graph_map),
        }

    @staticmethod
    def _normalize_lsp(repo: Path, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for item in diagnostics[:500]:
            rel = str(item.get("path") or "").replace("\\", "/").strip("/")
            path = (repo / rel).resolve()
            try: path.relative_to(repo)
            except ValueError: continue
            if not path.is_file(): continue
            rows.append({
                "path": rel, "line": max(1, int(item.get("line") or 1)),
                "column": max(1, int(item.get("column") or 1)),
                "severity": str(item.get("severity") or "error"),
                "code": str(item.get("code") or ""), "message": str(item.get("message") or "")[:1000],
                "source": str(item.get("source") or "lsp"), "symbol": str(item.get("symbol") or ""),
                "command": [], "trust": "tool_evidence",
            })
        return rows

    @staticmethod
    def _semantic_repo_map(graph: dict[str, Any]) -> dict[str, Any]:
        nodes = []
        for item in graph.get("graphs") or [graph]:
            nodes.extend(item.get("nodes") or [])
        paths = sorted({str(node.get("path")) for node in nodes if node.get("kind") == "symbol"})
        return {"files": [{
            "path": path,
            "symbols": [{"name": node.get("name"), "line": node.get("line"), "kind": node.get("symbol_kind"), "id": node.get("id")} for node in nodes if node.get("kind") == "symbol" and node.get("path") == path],
        } for path in paths]}

    def parse(self, repo: Path, output: str, command: list[str]) -> list[dict[str, Any]]:
        rows, seen = [], set()
        for source, pattern in self.PATTERNS:
            for match in pattern.finditer(output or ""):
                values = match.groupdict()
                rel = self._relative(repo, values.get("path") or "")
                if not rel:
                    continue
                line = max(1, int(values.get("line") or 1))
                column = max(1, int(values.get("column") or 1))
                message = (values.get("message") or self._nearby_message(output, match.end())).strip()[:1000]
                key = (rel, line, column, message)
                if key in seen:
                    continue
                seen.add(key)
                severity = str(values.get("severity") or "error").lower()
                rows.append({
                    "path": rel, "line": line, "column": column,
                    "severity": severity if severity in {"error", "warning", "info"} else "error",
                    "code": str(values.get("code") or "")[:100],
                    "message": message, "source": source,
                    "symbol": str(values.get("symbol") or ""),
                    "command": list(map(str, command)), "trust": "tool_evidence",
                })
        return rows

    def classify(self, output: str, *, nonzero: bool, timed_out: bool) -> tuple[str, float, str]:
        text = (output or "").lower()
        if not nonzero and not timed_out:
            return "none", 1.0, "all commands exited successfully"
        if timed_out:
            return "environment_failure", 0.9, "command exceeded its execution limit"
        marker = next((item for item in self.ENVIRONMENT_MARKERS if item in text), "")
        if marker:
            return "environment_failure", 0.9, f"matched environment marker: {marker}"
        marker = next((item for item in self.REQUIREMENT_MARKERS if item in text), "")
        if marker:
            return "requirements_failure", 0.85, f"matched requirements marker: {marker}"
        if any(item in text for item in (
            "syntaxerror", "compile error", "typeerror", "nameerror", "undefined",
            "undefined:", "undeclared", "cannot find name", "could not find",
        )):
            return "implementation_failure", 0.8, "compiler/runtime implementation diagnostic"
        marker = next((item for item in self.ASSERTION_MARKERS if item in text), "")
        if marker:
            return "test_failure", 0.85, f"matched test marker: {marker}"
        return "implementation_failure", 0.55, "non-zero execution without an environment marker"

    def link_symbols(
        self, repo: Path, diagnostics: list[dict[str, Any]], repo_map: dict[str, Any]
    ) -> list[dict[str, Any]]:
        maps = {str(item.get("path")): item for item in repo_map.get("files") or []}
        rows = []
        for diagnostic in diagnostics:
            row = dict(diagnostic)
            symbols = list((maps.get(row["path"]) or {}).get("symbols") or [])
            if not symbols and row["path"].endswith(".py"):
                try:
                    tree = ast.parse((repo / row["path"]).read_text(encoding="utf-8"))
                    symbols = [
                        {"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "line": node.lineno}
                        for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    ]
                except (OSError, SyntaxError, UnicodeError):
                    symbols = []
            preceding = [item for item in symbols if int(item.get("line") or 0) <= row["line"]]
            nearest = max(preceding, key=lambda item: int(item.get("line") or 0), default=None)
            if nearest and not row.get("symbol"):
                row["symbol"] = str(nearest.get("name") or "")
            row["related_symbol"] = {
                "path": row["path"], "name": row.get("symbol") or "",
                "definition_line": int((nearest or {}).get("line") or row["line"]),
            }
            rows.append(row)
        return rows

    @staticmethod
    def _relative(repo: Path, value: str) -> str:
        cleaned = str(value or "").strip().replace("\\", "/")
        if not cleaned:
            return ""
        candidate = Path(cleaned)
        if not candidate.is_absolute():
            candidate = repo / candidate
        try:
            relative = candidate.resolve().relative_to(repo)
        except (OSError, ValueError):
            return ""
        return relative.as_posix() if (repo / relative).is_file() else ""

    @staticmethod
    def _nearby_message(output: str, offset: int) -> str:
        tail = output[offset:].lstrip("\r\n ").splitlines()
        return tail[0] if tail else "stack frame"

    @staticmethod
    def _related_symbols(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = {}
        for row in rows:
            symbol = row.get("related_symbol") or {}
            key = (symbol.get("path"), symbol.get("name"), symbol.get("definition_line"))
            if key[0]:
                unique[key] = symbol
        return list(unique.values())[:100]


class CodingEvidenceGate:
    """Bound repository reads and decide whether patch evidence is sufficient."""

    def __init__(self, initial_manifest: dict[str, Any], max_observations: int = 6):
        self.max_observations = max(2, min(int(max_observations), 12))
        self.initial_paths = {
            str(item.get("path")) for item in initial_manifest.get("code_evidence") or []
            if item.get("path")
        }
        self.observed_paths: set[str] = set()
        self.actions: set[str] = set()
        self.observation_count = 0

    def register(self, action: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        fingerprint = repr(sorted((key, str(value)) for key, value in action.items()))
        duplicate = fingerprint in self.actions
        self.actions.add(fingerprint)
        self.observation_count += 1
        path = str(observation.get("path") or "")
        if path:
            self.observed_paths.add(path)
        successful = len(self.actions)
        sufficient = bool(self.initial_paths or self.observed_paths) and successful >= 1
        exhausted = len(self.actions) >= self.max_observations
        retrieval_complete = sufficient and self.observation_count >= 1
        return {
            "schema": "clawos.coding-evidence-gate.v1",
            "sufficient": sufficient, "duplicate": duplicate,
            "retrieval_exhausted": exhausted,
            "continue_retrieval": not duplicate and not exhausted and not retrieval_complete,
            "observed_paths": sorted(self.observed_paths),
            "reason": "duplicate observation" if duplicate else (
                "evidence budget exhausted" if exhausted else "target evidence sufficient; stop retrieval and act" if retrieval_complete else "target evidence missing"
            ),
        }

    def patch_ready(self) -> bool:
        return bool(self.initial_paths or self.observed_paths)

    def retrieval_complete(self) -> bool:
        return self.observation_count >= 1 and bool(self.initial_paths or self.observed_paths)

    def reopen_after_failure(self) -> None:
        """Allow one targeted retrieval cycle when new diagnostics add evidence."""
        self.observation_count = 0

    def automatic_target(self) -> str:
        return sorted(self.initial_paths)[0] if self.initial_paths else ""
