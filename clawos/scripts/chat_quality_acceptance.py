"""Synthetic chat acceptance/preview using real handlers and an isolated database.

--live explicitly enables the configured model (may incur provider charges).
No production memories, uploads, vector collection or database are loaded.
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import clawos_server as server
from memoryos.context_builder import ContextBuilder
from memoryos.memory_store import MemoryStore
from providers import create_model_provider
from security import ToolSecurityPolicy
from services.task_service import TaskService


def configure(directory, live):
    directory.mkdir(parents=True, exist_ok=True)
    server.config = server.load_config(server.CONFIG_PATH) if live else server.normalize_config({
        'model_provider': {'provider': 'mock', 'model': 'mock-chat', 'mock_response': '这是隔离预览。'}})
    server.logger = logging.getLogger('chat-acceptance')
    server.g_memory_store = MemoryStore(str(directory / 'chat.db'))
    server.g_context_builder = ContextBuilder(server.g_memory_store)
    server.g_task_service = TaskService(server.g_memory_store)
    server.g_security_policy = ToolSecurityPolicy(allowed_roots=[directory])
    server.g_routing_provider = create_model_provider(server.config['routing'])
    server.g_upstream_provider = create_model_provider(server.config['upstream'])
    server.OUTPUT_ROOT = directory / 'artifacts'
    server.tools_def = server.load_tools(ROOT / 'functions.jsonl')
    server.g_mtclaw_adapter = None
    server.g_vector_store = None
    server.g_reflection_engine = None
    return server.g_memory_store


async def run(directory):
    cases = [
        ('plain', '用两句话解释为什么缓存失效会读到旧数据，不要标题、口号或开场白。'),
        ('format', '只根据以下数据回答：甲方案成本10元、耗时3秒；乙方案成本20元、耗时1秒。先用一句话说明取舍，再用Markdown表格列出两方案，最后给一个Python字典代码块保存数据。'),
        ('history', '本次方案名字叫青禾，预算是37元。请只确认这两项。'),
        ('history', '刚才的方案名字和预算是什么？只回答事实。'),
        ('tool', '计算 137 * 29，只给结果。'),
    ]
    rows = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://qa') as client:
        for case, prompt in cases:
            response = await client.post('/v1/chat/completions', json={
                'session_id': f'acceptance-{case}', 'clawos_web_search_mode': 'off',
                'messages': [{'role': 'user', 'content': prompt}],
            })
            data = response.json()
            text = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
            meta = data.get('clawos', {})
            rows.append(dict(case=case, prompt=prompt, answer=text, status=response.status_code,
                             model_result=meta.get('model_result'), task_id=meta.get('task_id'),
                             used_tools=meta.get('used_tools'), failed=meta.get('status') == 'failed'))
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (directory / 'live-report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return not any(row['failed'] or row['status'] != 200 or not row['answer'] for row in rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=18901)
    parser.add_argument('--output', default=str(ROOT / 'output' / 'chat-quality-acceptance'))
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    configure(directory, args.live)
    if args.serve:
        # Use the production HTTP handlers without the production startup lifecycle.
        app = FastAPI()
        for route in server.app.routes:
            if not isinstance(route, __import__('starlette.routing', fromlist=['Mount']).Mount):
                app.router.routes.append(route)
        app.mount('/assets', StaticFiles(directory=server.STATIC_DIR / 'assets'))
        app.mount('/static', StaticFiles(directory=server.STATIC_DIR))
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
    else:
        raise SystemExit(0 if asyncio.run(run(directory)) else 1)


if __name__ == '__main__': main()
