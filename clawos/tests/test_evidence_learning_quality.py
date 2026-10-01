import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.knowledge_service import KnowledgeService
from services.meeting_audio_service import MeetingAudioService
from services.academy_materials import AcademyMaterials
from services.academy_material_api import materials_router


class EvidenceQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=MemoryStore(str(Path(self.tmp.name)/'db.sqlite'))
        self.knowledge=KnowledgeService(self.store,Path(self.tmp.name))
        self.materials=AcademyMaterials(self.store,Path(self.tmp.name)/'materials')

    def test_question_scoped_retrieval_reaches_late_chunks_and_refuses_missing(self):
        doc=self.store.add_document(title='Campus',filename='rules.txt',mime_type='text/plain',file_path='rules.txt')
        for i in range(1,30):
            self.store.add_document_chunk(doc['id'],i,'Opening hours are nine to five.',f"doc:{doc['id']}#chunk={i}")
        self.store.add_document_chunk(doc['id'],30,'Parking price is ten dollars.',f"doc:{doc['id']}#chunk=30")
        a=self.knowledge.citation_answer('parking price',document_id=doc['id'],limit=1)
        b=self.knowledge.citation_answer('opening hours',document_id=doc['id'],limit=1)
        self.assertIn('#chunk=30',a['citations'][0]['citation'])
        self.assertNotEqual(a['citations'],b['citations'])
        self.assertEqual(a['status'],'partial'); self.assertFalse(a['answer_verified'])
        self.assertEqual(self.knowledge.citation_answer('volcano eruption',document_id=doc['id'])['status'],'blocked')

    def test_review_evidence_is_withheld_across_sources(self):
        from services.evidence_retrieval import retrieve
        rows=[dict(id='a',text='parking price is ten',review_required=True),dict(id='b',text='opening hours nine')]
        self.assertEqual(retrieve('parking price',rows),[])
        self.assertEqual(retrieve('parking price',[dict(id='a',content='parking price is ten',metadata={'review_required':True})]),[])

    def test_asr_does_not_invent_speakers_or_timestamps(self):
        service=MeetingAudioService(None,Path(self.tmp.name))
        lines=service._format_asr_segments([SimpleNamespace(start=i,end=i+1,text=f'Sentence {i}') for i in range(3)])
        turns=service.diarize('\n'.join(lines),[])
        self.assertEqual(len(turns),3)
        self.assertTrue(all(t['speaker'] is None for t in turns))
        self.assertEqual(turns[2]['time'],'2.00-3.00')
        mixed=service.diarize('Alice: hello\nUnlabelled speech\nBob: agreed',[dict(start=9,end=12)])
        self.assertEqual([t['speaker'] for t in mixed],['Alice',None,'Bob'])
        self.assertEqual(mixed[1]['text'],'Unlabelled speech')
        self.assertEqual(mixed[1]['time'],'')

    def test_chapters_are_source_bound_and_answers_do_not_create_mastery(self):
        state=self.materials.upload('book.md','# 第一章\n证据充分时才回答。\n# 第二章\n缺少证据就拒答。'.encode())
        mid=state['document']['id']; chapters=state['chapters']
        self.assertEqual(len(chapters),2)
        self.assertNotIn('缺少证据',chapters[0]['text'])
        chapter=chapters[0]
        questions=dict(questions=[dict(dimension=d,question='请解释本章证据条件如何成立？',quote='证据充分时才回答',criterion='说明证据如何支持结论') for d in ('concept','reasoning','transfer')])
        original_questions=self.materials.save_chapter_questions(mid,chapter['id'],'研究方法',questions)
        self.materials.chapter_draft(mid,chapter['id'],['尚未写完','',''],dict(question='',method='',result='',reflection='',quote=''),original_questions['id'])
        self.assertEqual(self.materials.state(mid)['events'][0]['data']['answers'][0],'尚未写完')
        self.materials.save_chapter_questions(mid,chapter['id'],'研究方法',questions)
        project=dict(question='证据不足会如何？',method='移除依据后检查答案',result='系统没有给出猜测',reflection='还需要更多测试问题',quote='证据充分时才回答')
        saved=self.materials.chapter_response(mid,chapter['id'],['应当先查找证据，再解释结论成立条件。']*3,project,question_event_id=original_questions['id'])
        self.assertEqual(saved['data']['question_event_id'],original_questions['id'])
        self.assertEqual(saved['data']['status'],'needs_review')
        # The older submission is retained, but does not complete the newer questions.
        self.assertEqual(self.materials.state(mid)['chapters'][0]['status'],'in_progress')
        self.assertEqual(self.materials.chapter_submission(mid,saved['id'])['question_event_id'],original_questions['id'])
        with self.assertRaises(ValueError):self.materials.chapter_response(mid,chapter['id'],['x']*3,project)
        with self.assertRaises(ValueError):self.materials.chapter_response(mid,chapter['id'],['应当先查找证据，再解释结论成立条件。']*3,dict(project,quote='缺少证据就拒答'))
        with self.assertRaises(ValueError):self.materials.chapter(mid,chapter['id'],'another-learner')
        changed=self.materials.upload('book.md','# 第一章\n资料已经更新。'.encode())
        self.assertEqual(changed['chapters'][0]['status'],'not_started')
        self.assertNotEqual(changed['chapters'][0]['revision'],chapter['revision'])

    def test_chapter_http_and_model_failure_recovery(self):
        from fastapi import FastAPI
        import httpx
        state=self.materials.upload('source.md','# 证据\n只有证据充分才能作答。'.encode())
        mid=state['document']['id']; chapter=state['chapters'][0]
        questions=dict(questions=[dict(dimension=d,question='请解释证据如何支持作答？',quote='只有证据充分才能作答',criterion='描述结论成立的条件') for d in ('concept','reasoning','transfer')])
        model=AsyncMock(side_effect=RuntimeError('offline'))
        app=FastAPI();app.include_router(materials_router(lambda:self.materials,model))
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                path='/api/academy/learning/materials/'+mid
                data=dict(chapter=chapter['id'],subject='研究方法')
                bad=await c.post(path+'/chapter-questions',json=data)
                self.assertEqual(bad.status_code,502)
                events=self.materials.state(mid)['events']
                self.assertFalse([e for e in events if e['kind']!='model_run'])
                self.assertEqual(events[0]['data']['status'],'failed')
                self.assertEqual(self.store.get_run_record(events[0]['data']['run_id'])['status'],'failed')
                model.side_effect=None;model.return_value={'choices':[{'message':{'content':json.dumps(questions,ensure_ascii=False)}}]}
                good=await c.post(path+'/chapter-questions',json=data)
                self.assertEqual(good.status_code,200,good.text)
                self.assertEqual(len(good.json()['data']['questions']),3)
        asyncio.run(run())

if __name__=='__main__':unittest.main()
