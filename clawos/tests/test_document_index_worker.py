import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import httpx
import clawos_server as server
from memoryos.memory_store import MemoryStore
from services.knowledge_core_service import KnowledgeCoreService
from services.document_index_worker import DocumentIndexWorker


class DocumentIndexWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_upload_returns_pending_while_indexing_and_unrelated_reads_continue(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            KnowledgeCoreService(store).absorb(title='Fixture',statement='Evidence fixture.',source_ref='fixture:index')
            started=threading.Event();release=threading.Event()
            class SlowIndex:
                def refresh(self,limit=1000):
                    started.set()
                    if not release.wait(5):raise RuntimeError('index was not released')
                    with store._conn() as c:
                        count=c.execute("SELECT COUNT(*) FROM knowledge_vector_outbox_v2 WHERE processed_at='' ").fetchone()[0]
                        c.execute("UPDATE knowledge_vector_outbox_v2 SET processed_at='fixture' WHERE processed_at='' ")
                    return dict(processed=count,failed=0)
            with patch.object(server,'g_memory_store',store),patch.object(server,'g_vector_store',SlowIndex()),patch.object(server,'g_document_index_worker',None),\
                 patch.object(server,'UPLOAD_DIR',Path(td)/'uploads'),patch('memoryos.document_ingestion.ingest_file',return_value=dict(id=1,chunk_count=32)):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://127.0.0.1') as client:
                    worker=None
                    try:
                        response=await asyncio.wait_for(client.post('/api/documents/upload',files={'files':('paper.pdf',b'%PDF-fixture','application/pdf')}),2)
                        worker=server.g_document_index_worker
                        self.assertEqual(202,response.status_code)
                        self.assertEqual(1,response.json()['count']);self.assertGreater(response.json()['indexing']['pending'],0)
                        self.assertTrue(await asyncio.to_thread(started.wait,2))
                        self.assertEqual(200,(await asyncio.wait_for(client.get('/api/knowledge'),1)).status_code)
                        status=(await client.get('/api/documents/indexing')).json()
                        self.assertEqual('indexing',status['state'])
                    finally:
                        release.set()
                        if worker and worker.task:await worker.task
                    self.assertEqual('ready',(await client.get('/api/documents/indexing')).json()['state'])

    async def test_unacknowledged_events_survive_worker_stop_and_are_resumed(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'));core=KnowledgeCoreService(store)
            for index in range(2):core.absorb(title=f'Fixture {index}',statement=f'Value {index} units.',source_ref=f'fixture:{index}')
            started=threading.Event();release=threading.Event();finished=threading.Event()
            class Index:
                hold=True
                def refresh(self,limit=1):
                    if self.hold:
                        started.set();release.wait(5)
                    with store._conn() as c:
                        ids=[r[0] for r in c.execute("SELECT id FROM knowledge_vector_outbox_v2 WHERE processed_at='' ORDER BY id LIMIT ?",(limit,))]
                        c.executemany("UPDATE knowledge_vector_outbox_v2 SET processed_at='fixture' WHERE id=?",[(i,) for i in ids])
                    finished.set();return dict(processed=len(ids),failed=0)
            vector=Index();worker=DocumentIndexWorker(store,vector,batch_limit=1);worker.start()
            try:
                self.assertTrue(await asyncio.to_thread(started.wait,2));await worker.close()
            finally:release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait,2))
            self.assertGreater(worker.status()['pending'],0)
            vector.hold=False;resumed=DocumentIndexWorker(store,vector,batch_limit=1);resumed.start()
            await asyncio.wait_for(resumed.task,2)
            self.assertEqual('ready',resumed.status()['state'])


if __name__=='__main__':unittest.main()
