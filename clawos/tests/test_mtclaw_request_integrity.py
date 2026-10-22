import asyncio
import json
import sys
import unittest
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent/'MTClaw-框架代码'))
from mtclaw.adapter import MTClawAdapter


class RequestIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_cannot_claim_old_or_parallel_same_session_call(self):
        request_id=None
        async def handle(request):
            nonlocal request_id
            if request.method=='POST':
                request_id=request.headers['x-clawos-request-id']
                return httpx.Response(200,json=dict(choices=[dict(message=dict(content='current response'))]))
            def entry(rid,name):return dict(request_id=rid,session_key='same',tool_calls=[dict(id=name,name=name,arguments='{}')],tool_results=[])
            return httpx.Response(200,json=dict(entries=[entry('old','old_tool'),entry('concurrent','concurrent_tool'),entry(request_id,'current_tool')]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result=await MTClawAdapter(dict(enabled=True,base_url='http://router'),client).route([dict(role='user',content='test')],'same')
        self.assertEqual([t['function_name'] for t in result['trace']],['current_tool'])
        self.assertEqual(result['trace'][0]['request_id'],request_id)
        self.assertTrue(result['trace'][0]['is_error'])  # call without a result is not successful evidence

    async def test_old_router_trace_is_not_falsely_attributed_and_empty_reply_fails(self):
        async def handle(request):
            if request.method=='POST':return httpx.Response(200,json=dict(choices=[dict(message=dict(content='answer'))]))
            return httpx.Response(200,json=dict(entries=[dict(session_key='same',tool_calls=[dict(name='old')])]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            r=await MTClawAdapter(dict(enabled=True,base_url='http://router'),client).route([],'same')
            self.assertTrue(r['ok']);self.assertEqual(r['trace'],[]);self.assertEqual(r['trace_status'],'no_current_tool_evidence')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=dict(choices=[dict(message=dict(content=''))])))) as client:
            r=await MTClawAdapter(dict(enabled=True,base_url='http://router'),client).route([],'same')
            self.assertFalse(r['ok']);self.assertEqual(r['error'],'ValueError')

    async def test_same_session_turns_serialize_and_lock_entries_are_released(self):
        active=0;peak=0
        async def handle(request):
            nonlocal active,peak
            if request.method=='POST':
                active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1
                return httpx.Response(200,json=dict(choices=[dict(message=dict(content='answer'))]))
            return httpx.Response(200,json=dict(entries=[]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            adapter=MTClawAdapter(dict(enabled=True,base_url='http://router'),client)
            result=await asyncio.gather(*[adapter.route([],'same') for _ in range(4)])
            self.assertTrue(all(r['ok'] for r in result));self.assertEqual(peak,1);self.assertEqual(adapter._sessions,{})

    def test_memory_context_preserved_bounded_without_importing_tool_calls(self):
        from function_router.server import clawos_context
        context=clawos_context([dict(role='system',content='Memory: project is local'),dict(role='assistant',content='Previous answer',tool_calls=[dict(id='old')]),dict(role='tool',content='old tool result'),dict(role='user',content='Current request')])
        self.assertIn('project is local',context[0]['content']);self.assertEqual(context[1]['content'],'Previous answer')
        self.assertFalse(any('tool_calls' in m or m['role']=='tool' for m in context))
        self.assertLessEqual(sum(len(m['content']) for m in clawos_context([dict(role='system',content='x'*50000),dict(role='user',content='now')])),20100)

    async def test_router_history_endpoint_filters_request_and_session(self):
        from function_router import server
        previous=list(server.TOOL_HISTORY);server.TOOL_HISTORY.clear()
        self.addCleanup(lambda:(server.TOOL_HISTORY.clear(),server.TOOL_HISTORY.extend(previous)))
        server.TOOL_HISTORY.extend([dict(timestamp='1',session_key='A',request_id='one'),dict(timestamp='2',session_key='A',request_id='two'),dict(timestamp='3',session_key='B',request_id='two')])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(server.app),base_url='http://router') as client:
            r=await client.get('/v1/tool_history',params=dict(session_key='A',request_id='two'))
        self.assertEqual([x['timestamp'] for x in r.json()['entries']],['2'])

    async def test_router_ready_requires_warmup_tools_and_model(self):
        from function_router import server
        from unittest.mock import patch,AsyncMock
        previous_tools,previous_warmup=server.STATE.tools,server.STATE.warmup_ok
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(server.app),base_url='http://router') as client:
                for warmup,tools,model,expected in [(False,[{}],True,503),(True,[],True,503),(True,[{}],False,503),(True,[{}],True,200)]:
                    server.STATE.tools,server.STATE.warmup_ok=tools,warmup
                    with patch.object(server,'qwen_health_check',new=AsyncMock(return_value=model)):
                        self.assertEqual((await client.get('/ready')).status_code,expected)
        finally:server.STATE.tools,server.STATE.warmup_ok=previous_tools,previous_warmup

    def test_upstream_receives_observation_not_router_prose_or_executable_calls(self):
        from function_router.server import _build_upstream_request
        result=_build_upstream_request(dict(messages=[dict(role='system',content='Memory'),dict(role='user',content='Current question')]),session_key='isolated',tool_context=[dict(role='assistant',content='Unverified claim',tool_calls=[dict(id='x')]),dict(role='tool',name='time_now',tool_call_id='x',content='{"datetime":"2026-10-02 21:00:00"}')])
        text=json.dumps(result)
        self.assertIn('2026-10-02 21:00:00',text);self.assertNotIn('Unverified claim',text);self.assertNotIn('tool_calls',text)
        self.assertEqual(result['messages'][-1]['content'],'Current question')

    async def test_clawos_runtime_disables_unrestricted_builtins_and_interception(self):
        from function_router import server
        from mtclaw.prepare_runtime import prepare
        import tempfile
        previous_config,previous_tools=server.STATE.config,server.STATE.tools
        try:
            with tempfile.TemporaryDirectory() as td:
                result=prepare(Path(td));config=json.loads(Path(result['config']).read_text(encoding='utf-8'))
                self.assertFalse(config['builtin_tools_enabled'])
                # Loading config may expand env keys; the policy itself is not optional.
                server.STATE.config=server.AppConfig('127.0.0.1',1,server.ModelConfig('http://a','a',''),server.ModelConfig('http://a','a',''),'functions.jsonl','scripts',1,3,Path(td),Path(td)/'config.json',builtin_tools_enabled=False)
                server.STATE.tools=server.load_tools(Path(result['functions']))
                self.assertNotIn('sleep',{t['function']['name'] for t in server.STATE.tools})
                self.assertIn('ls',{t['function']['name'] for t in server.STATE.tools})
                denied=await server.execute_tool('find','{}');self.assertIn('whitelist',denied['error'])
                from unittest.mock import patch,AsyncMock
                # ls must use the guarded wrapper, never the unbounded builtin.
                with patch.object(server,'execute_builtin_tool',side_effect=AssertionError('unguarded builtin')):
                    r=await server.execute_tool('ls',json.dumps({'path':str(Path(td))}))
                    self.assertIsInstance(r,dict)
        finally:server.STATE.config,server.STATE.tools=previous_config,previous_tools

if __name__=='__main__':unittest.main()
