"""Independent evidence-update transactions, scope and notification tests."""
import copy
import asyncio
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_synthesis as fixtures
from services.research_synthesis import ResearchSynthesis
from services.research_updates import ResearchUpdates,evidence_delta
from services.research_watch import fingerprint
from services.research_watch import ResearchWatchWorker
from services.research_watch_api import research_watch_router


class UpdateTests(unittest.TestCase):
    setUp=fixtures.SynthesisTests.setUp
    subscription=fixtures.SynthesisTests.subscription
    run_page=fixtures.SynthesisTests.run_page
    seed=fixtures.SynthesisTests.seed

    def setup_report(self,**data):
        self.sid=self.seed();self.updates=ResearchUpdates(self.watch)
        self.base=self.synthesis.create('alice',data);return self.base

    def ingest(self,rows):
        self.now[0]+=21601;self.run_page(fixtures.page(rows))

    def count(self,table):
        with self.store._conn() as c:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_new_paper_creates_frozen_lineage_delta_and_single_notification(self):
        self.setup_report();before=copy.deepcopy(self.base)
        edge=self.base['report']['edges'][0];papers={p['id']:p for p in self.base['report']['papers']}
        self.synthesis.review('alice',self.base['id'],edge['id'],dict(status='confirmed',kind='related',reason='两端原文已由人工核对，仅为相关工作判断。',version=0,
            evidence=[dict(paper_id=p,source_index=0,quote=papers[p]['sources'][0]['text'][:40]) for p in (edge['source'],edge['target'])]))
        self.ingest([fixtures.row(title='New study',doi='10.1234/new',abstract='We propose a new retrieval method. Results show limited gains.')])
        out=self.updates.check('alice',self.base['id'],dict(version=0));self.assertTrue(out['changed'])
        value=self.synthesis.get('alice',out['head_id']);d=out['update']['delta']
        self.assertEqual(d['counts']['added_papers'],1);self.assertGreater(d['counts']['added_excerpts'],0)
        self.assertEqual(value['report']['lineage']['parent_report_id'],self.base['id'])
        self.assertEqual(value['report']['lineage']['generation'],2)
        self.assertEqual(self.updates.status('alice',value['id'])['previous']['base_id'],self.base['id'])
        self.assertEqual(self.updates.status('alice',self.base['id'])['next']['report_id'],value['id'])
        self.assertEqual(self.synthesis.get('alice',self.base['id'])['report'],before['report'])
        self.assertEqual(self.updates.notifications('alice')['unread'],1)
        self.assertEqual(value['reviews'],{})
        self.assertTrue(self.synthesis.get('alice',self.base['id'])['reviews'])
        with self.assertRaises(ValueError):self.updates.check('alice',self.base['id'],dict(version=0))

    def test_identical_checks_do_not_make_versions_or_notifications(self):
        self.setup_report();out=self.updates.check('alice',self.base['id'],dict(version=0))
        self.assertFalse(out['changed']);self.assertEqual(self.count('research_synthesis_reports'),1)
        self.assertEqual(self.count('research_synthesis_updates'),0)
        self.now[0]+=61;self.assertFalse(self.updates.check('alice',self.base['id'],dict(version=1))['changed'])
        self.assertEqual(self.updates.notifications('alice')['unread'],0)

    def test_explicit_scope_does_not_expand_and_subscription_scope_does(self):
        self.setup_report();pid=self.base['report']['papers'][0]['id']
        fixed=self.synthesis.create('alice',dict(paper_ids=[pid]))
        dynamic=self.synthesis.create('alice',dict(subscription_id=self.sid))
        self.ingest([fixtures.row(title='New study',doi='10.1234/new')])
        self.assertFalse(self.updates.check('alice',fixed['id'],dict(version=0))['changed'])
        self.assertEqual(self.updates.check('alice',dynamic['id'],dict(version=0))['update']['delta']['counts']['added_papers'],1)

    def test_exact_old_and_new_evidence_is_retained_in_delta_and_export(self):
        self.setup_report();self.ingest([fixtures.row(title='Evidence method A',doi='10.1234/a',abstract='We propose a changed retrieval method. Results show no improvement. However this study is limited.')])
        out=self.updates.check('alice',self.base['id'],dict(version=0));d=out['update']['delta']
        changed=next(p for p in d['papers'] if p['after']['doi']=='10.1234/a')
        self.assertTrue(changed['text_changed']);self.assertTrue(changed['sections']['method']['added']);self.assertTrue(changed['sections']['method']['removed'])
        for section in changed['sections'].values():
            for claim in section['added']+section['removed']:
                e=claim['evidence'];snap=self.watch.snapshot('alice',e['snapshot_id'])
                self.assertEqual(snap['paper'][e['field']][e['start']:e['end']],claim['text'])
                self.assertEqual(snap['hash'],e['sha256'])
        export=self.updates.export('alice',out['update']['id'])
        self.assertIn('Results show no improvement.',export['markdown'])
        self.assertIn('SHA256',export['markdown']);self.assertIn(self.base['id'],export['markdown'])

    def test_reference_only_update_not_described_as_new_semantic_evidence(self):
        self.setup_report();original=next(p for p in self.base['report']['papers'] if p['doi']=='10.1234/a')
        self.ingest([fixtures.row(title=original['title'],doi=original['doi'],published='2025',abstract=original['sources'][0]['text'],references=[dict(doi='10.1234/external')],references_available=True)])
        d=self.updates.check('alice',self.base['id'],dict(version=0))['update']['delta']
        self.assertEqual(d['counts']['added_excerpts'],0);self.assertEqual(d['counts']['added_relations'],1)
        self.assertFalse(d['papers'][0]['text_changed']);self.assertTrue(d['papers'][0]['bibliography_changed'])

    def test_index_timestamp_and_snapshot_ids_alone_do_not_trigger_update(self):
        self.setup_report();p=next(p for p in self.base['report']['papers'] if p['doi']=='10.1234/a')
        self.ingest([fixtures.row(title=p['title'],doi=p['doi'],published='2025',abstract=p['sources'][0]['text'],updated='2026-10-31T00:00:00Z')])
        self.assertFalse(self.updates.check('alice',self.base['id'],dict(version=0))['changed'])

    def test_author_metadata_change_is_visible_without_new_scholarly_excerpt(self):
        self.setup_report();p=next(p for p in self.base['report']['papers'] if p['doi']=='10.1234/a')
        self.ingest([fixtures.row(title=p['title'],doi=p['doi'],published='2025',abstract=p['sources'][0]['text'],authors=['Corrected Author'])])
        delta=self.updates.check('alice',self.base['id'],dict(version=0))['update']['delta']
        self.assertIn('authors',delta['papers'][0]['fields']);self.assertEqual(delta['counts']['added_excerpts'],0)

    def test_scheduled_failure_rolls_back_report_and_preserves_head(self):
        self.setup_report();self.updates.configure('alice',self.base['id'],dict(enabled=True,interval_hours=6,version=0))
        self.ingest([fixtures.row(title='New study',doi='10.1234/new')])
        original=self.synthesis.create
        def fail(*args,**kw):original(*args,**kw);raise RuntimeError('sensitive message must not persist')
        with patch.object(self.updates.synthesis,'create',side_effect=fail):self.assertEqual(self.updates.tick()[0]['error'],'RuntimeError')
        t=self.updates.status('alice',self.base['id'])['track'];self.assertEqual(t['head_id'],self.base['id'])
        self.assertEqual(t['last_error'],'RuntimeError');self.assertEqual(t['next_due'],self.now[0]+900)
        self.assertEqual(self.count('research_synthesis_reports'),1);self.assertEqual(self.updates.notifications('alice')['unread'],0)

    def test_atomic_outbox_rolls_back_if_notification_insert_fails(self):
        self.setup_report();self.ingest([fixtures.row(title='New study',doi='10.1234/new')])
        with self.store._conn() as c:c.execute("CREATE TRIGGER reject_notice BEFORE INSERT ON research_synthesis_update_notifications BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(Exception):self.updates.check('alice',self.base['id'],dict(version=0))
        self.assertEqual(self.count('research_synthesis_reports'),1);self.assertEqual(self.count('research_synthesis_updates'),0)
        self.assertIsNone(self.updates.status('alice',self.base['id'])['track'])

    def test_concurrent_checks_publish_once_and_reject_stale_version(self):
        self.setup_report();self.ingest([fixtures.row(title='New study',doi='10.1234/new')]);barrier=threading.Barrier(2)
        def check():
            barrier.wait()
            try:return self.updates.check('alice',self.base['id'],dict(version=0))
            except ValueError:return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:check(),range(2)))
        self.assertEqual(results.count('stale'),1);self.assertEqual(self.count('research_synthesis_updates'),1)
        self.assertEqual(self.updates.notifications('alice')['unread'],1)

    def test_legacy_reports_keep_original_ids_and_tampering_fails(self):
        self.setup_report();r=copy.deepcopy(self.base['report']);r.pop('selection')
        with self.store._conn() as c:c.execute('UPDATE research_synthesis_reports SET payload=?,hash=? WHERE id=?',(json.dumps(r),fingerprint(r),r['id']))
        self.ingest([fixtures.row(title='New study',doi='10.1234/new')])
        self.assertFalse(self.updates.check('alice',r['id'],dict(version=0))['changed'])
        with self.store._conn() as c:c.execute("UPDATE research_synthesis_reports SET payload='{}' WHERE id=?",(r['id'],))
        with self.assertRaisesRegex(ValueError,'完整性'):self.updates.status('alice',r['id'])

    def test_pause_resume_due_time_and_deleted_subscription_failure(self):
        self.setup_report()
        # Create an explicitly subscription-scoped report after seed.
        r=self.synthesis.create('alice',dict(subscription_id=self.sid));self.updates.configure('alice',r['id'],dict(enabled=True,interval_hours=6,version=0))
        self.assertEqual(self.updates.tick(),[])
        self.updates.configure('alice',r['id'],dict(enabled=False,interval_hours=6,version=1));self.now[0]+=21601
        self.assertEqual(self.updates.tick(),[])
        self.updates.configure('alice',r['id'],dict(enabled=True,interval_hours=6,version=2));self.now[0]+=21601
        self.watch.action('alice',self.sid,'delete');self.assertEqual(self.updates.tick()[0]['error'],'LookupError')
        self.assertEqual(self.updates.status('alice',r['id'])['track']['head_id'],r['id'])

    def test_owner_scoped_api_notifications_and_corrupt_delta(self):
        self.setup_report();self.ingest([fixtures.row(title='New study',doi='10.1234/new')]);out=self.updates.check('alice',self.base['id'],dict(version=0));uid=out['update']['id']
        class Identity:
            def identity(self,request):
                owner=request.headers.get('x-fixture-owner')
                if owner not in ('alice','bob'):raise HTTPException(401,'test identity')
                return dict(id=owner)
        app=FastAPI();app.include_router(research_watch_router(lambda:self.watch,Identity,lambda:{}))
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/research/watch/updates/'+uid,headers={'x-fixture-owner':'bob'}).status_code,404)
            self.assertEqual(client.get('/api/research/watch/updates/'+uid,headers={'x-fixture-owner':'alice'}).status_code,200)
            state=client.get('/api/research/watch',headers={'x-fixture-owner':'alice'}).json();nid=state['review_updates']['items'][0]['id']
            self.assertEqual(client.post('/api/research/watch/update-notifications/'+nid+'/read',json={},headers={'x-fixture-owner':'bob'}).status_code,404)
            self.assertEqual(client.post('/api/research/watch/update-notifications/'+nid+'/read',json={},headers={'x-fixture-owner':'alice'}).status_code,200)
        with self.store._conn() as c:c.execute("UPDATE research_synthesis_updates SET payload='{}' WHERE id=?",(uid,))
        with self.assertRaisesRegex(ValueError,'完整性'):self.updates.get('alice',uid)

    def test_explicit_fulltext_is_rebound_and_old_excerpt_stays_frozen(self):
        self.subscription(owner='local-user');self.run_page(fixtures.page([fixtures.row(title='Bound full paper',doi='10.1234/full')]))
        pid=self.watch.feed('local-user')['items'][0]['paper_id']
        doc=self.store.add_document(title='Bound full paper',filename='full.txt',file_hash='update-fulltext',category='research')
        self.store.add_document_chunk(doc['id'],1,'We propose an original retrieval method for controlled experiments.','fixture:full#1')
        s=ResearchSynthesis(self.watch);base=s.create('local-user',dict(paper_ids=[pid],documents={pid:doc['id']}))
        with self.store._conn() as c:c.execute('UPDATE document_chunks SET content=? WHERE document_id=?',('We propose a revised retrieval method with a different design.',doc['id']))
        updates=ResearchUpdates(self.watch);out=updates.check('local-user',base['id'],dict(version=0))
        self.assertTrue(out['changed']);changed=out['update']['delta']['papers'][0]
        self.assertTrue(changed['text_changed'])
        self.assertTrue(any('revised' in v['text'] for v in changed['sections']['method']['added']))
        self.assertEqual(s.get('local-user',base['id'])['report'],base['report'])

    def test_stable_identity_merge_is_not_a_paper_removal(self):
        self.subscription();self.run_page(fixtures.page([fixtures.row(title='Preprint',doi='',arxiv_id='2610.12345',source_id='arxiv-first'),fixtures.row(title='Published',doi='10.1234/published',source_id='doi-first')]))
        s=ResearchSynthesis(self.watch);base=s.create('alice',{});updates=ResearchUpdates(self.watch)
        self.ingest([fixtures.row(title='Published',doi='10.1234/published',arxiv_id='2610.12345',source_id='bridge')])
        d=updates.check('alice',base['id'],dict(version=0))['update']['delta']
        self.assertEqual(d['counts']['merged_papers'],1);self.assertEqual(d['counts']['removed_papers'],0)
        self.assertEqual(d['counts']['added_papers'],0)

    def test_existing_background_worker_runs_due_overview_updates(self):
        self.setup_report();self.updates.configure('alice',self.base['id'],dict(enabled=True,interval_hours=6,version=0))
        self.ingest([fixtures.row(title='New study',doi='10.1234/new')]);worker=ResearchWatchWorker(self.watch)
        async def stop_at_sleep(_):worker.stopping=True
        with patch('services.research_watch.asyncio.sleep',new=stop_at_sleep):asyncio.run(worker.run())
        self.assertEqual(worker.last_error,'');self.assertEqual(self.updates.notifications('alice')['unread'],1)


if __name__=='__main__':unittest.main()
