"""Gateway trust boundaries; no production DB, source credentials or model calls."""
import json
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from services.vision_api import vision_router
from services.vision_runtime import VisionRuntime


class FakeRuntime:
    def __init__(self):self.started=0
    def status(self):return dict(running=False)
    def start(self):self.started+=1;return dict(running=True)
    def close(self):return dict(running=False)
    def endpoint(self):return 'http://127.0.0.1:19432','test-only-gateway-handshake'


class VisionGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        (self.root/'index.html').write_text('owned-frontend',encoding='utf-8');self.runtime=FakeRuntime()
        class Identity:
            def identity(self,request):return dict(id='local-user')
        self.app=FastAPI();self.app.include_router(vision_router(lambda:self.runtime,Identity,self.root))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('127.0.0.1',50000)),base_url='http://127.0.0.1:18935')
    async def asyncTearDown(self):await self.client.aclose();self.folder.cleanup()
    async def test_status_does_not_start_and_start_rejects_config_injection(self):
        self.assertEqual((await self.client.get('/api/vision/runtime')).status_code,200);self.assertEqual(self.runtime.started,0)
        self.assertEqual((await self.client.post('/api/vision/start',json={'source':'elsewhere'})).status_code,400)
        self.assertEqual((await self.client.post('/api/vision/start',json={})).status_code,200);self.assertEqual(self.runtime.started,1)
    async def test_foreign_origin_forwarded_headers_and_bearer_do_not_become_owner(self):
        for headers in ({'Origin':'https://untrusted.invalid'},{'X-Forwarded-For':'127.0.0.1'},{'Authorization':'Bearer fake'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual((await self.client.get('/api/vision/runtime',headers=headers)).status_code,403)
        self.assertEqual(self.runtime.started,0)
    async def test_document_guest_is_not_promoted_to_experiment_owner(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('192.0.2.9',50000)),base_url='http://127.0.0.1:18935') as c:
            self.assertEqual((await c.get('/api/vision/runtime')).status_code,403)
    async def test_private_shutdown_and_secondary_identity_writes_rejected(self):
        for p in ('auth/bootstrap','auth/tokens','__clawos_shutdown','credentials'):
            self.assertEqual((await self.client.post('/api/vision/service/'+p,json={})).status_code,403)
    async def test_proxy_preserves_range_but_strips_credentials_cookie_cors(self):
        original=httpx.AsyncClient;seen=[]
        class Bytes(httpx.AsyncByteStream):
            async def __aiter__(self):yield b'test'
        def upstream(request):
            seen.append(request);return httpx.Response(206,stream=Bytes(),headers={'Content-Range':'bytes 0-3/8','Set-Cookie':'never=forward','Access-Control-Allow-Origin':'*'})
        def factory(**kwargs):return original(transport=httpx.MockTransport(upstream),**kwargs)
        with patch('services.vision_api.httpx.AsyncClient',factory):
            r=await self.client.get('/api/vision/service/model-assets/example/content',headers={'Range':'bytes=0-3','Cookie':'unrelated=test'})
        self.assertEqual(r.status_code,206);self.assertEqual(r.content,b'test');self.assertEqual(r.headers['content-range'],'bytes 0-3/8')
        self.assertNotIn('set-cookie',r.headers);self.assertNotIn('access-control-allow-origin',r.headers)
        self.assertNotIn('cookie',seen[0].headers);self.assertNotIn('authorization',seen[0].headers)
        self.assertEqual(seen[0].headers['x-clawos-vision-gateway'],'test-only-gateway-handshake')
    async def test_static_entry_and_traversal(self):
        self.assertEqual((await self.client.get('/academy/vision/')).text,'owned-frontend')
        self.assertEqual((await self.client.get('/academy/vision/%2e%2e/hidden')).status_code,404)
    async def test_runtime_lock_waits_do_not_run_on_the_asgi_event_loop(self):
        threads=[]
        self.runtime.status=lambda:(threads.append(threading.get_ident()) or dict(running=False))
        self.assertEqual((await self.client.get('/api/vision/runtime')).status_code,200)
        self.assertNotEqual(threads[0],threading.get_ident())


class VisionRuntimeTests(unittest.TestCase):
    def test_stopped_status_does_not_create_data_or_process(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'new';runtime=VisionRuntime(target)
            self.assertFalse(runtime.status()['running']);self.assertFalse(target.exists());runtime.close()
    def test_missing_source_fails_before_process_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=VisionRuntime(Path(folder)/'data',source_root=Path(folder)/'missing')
            with patch('services.vision_runtime.subprocess.Popen') as launch:
                with self.assertRaises(ValueError):runtime.start()
                launch.assert_not_called()
            runtime.close()
