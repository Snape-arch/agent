"""Loopback-only Academy QA with actual HTTP handlers and an isolated store."""
import sys
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
    # Keep temporary QA state in the ignored workspace output directory. Some
    # desktop sessions clean OS temp storage between turns while uvicorn lives.
    qa_root = Path(__file__).resolve().parents[1] / "output" / "learning-preview"
    qa_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="session-", dir=qa_root) as td:
        service = LearningProductService(MemoryStore(str(Path(td) / "learning.db")))
        course = service.create_course(course_key="qa-chinese", title="中文学习验收", description="隔离测试课程",
            topics=[{"topic_key": "reasoning", "title": "证据推理", "source_ref": "fixture:reasoning"}], created_by="qa")
        service.add_question(course["id"], topic_key="reasoning", prompt="请解释为什么需要检查答案证据，并用一个具体的例子说明。",
            expected_concepts=["证据", "检查"], cognitive_level="explain", difficulty=.5, source_ref="fixture:reasoning")
        service.publish_course(course["id"])
        server._learning_product = lambda: service
        app = FastAPI()
        for route in server.app.routes:
            if route.path.startswith("/api/academy/learning/") or route.path.startswith("/academy"):
                app.router.routes.append(route)
        app.mount("/static", StaticFiles(directory=server.STATIC_DIR), name="static")
        app.mount("/assets", StaticFiles(directory=server.STATIC_DIR / "assets"), name="assets")
        uvicorn.run(app, host="127.0.0.1", port=18897, log_level="warning")


if __name__ == "__main__":
    main()
