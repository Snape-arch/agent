import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from memoryos.document_ingestion import ingest_file
from services.academy_materials import AcademyMaterials


class KnowledgeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=MemoryStore(str(self.root/'db.sqlite'))
        self.file=self.root/'source.txt';self.file.write_text('Evidence supports conclusions. Missing evidence requires refusal.',encoding='utf-8')

    def snapshot(self):
        with self.store._conn() as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'knowledge%' OR name IN ('documents','document_chunks')) ORDER BY name")]
            return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in names}

    def test_reingestion_failure_restores_documents_legacy_core_and_outbox(self):
        doc=ingest_file(self.store,self.root/'uploads',self.file)
        before=self.snapshot()
        with patch.object(self.store,'add_document_chunk',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):ingest_file(self.store,self.root/'uploads',self.file,title='replacement')
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(self.store.get_document_chunks(doc['id']))
        from services.knowledge_core_service import KnowledgeCoreService
        with patch.object(KnowledgeCoreService,'absorb',side_effect=ValueError('invalid core evidence')):
            with self.assertRaises(ValueError):ingest_file(self.store,self.root/'uploads',self.file)
        self.assertEqual(self.snapshot(),before)

    def test_successful_repeat_has_no_duplicate_active_chunks(self):
        one=ingest_file(self.store,self.root/'uploads',self.file)
        two=ingest_file(self.store,self.root/'uploads',self.file)
        self.assertEqual(one['id'],two['id'])
        self.assertEqual(len(self.store.get_document_chunks(one['id'])),one['chunk_count'])
        self.assertEqual(len(self.store.list_knowledge()),len(two['knowledge_ids']))

    def test_nested_savepoint_and_schema_do_not_commit_outer_work(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.add_document('must roll back')
                try:
                    with self.store.transaction():
                        self.store.add_document('inner rolled back')
                        raise ValueError('recover locally')
                except ValueError:pass
                self.assertEqual(len(self.store.list_documents()),1)
                self.store.add_knowledge('schema created here','temporary fact')
                other=sqlite3.connect(self.store._db_path)
                try:self.assertEqual(other.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
                finally:other.close()
                raise RuntimeError('abort outer workflow')
        self.assertEqual(self.store.list_documents(),[])
        self.assertEqual(self.store.list_knowledge(),[])

    def test_manual_knowledge_failure_preserves_both_versions(self):
        from services.knowledge_core_service import KnowledgeCoreService
        item=self.store.add_knowledge('test fact','before')
        before=self.snapshot()
        with patch.object(KnowledgeCoreService,'absorb',side_effect=ValueError('index failure')):
            with self.assertRaises(ValueError):self.store.update_knowledge(item['id'],'test fact','after')
        self.assertEqual(self.snapshot(),before)
        with patch.object(KnowledgeCoreService,'expire_legacy',side_effect=ValueError('expiry failure')):
            with self.assertRaises(ValueError):self.store.delete_knowledge(item['id'])
        self.assertEqual(self.snapshot(),before)

    def test_missing_document_or_fragment_cannot_be_used_as_evidence(self):
        self.assertFalse(self.store.document_source_usable('doc:999#chunk=1'))
        doc=ingest_file(self.store,self.root/'uploads',self.file)
        self.assertFalse(self.store.document_source_usable(f"doc:{doc['id']}#chunk=999"))
        self.assertTrue(self.store.document_source_usable(self.store.get_document_chunks(doc['id'])[0]['citation']))

    def test_learning_state_survives_long_activity_history(self):
        service=AcademyMaterials(self.store,self.root/'materials')
        state=service.upload('book.txt',self.file.read_bytes());mid=state['document']['id'];cid=state['chapters'][0]['id']
        event=service.event(mid,'chapter_response',dict(chapter=cid,answers=['saved'],status='needs_review'))
        for i in range(210):service.event(mid,'tutor',dict(citation='another',answer=str(i)))
        state=service.state(mid)
        self.assertEqual(state['chapters'][0]['status'],'submitted')
        self.assertTrue(any(e['id']==event['id'] for e in state['events']))

    def test_disabled_and_edited_preferences_do_not_return_through_legacy_prompt(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.services.management import ManagementService
        pref=self.store.set_preference('tone','formal')
        ManagementService(self.store).update_preference_confidence('tone','casual')
        self.assertEqual(self.store.get_preference('tone')['value'],'casual')
        self.store.set_memory_enabled(pref['id'],False)
        self.assertIsNone(self.store.get_preference('tone'))
        self.assertNotIn('casual',ContextBuilder(self.store).build_system_prompt('s'))

    def test_compaction_archives_all_raw_text_and_rolls_back_on_failure(self):
        from memoryos.services.management import ManagementService
        long='original full text '*600
        self.store.add_message('s','user',long)
        for i in range(4):self.store.add_message('s','assistant',str(i))
        with patch.object(self.store,'archive_session_messages',side_effect=RuntimeError('archive unavailable')):
            with self.assertRaises(RuntimeError):ManagementService(self.store).compact_conversation('s',2)
        self.assertEqual(len(self.store.get_session_messages('s')),5)
        self.assertEqual(self.store.get_persisted_session_summary('s'),'')
        ManagementService(self.store).compact_conversation('s',2)
        with self.store._conn() as c:
            archived=c.execute('SELECT content FROM conversation_archive WHERE session_id=? ORDER BY original_id',('s',)).fetchall()
        self.assertEqual(archived[0]['content'],long)
        self.assertEqual(len(archived),3)
        self.assertEqual(len(self.store.get_session_messages('s')),2)

    def test_nondefault_retrieval_cannot_fall_back_to_global_legacy_memory(self):
        from memoryos.services.retrieval import RetrievalService
        self.store.add_knowledge('global-secret','global-secret information')
        self.store.set_preference('global-secret','global-secret preference')
        self.assertEqual(RetrievalService(self.store).retrieve('global-secret',owner_id='another',workspace_id='private'),[])

    def test_chapter_review_is_bound_to_submitted_answers_and_requires_two_judges(self):
        service=AcademyMaterials(self.store,self.root/'materials')
        state=service.upload('book.txt',self.file.read_bytes());mid=state['document']['id'];chapter=state['chapters'][0]
        questions=dict(questions=[dict(dimension=d,question='Explain the evidence condition.',quote='Evidence supports conclusions.',criterion='Explain why the condition matters.') for d in ('concept','reasoning','transfer')])
        service.save_chapter_questions(mid,chapter['id'],'research',questions)
        submission=service.chapter_response(mid,chapter['id'],['Evidence must support the conclusion.']*3,dict(question='What supports answers?',method='Check the source text.',result='Evidence is required.',reflection='More tests are needed.',quote='Evidence supports conclusions.'))
        judge=dict(dimensions={d:dict(score=2,reason='The answer explains the condition.',student_quote='Evidence must support',source_quote='Evidence supports conclusions.',next_step='Try an example without evidence.') for d in ('concept','reasoning','transfer')})
        saved=service.save_chapter_review(mid,submission['id'],[judge,judge])
        self.assertEqual(saved['data']['status'],'passed')
        import copy
        other=copy.deepcopy(judge);other['dimensions']['concept']['score']=1
        self.assertEqual(service.save_chapter_review(mid,submission['id'],[judge,other])['data']['status'],'needs_review')
        other['dimensions']['concept']['student_quote']='Never written by the learner'
        with self.assertRaises(ValueError):service.save_chapter_review(mid,submission['id'],[judge,other])
        with self.assertRaises(ValueError):service.chapter_review_prompt(mid,submission['id'],'other-learner')
        import asyncio, json
        import httpx
        from fastapi import FastAPI
        from unittest.mock import AsyncMock
        from services.academy_material_api import materials_router
        model=AsyncMock(return_value={'choices':[{'message':{'content':json.dumps(judge)}}]})
        app=FastAPI();app.include_router(materials_router(lambda:service,model))
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                url=f'/api/academy/learning/materials/{mid}/chapter-review'
                result=await client.post(url,json={'response_id':submission['id']})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['data']['response_id'],submission['id'])
                self.assertEqual(model.call_count,2)
                model.side_effect=RuntimeError('offline')
                result=await client.post(url,json={'response_id':submission['id']})
                self.assertEqual(result.status_code,502)
        asyncio.run(check())

    def test_personal_vector_updates_and_disable_take_effect_without_refresh(self):
        from memoryos.services.vector_store import MemoryVectorStore
        vector=MemoryVectorStore(self.store._db_path,provider='lightweight',embedding_provider='hash')
        memory=self.store.set_preference('drink','apple juice')
        self.assertTrue(vector.search('apple juice',min_score=0))
        self.store.set_preference('drink','orange tea')
        hits=vector.search('orange tea',min_score=0)
        self.assertTrue(any('orange tea' in h['text'] for h in hits))
        self.assertFalse(any('apple juice' in h['text'] for h in hits))
        self.store.set_memory_enabled(memory['id'],False)
        self.assertFalse(any(h['id']==f"mem_{memory['id']}" for h in vector.search('orange tea',min_score=0)))

    def test_ocr_retry_is_atomic_preserves_id_and_old_evidence_on_failure(self):
        from services.knowledge_service import KnowledgeService
        doc=self.store.add_document('scan',status='needs_ocr')
        self.store.add_document_chunk(doc['id'],1,'Previous evidence.',f"doc:{doc['id']}#chunk=1")
        service=KnowledgeService(self.store,self.root)
        with patch.object(service,'_load_ocr_text',return_value=('', 'unavailable', 'offline')):
            failed=service.run_ocr(doc['id'],force=True)
        self.assertFalse(failed['ok']);self.assertEqual(failed['chunk_count'],1)
        before=self.snapshot()
        with patch.object(self.store,'add_document_chunk',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):service.run_ocr(doc['id'],sidecar_text='Replacement evidence.',force=True)
        self.assertEqual(self.snapshot(),before)
        result=service.run_ocr(doc['id'],sidecar_text='Replacement evidence.',force=True)
        self.assertEqual(result['document']['id'],doc['id'])
        self.assertEqual(len(self.store.list_documents()),1)
        self.assertIn('Replacement',self.store.get_document_chunks(doc['id'])[0]['content'])

if __name__=='__main__':unittest.main()
