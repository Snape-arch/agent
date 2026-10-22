import asyncio
import json
import logging
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clawos_server as server
from memoryos.context_builder import ContextBuilder
from memoryos.memory_store import MemoryStore
from services.task_service import TaskService
from providers.openai_compatible import OpenAICompatibleProvider
from test_model_provider import FakeHttpClient, FakeResponse


class Request:
    headers = {}
    def __init__(self, **kwargs):
        self.payload = dict(session_id='quality', messages=[dict(role='user', content='解释缓存的作用')], **kwargs)
    async def body(self):
        return json.dumps(self.payload).encode()


class ChatQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(str(Path(self.temp.name) / 'memory.db'))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in dict(g_memory_store=self.store, g_context_builder=ContextBuilder(self.store),
                               g_task_service=TaskService(self.store), g_mtclaw_adapter=None,
                               g_policy_optimizer=None, g_runtime_policy_controller=None,
                               g_reflection_engine=None, config={}, logger=logging.getLogger('qa')).items():
            self.stack.enter_context(patch.object(server, key, value))

    def test_completed_tool_answer_is_delivered_once_and_survives_reload(self):
        answer = '证据支持的回答。\n' + '正文' * 2300 + '\n```python\nprint(42)\n```'
        loop = AsyncMock(return_value=dict(used_tools=True, tool_calls=[], final_text=answer,
                                           answer_complete=True, model_result={'model': 'actual-model'}))
        upstream = AsyncMock(side_effect=AssertionError('must not rewrite a completed answer'))
        with patch.object(server, 'run_tool_loop', loop), patch.object(server, 'proxy_upstream', upstream):
            body = json.loads(asyncio.run(server.chat_completions(Request())).body)
        self.assertEqual(body['choices'][0]['message']['content'], answer)
        self.assertEqual(body['model'], 'actual-model')
        self.assertEqual(self.store.get_recent_messages('quality', 2)[-1]['content'], answer)
        upstream.assert_not_called()

    def test_failed_model_is_failed_task_for_json_and_stream(self):
        for stream in (False, True):
            with self.subTest(stream=stream), patch.object(server, 'run_tool_loop', AsyncMock(return_value=dict(
                used_tools=False, tool_calls=[], final_text='模型未能完成回答', model_error='empty_final_answer'
            ))):
                response = asyncio.run(server.chat_completions(Request(stream=stream)))
                if stream:
                    async def consume():
                        return b''.join([part async for part in response.body_iterator]).decode()
                    self.assertIn('"status": "failed"', asyncio.run(consume()))
                else:
                    self.assertEqual(json.loads(response.body)['clawos']['status'], 'failed')
                self.assertEqual(self.store.list_tasks(session_id='quality')[0]['status'], 'failed')

    def test_explicit_history_and_attachment_do_not_duplicate_current_question(self):
        builder = server.g_context_builder
        self.store.add_message('quality', 'user', '分析附件')
        supplied = [dict(role='user', content='计划名为青禾'), dict(role='assistant', content='已记录'), dict(role='user', content='分析附件')]
        result = builder.build_messages('quality', '分析附件\n\n[ClawOS hidden attachment context]\n数据', conversation_messages=supplied)
        self.assertEqual([m['content'] for m in result if m['role']=='user'], ['计划名为青禾', '分析附件\n\n[ClawOS hidden attachment context]\n数据'])

    def test_fallback_keeps_its_model_and_expands_list_config(self):
        class Provider:
            def __init__(self, ok): self.ok=ok; self.options=None
            async def complete(self, messages, options, **kwargs):
                self.options=options
                return dict(ok=self.ok, content='答复', raw={}, error='' if self.ok else 'network_error')
        primary, fallback = Provider(False), Provider(True)
        with patch.object(server, '_provider_candidates', return_value=[primary, fallback]):
            result=asyncio.run(server.call_model_with_fallback('upstream', [], {'model':'primary-only','max_tokens':100}))
        self.assertTrue(result['ok']); self.assertNotIn('model',fallback.options)
        self.assertEqual(fallback.options['max_tokens'],100)
        path=Path(self.temp.name)/'config.json'
        path.write_text(json.dumps({'model_fallbacks':[{'model':'${CLAWOS_QA_UNSET_MODEL:-local-model}'}]}))
        self.assertEqual(server.load_config(path)['model_fallbacks'][0]['model'],'local-model')

    def test_reasoning_truncation_and_empty_output_cannot_be_success(self):
        provider=OpenAICompatibleProvider(dict(base_url='http://localhost/v1',model='qa',requires_api_key=False))
        for message, finish, expected in [
            ({'content':'','reasoning_content':'private deliberation'},'stop','empty_final_answer'),
            ({'content':'unfinished'},'length','incomplete_output'),
            ({'content':'<think>private</think>'},'stop','empty_final_answer'),
        ]:
            with self.subTest(expected=expected):
                client=FakeHttpClient(FakeResponse({'choices':[{'message':message,'finish_reason':finish}]}))
                result=asyncio.run(provider.complete([],http_client=client))
                self.assertFalse(result['ok']); self.assertEqual(result['error'],expected)

    def test_content_blocks_and_tool_only_responses_are_valid(self):
        provider=OpenAICompatibleProvider(dict(base_url='http://localhost/v1',model='qa',requires_api_key=False))
        for message in ({'content':[{'type':'text','text':'最终答案'}]}, {'content':None,'tool_calls':[{'id':'t','type':'function','function':{'name':'calc','arguments':'{}'}}]}):
            result=asyncio.run(provider.complete([],http_client=FakeHttpClient(FakeResponse({'choices':[{'message':message}]}))))
            self.assertTrue(result['ok'])
            self.assertEqual(result['raw']['choices'][0]['message']['content'],result['content'])

    def test_unconfigured_primary_can_use_configured_fallback(self):
        from providers import create_model_provider
        primary = create_model_provider({'provider': 'deepseek', 'api_key': ''})
        fallback = create_model_provider({'provider': 'mock', 'model': 'offline'})
        with patch.object(server, '_provider_candidates', return_value=[primary, fallback]):
            self.assertTrue(server.has_api_key('routing'))

    def test_missing_answer_provider_does_not_dump_tool_json_or_report_success(self):
        loop = AsyncMock(return_value=dict(used_tools=True, tool_calls=[dict(name='calc', arguments='{}', result={'ok': True, 'data': {'result': 42}})], final_text=''))
        with patch.object(server, 'run_tool_loop', loop), patch.object(server, 'has_api_key', return_value=False):
            body = json.loads(asyncio.run(server.chat_completions(Request())).body)
        self.assertNotIn('Evidence/action result', body['choices'][0]['message']['content'])
        self.assertEqual(body['clawos']['status'], 'failed')
        self.assertEqual(self.store.list_tasks(session_id='quality')[0]['status'], 'failed')


if __name__ == '__main__': unittest.main()
