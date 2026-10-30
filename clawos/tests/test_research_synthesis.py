"""Research overviews are frozen evidence drafts, not scholarly truth certificates."""
import copy
import json
import unittest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_watch as fixtures
page,row=fixtures.page,fixtures.row
from services.research_synthesis import ResearchSynthesis,publication
from services.research_watch_api import research_watch_router


class SynthesisTests(unittest.TestCase):
    setUp=fixtures.WatchTests.setUp
    subscription=fixtures.WatchTests.subscription
    run_page=fixtures.WatchTests.run_page

    def seed(self):
        sid=self.subscription()
        self.run_page(page([row(title='Evidence method A',doi='10.1234/a',published='2025',abstract='We study retrieval evidence. We propose a method. Results show better accuracy. However the evaluation is limited.'),
                            row(title='Evidence method B',doi='10.1234/b',published='2026-02',abstract='We study retrieval evidence. We introduce a framework. We evaluate on a small dataset. Results show no improvement.')]))
        self.synthesis=ResearchSynthesis(self.watch)
        return sid

    def report(self,**changes):
        self.seed();data=dict(title='Evidence survey');data.update(changes)
        return self.synthesis.create('alice',data)

    def test_overview_has_sections_dates_gaps_and_exact_evidence(self):
        v=self.report();r=v['report']
        self.assertEqual(r['coverage']['papers'],2)
        self.assertEqual(r['coverage']['full_text_bound'],0)
        self.assertEqual([t['date']['precision'] for t in r['timeline']],['year','month'])
        self.assertTrue(r['groups'][0]['sections']['method'])
        self.assertTrue(r['groups'][0]['sections']['finding'])
        for p in r['papers']:
            for claims in p['sections'].values():
                for claim in claims:
                    e=claim['evidence'];source=next(s for s in p['sources'] if s['sha256']==e['sha256'])
                    self.assertEqual(source['text'][e['start']:e['end']],e['quote'])
        self.assertTrue(all(e['status']=='proposed' for e in r['edges']))

    def test_report_remains_frozen_after_new_metadata_and_classification(self):
        v=self.report();before=self.synthesis.get('alice',v['id'])
        item=self.watch.feed('alice')['items'][0]
        self.watch.reclassify('alice',item['subscription_id'],item['paper_id'],['待归类'])
        self.now[0]+=21601;self.run_page(page([row(title='Updated metadata',doi='10.1234/a',abstract='Different source text.')]))
        self.assertEqual(before,self.synthesis.get('alice',v['id']))

    def test_rejects_other_user_ids_and_reports_and_fulltext(self):
        v=self.report();pid=v['report']['papers'][0]['id']
        with self.assertRaises(LookupError):self.synthesis.get('bob',v['id'])
        with self.assertRaises(LookupError):self.synthesis.create('bob',dict(paper_ids=[pid]))
        with self.assertRaises(PermissionError):self.synthesis.create('alice',dict(documents={pid:1}))

    def test_relation_confirmation_requires_both_exact_quotes_and_compare_and_swap(self):
        v=self.report();r=v['report'];edge=r['edges'][0]
        data=dict(status='confirmed',kind='extends',reason='人工检查两项方法的关联，仍需独立学术复核。',version=0,evidence=[])
        with self.assertRaises(ValueError):self.synthesis.review('alice',v['id'],edge['id'],data)
        for pid in [edge['source'],edge['target']]:
            p=next(p for p in r['papers'] if p['id']==pid)
            data['evidence'].append(dict(paper_id=pid,source_index=0,quote=p['sources'][0]['text'][:40]))
        invalid=copy.deepcopy(data);invalid['evidence'][0]['quote']='Invented unsupported source quote.'
        with self.assertRaises(ValueError):self.synthesis.review('alice',v['id'],edge['id'],invalid)
        result=self.synthesis.review('alice',v['id'],edge['id'],data)
        self.assertEqual(result['version'],1)
        with self.assertRaisesRegex(ValueError,'冲突'):self.synthesis.review('alice',v['id'],edge['id'],data)
        self.assertEqual(self.synthesis.get('alice',v['id'])['report'],r)

    def test_empty_evidence_is_explicit_and_unknown_dates_not_fabricated(self):
        sid=self.seed();self.now[0]+=21601
        self.run_page(page([row(title='Evidence title only',doi='10.1234/c',published='',abstract='')]))
        r=self.synthesis.create('alice',{})['report']
        p=next(p for p in r['papers'] if p['doi']=='10.1234/c')
        self.assertEqual(len(p['missing']),5);self.assertEqual(p['date']['precision'],'unknown')
        self.assertFalse(p['full_text_bound'])

    def test_partial_invalid_dates(self):
        self.assertEqual(publication('2025')['value'],'2025')
        self.assertEqual(publication('2025-02')['precision'],'month')
        self.assertEqual(publication('2025-02-30')['precision'],'unknown')

    def test_explicit_fulltext_binding_validates_identity_and_freezes_local_chunks(self):
        sid=self.subscription(owner='local-user')
        self.run_page(page([row(title='Evidence full paper',doi='10.1234/full',abstract='We study retrieval evidence.')]))
        item=self.watch.feed('local-user')['items'][0];pid=item['paper_id']
        doc=self.store.add_document(title='Evidence full paper',filename='full.txt',file_hash='fixture-full',category='research')
        self.store.add_document_chunk(doc['id'],1,'We propose a grounded algorithm. Experiments evaluate 20 cases. However the study is limited.',f"doc:{doc['id']}#page=1&chunk=1")
        s=ResearchSynthesis(self.watch)
        v=s.create('local-user',dict(documents={pid:doc['id']}))
        self.assertEqual(v['report']['coverage']['full_text_bound'],1)
        claims=v['report']['papers'][0]['sections']['method']
        self.assertTrue(any(c['evidence']['basis']=='parsed_full_text' for c in claims))
        wrong=self.store.add_document(title='Wrong paper',filename='wrong.txt',file_hash='wrong',category='research')
        self.store.add_document_chunk(wrong['id'],1,'An unrelated source document cites 10.1234/full in its bibliography.','fixture:wrong')
        with self.assertRaisesRegex(ValueError,'不匹配'):s.create('local-user',dict(documents={pid:wrong['id']}))

    def test_corrupt_source_snapshot_is_not_used_for_cited_overview(self):
        self.seed()
        with self.store._conn() as c:
            c.execute('UPDATE research_watch_snapshots SET payload=?',(json.dumps(dict(title='Corrupt source')),))
        with self.assertRaisesRegex(ValueError,'快照完整性'):self.synthesis.create('alice',{})

    def test_export_preserves_evidence_and_report_integrity(self):
        v=self.report();out=self.synthesis.export('alice',v['id'])
        self.assertIn('SHA256',out['markdown']);self.assertIn('待复核',out['markdown'])
        with self.store._conn() as c:c.execute('UPDATE research_synthesis_reports SET payload=? WHERE id=?',('{}',v['id']))
        with self.assertRaisesRegex(ValueError,'完整性'):self.synthesis.get('alice',v['id'])

    def test_no_empty_or_invalid_selection_silently_accepted(self):
        self.seed()
        with self.assertRaises(LookupError):self.synthesis.create('alice',dict(paper_ids=['missing']))
        with self.assertRaises(ValueError):self.synthesis.create('alice',dict(paper_ids=['x']*101))
        with self.assertRaises(ValueError):self.synthesis.create('bob',{})

    def test_synthesis_router_create_read_review_export_and_owner_scope(self):
        self.seed()
        class Identity:
            def identity(self,request):
                if request.headers.get('authorization') not in ('Bearer alice','Bearer bob'):raise HTTPException(401,'session required')
                return dict(id=request.headers['authorization'][7:])
        app=FastAPI();app.include_router(research_watch_router(lambda:self.watch,Identity,lambda:dict(running=True)))
        with TestClient(app) as client:
            h={'Authorization':'Bearer alice'}
            made=client.post('/api/research/watch/syntheses',json={},headers=h)
            self.assertEqual(made.status_code,201,made.text)
            rid=made.json()['id']
            self.assertEqual(client.get(f'/api/research/watch/syntheses/{rid}/export',headers=h).status_code,200)
            self.assertEqual(client.get(f'/api/research/watch/syntheses/{rid}',headers={'Authorization':'Bearer bob'}).status_code,404)


if __name__=='__main__':unittest.main()
