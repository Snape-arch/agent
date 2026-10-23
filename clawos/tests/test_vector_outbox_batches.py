from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
import tempfile
import threading
import unittest

from memoryos.memory_store import MemoryStore
from memoryos.services.vector_store import MemoryVectorStore,VectorStore,ChromaVectorStore
from services.knowledge_core_service import KnowledgeCoreService


class BatchStore(VectorStore):
    def __init__(self):
        super().__init__(dim=32);self.batches=[];self.hook=None;self.fail=False
    def add_many(self,rows):
        self.batches.append(len(rows))
        if self.hook:self.hook()
        if self.fail:
            super().add_many(rows[:1])
            raise RuntimeError('partial write fixture')
        super().add_many(rows)


class VectorOutboxBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=MemoryStore(str(Path(self.temp.name)/'memory.db'))
        self.core=KnowledgeCoreService(self.store)
        self.vector=MemoryVectorStore(self.store._db_path,provider='lightweight',embedding_provider='hash',dim=32)
        self.vector.refresh();self.backend=BatchStore();self.vector._store=self.backend
    def tearDown(self):self.temp.cleanup()
    def add(self,index,source='first'):
        return self.core.absorb(title=f'Measurement {index}',statement=f'The measured fixture result is {index} units.',category='research',source_ref=f'https://example.test/{index}/{source}')
    def events(self):
        with self.store._conn() as c:return [dict(row) for row in c.execute('SELECT * FROM knowledge_vector_outbox_v2 ORDER BY id')]

    def test_duplicate_events_coalesce_into_bounded_batches_of_current_versions(self):
        records=[]
        for index in range(33):
            records.append(self.add(index));self.add(index,'second')
        count=len(self.events());result=self.vector.refresh()
        self.assertEqual(0,result['failed']);self.assertEqual(count,result['processed'])
        self.assertEqual([32,1],self.backend.batches)
        self.assertEqual(33,self.backend.count())
        for record in records:
            with self.store._conn() as c:version=c.execute('SELECT current_version FROM knowledge_records_v2 WHERE id=?',(record['id'],)).fetchone()[0]
            self.assertEqual(version,self.backend.get('kv2_'+str(record['id']))['metadata']['version'])
        self.assertTrue(all(row['processed_at'] and row['attempts']==1 for row in self.events()))

    def test_partial_batch_failure_stays_pending_and_retry_is_idempotent(self):
        for index in range(4):self.add(index)
        self.backend.fail=True;result=self.vector.refresh()
        self.assertEqual(0,result['processed']);self.assertEqual(len(self.events()),result['failed'])
        self.assertTrue(all(not row['processed_at'] and row['attempts']==1 and row['error'] for row in self.events()))
        self.backend.fail=False;result=self.vector.refresh()
        self.assertEqual(0,result['failed']);self.assertEqual(4,self.backend.count())
        self.assertTrue(all(row['processed_at'] and row['attempts']==2 and not row['error'] for row in self.events()))

    def test_full_load_does_not_ack_events_created_during_embedding(self):
        self.add(1);self.vector._loaded=False
        self.backend.hook=lambda:self.add(2)
        self.vector._ensure_loaded();self.backend.hook=None
        self.assertTrue(any(not row['processed_at'] for row in self.events()))
        self.assertEqual(1,self.backend.count())
        self.vector.refresh();self.assertEqual(2,self.backend.count())
        self.assertTrue(all(row['processed_at'] for row in self.events()))

    def test_two_consumers_serialize_and_encoder_does_not_hold_database_write_lock(self):
        record=self.add(1);started=threading.Event();release=threading.Event()
        def hold():
            started.set()
            if not release.wait(5):raise RuntimeError('encoder not released')
        self.backend.hook=hold
        other=MemoryVectorStore(self.store._db_path,provider='lightweight',embedding_provider='hash',dim=32)
        other._loaded=True;other._store=self.backend
        with ThreadPoolExecutor(max_workers=3) as pool:
            first=pool.submit(self.vector.refresh)
            try:
                self.assertTrue(started.wait(2))
                update=pool.submit(self.add,1,'second');update.result(timeout=2)
                second=pool.submit(other.refresh)
                with self.assertRaises(FutureTimeoutError):second.result(timeout=.1)
            finally:
                self.backend.hook=None;release.set()
            self.assertEqual(0,first.result(timeout=3)['failed']);self.assertEqual(0,second.result(timeout=3)['failed'])
        with self.store._conn() as c:version=c.execute('SELECT current_version FROM knowledge_records_v2 WHERE id=?',(record['id'],)).fetchone()[0]
        self.assertEqual(version,self.backend.get('kv2_'+str(record['id']))['metadata']['version'])
        self.assertTrue(all(row['processed_at'] and row['attempts']==1 for row in self.events()))

    def test_chroma_delete_failure_is_not_silently_acknowledged(self):
        backend=object.__new__(ChromaVectorStore);backend._lock=threading.RLock()
        class BrokenCollection:
            def delete(self,**kwargs):raise RuntimeError('storage unavailable')
        backend._collection=BrokenCollection()
        with self.assertRaisesRegex(RuntimeError,'storage unavailable'):backend.remove('kv2_1')


if __name__=='__main__':unittest.main()
