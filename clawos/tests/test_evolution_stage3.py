"""Isolated protocol, session/role, fencing and adjudication regressions.

ProtocolProvider is deliberately synthetic. This suite proves no real teacher
or model quality gain; actual model/browser checks are separate acceptance.
"""
import asyncio
import copy
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)) if str(ROOT) not in sys.path else None
from memoryos.memory_store import MemoryStore
from services.evolution_experiments import EvolutionExperimentService,digest
from services.evolution_capture import EvolutionModelCapture
from services.evolution_review import EvolutionReviewService
from services.collaboration import Collaboration,digest as session_hash
from services.academy_documents import AcademyDocuments


def cohort(count):
    return [{'id':f'case-{i}','group_id':f'group-{i}','query':f'Stage three fixture question {i}',
             'reviewed_by':'synthetic-author','route':{'allowed_tools':['file_read','file_write','shell_exec','web_fetch','web_search']},
             'required_tools':['file_read'],'forbidden_tools':['file_write','shell_exec','web_fetch']} for i in range(count)]


class ProtocolProvider:
    name='synthetic-protocol';model='fixture-only';base_url='http://127.0.0.1:1/v1'
    def __init__(self, failure_at=None, finish='stop'):
        self.calls=[];self.failure_at=failure_at;self.finish=finish;self.hook=None;self.tool_calls=False
    def is_configured(self):return True
    async def complete(self,messages,options,**kwargs):
        self.calls.append((messages,options))
        if self.hook:await self.hook()
        if self.failure_at==len(self.calls):raise asyncio.TimeoutError()
        return {'ok':True,'provider':self.name,'model':self.model,'content':'Synthetic answer; no real model executed.',
                'raw':{'choices':[{'finish_reason':self.finish,'message':{'content':'synthetic','tool_calls':[{}] if self.tool_calls else []}}],'secret':'MUST-NOT-PERSIST'},
                'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18,'secret':'MUST-NOT-PERSIST'}}


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tempfile.TemporaryDirectory();cls.db=str(Path(cls.root.name)/'fixture.db')
        store=MemoryStore(cls.db);service=EvolutionExperimentService(store)
        exp=service.freeze(target_type='tool_routing_policy',target_key='default',baseline_payload={},cases=cohort(cls.size),created_by='local-user')
        cls.exp=service.replay(exp['id'])
    @classmethod
    def tearDownClass(cls):cls.root.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=MemoryStore(str(Path(self.tmp.name)/'isolated.db'))
        with closing(sqlite3.connect(self.db)) as source,closing(sqlite3.connect(self.store._db_path)) as target:source.backup(target)
        self.capture=EvolutionModelCapture(self.store);self.review=EvolutionReviewService(self.store)
    def packet(self):
        exp=self.exp;report=exp['report']
        return self.review.freeze_outputs(exp['id'],{'definition_digest':exp['definition_digest'],'report_digest':report['report_digest'],
            'outputs':[{'case_id':pair['case_id'],'input_digest':pair['input_digest'],'variants':{variant:{'text':'Synthetic fixture answer',
                'provider':'fixture','model':'fixture','policy_digest':digest(policy)} for variant,policy in
                [('control',exp['definition']['baseline_payload']),('candidate',report['selected_payload'])]}} for pair in report['holdout_pairs']]},'local-user')
    def user(self,role='reviewer',name='Same display name'):
        access=getattr(self,'access',None) or Collaboration(self.store);self.access=access
        if not hasattr(self,'doc'):
            self.doc=AcademyDocuments(self.store).save({'title':'Review invitations fixture','blocks':[{'id':'p','type':'paragraph','text':'fixture'}]})
        token,user=access.join(access.invite(self.doc['id'],'local-user','viewer')['code'],name)
        if role:self.review.grant(self.exp['id'],user['id'],role)
        return token,user['id']
    @staticmethod
    def rating(packet,score=.8):
        return {'packet_digest':packet['packet_digest'],'reviewer':'spoofed-name','ratings':[{'entry_id':entry['entry_id'],
          'options':{label:{'score':score,'rationale':'Synthetic explanation; not a teacher label','critical_error':False,
              'text_digest':value['text_digest']} for label,value in entry['options'].items()}} for entry in packet['entries']]}


class CaptureTests(Fixtures):
    size=20
    def run_capture(self,provider,**options):return asyncio.run(self.capture.capture(self.exp['id'],provider,**options))
    def test_capture_pairs_bind_exact_inputs_and_hide_raw_credentials(self):
        provider=ProtocolProvider();data=self.run_capture(provider)
        receipts=self.capture.receipts(self.exp['id']);self.assertEqual(len(receipts),len(self.exp['report']['holdout_pairs'])*2)
        self.assertEqual(len(provider.calls),len(receipts));self.assertTrue(self.review.summary(self.exp['id'])['provider_execution_verified'])
        self.assertTrue(all(options=={'temperature':0.,'max_tokens':256,'tools':[]} for _,options in provider.calls))
        self.assertNotIn('MUST-NOT-PERSIST',json.dumps(receipts));self.assertNotIn('http://',json.dumps(receipts))
        for row in receipts:self.assertEqual(row['request_digest'],digest(row['request']));self.assertEqual(row['text_digest'],digest(row['text']))
        self.assertEqual(data['capture']['status'],'completed')
        with self.assertRaisesRegex(ValueError,'already frozen'):self.run_capture(provider)
    def test_budget_and_provider_preflight_make_no_calls(self):
        provider=ProtocolProvider()
        with self.assertRaisesRegex(ValueError,'budget'):self.run_capture(provider,max_calls=1)
        with self.assertRaisesRegex(ValueError,'max_tokens'):self.run_capture(provider,max_tokens=1025)
        provider.name='mock'
        with self.assertRaisesRegex(ValueError,'non-mock'):self.run_capture(provider)
        self.assertEqual(provider.calls,[])
    def test_timeout_preserves_partial_and_explicit_resume_reuses_same_answer(self):
        provider=ProtocolProvider(failure_at=2)
        with self.assertRaises(asyncio.TimeoutError):self.run_capture(provider)
        before=self.capture.receipts(self.exp['id']);self.assertEqual(len(before),1);self.assertEqual(self.capture.state(self.exp['id'])['status'],'failed')
        provider.failure_at=None;self.run_capture(provider)
        self.assertIn(before[0],self.capture.receipts(self.exp['id']));self.assertEqual(len(provider.calls),self.capture.plan(self.exp['id'])['calls']+1)
    def test_changed_endpoint_or_options_cannot_mix_partial_evidence(self):
        provider=ProtocolProvider(failure_at=2)
        with self.assertRaises(asyncio.TimeoutError):self.run_capture(provider)
        with self.assertRaisesRegex(ValueError,'options changed'):self.run_capture(provider,max_tokens=64)
        provider.base_url='http://127.0.0.1:2/v1'
        with self.assertRaisesRegex(ValueError,'options changed'):self.run_capture(provider)
        self.assertEqual(len(provider.calls),2)
    def test_active_provider_configuration_drift_cannot_publish_a_response(self):
        provider=ProtocolProvider()
        async def drift():provider.base_url='http://127.0.0.1:2/v1'
        provider.hook=drift
        with self.assertRaisesRegex(ValueError,'configuration changed'):self.run_capture(provider)
        self.assertEqual(self.capture.receipts(self.exp['id']),[])
    def test_partial_or_tool_response_is_not_captured(self):
        provider=ProtocolProvider(finish='length')
        with self.assertRaisesRegex(ValueError,'incomplete/tool'):self.run_capture(provider)
        self.assertEqual(self.capture.receipts(self.exp['id']),[])
        provider.finish='stop';provider.tool_calls=True
        with self.assertRaisesRegex(ValueError,'incomplete/tool'):self.run_capture(provider)
    def test_pause_fences_inflight_answer_and_resume_keeps_same_definition(self):
        provider=ProtocolProvider()
        async def pause():self.capture.control(self.exp['id'])
        provider.hook=pause
        with self.assertRaisesRegex(ValueError,'lease lost'):self.run_capture(provider)
        self.assertEqual(self.capture.state(self.exp['id'])['status'],'paused');self.assertEqual(self.capture.receipts(self.exp['id']),[])
        provider.hook=None;self.run_capture(provider);self.assertEqual(self.store.get_evolution_experiment(self.exp['id'])['definition_digest'],self.exp['definition_digest'])
    def test_replaced_worker_cannot_write_or_mark_new_worker_failed(self):
        provider=ProtocolProvider()
        async def replace():
            with self.store.transaction() as conn:conn.execute("UPDATE evolution_model_jobs SET token='new-worker',lease_until=9999999999")
        provider.hook=replace
        with self.assertRaisesRegex(ValueError,'lease lost'):self.run_capture(provider)
        self.assertEqual(self.capture.state(self.exp['id'])['status'],'running');self.assertEqual(self.capture.receipts(self.exp['id']),[])
        with self.assertRaisesRegex(ValueError,'already running'):self.run_capture(ProtocolProvider())
    def test_corrupt_receipt_fails_closed_on_resume(self):
        provider=ProtocolProvider(failure_at=2)
        with self.assertRaises(asyncio.TimeoutError):self.run_capture(provider)
        with self.store._conn() as conn:conn.execute("UPDATE evolution_model_receipts SET receipt='{}'")
        with self.assertRaisesRegex(ValueError,'mismatch'):self.capture.receipts(self.exp['id'])
        with self.assertRaisesRegex(ValueError,'mismatch'):self.run_capture(ProtocolProvider())
    def test_baseline_drift_rejects_capture_before_provider_calls(self):
        with self.store._conn() as conn:conn.execute("INSERT INTO runtime_policies(target_type,target_key,payload,version) VALUES ('tool_routing_policy','default','{}',1)")
        provider=ProtocolProvider()
        with self.assertRaisesRegex(ValueError,'baseline policy changed'):self.run_capture(provider)
        self.assertEqual(provider.calls,[])
    def test_external_import_cannot_claim_application_captured_origin(self):
        self.packet();self.assertFalse(self.review.summary(self.exp['id'])['provider_execution_verified'])


class SessionReviewTests(Fixtures):
    size=200
    def setUp(self):
        super().setUp();self.blind=self.packet()
    def disputed(self):
        _,a=self.user();_,b=self.user();_,c=self.user('adjudicator')
        first=self.rating(self.blind,.8);second=self.rating(self.blind,.8)
        second['ratings'][0]['options']['A']['score']=.2
        self.review.submit(self.exp['id'],first,authenticated_uid=a);summary=self.review.submit(self.exp['id'],second,authenticated_uid=b)
        entry=self.blind['entries'][0]
        decision={'packet_digest':self.blind['packet_digest'],'review_set_digest':summary['authenticated_review_set_digest'],
                  'entry_id':entry['entry_id'],'options':copy.deepcopy(first['ratings'][0]['options'])}
        return a,b,c,decision
    def test_same_display_names_have_distinct_server_bound_identities(self):
        _,a=self.user();_,b=self.user()
        self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=a)
        summary=self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=b)
        self.assertEqual(summary['authenticated_reviewer_count'],2);self.assertTrue(summary['authenticated_review_passed'])
        self.assertFalse(summary['reviewer_identity_verified']);self.assertFalse(summary['real_person_independence_verified'])
        self.assertFalse(summary['runtime_promotion_evidence']);self.assertEqual(self.store.list_self_evolution_quality_signals(1),[])
        self.assertEqual({row['reviewer'] for row in self.review.evidence(self.exp['id'])['reviews']},{'session:'+a,'session:'+b})
    def test_legacy_uploads_cannot_spoof_session_reviewer_names(self):
        rating=self.rating(self.blind);rating['reviewer']='session:someone'
        with self.assertRaisesRegex(ValueError,'authenticated'):self.review.submit(self.exp['id'],rating)
    def test_roles_cannot_swap_or_self_assign_and_revocation_blocks_new_actions(self):
        _,a=self.user()
        with self.assertRaisesRegex(ValueError,'swapped'):self.review.grant(self.exp['id'],a,'adjudicator')
        with self.assertRaises(ValueError):self.review.grant(self.exp['id'],'local-user','reviewer')
        self.review.grant(self.exp['id'],a,'revoked')
        with self.assertRaises(PermissionError):self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=a)
        self.review.grant(self.exp['id'],a,'reviewer');self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=a)
        self.review.grant(self.exp['id'],a,'revoked');self.assertEqual(self.review.summary(self.exp['id'])['authenticated_reviewer_count'],1)
    def test_different_assigned_adjudicator_resolves_one_snapshot_and_preserves_original(self):
        a,b,c,decision=self.disputed();before=self.review.evidence(self.exp['id'])['reviews']
        with self.assertRaises(PermissionError):self.review.adjudicate(self.exp['id'],decision,a)
        summary=self.review.adjudicate(self.exp['id'],decision,c)
        self.assertEqual(summary['authenticated_resolved_entries'],1);self.assertTrue(summary['authenticated_review_passed'])
        self.assertEqual(self.review.evidence(self.exp['id'])['reviews'],before)
        self.review.adjudicate(self.exp['id'],decision,c)
        decision['options']['A']['score']=.4
        with self.assertRaisesRegex(ValueError,'immutable'):self.review.adjudicate(self.exp['id'],decision,c)
    def test_new_review_invalidates_old_decision_without_deleting_evidence(self):
        _,_,c,decision=self.disputed();self.review.adjudicate(self.exp['id'],decision,c)
        _,d=self.user();summary=self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=d)
        self.assertEqual(summary['authenticated_resolved_entries'],0);self.assertFalse(summary['authenticated_review_passed'])
        self.assertEqual(len(self.review.evidence(self.exp['id'])['adjudications']),1)
        with self.assertRaisesRegex(ValueError,'current snapshot'):self.review.adjudicate(self.exp['id'],decision,c)
    def test_critical_error_can_be_confirmed_and_still_blocks_release(self):
        _,_,c,decision=self.disputed();decision['options']['A']['critical_error']=True
        summary=self.review.adjudicate(self.exp['id'],decision,c)
        self.assertFalse(summary['authenticated_review_passed']);self.assertTrue(summary['authenticated_critical_errors'])
        self.assertFalse(summary['runtime_promotion_evidence'])
    def test_corrupt_original_review_cannot_be_laundered_by_adjudication(self):
        _,_,c,decision=self.disputed()
        with self.store._conn() as conn:conn.execute("UPDATE evolution_reviews SET submission='{}'")
        with self.assertRaisesRegex(ValueError,'digest mismatch'):self.review.adjudicate(self.exp['id'],decision,c)
    def test_authorization_is_rechecked_inside_write_transaction(self):
        _,a=self.user()
        with self.assertRaises(PermissionError):
            self.review.submit(self.exp['id'],self.rating(self.blind),authenticated_uid=a,authorization_check=lambda:False)
        self.assertEqual(self.review.summary(self.exp['id'])['reviewer_count'],0)
    def test_actual_http_sessions_cannot_cross_role_or_owner_boundaries(self):
        import clawos_server as server
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        token,a=self.user();other_token,b=self.user(role=None);self.user('adjudicator')
        app=FastAPI();app.middleware('http')(server.workbench_access)
        for route in server.app.routes:
            if route.path.startswith(('/api/evolution-review/','/api/self-evolution/')):app.router.routes.append(route)
        base=f'/api/evolution-review/{self.exp["id"]}'
        with patch.object(server,'g_memory_store',self.store),patch.object(server,'_collaboration',return_value=self.access),TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',45678)) as client:
            headers={'Authorization':'Bearer '+token}
            response=client.get(base+'/packet',headers=headers);self.assertEqual(response.status_code,200,response.text)
            data=response.json();self.assertEqual(data['viewer']['id'],a);self.assertNotIn('reviewed_gate',data['summary']);self.assertNotIn('prior_ratings',data['packet'])
            self.assertEqual(client.get(base+'/packet',headers={'Authorization':'Bearer '+other_token}).status_code,403)
            self.assertEqual(client.get('/api/evolution-review/999999/packet',headers=headers).status_code,403)
            self.assertEqual(client.get('/api/self-evolution/review-users',headers=headers).status_code,403)
            self.assertEqual(client.post(f'/api/self-evolution/experiments/{self.exp["id"]}/review-grants',headers=headers,json={'user_id':b,'role':'reviewer'}).status_code,403)
            self.assertEqual(client.post(base+'/adjudication',headers=headers,json={}).status_code,403)
            self.assertEqual(client.post(base+'/ratings',headers={**headers,'Origin':'https://bad.example'},json=self.rating(self.blind)).status_code,403)
            self.assertEqual(client.get(base+'/packet',headers={'X-Forwarded-For':'127.0.0.1'}).status_code,401)
            self.assertEqual(client.get(base+'/packet').status_code,403)
            response=client.post(base+'/ratings',headers=headers,json=self.rating(self.blind));self.assertEqual(response.status_code,200,response.text)
            own=client.get(base+'/packet',headers=headers).json()
            self.assertEqual(own['packet']['own_ratings'],sorted(self.rating(self.blind)['ratings'],key=lambda row:row['entry_id']))
            self.assertEqual(self.review.evidence(self.exp['id'])['reviews'][0]['reviewer'],'session:'+a)
            self.review.grant(self.exp['id'],a,'revoked');self.assertEqual(client.post(base+'/ratings',headers=headers,json=self.rating(self.blind)).status_code,403)
            with self.store._conn() as conn:conn.execute('UPDATE collaboration_sessions SET expires=0 WHERE hash=?',(session_hash(other_token),))
            self.assertEqual(client.get(base+'/packet',headers={'Authorization':'Bearer '+other_token}).status_code,401)


if __name__=='__main__':unittest.main()
