"""A slow encoder/parser must not prevent unrelated HTTP reads."""
import asyncio
import threading
import unittest
from unittest.mock import patch
import httpx
import clawos_server as server


class Store:
    def add_knowledge(self,**kwargs):return dict(id=1,**kwargs)
    def update_knowledge(self,*args,**kwargs):return dict(id=1,**kwargs)
    def delete_knowledge(self,*args):return True
    def list_knowledge(self,*args):return []


class WriteResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_export_keeps_read_routes_responsive(self):
        started=threading.Event();release=threading.Event()
        class SlowReports:
            def generate_research_learning_analysis(self,**kwargs):
                started.set()
                if not release.wait(5):raise RuntimeError('test report was never released')
                return dict(report={},preview='Fixture export')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://127.0.0.1') as client:
            with patch.object(server,'g_memory_store',Store()),patch.object(server,'g_workspace_services',SlowReports()):
                pending=asyncio.create_task(client.post('/api/workspace/research/learning-analysis',json=dict(formats=['pdf'])))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait,2))
                    response=await asyncio.wait_for(client.get('/api/knowledge'),1)
                    self.assertEqual(200,response.status_code)
                    self.assertFalse(pending.done(),'report export blocked the HTTP event loop')
                finally:
                    release.set()
                    response=await pending
                self.assertEqual(200,response.status_code)

    async def assert_responsive(self,method,path,**kwargs):
        started=threading.Event();release=threading.Event()
        class SlowVector:
            def refresh(self):
                started.set()
                if not release.wait(5):raise RuntimeError('test encoder was never released')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://127.0.0.1') as client:
            with patch.object(server,'g_memory_store',Store()),patch.object(server,'g_vector_store',SlowVector()):
                pending=asyncio.create_task(client.request(method,path,**kwargs))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait,2))
                    response=await asyncio.wait_for(client.get('/api/knowledge'),1)
                    self.assertEqual(200,response.status_code)
                    self.assertFalse(pending.done(),'encoder blocked the HTTP event loop')
                finally:
                    release.set()
                    response=await pending
                self.assertEqual(200,response.status_code)

    async def test_knowledge_writes_keep_read_routes_responsive(self):
        for method,path,payload in [('POST','/api/knowledge',dict(title='Fixture',content='Evidence')),
                                   ('PUT','/api/knowledge/1',dict(title='Fixture',content='Updated evidence')),
                                   ('DELETE','/api/knowledge/1',None)]:
            with self.subTest(method=method):
                await self.assert_responsive(method,path,**({'json':payload} if payload else {}))

    async def test_upload_indexing_keeps_read_routes_responsive(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td,patch.object(server,'UPLOAD_DIR',Path(td)), \
             patch('memoryos.document_ingestion.ingest_file',return_value={'id':1}):
            await self.assert_responsive('POST','/api/documents/upload',files={'files':('source.txt',b'Evidence','text/plain')})


if __name__=='__main__':unittest.main()
