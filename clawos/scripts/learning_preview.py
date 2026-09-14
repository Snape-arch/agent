"""Loopback-only Academy QA with actual HTTP handlers and an isolated store."""
import sys
import argparse
from contextlib import asynccontextmanager, nullcontext
import httpx
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import clawos_server as server
from memoryos.memory_store import MemoryStore
from services.learning_product_service import LearningProductService


def main():
    parser = argparse.ArgumentParser(description="Isolated Academy preview")
    parser.add_argument("--models", action="store_true", help="Use the existing configured provider only on explicit model actions")
    parser.add_argument("--port", type=int, default=18897)
    parser.add_argument("--session", help="Persistent QA session name under ignored output/learning-preview")
    args = parser.parse_args()
    @asynccontextmanager
    async def preview_lifespan(app):
        if args.models:
            server.config = server.load_config(server.CONFIG_PATH)
            server.g_routing_provider = server.create_model_provider(server.config.get("routing", {}))
            async with httpx.AsyncClient(timeout=75) as client:
                server.http_client = client
                yield
            server.http_client = None
        else:
            yield
    # Keep temporary QA state in the ignored workspace output directory. Some
    # desktop sessions clean OS temp storage between turns while uvicorn lives.
    qa_root = Path(__file__).resolve().parents[1] / "output" / "learning-preview"
    qa_root.mkdir(parents=True, exist_ok=True)
    if args.session:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.session):
            parser.error("session name must contain only letters, numbers, underscore or hyphen")
        session_dir = qa_root / args.session
        session_dir.mkdir(exist_ok=True)
        context = nullcontext(str(session_dir))
    else:
        context = tempfile.TemporaryDirectory(prefix="session-", dir=qa_root)
    with context as td:
        service = LearningProductService(MemoryStore(str(Path(td) / "learning.db")))
        course = service.create_course(course_key="qa-chinese", title="中文学习验收", description="隔离测试课程",
            topics=[{"topic_key": "reasoning", "title": "证据推理", "source_ref": "fixture:reasoning"}], created_by="qa")
        service.add_question(course["id"], topic_key="reasoning", prompt="请解释为什么需要检查答案证据，并用一个具体的例子说明。",
            expected_concepts=["证据", "检查"], cognitive_level="explain", difficulty=.5, source_ref="fixture:reasoning")
        service.publish_course(course["id"])
        server._learning_product = lambda: service
        server.OUTPUT_ROOT = Path(td) / "output"
        app = FastAPI(lifespan=preview_lifespan)
        for route in server.app.routes:
            if route.path.startswith("/api/academy/learning/") or route.path.startswith("/academy"):
                app.router.routes.append(route)
        app.mount("/static", StaticFiles(directory=server.STATIC_DIR), name="static")
        app.mount("/assets", StaticFiles(directory=server.STATIC_DIR / "assets"), name="assets")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
