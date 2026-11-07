"""Benchmarks HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import json


class BenchmarksAPI:
    def __init__(self, *,
        create_runtime_task: Callable[..., Any],
        execute_tool_call: Callable[..., Any],
        finish_runtime_task: Callable[..., Any],
        scenario_benchmark_provider: Callable[[], Any],
    ):
        self.create_runtime_task = create_runtime_task
        self.execute_tool_call = execute_tool_call
        self.finish_runtime_task = finish_runtime_task
        self.scenario_benchmark_provider = scenario_benchmark_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/benchmarks/scenarios/suites', self.api_scenario_benchmark_suites, methods=['GET'])
        self.router.add_api_route('/api/benchmarks/scenarios/suites', self.api_scenario_benchmark_create_suite, methods=['POST'])
        self.router.add_api_route('/api/benchmarks/scenarios/runs', self.api_scenario_benchmark_runs, methods=['GET'])
        self.router.add_api_route('/api/benchmarks/scenarios/run', self.api_scenario_benchmark_run, methods=['POST'])

    async def api_scenario_benchmark_suites(self):
        if not self.scenario_benchmark_provider():
            return JSONResponse({"suites": [], "count": 0}, status_code=503)
        rows = self.scenario_benchmark_provider().list_suites()
        return JSONResponse({"suites": rows, "count": len(rows)})


    async def api_scenario_benchmark_create_suite(self, request: Request):
        if not self.scenario_benchmark_provider():
            raise HTTPException(503, "Scenario benchmark is unavailable")
        data = await request.json()
        try:
            suite = self.scenario_benchmark_provider().create_suite(
                str(data.get("name", "")),
                data.get("cases") or [],
                description=str(data.get("description", "")),
                created_by=str(data.get("created_by", "user")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(suite)


    async def api_scenario_benchmark_runs(self, suite_id: int = 0, limit: int = 50):
        if not self.scenario_benchmark_provider():
            return JSONResponse({"runs": [], "count": 0}, status_code=503)
        rows = self.scenario_benchmark_provider().list_runs(suite_id=suite_id, limit=limit)
        return JSONResponse({"runs": rows, "count": len(rows)})


    async def api_scenario_benchmark_run(self, request: Request):
        if not self.scenario_benchmark_provider():
            raise HTTPException(503, "Scenario benchmark is unavailable")
        data = await request.json()
        suite_id = int(data.get("suite_id", 0) or 0)
        if not suite_id:
            suites = self.scenario_benchmark_provider().list_suites()
            suite_id = int(suites[-1]["id"] if suites else 0)

        def runner(tool_name: str, args: dict[str, Any]):
            task = self.create_runtime_task(
                "benchmark",
                f"Benchmark: {tool_name}",
                source="scenario_benchmark",
                metadata={"tool": tool_name, "args": args},
            )
            result = self.execute_tool_call(
                tool_name,
                json.dumps(args or {}, ensure_ascii=False),
                session_id="benchmark",
                confirmed_tools=set(data.get("confirmed_tools") or []),
                task_id=task.get("id"),
            )
            self.finish_runtime_task(task.get("id"), "succeeded" if result.get("ok") else "failed")
            return result

        try:
            run = self.scenario_benchmark_provider().run_suite(
                suite_id,
                runner,
                thresholds=data.get("thresholds") or {},
                created_by=str(data.get("created_by", "user")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(run)
