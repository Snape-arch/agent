"""Citations/versions require provider records, not title similarity or time order."""
import copy
import json
import unittest
from urllib.parse import unquote
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_synthesis as fixtures
from services.research_watch_sources import WatchSources
from services.research_bibliography import arxiv_parts,metadata_fields,build_graph,source_records
from services.research_metadata import ResearchMetadata
from services.research_watch_api import research_watch_router


class BibliographyTests(unittest.TestCase):
    setUp=fixtures.SynthesisTests.setUp
    subscription=fixtures.SynthesisTests.subscription
    run_page=fixtures.SynthesisTests.run_page

    def seed(self):
        sid=self.subscription(sources=['crossref'])
        self.run_page(fixtures.page([fixtures.row(title='Evidence paper A',doi='10.1234/a',publication_type='journal-article',references=[dict(doi='10.1234/b',key='r1'),dict(doi='10.1234/outside',key='r2'),dict(unstructured='Missing DOI')],references_available=True,reference_count_reported=3,
             relations=[dict(kind='has-preprint',doi='10.1234/preprint')]),fixtures.row(title='Evidence paper B',doi='10.1234/b',publication_type='journal-article',references=[],references_available=True,reference_count_reported=0)]))
        from services.research_synthesis import ResearchSynthesis
        self.synthesis=ResearchSynthesis(self.watch)
        return sid

    def test_citations_and_preprint_links_are_separate_from_proposed_semantic_edges(self):
        self.seed();r=self.synthesis.create('alice',{})['report'];g=r['bibliography_graph']
        cites=[e for e in g['edges'] if e['kind']=='cites']
        self.assertEqual(len(cites),2)
        self.assertTrue(all(e['status']=='source_reported' for e in cites))
        self.assertTrue(any(e['source']=='doi:10.1234/preprint' and e['target']=='doi:10.1234/a' for e in g['edges']))
        self.assertEqual(g['coverage']['references_without_doi'],1)
        self.assertEqual(g['coverage']['unresolved_reference_occurrences'],1)
        self.assertTrue(all(e['status']=='proposed' for e in r['edges']))
        for edge in cites:
            for e in edge['evidence']:
                snapshot=self.watch.snapshot('alice',e['snapshot_id'])
                self.assertEqual('doi:'+snapshot['paper']['references'][e['index']]['doi'],edge['target'])

    def test_observed_arxiv_versions_do_not_fabricate_missing_versions(self):
        self.subscription()
        self.run_page(fixtures.page([fixtures.row(doi='',arxiv_id='2610.12345v1',source_id='https://arxiv.org/abs/2610.12345v1')]))
        self.now[0]+=21601
        self.run_page(fixtures.page([fixtures.row(doi='',arxiv_id='2610.12345v3',source_id='https://arxiv.org/abs/2610.12345v3')]))
        from services.research_synthesis import ResearchSynthesis
        g=ResearchSynthesis(self.watch).create('alice',{})['report']['bibliography_graph']
        self.assertEqual(g['families'][0]['observed_versions'],[1,3])
        self.assertFalse(any(n['id'].endswith('v2') for n in g['nodes']))
        edge=next(e for e in g['edges'] if e['kind']=='observed_revision_order')
        self.assertEqual(edge['missing_intermediate_count'],1)

    def test_deleted_subscription_during_refresh_rejects_late_metadata(self):
        sid=self.seed();pid=self.watch.feed('alice')['items'][0]['paper_id'];self.now[0]+=4
        with self.store._conn() as c:before=c.execute('SELECT COUNT(*) FROM research_watch_snapshots').fetchone()[0]
        def lookup(*_):
            self.watch.action('alice',sid,'delete')
            return fixtures.row(title='Unaccepted late data',doi='10.1234/new')
        self.sources.lookup=lookup
        with self.assertRaises(LookupError):ResearchMetadata(self.watch).refresh('alice',pid,dict(source='crossref'))
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_watch_snapshots').fetchone()[0],before)
            self.assertEqual(c.execute('SELECT token FROM research_watch_collector_lock').fetchone()[0],'')

    def test_reference_updates_leave_old_report_frozen(self):
        self.seed();r=self.synthesis.create('alice',{})
        self.now[0]+=21601;self.run_page(fixtures.page([fixtures.row(title='Evidence paper A',doi='10.1234/a',references=[],references_available=True,reference_count_reported=0)]))
        self.assertEqual(self.synthesis.get('alice',r['id'])['report'],r['report'])
        self.assertFalse(any(e['kind']=='cites' for e in self.synthesis.create('alice',{})['report']['bibliography_graph']['edges']))

    def test_metadata_refresh_does_not_advance_search_watermark_or_duplicate_notifications(self):
        self.seed();pid=next(i['paper_id'] for i in self.watch.feed('alice')['items'] if i['paper']['doi']=='10.1234/a')
        before=self.watch.state('alice');self.now[0]+=4
        self.sources.lookup=lambda source,identifier:fixtures.row(title='Evidence paper A',doi=identifier,references=[dict(doi='10.1234/b')],references_available=True)
        m=ResearchMetadata(self.watch);result=m.refresh('alice',pid,dict(source='crossref'))
        self.assertEqual(result['paper_id'],pid)
        after=self.watch.state('alice')
        self.assertEqual(before['unread'],after['unread'])
        self.assertEqual(before['subscriptions'][0]['jobs'][0]['watermark'],after['subscriptions'][0]['jobs'][0]['watermark'])
        self.assertEqual(m.get('alice',pid)['records'][0]['references'][0]['doi'],'10.1234/b')
        with self.assertRaises(LookupError):m.refresh('bob',pid,dict(source='crossref'))
        with self.assertRaises(ValueError):m.refresh('alice',pid,dict(source='crossref'))

    def test_metadata_failure_releases_collector_without_mutating_snapshots(self):
        self.seed();pid=self.watch.feed('alice')['items'][0]['paper_id'];self.now[0]+=4
        def fail(*_):raise TimeoutError('private message not saved')
        self.sources.lookup=fail;m=ResearchMetadata(self.watch);before=m.get('alice',pid)
        with self.assertRaises(TimeoutError):m.refresh('alice',pid,dict(source='crossref'))
        self.assertEqual(m.get('alice',pid),before)
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT token FROM research_watch_collector_lock').fetchone()[0],'')
            self.assertEqual(c.execute('SELECT error FROM research_metadata_refreshes').fetchone()[0],'TimeoutError')

    def test_missing_references_not_treated_as_zero_and_budget_is_explicit(self):
        self.seed();r=self.synthesis.create('alice',{})['report']
        limited=build_graph(r['papers'],max_edges=1,max_nodes=3)
        self.assertGreater(limited['coverage']['omitted_edges'],0)
        self.assertEqual(len(limited['edges']),1)
        fields=metadata_fields(dict(references=[dict(doi='10.1234/a')]*501,references_available=True))
        self.assertEqual(len(fields['references']),500);self.assertTrue(fields['references_truncated'])
        self.assertFalse(metadata_fields({})['references_available'])
        fields=metadata_fields(dict(relations=[dict(kind='is-preprint-of',doi='10.1234/a')]*101))
        self.assertEqual(len(fields['relations']),100);self.assertTrue(fields['relations_truncated'])

    def test_corpus_metadata_budget_is_shared_and_omissions_are_visible(self):
        self.seed()
        with self.store._conn() as c:rows=c.execute('SELECT * FROM research_watch_snapshots ORDER BY captured DESC,id').fetchall()
        budget=dict(records=1,references=0,relations=0)
        records=source_records(rows,budget=budget)
        self.assertEqual(len(records['records']),1);self.assertEqual(records['omitted_artifacts'],1)
        self.assertEqual(budget['records'],0)
        self.assertEqual(records['records'][0]['references'],[])
        self.assertEqual(records['records'][0]['relations'],[])

    def test_arxiv_identifier_and_lookup_exact_version_reject_wrong_response(self):
        self.assertEqual(arxiv_parts('https://arxiv.org/abs/hep-th/9901001v2'),('hep-th/9901001',2))
        self.assertEqual(arxiv_parts('https://evil.example/a'),('',None))
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2610.12345v3</id><title>Evidence</title></entry></feed>'
        source=WatchSources(lambda _:raw)
        with self.assertRaisesRegex(ValueError,'version mismatch'):source.lookup('arxiv','2610.12345v1')
        self.assertEqual(source.lookup('arxiv','2610.12345v3')['arxiv_id'],'2610.12345v3')

    def test_crossref_lookup_preserves_reference_and_relation_fields(self):
        urls=[]
        raw=dict(message=dict(DOI='10.1234/a',title=['Evidence'],reference=[dict(DOI='10.1234/b')],**{'reference-count':2},relation={'is-preprint-of':[{'id':'10.1234/published','id-type':'doi','asserted-by':'subject'}]}))
        source=WatchSources(lambda url:(urls.append(url),json.dumps(raw).encode())[1])
        p=source.lookup('crossref','10.1234/a')
        self.assertIn('/works/10.1234%2Fa',urls[0]);self.assertTrue(p['references_truncated'])
        self.assertEqual(p['references'][0]['doi'],'10.1234/b');self.assertEqual(p['relations'][0]['kind'],'is-preprint-of')
        with self.assertRaises(ValueError):source.lookup('crossref','10.1234/wrong')

    def test_metadata_api_owner_scope_and_explicit_version_validation(self):
        self.seed();pid=self.watch.feed('alice')['items'][0]['paper_id']
        class Identity:
            def identity(self,request):
                token=request.headers.get('authorization','')
                if token not in ('Bearer alice','Bearer bob'):raise HTTPException(401,'auth')
                return dict(id=token[7:])
        app=FastAPI();app.include_router(research_watch_router(lambda:self.watch,Identity,lambda:{}))
        with TestClient(app) as client:
            path=f'/api/research/watch/papers/{pid}/metadata'
            self.assertEqual(client.get(path,headers={'Authorization':'Bearer alice'}).status_code,200)
            self.assertEqual(client.get(path,headers={'Authorization':'Bearer bob'}).status_code,404)
            self.assertEqual(client.post(path,headers={'Authorization':'Bearer alice'},json=dict(source='arxiv',version=0)).status_code,400)


if __name__=='__main__':unittest.main()
