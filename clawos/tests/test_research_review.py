"""Review-account fixtures test mechanisms, never independent human acceptance."""
import asyncio
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_synthesis as fixtures
from services.research_review import ResearchReview
from services.research_review_examples import candidate_suite
from services.research_watch_api import research_watch_router
from services.research_ai import ResearchAI,SECTIONS
from services.collaboration import Collaboration


class ReviewTests(unittest.TestCase):
    setUp=fixtures.SynthesisTests.setUp
    subscription=fixtures.SynthesisTests.subscription
    run_page=fixtures.SynthesisTests.run_page
    seed=fixtures.SynthesisTests.seed

    def setup_review(self,assigned=True,**data):
        Collaboration(self.store)
        with self.store._conn() as c:c.executemany('INSERT INTO collaboration_users VALUES (?,?)',[(v,'Test fixture '+v) for v in ('r1','r2','judge','outsider')])
        self.review=ResearchReview(self.watch)
        value=dict(kind='benchmark')
        if assigned:value.update(reviewer_ids=['r1','r2'],adjudicator_id='judge')
        value.update(data);self.round=self.review.create('alice',value);return self.round

    @staticmethod
    def judgment(verdict='supported',ref='attention-v7',**changes):
        data=dict(verdict=verdict,reason='Test-only assessment of the supplied excerpt and its boundary.',issues=['version'],evidence_ids=[ref] if ref else [],human_confirmed=True)
        data.update(changes);return data

    def test_three_domain_candidates_are_unreviewed_controls_not_gold(self):
        value=self.setup_review();self.assertEqual(len(value['cases']),15)
        self.assertEqual({c['domain'] for c in value['cases']},{'AI方法','生物医学','气候科学'})
        self.assertEqual(value['summary']['pending'],15);self.assertIsNone(value['summary']['agreement_rate'])
        self.assertFalse(value['human_validation_complete'])
        self.assertTrue(all(c['origin']=='constructed_claim_control' and c['curator_proposal']['status']=='unreviewed_assistant_proposal' for c in value['cases']))
        sources={e['id']:e for c in value['cases'] for e in c['evidence']}
        self.assertEqual(len(sources),8);self.assertEqual(sum(e['capture']['verified'] for e in sources.values()),7)
        self.assertEqual(sources['ipcc']['capture']['http_status'],403)

    def test_peer_labels_are_blind_until_own_immutable_submission(self):
        r=self.setup_review();rid=r['id']
        self.review.vote('r1',rid,'AI-01',self.judgment())
        blind=self.review.get('r2',rid);case=blind['cases'][0]
        self.assertEqual(case['peer_votes'],[]);self.assertIsNone(blind['summary']);self.assertNotIn('curator_proposal',case)
        self.assertNotIn('mechanical_check',case)
        self.assertNotIn('report_id',blind['source']);self.assertEqual(case['status'],'blind_review')
        shown=self.review.vote('r2',rid,'AI-01',self.judgment())
        self.assertEqual(len(shown['cases'][0]['peer_votes']),2)
        self.assertEqual(shown['cases'][0]['status'],'account_agreement')
        with self.assertRaisesRegex(ValueError,'冻结'):self.review.vote('r2',rid,'AI-01',self.judgment(verdict='insufficient'))

    def test_two_account_agreement_is_not_independent_expert_acceptance(self):
        r=self.setup_review();rid=r['id']
        for actor in ('r1','r2'):self.review.vote(actor,rid,'AI-01',self.judgment())
        owner=self.review.get('alice',rid);self.assertEqual(owner['summary']['account_resolved'],1)
        self.assertEqual(owner['summary']['agreement_rate'],1)
        self.assertFalse(owner['summary']['human_independence_verified']);self.assertFalse(owner['human_validation_complete'])

    def test_mechanical_negative_control_exposes_remaining_semantic_gap(self):
        r=self.setup_review(assigned=False)
        control=next(c for c in r['cases'] if c['id']=='BIO-02')
        self.assertEqual(control['curator_proposal']['verdict'],'contradicted')
        self.assertTrue(control['mechanical_check']['kept'])
        self.assertFalse(control['mechanical_check']['semantic_entailment_verified'])

    def test_disagreement_requires_distinct_adjudicator_after_both_votes(self):
        r=self.setup_review();rid=r['id']
        with self.assertRaises(ValueError):self.review.vote('judge',rid,'AI-01',self.judgment())
        self.review.vote('r1',rid,'AI-01',self.judgment())
        self.review.vote('r2',rid,'AI-01',self.judgment(verdict='needs_full_text',ref=''))
        self.assertEqual(self.review.get('alice',rid)['summary']['unresolved_conflicts'],1)
        self.review.vote('judge',rid,'AI-01',self.judgment(verdict='insufficient',ref=''))
        result=self.review.get('alice',rid)
        self.assertEqual(result['cases'][0]['status'],'account_adjudicated')
        self.assertEqual(result['cases'][0]['verdict'],'insufficient');self.assertEqual(result['summary']['unresolved_conflicts'],0)

    def test_self_review_does_not_satisfy_double_review_and_retries_are_idempotent(self):
        r=self.setup_review(assigned=False);rid=r['id']
        for _ in range(2):self.review.vote('alice',rid,'AI-01',self.judgment())
        value=self.review.get('alice',rid);self.assertTrue(value['cases'][0]['own_vote']['self_review'])
        self.assertEqual(value['summary']['double_reviewed'],0);self.assertEqual(value['summary']['pending'],15)
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM research_review_votes').fetchone()[0],1)

    def test_permissions_revocation_removes_read_write_export_and_quorum(self):
        r=self.setup_review();rid=r['id']
        with self.assertRaises(LookupError):self.review.get('outsider',rid)
        with self.assertRaises(PermissionError):self.review.export('r1',rid)
        with self.assertRaises(PermissionError):self.review.revoke('r1',rid,'r2')
        for actor in ('r1','r2'):self.review.vote(actor,rid,'AI-01',self.judgment())
        self.review.revoke('alice',rid,'r1')
        with self.assertRaises(LookupError):self.review.get('r1',rid)
        with self.assertRaises(LookupError):self.review.vote('r1',rid,'AI-02',self.judgment(ref='attention-v1'))
        self.assertEqual(self.review.list('r1')['items'],[])
        self.assertEqual(self.review.get('alice',rid)['summary']['account_resolved'],0)

    def test_duplicate_owner_unknown_and_reused_role_assignments_are_rejected(self):
        self.setup_review()
        for peers,judge in [(['r1','r1'],'judge'),(['alice','r2'],'judge'),(['r1','r2'],'r1'),(['r1','unknown'],'judge')]:
            with self.assertRaises(ValueError):self.review.create('alice',dict(kind='benchmark',reviewer_ids=peers,adjudicator_id=judge))

    def test_per_claim_citations_human_attestation_and_reason_are_required(self):
        r=self.setup_review()
        for change in [dict(ref='gpt3'),dict(ref=''),dict(human_confirmed=False),dict(reason='short')]:
            with self.assertRaises(ValueError):self.review.vote('r1',r['id'],'AI-01',self.judgment(**change))

    def test_corrupt_round_and_prior_vote_fail_before_new_vote_write(self):
        r=self.setup_review();rid=r['id'];self.review.vote('r1',rid,'AI-01',self.judgment())
        with self.store._conn() as c:c.execute("UPDATE research_review_votes SET payload='{}'")
        with self.assertRaisesRegex(ValueError,'完整性'):self.review.vote('r2',rid,'AI-01',self.judgment())
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_review_votes').fetchone()[0],1)
            c.execute("UPDATE research_review_rounds SET payload='{}' WHERE id=?",(rid,))
        with self.assertRaisesRegex(ValueError,'完整性'):self.review.get('alice',rid)

    def test_concurrent_different_submissions_cannot_overwrite_first_vote(self):
        r=self.setup_review();barrier=threading.Barrier(2)
        def submit(label):
            barrier.wait()
            try:self.review.vote('r1',r['id'],'AI-01',self.judgment(verdict=label));return 'submitted'
            except ValueError:return 'frozen'
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(submit,['supported','insufficient']))
        self.assertEqual(sorted(result),['frozen','submitted'])

    def test_owned_report_and_ai_job_are_frozen_with_explicit_coverage(self):
        self.seed();report=self.synthesis.create('alice',{})
        self.setup_review(assigned=False)
        r=self.review.create('alice',dict(kind='report',report_id=report['id'],limit=1))
        self.assertEqual(r['source']['report_hash'],report['hash']);self.assertEqual(r['coverage']['selected'],1)
        self.assertGreater(r['coverage']['omitted'],0)
        with self.assertRaises(LookupError):self.review.create('bob',dict(kind='report',report_id=report['id']))
        ai=ResearchAI(self.watch);job=ai.enqueue('alice',report['id']);claimed=ai.claim()
        async def model(messages,*_,**__):
            data=json.loads(messages[-1]['content'])
            if 'claims' in data:value=dict(reviews=[dict(id=c['id'],verdict='supported',reason='fixture only') for c in data['claims']])
            else:
                value={k:[] for k in SECTIONS};value['overview']=[dict(text=data['evidence'][0]['quote'],citations=[data['evidence'][0]['id']],kind='reported')]
            return dict(choices=[dict(message=dict(content=json.dumps(value)),finish_reason='stop')])
        asyncio.run(ai.execute(claimed,model))
        generated=self.review.create('alice',dict(kind='ai',report_id=report['id'],job_id=job['id']))
        self.assertEqual(generated['cases'][0]['origin'],'frozen_ai_job');self.assertEqual(len(generated['cases'][0]['evidence']),1)
        self.assertEqual(self.synthesis.get('alice',report['id'])['report'],report['report'])

    def test_api_identity_scope_csrf_and_owner_exports(self):
        r=self.setup_review();rid=r['id']
        class Identity:
            def identity(self,request):
                actor=request.headers.get('x-fixture-actor')
                if actor not in ('alice','r1','outsider'):raise HTTPException(401,'fixture identity')
                return dict(id=actor)
        app=FastAPI();app.include_router(research_watch_router(lambda:self.watch,Identity,lambda:{}))
        path='/api/research/watch/reviews/'+rid
        with TestClient(app) as client:
            self.assertEqual(client.get(path).status_code,401)
            self.assertEqual(client.get(path,headers={'x-fixture-actor':'outsider'}).status_code,404)
            self.assertEqual(client.get(path+'/export',headers={'x-fixture-actor':'r1'}).status_code,403)
            self.assertEqual(client.get(path+'/export',headers={'x-fixture-actor':'alice'}).status_code,200)
            self.assertEqual(client.post(path+'/cases/AI-01',json=self.judgment(),headers={'x-fixture-actor':'r1','Origin':'https://evil.example'}).status_code,403)


if __name__=='__main__':unittest.main()
