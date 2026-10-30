"""Negative controls for citation/quantity/reviewer gates and durable AI jobs."""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_synthesis as fixtures
from services.research_ai import ResearchAI,ResearchAIWorker,SECTIONS,catalog,decode,normalize
from services.research_watch_api import research_watch_router


def reply(value):
    return dict(choices=[dict(message=dict(content=json.dumps(value)),finish_reason='stop')],clawos_model=dict(provider='fixture',model='fixture',usage=dict(total_tokens=10)))


class AITests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.SynthesisTests.setUp
    subscription=fixtures.SynthesisTests.subscription
    run_page=fixtures.SynthesisTests.run_page
    seed=fixtures.SynthesisTests.seed

    def prepare(self):
        self.seed();self.report=self.synthesis.create('alice',{})
        self.ai=ResearchAI(self.watch)
        return self.ai.enqueue('alice',self.report['id'])

    def provider(self,verdict='supported'):
        self.calls=[]
        async def model(messages,tools,**options):
            self.calls.append((messages,options));data=json.loads(messages[-1]['content'])
            if 'claims' in data:return reply(dict(reviews=[dict(id=c['id'],verdict=verdict,reason='Fixture direct quote review.') for c in data['claims']]))
            refs=data['evidence'];value={k:[] for k in SECTIONS}
            value['overview']=[dict(text=refs[0]['quote'],citations=[refs[0]['id']],kind='reported')]
            return reply(value)
        return model

    async def test_two_model_calls_create_frozen_draft_with_provenance_and_export(self):
        queued=self.prepare();job=self.ai.claim()
        await self.ai.execute(job,self.provider())
        result=self.ai.get('alice',queued['id'])
        self.assertEqual(result['status'],'completed');self.assertEqual(len(self.calls),2)
        review_payload=json.loads(self.calls[1][0][-1]['content'])
        self.assertNotIn('evidence',review_payload)
        for claim in review_payload['claims']:self.assertEqual({e['id'] for e in claim['evidence']},set(claim['citations']))
        self.assertEqual(result['result']['outcome'],'draft_ready')
        self.assertFalse(result['result']['semantic_entailment_verified'])
        self.assertTrue(result['result']['sections']['overview'][0]['human_review_required'])
        exported=self.synthesis.export('alice',self.report['id'])
        self.assertIn('## AI综合草稿',exported['markdown']);self.assertIn('E1',exported['markdown'])
        self.assertEqual(exported['data']['ai_synthesis']['id'],queued['id'])
        self.assertEqual(self.synthesis.get('alice',self.report['id'])['hash'],self.report['hash'])

    async def test_uncertain_reviewer_leaves_body_empty_instead_of_publishing(self):
        self.prepare();job=self.ai.claim();await self.ai.execute(job,self.provider('uncertain'))
        result=self.ai.get('alice',job['id'])['result']
        self.assertEqual(result['sections']['overview'],[])
        self.assertEqual(result['outcome'],'insufficient_evidence')
        self.assertEqual(result['excluded'][0]['reason'],'model_uncertain')

    async def test_incomplete_review_is_failed_not_a_false_success(self):
        self.prepare();job=self.ai.claim();base=self.provider()
        async def model(messages,*args,**kwargs):
            if 'claims' in json.loads(messages[-1]['content']):return reply(dict(reviews=[]))
            return await base(messages,*args,**kwargs)
        await self.ai.execute(job,model)
        self.assertEqual(self.ai.get('alice',job['id'])['status'],'failed')

    def test_unknown_citation_numeric_invention_and_single_paper_conflict_excluded(self):
        self.prepare();refs,_=catalog(self.report['report'])
        value={k:[] for k in SECTIONS}
        value['overview']=[dict(text='The method is effective.',citations=['invented'],kind='reported')]
        value['evidence']=[dict(text='Accuracy reaches 99.9 percent.',citations=['E1'],kind='reported')]
        value['disagreements']=[dict(text='These two papers contradict each other.',citations=['E1'],kind='reported')]
        kept,excluded=normalize(value,refs)
        self.assertEqual(kept,[])
        self.assertEqual({e['reason'] for e in excluded},{'missing_or_unknown_citation','unsupported_quantity','comparison_requires_two_papers'})

    def test_polarity_and_inference_gates(self):
        refs=[dict(id='E1',paper_id='p',quote='This method does not improve accuracy.')]
        value={k:[] for k in SECTIONS};value['overview']=[dict(text='The method improves accuracy.',citations=['E1'],kind='reported')]
        value['next_questions']=[dict(text='What changes under new conditions?',citations=['E1'],kind='reported')]
        kept,excluded=normalize(value,refs)
        self.assertFalse(kept);self.assertEqual(len(excluded),2)

    def test_job_idempotency_scope_quota_and_expired_lease(self):
        queued=self.prepare()
        self.assertEqual(self.ai.enqueue('alice',self.report['id'])['id'],queued['id'])
        with self.assertRaises(LookupError):self.ai.get('bob',queued['id'])
        with self.assertRaises(LookupError):self.ai.cancel('bob',queued['id'])
        old=self.ai.claim();self.assertIsNone(self.ai.claim())
        self.now[0]+=421;self.ai.claim()
        self.assertEqual(self.ai.get('alice',queued['id'])['status'],'failed')
        self.assertFalse(self.ai.finish(old,dict(fake=True)))

    async def test_running_cancel_stops_call_and_does_not_kill_worker_contract(self):
        self.prepare();job=self.ai.claim();entered=asyncio.Event();cancelled=asyncio.Event()
        async def slow(*args,**kwargs):
            entered.set()
            try:await asyncio.sleep(60)
            except asyncio.CancelledError:cancelled.set();raise
        task=asyncio.create_task(self.ai.execute(job,slow));await entered.wait()
        self.ai.cancel('alice',job['id']);self.assertIsNone(self.ai.claim())
        await asyncio.wait_for(task,3)
        self.assertTrue(cancelled.is_set());self.assertEqual(self.ai.get('alice',job['id'])['status'],'cancelled')

    async def test_shutdown_is_failed_and_never_commits_late_content(self):
        self.prepare();job=self.ai.claim();entered=asyncio.Event()
        async def slow(*args,**kwargs):entered.set();await asyncio.sleep(60)
        task=asyncio.create_task(self.ai.execute(job,slow));await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.ai.get('alice',job['id'])['error'],'cancelled_or_shutdown')

    def test_invalid_json_duplicates_truncation_are_rejected(self):
        for raw in ['{"a":1,"a":2}','{"a":NaN}','```json\n{}\n```']:
            with self.assertRaises(ValueError):decode(dict(choices=[dict(message=dict(content=raw),finish_reason='stop')]))
        with self.assertRaises(ValueError):decode(dict(choices=[dict(message=dict(content='{}'),finish_reason='length')]))
        with self.assertRaises(ValueError):decode(dict(choices=[dict(message=dict(content='{}'))]))

    def test_catalog_budget_discloses_omitted_evidence(self):
        self.prepare();report=copy.deepcopy(self.report['report'])
        for p in report['papers']:
            text=' Evidence fragment for bounded synthesis.'*60;p['sources'][0]['text']=text
            p['sections']={'problem':[dict(text=text[i:i+35],evidence=dict(p['sources'][0],start=i,end=i+35,quote=text[i:i+35])) for i in range(50)]}
        refs,coverage=catalog(report)
        self.assertEqual(len(refs),80);self.assertEqual(coverage['omitted_excerpts'],20)
        self.assertEqual(len({r['paper_id'] for r in refs}),2)

    async def test_server_model_bridge_refuses_external_provider_without_fallback(self):
        import clawos_server as server
        class Provider:
            base_url='https://example.org/v1';model='external';called=False
            def is_configured(self):return True
            async def complete(self,*args,**kwargs):self.called=True;raise AssertionError('No external calls')
        class Task:
            def done(self):return False
        class Worker:task=Task()
        provider=Provider()
        with patch.object(server,'g_routing_provider',provider),patch.object(server,'g_research_ai_worker',Worker()):
            self.assertFalse(server._research_ai_ready()['ready'])
            with self.assertRaises(RuntimeError):await server._research_ai_model([],[])
        self.assertFalse(provider.called)

    async def test_corrupt_ai_result_fails_integrity_check(self):
        self.prepare();job=self.ai.claim();await self.ai.execute(job,self.provider())
        with self.store._conn() as c:c.execute('UPDATE research_ai_jobs SET result=? WHERE id=?',('{"content":{},"hash":"bad"}',job['id']))
        with self.assertRaisesRegex(ValueError,'完整性'):self.ai.get('alice',job['id'])

    def test_api_requires_explicit_confirmation_ready_local_worker_and_owner(self):
        self.prepare();ready=[False]
        class Identity:
            def identity(self,request):
                token=request.headers.get('authorization','')
                if token not in ('Bearer alice','Bearer bob'):raise HTTPException(401,'auth')
                return dict(id=token[7:])
        app=FastAPI();app.include_router(research_watch_router(lambda:self.watch,Identity,lambda:{},lambda:dict(ready=ready[0])))
        with TestClient(app) as client:
            path=f"/api/research/watch/syntheses/{self.report['id']}/ai";h={'Authorization':'Bearer alice'}
            self.assertEqual(client.post(path,json={},headers=h).status_code,400)
            self.assertEqual(client.post(path,json=dict(confirmed=True),headers=h).status_code,503)
            ready[0]=True
            self.assertEqual(client.post(path,json=dict(confirmed=True),headers=h).status_code,202)
            self.assertEqual(client.post(path,json=dict(confirmed=True),headers={'Authorization':'Bearer bob'}).status_code,404)


if __name__=='__main__':unittest.main()
