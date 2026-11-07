"""Tools HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi.responses import JSONResponse


class ToolsAPI:
    def __init__(self, *,
        memory_store_provider: Callable[[], Any],
        tools_def_provider: Callable[[], Any],
    ):
        self.memory_store_provider = memory_store_provider
        self.tools_def_provider = tools_def_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/tools/list', self.api_tools_list, methods=['GET'])
        self.router.add_api_route('/api/tools/executions', self.api_tool_executions, methods=['GET'])
        self.router.add_api_route('/api/tools/accuracy', self.api_tools_accuracy, methods=['GET'])

    async def api_tools_list(self):
        items = []
        for t in self.tools_def_provider():
            fn = t.get("function", {})
            items.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        return JSONResponse({"tools": items, "count": len(items)})


    async def api_tool_executions(self, session_id: str = "", limit: int = 50):
        if not self.memory_store_provider():
            return JSONResponse({"executions": [], "count": 0}, status_code=503)
        rows = self.memory_store_provider().list_tool_executions(session_id, limit)
        return JSONResponse({"executions": rows, "count": len(rows)})


    async def api_tools_accuracy(self, session_id: str = "", limit: int = 200):
        if not self.memory_store_provider():
            return JSONResponse({"tools": [], "count": 0}, status_code=503)
        rows = self.memory_store_provider().list_tool_executions(session_id, limit)
        stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = row.get("tool_name") or "unknown"
            item = stats.setdefault(name, {"tool": name, "calls": 0, "success": 0, "errors": 0, "confirmations": 0, "duration_total": 0.0})
            item["calls"] += 1
            item["duration_total"] += float(row.get("duration_ms") or 0)
            if row.get("status") == "success":
                item["success"] += 1
            else:
                item["errors"] += 1
            if row.get("requires_confirmation"):
                item["confirmations"] += 1
        tools = []
        for item in stats.values():
            calls = max(1, int(item["calls"]))
            tools.append({
                "tool": item["tool"],
                "calls": item["calls"],
                "success": item["success"],
                "errors": item["errors"],
                "success_rate": round(item["success"] / calls, 4),
                "confirmation_rate": round(item["confirmations"] / calls, 4),
                "avg_duration_ms": round(item["duration_total"] / calls, 2),
            })
        tools.sort(key=lambda x: (-x["calls"], x["tool"]))
        return JSONResponse({"tools": tools, "count": len(tools)})
