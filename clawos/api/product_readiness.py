"""Product-readiness API boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.product_readiness_service import ProductReadinessService


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def create_product_readiness_router(
    repository_root: str | Path,
    output_root: str | Path,
    *,
    learning_provider: Callable[[], dict[str, Any]],
    hardware_provider: Callable[[], dict[str, Any]],
) -> APIRouter:
    root = Path(repository_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    router = APIRouter(tags=["product-readiness"])

    @router.get("/api/product/readiness")
    async def product_readiness() -> JSONResponse:
        evaluator = _load_json(
            output / "coding-evaluator" / "summary.json"
        )
        outcome = _load_json(
            output / "coding-benchmark" / "latest.json"
        )
        ide_artifact = _load_json(
            output / "evidence" / "vscode-extension.json"
        )
        result = ProductReadinessService(root).report(
            learning=learning_provider(),
            evaluator=evaluator,
            outcome_benchmark=outcome,
            hardware=hardware_provider(),
            ide_artifact=ide_artifact,
        )
        return JSONResponse(result)

    return router
