"""Evidence benchmark for multi-language failure classification and repair."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .coding_diagnostics_service import CodingDiagnosticsService


class CodingMultilanguageBenchmark:
    """Run real local compiler/test commands over temporary Git repositories."""

    CASES = (
        {
            "id": "typescript-implementation", "language": "typescript", "expected": "implementation_failure",
            "requires": "tsc", "files": {"app.ts": "export const value:number = MissingName;\n"},
            "command": ["tsc", "--noEmit", "app.ts"], "repair": ("app.ts", "MissingName", "1"),
        },
        {
            "id": "go-implementation", "language": "go", "expected": "implementation_failure",
            "requires": "go", "files": {"go.mod": "module example.test/case\n\ngo 1.24\n", "case.go": "package sample\nvar Value = MissingName\n"},
            "command": ["go", "test", "./..."], "repair": ("case.go", "MissingName", "1"),
        },
        {
            "id": "rust-implementation", "language": "rust", "expected": "implementation_failure",
            "requires": "cargo", "files": {"Cargo.toml": '[package]\nname="case"\nversion="0.1.0"\nedition="2021"\n', "src/lib.rs": "pub const VALUE:i32 = MISSING_NAME;\n"},
            "command": ["cargo", "check", "--quiet"], "repair": ("src/lib.rs", "MISSING_NAME", "1"),
        },
        {
            "id": "python-test", "language": "python", "expected": "test_failure",
            "files": {"calc.py": "def add(a,b):\n return a-b\n", "test_calc.py": "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n"},
            "command": ["python", "-m", "unittest", "test_calc.py"],
            "repair": ("calc.py", "return a-b", "return a+b"),
        },
        {
            "id": "python-implementation", "language": "python", "expected": "implementation_failure",
            "files": {"app.py": "def run():\n return missing_name\nrun()\n"},
            "command": ["python", "app.py"], "repair": ("app.py", "missing_name", "1"),
        },
        {
            "id": "c-implementation", "language": "c", "expected": "implementation_failure",
            "requires": "gcc", "files": {"main.c": "int main(void){ return missing; }\n"},
            "command": ["gcc", "-fsyntax-only", "main.c"], "repair": ("main.c", "missing", "0"),
        },
        {
            "id": "c-test", "language": "c", "expected": "test_failure",
            "requires": "gcc", "files": {"main.c": "#include <stdio.h>\nint add(int a,int b){return a-b;}\nint main(void){if(add(2,3)!=5){fprintf(stderr,\"AssertionError: expected 5\\n\");return 1;}return 0;}\n"},
            "command": ["gcc", "main.c", "-o", "case.exe"], "after_command": ["case.exe"],
            "repair": ("main.c", "return a-b", "return a+b"),
        },
        {
            "id": "dotnet-implementation", "language": "csharp", "expected": "implementation_failure",
            "requires": "dotnet", "requires_probe": ["dotnet", "--list-sdks"], "files": {
                "Case.csproj": '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><RestoreIgnoreFailedSources>true</RestoreIgnoreFailedSources></PropertyGroup></Project>',
                "Program.cs": 'System.Console.WriteLine(MissingName);\n',
            },
            "command": ["dotnet", "build", "--nologo", "--ignore-failed-sources"],
            "repair": ("Program.cs", "MissingName", '"ok"'),
        },
        {
            "id": "environment", "language": "generic", "expected": "environment_failure",
            "files": {"README.md": "fixture\n"}, "command": ["definitely-missing-clawos-runtime"],
            "repair": None,
        },
        {
            "id": "requirements", "language": "generic", "expected": "requirements_failure",
            "files": {"requirements.txt": "acceptance criteria missing\n"},
            "synthetic": "acceptance criteria missing", "repair": None,
        },
    )

    def run(self, output_path: str | Path | None = None) -> dict[str, Any]:
        analyzer = CodingDiagnosticsService()
        rows = []
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="clawos-multilang-") as td:
            root = Path(td)
            for case in self.CASES:
                required = str(case.get("requires") or "")
                resolved = self._resolve_executable(required) if required else ""
                if required and not resolved:
                    rows.append({"id": case["id"], "language": case["language"], "skipped": True, "reason": f"{required} unavailable"})
                    continue
                probe = list(case.get("requires_probe") or [])
                if probe:
                    probed = self._execute(root, self._resolved_command(probe))
                    if probed["exit_code"] != 0 or not str(probed.get("stdout") or "").strip():
                        rows.append({
                            "id": case["id"], "language": case["language"],
                            "skipped": True, "reason": f"{required} runtime exists but required SDK/toolchain is unavailable",
                        })
                        continue
                repo = root / str(case["id"]); repo.mkdir()
                for rel, content in case["files"].items():
                    path = repo / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
                subprocess.run(["git", "init"], cwd=repo, capture_output=True)
                if case.get("synthetic"):
                    execution = {"command": ["synthetic"], "exit_code": 1, "stdout": "", "stderr": case["synthetic"], "timed_out": False}
                else:
                    execution = self._execute(repo, self._resolved_command(list(case["command"])))
                    if execution["exit_code"] == 0 and case.get("after_command"):
                        after = list(case["after_command"])
                        after[0] = str(repo / after[0])
                        execution = self._execute(repo, after)
                analysis = analyzer.analyze(repo, [execution])
                classified = analysis["failure_category"] == case["expected"]
                repair_success = None
                if case.get("repair"):
                    rel, old, new = case["repair"]
                    path = repo / rel; path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
                    # Avoid same-size/same-timestamp stale Python bytecode making a
                    # successful source repair look like a failure in a fast fixture.
                    shutil.rmtree(repo / "__pycache__", ignore_errors=True)
                    repaired = self._execute(repo, self._resolved_command(list(case["command"])))
                    if repaired["exit_code"] == 0 and case.get("after_command"):
                        after = list(case["after_command"]); after[0] = str(repo / after[0]); repaired = self._execute(repo, after)
                    repair_success = repaired["exit_code"] == 0
                rows.append({
                    "id": case["id"], "language": case["language"], "expected": case["expected"],
                    "actual": analysis["failure_category"], "classified_correctly": classified,
                    "repair_attempted": repair_success is not None, "repair_success": repair_success,
                    "diagnostic_count": len(analysis["diagnostics"]),
                    "classification_reason": analysis["classification_reason"],
                })
        executed = [item for item in rows if not item.get("skipped")]
        repairs = [item for item in executed if item.get("repair_attempted")]
        report = {
            "schema": "clawos.coding-multilanguage-benchmark.v1", "cases": rows,
            "metrics": {
                "total_cases": len(rows), "executed_cases": len(executed), "skipped_cases": len(rows) - len(executed),
                "languages": sorted({item["language"] for item in executed}),
                "classification_accuracy": sum(item["classified_correctly"] for item in executed) / len(executed) if executed else 0.0,
                "repair_success_rate": sum(bool(item.get("repair_success")) for item in repairs) / len(repairs) if repairs else 0.0,
                "repair_cases": len(repairs), "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
            "truth_boundary": "Commands execute in temporary real Git repositories using locally installed runtimes; unavailable runtimes are skipped and reported.",
        }
        if output_path:
            target = Path(output_path).expanduser().resolve(); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["report_path"] = str(target)
        return report

    @staticmethod
    def _execute(repo: Path, command: list[str]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            environment = None
            if command and Path(command[0]).name.lower() in {"dotnet", "dotnet.exe"}:
                import os
                environment = dict(os.environ)
                environment.update({
                    "DOTNET_CLI_HOME": str(repo / ".dotnet-home"),
                    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                    "DOTNET_NOLOGO": "1",
                })
            elif command and Path(command[0]).name.lower() in {"tsc", "tsc.cmd"}:
                import os
                environment = dict(os.environ)
                node_dir = str(Path("C:/Program Files/nodejs"))
                environment["PATH"] = node_dir + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(command, cwd=repo, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            return {"command": command, "exit_code": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:], "timed_out": False, "duration_ms": round((time.perf_counter()-started)*1000,2)}
        except FileNotFoundError as exc:
            return {"command": command, "exit_code": 127, "stdout": "", "stderr": f"command not found: {exc}", "timed_out": False}
        except subprocess.TimeoutExpired as exc:
            return {"command": command, "exit_code": 124, "stdout": str(exc.stdout or ""), "stderr": str(exc.stderr or ""), "timed_out": True}

    @classmethod
    def _resolved_command(cls, command: list[str]) -> list[str]:
        if not command: return command
        return [cls._resolve_executable(command[0]) or command[0], *command[1:]]

    @staticmethod
    def _resolve_executable(name: str) -> str:
        standard = {
            "tsc": Path.home() / "AppData/Roaming/npm/tsc.cmd",
            "go": Path("C:/Program Files/Go/bin/go.exe"),
            "cargo": Path.home() / ".cargo/bin/cargo.exe",
            "rustc": Path.home() / ".cargo/bin/rustc.exe",
            "clang": Path("C:/Program Files/LLVM/bin/clang.exe"),
            "clangd": Path("C:/Program Files/LLVM/bin/clangd.exe"),
            "dotnet": Path.home() / "AppData/Local/Microsoft/dotnet-sdk/dotnet.exe",
        }.get(name)
        if standard and standard.is_file(): return str(standard)
        return shutil.which(name) or ""
