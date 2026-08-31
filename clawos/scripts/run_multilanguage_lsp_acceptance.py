"""Build real semantic graphs for locally installed language servers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.lsp_bridge_service import LanguageServerManager
from services.lsp_semantic_graph_service import LSPSemanticGraphService, LanguageServerDiscovery


FIXTURES = {
    "typescript": ("main.ts", "export function add(a:number,b:number){return a+b}\nexport function use(){return add(1,2)}\nmissingSymbol();\n"),
    "go": ("main.go", "package sample\nfunc Add(a int,b int) int{return a+b}\nfunc Use() int{return Add(1,2)}\nvar _ = MissingSymbol\n"),
    "rust": ("src/lib.rs", "pub fn add(a:i32,b:i32)->i32{a+b}\npub fn use_add()->i32{add(1,2)}\npub fn broken(){ missing_symbol(); }\n"),
    "c": ("main.c", "int add(int a,int b){return a+b;}\nint use_add(void){return add(1,2);}\nint broken(void){return missing_symbol;}\n"),
    "csharp": ("Program.cs", "static int Add(int a,int b)=>a+b;\nSystem.Console.WriteLine(Add(1,2));\nSystem.Console.WriteLine(MissingSymbol);\n"),
}


def main(output: str = "output/coding-benchmark/multilanguage-lsp-acceptance.json") -> dict:
    discovery = LanguageServerDiscovery().discover()
    manager, rows = LanguageServerManager(), []
    try:
        with tempfile.TemporaryDirectory(prefix="clawos-lsp-acceptance-", ignore_cleanup_errors=True) as td:
            root = Path(td)
            for language, (rel, content) in FIXTURES.items():
                repo = root / language; repo.mkdir()
                subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
                path = repo / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
                if language == "go": (repo / "go.mod").write_text("module example.test/sample\n\ngo 1.24\n", encoding="utf-8")
                if language == "rust": (repo / "Cargo.toml").write_text('[package]\nname="sample"\nversion="0.1.0"\nedition="2021"\n', encoding="utf-8")
                if language == "typescript": (repo / "tsconfig.json").write_text('{"compilerOptions":{"strict":true}}\n', encoding="utf-8")
                if language == "csharp": (repo / "Sample.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework></PropertyGroup></Project>', encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                row = discovery["languages"].get(language) or {}
                if not row.get("available"):
                    rows.append({"language": language, "skipped": True, "reason": "language server unavailable"}); continue
                service = LSPSemanticGraphService(manager=manager, cache_root=root / "cache")
                try:
                    graph = service.build(
                        repo, language=language, command=row["command"], files=[rel],
                        max_symbols=40, include_calls=False,
                        timeout_seconds=60 if language == "csharp" else 15,
                    )
                    rows.append({"language": language, "available": True, "command": row["command"], "metrics": graph["metrics"], "capabilities": sorted(graph["server"]["capabilities"]), "stderr_tail": graph["server"].get("stderr_tail") or []})
                except Exception as exc:  # acceptance records server-specific failures
                    rows.append({"language": language, "available": True, "failed": True, "error": f"{type(exc).__name__}: {exc}"})
            manager.stop_all()
    finally:
        manager.stop_all()
    report = {"schema": "clawos.multilanguage-lsp-acceptance.v1", "discovery": discovery, "languages": rows, "passed": sum(bool(row.get("metrics")) for row in rows), "failed": sum(bool(row.get("failed")) for row in rows), "skipped": sum(bool(row.get("skipped")) for row in rows)}
    target = Path(output).resolve(); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(target)
    return report


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
