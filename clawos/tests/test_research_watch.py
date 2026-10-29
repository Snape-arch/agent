"""Isolated subscription recovery/identity/evidence tests; no production DB or network."""
import asyncio
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch, ResearchWatchWorker, classify, fingerprint
from services.research_watch_api import research_watch_router
from services.research_watch_sources import WatchSources


def paper(**changes):
    return dict(title='Retrieval evidence with controlled experiments', doi='10.1234/example',
                authors=['A. Researcher'], published='2026-10-01', abstract='We study retrieval. Experiments compare evidence quality.',
                categories=['cs.IR'], url='https://doi.org/10.1234/example', source_id='10.1234/example', **changes)


def row(**changes):
    value = paper(); value.update(changes); return value


def page(rows, cursor='', complete=True):
    return dict(rows=rows, cursor=cursor, complete=complete)


class Sources:
    def __init__(self):
        self.pages, self.calls = [], []

    def page(self, *args):
        self.calls.append(args)
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(str(Path(self.tmp.name) / 'test.db'))
        self.now = [1793376000.0]
        self.sources = Sources()
        self.watch = ResearchWatch(self.store, self.sources, clock=lambda: self.now[0], source_interval=0)

    def subscription(self, owner='alice', **changes):
        data = dict(name='Evidence research', query='retrieval evidence', sources=['crossref'], interval_hours=6,
                    directions=[dict(name='Evidence', terms=['evidence']), dict(name='Retrieval', terms=['retrieval'])])
        data.update(changes)
        return self.watch.create(owner, data)['id']

    def run_page(self, data):
        self.sources.pages.append(data)
        return self.watch.tick(limit=1)[0]

    def advance(self, seconds=21601):
        self.now[0] += seconds

    def test_chain_creates_cited_feed_notification_and_beijing_daily_digest(self):
        sid = self.subscription()
        result = self.run_page(page([paper()]))
        self.assertEqual(result['new_count'], 1)
        state = self.watch.state('alice')
        self.assertEqual(state['unread'], 1)
        self.assertEqual(state['digests'][0]['paper_count'], 1)
        item = self.watch.feed('alice', sid)['items'][0]
        self.assertEqual({c['name'] for c in item['classification']}, {'Evidence', 'Retrieval'})
        evidence = item['summary']['evidence']
        snapshot = self.watch.snapshot('alice', evidence['snapshot_id'])
        self.assertEqual(snapshot['hash'], evidence['content_sha256'])
        self.assertEqual(snapshot['paper'][evidence['field']][evidence['start']:evidence['end']], evidence['quote'])
        digest = self.watch.digest('alice', state['digests'][0]['id'])
        self.assertEqual(digest['items'][0]['snapshot_id'], snapshot['id'])
        self.watch.read('alice', state['notifications'][0]['id'])
        self.assertEqual(self.watch.state('alice')['unread'], 0)

    def test_cross_batch_and_cross_source_doi_dedup_survives_restart(self):
        self.subscription(sources=['crossref', 'arxiv'])
        self.run_page(page([paper()]))
        self.run_page(page([row(doi='https://doi.org/10.1234/EXAMPLE', arxiv_id='2610.12345v2', abstract='A revised source abstract.')]))
        self.watch = ResearchWatch(MemoryStore(str(Path(self.tmp.name)/'test.db')), self.sources, clock=lambda: self.now[0], source_interval=0)
        self.advance(); self.run_page(page([paper()]))
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_watch_papers').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_watch_snapshots').fetchone()[0], 2)
        self.assertEqual(len(self.watch.feed('alice')['items']), 1)
        self.assertEqual(self.watch.state('alice')['unread'], 1)

    def test_title_fallback_adds_later_doi_but_conflicting_doi_is_not_merged(self):
        self.subscription()
        self.run_page(page([row(doi='')]))
        self.advance(); self.run_page(page([paper()]))
        self.advance(); self.run_page(page([row(doi='10.1234/other')]))
        self.assertEqual(len(self.watch.feed('alice')['items']), 2)

    def test_same_title_without_author_is_not_claimed_as_definite_duplicate(self):
        self.subscription()
        self.run_page(page([row(doi='', authors=[], source_id='a'), row(doi='', authors=[], source_id='b')]))
        self.assertEqual(len(self.watch.feed('alice')['items']), 2)

    def test_page_continuation_keeps_fixed_window_watermark_and_survives_process_loss(self):
        sid = self.subscription()
        self.run_page(page([paper()], 'cursor-one', False))
        job = self.watch.state('alice')['subscriptions'][0]['jobs'][0]
        self.assertEqual(job['watermark'], 0); self.assertEqual(job['status'], 'backlog')
        self.advance(61)
        claimed = self.watch.claim()
        self.assertEqual(claimed['cursor'], 'cursor-one')
        self.assertIsNone(self.watch.claim())
        self.advance(121)
        resumed = ResearchWatch(self.store, self.sources, clock=lambda: self.now[0]).claim()
        self.assertEqual(resumed['window_end'], claimed['window_end'])
        self.assertEqual(resumed['cursor'], 'cursor-one')
        self.assertEqual(self.watch.commit_page(claimed, page([row(doi='10.1234/stale')]))['stale'], True)
        self.watch.commit_page(resumed, page([row(doi='10.1234/new')]))
        job = self.watch.state('alice')['subscriptions'][0]['jobs'][0]
        self.assertEqual(job['watermark'], claimed['window_end'])
        self.assertEqual(len(self.watch.feed('alice', sid)['items']), 2)

    def test_failure_restarts_same_window_dedups_replay_and_does_not_advance(self):
        self.subscription()
        self.run_page(page([paper()], 'old-cursor', False))
        self.advance(61)
        self.run_page(TimeoutError('DO NOT PERSIST secret request data'))
        job = self.watch.state('alice')['subscriptions'][0]['jobs'][0]
        self.assertEqual(job['watermark'], 0); self.assertEqual(job['last_error'], 'TimeoutError')
        self.assertNotIn('secret', json.dumps(self.watch.state('alice')))
        self.assertIsNone(self.watch.claim())
        self.advance(901)
        self.run_page(page([paper()]))
        self.assertEqual(self.sources.calls[-1][4], '')
        self.assertEqual(self.sources.calls[0][2:4], self.sources.calls[-1][2:4])
        self.assertEqual(self.watch.state('alice')['unread'], 1)

    def test_pause_during_request_fences_late_result_and_resume_continues(self):
        sid = self.subscription(); job = self.watch.claim()
        self.watch.action('alice', sid, 'pause')
        self.assertEqual(self.watch.commit_page(job, page([paper()])), {'stale': True})
        self.assertIsNone(self.watch.claim())
        with self.assertRaises(ValueError): self.watch.action('alice', sid, 'collect')
        self.watch.action('alice', sid, 'resume'); self.run_page(page([paper()]))
        self.assertEqual(len(self.watch.feed('alice')['items']), 1)

    def test_delete_during_request_preserves_prior_digest_but_fences_late_page(self):
        sid = self.subscription(); self.run_page(page([paper()]))
        did = self.watch.state('alice')['digests'][0]['id']
        self.advance(); job = self.watch.claim(); self.watch.action('alice', sid, 'delete')
        self.assertEqual(self.watch.commit_page(job, page([row(doi='10.1234/late')])), {'stale': True})
        self.assertEqual(self.watch.digest('alice', did)['items'][0]['subscription_name'], '已删除订阅')

    def test_scope_blocks_other_users_subscriptions_snapshot_digest_and_notifications(self):
        sid = self.subscription(); self.run_page(page([paper()]))
        state = self.watch.state('alice'); item = self.watch.feed('alice')['items'][0]
        self.assertEqual(self.watch.feed('bob')['items'], [])
        for method, args in [('action', (sid, 'collect')), ('feed', (sid,)), ('snapshot', (item['snapshot_id'],)),
                             ('digest', (state['digests'][0]['id'],)), ('read', (state['notifications'][0]['id'],))]:
            with self.subTest(method=method), self.assertRaises(LookupError): getattr(self.watch, method)('bob', *args)

    def test_source_metadata_change_cannot_rewrite_published_digest_evidence(self):
        self.subscription(); self.run_page(page([paper()]))
        did = self.watch.state('alice')['digests'][0]['id']
        before = self.watch.digest('alice', did)['items'][0]['summary']
        self.advance(); self.run_page(page([row(abstract='Later corrected abstract.')]))
        self.assertEqual(self.watch.digest('alice', did)['items'][0]['summary'], before)
        self.assertEqual(self.watch.state('alice')['unread'], 1)

    def test_failure_rolls_back_partial_page_and_outbox(self):
        self.subscription()
        self.run_page(page([paper(), row(title='')]))
        self.assertEqual(self.watch.feed('alice')['items'], [])
        self.assertEqual(self.watch.state('alice')['unread'], 0)

    def test_no_abstract_summary_only_uses_title_and_refuses_full_text_inference(self):
        self.subscription(); self.run_page(page([row(abstract='')]))
        item = self.watch.feed('alice')['items'][0]
        self.assertEqual(item['summary']['basis'], 'title')
        self.assertFalse(item['summary']['full_text_reviewed'])
        self.assertIn('不能', item['summary']['boundary'])

    def test_manual_classification_and_unclassified_evidence(self):
        sid = self.subscription(); self.run_page(page([row(title='Unrelated topic', abstract='Other content', categories=[])]))
        item = self.watch.feed('alice')['items'][0]
        self.assertEqual(item['classification'][0]['name'], '待归类')
        self.watch.reclassify('alice', sid, item['paper_id'], ['Evidence'])
        self.assertEqual(self.watch.feed('alice')['items'][0]['classification'][0]['method'], 'manual')
        with self.assertRaises(ValueError): self.watch.reclassify('alice', sid, item['paper_id'], ['Unknown'])

    def test_empty_success_advances_window_without_empty_notifications(self):
        self.subscription(); self.run_page(page([]))
        state = self.watch.state('alice')
        self.assertEqual(state['digests'], [])
        self.assertGreater(state['subscriptions'][0]['jobs'][0]['watermark'], 0)

    def test_overlap_uses_index_watermark_instead_of_publication_date(self):
        self.subscription(); self.run_page(page([row(published='2019-01-01')]))
        end = self.sources.calls[-1][3]
        self.advance(); self.run_page(page([]))
        self.assertEqual(self.sources.calls[-1][2], end - 7*86400)

    def test_invalid_subscription_payloads_rejected(self):
        for changes in [dict(query='!!'), dict(sources=['unsupported']), dict(sources=[{}]), dict(interval_hours=True),
                        dict(directions=[dict(name='x', terms=['!!!'])]), dict(directions=[]), dict(extra='bad')]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.subscription(**changes)

    def test_duplicate_page_does_not_infinite_advance(self):
        self.subscription(); self.run_page(page([paper()], 'a', False)); self.advance(61)
        result = self.run_page(page([paper()], 'b', False))
        self.assertEqual(result['error'], 'ValueError')

    def test_two_claimers_cannot_own_same_job(self):
        self.subscription(); results = []
        threads = [threading.Thread(target=lambda: results.append(self.watch.claim())) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_late_identifier_bridge_consolidates_preprint_and_journal_records(self):
        self.subscription()
        self.run_page(page([row(doi='', arxiv_id='2610.12345v1', authors=['Preprint Author'], source_id='preprint'),
                            row(doi='10.1234/journal', authors=['Journal Author'], source_id='journal')]))
        did = self.watch.state('alice')['digests'][0]['id']
        self.advance(); self.run_page(page([row(doi='10.1234/journal', arxiv_id='2610.12345v2')]))
        self.assertEqual(len(self.watch.feed('alice')['items']), 1)
        self.assertEqual(len(self.watch.digest('alice', did)['items']), 1)
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_watch_papers').fetchone()[0], 1)

    def test_global_feed_and_daily_digest_dedup_multiple_subscriptions(self):
        left = self.subscription(); right = self.subscription(name='Second direction')
        self.run_page(page([paper()])); self.run_page(page([paper()]))
        self.assertEqual(len(self.watch.feed('alice')['items']), 1)
        self.assertEqual(len(self.watch.feed('alice', left)['items']), 1)
        self.assertEqual(len(self.watch.feed('alice', right)['items']), 1)
        did = self.watch.state('alice')['digests'][0]['id']
        self.assertEqual(len(self.watch.digest('alice', did)['items']), 1)

    def test_collector_lease_and_spacing_are_shared_by_multiple_worker_instances(self):
        self.subscription(); self.subscription(name='Second subscription')
        first = ResearchWatch(self.store, self.sources, clock=lambda: self.now[0])
        second = ResearchWatch(self.store, self.sources, clock=lambda: self.now[0])
        job = first.claim()
        self.assertIsNone(second.claim())
        first.commit_page(job, page([]))
        self.assertIsNone(second.claim())
        self.advance(3.2)
        self.assertIsNotNone(second.claim())


class CollectorTests(unittest.TestCase):
    def test_crossref_builds_fixed_index_window_cursor_and_keeps_abstract_categories(self):
        urls = []
        def transport(url):
            urls.append(url)
            return json.dumps({'message': {'items': [{'DOI': '10.1234/test', 'title': ['Evidence'], 'abstract': '<p>Exact evidence.</p>',
                     'subject': ['Information Retrieval'], 'published': {'date-parts': [[2026, 10, 1]]}, 'indexed': {'date-time': '2026-10-20T00:00:00Z'}}]}}).encode()
        source = WatchSources(transport)
        result = source.page('crossref', 'retrieval', 1792454400, 1792540800)
        params = parse_qs(urlsplit(urls[0]).query)
        self.assertIn('from-index-date:', params['filter'][0]); self.assertIn('until-index-date:', params['filter'][0])
        self.assertNotIn('Z', params['filter'][0])  # Crossref rejects ISO timezone suffixes.
        self.assertEqual(params['cursor'], ['*'])
        self.assertEqual(result['rows'][0]['abstract'], 'Exact evidence.')
        self.assertEqual(result['rows'][0]['categories'], ['Information Retrieval'])
        self.assertTrue(result['complete'])

    def test_arxiv_parses_atom_ids_categories_dates_and_bounds_query(self):
        urls = []
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:os="http://a9.com/-/spec/opensearch/1.1/" xmlns:ax="http://arxiv.org/schemas/atom"><os:totalResults>2</os:totalResults><entry><id>http://arxiv.org/abs/2610.12345v2</id><title>Evidence</title><summary>Exact abstract.</summary><published>2026-10-01T00:00:00Z</published><updated>2026-10-02T00:00:00Z</updated><author><name>A</name></author><category term="cs.AI"/><ax:doi>10.1234/test</ax:doi></entry></feed>'''
        result = WatchSources(lambda url: (urls.append(url), raw)[1]).page('arxiv', 'retrieval OR cat:evil', 1792454400, 1792540800, size=1)
        params = parse_qs(urlsplit(urls[0]).query)
        self.assertIn('submittedDate:[', params['search_query'][0]); self.assertNotIn('cat:evil', params['search_query'][0])
        self.assertEqual(result['cursor'], '1'); self.assertFalse(result['complete'])
        self.assertEqual(result['rows'][0]['categories'], ['cs.AI']); self.assertEqual(result['rows'][0]['doi'], '10.1234/test')

    def test_malformed_source_response_is_not_treated_as_empty_success(self):
        for source, raw in [('crossref', b'{"message":{}}'), ('arxiv', b'<feed/>')]:
            with self.subTest(source=source), self.assertRaises((ValueError, KeyError)):
                WatchSources(lambda _: raw).page(source, 'evidence', 1, 2)


class ApiTests(unittest.TestCase):
    setUp = WatchTests.setUp
    subscription = WatchTests.subscription
    run_page = WatchTests.run_page
    def test_router_identity_cors_and_pagination(self):
        class Identity:
            def identity(self, request):
                token = request.headers.get('authorization')
                if token not in ('Bearer alice', 'Bearer bob'):
                    raise HTTPException(401, 'session required')
                return {'id': token[7:]}
        app = FastAPI(); app.include_router(research_watch_router(lambda: self.watch, Identity, lambda: {'running': True}))
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/research/watch').status_code, 401)
            sid = self.subscription(); self.run_page(page([paper()]))
            headers = {'Authorization': 'Bearer alice'}
            self.assertEqual(client.get('/api/research/watch', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/research/watch/feed?offset=-1', headers=headers).status_code, 422)
            self.assertEqual(client.post(f'/api/research/watch/subscriptions/{sid}/pause', headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
            self.assertEqual(client.post(f'/api/research/watch/subscriptions/{sid}/pause', headers={'Authorization': 'Bearer bob'}).status_code, 404)
            self.assertEqual(client.post('/api/research/watch/subscriptions', headers=headers, content='[]').status_code, 400)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_runs_collection_off_loop_and_close_waits_for_inflight_commit(self):
        started, release = threading.Event(), threading.Event()
        class Service:
            def tick(self):
                started.set(); release.wait(3)
        worker = ResearchWatchWorker(Service()); worker.start()
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        close = asyncio.create_task(worker.close()); await asyncio.sleep(0)
        self.assertFalse(close.done()); release.set(); await asyncio.wait_for(close, 2)

    async def test_actual_app_router_and_middleware_keep_existing_sessions_scoped(self):
        import clawos_server as server
        from services.collaboration import Collaboration, digest
        from services.academy_documents import AcademyDocuments
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td)/'db'))
            AcademyDocuments(store); collaboration = Collaboration(store)
            with store._conn() as c:
                c.execute('INSERT INTO collaboration_users VALUES (?,?)', ('guest', 'Guest'))
                c.execute('INSERT INTO collaboration_sessions VALUES (?,?,?)', (digest('fixture-token'), 'guest', 4000000000))
            watch = ResearchWatch(store, Sources())
            with patch.object(server, 'g_memory_store', store), patch.object(server, 'g_research_watch_service', watch), patch.object(server, '_collaboration', return_value=collaboration):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://127.0.0.1') as client:
                    self.assertEqual((await client.get('/academy/research')).status_code, 200)
                    self.assertEqual((await client.get('/api/research/watch')).status_code, 200)
                    headers = {'Authorization': 'Bearer fixture-token'}
                    self.assertEqual((await client.get('/api/research/watch', headers=headers)).status_code, 200)
                    self.assertEqual((await client.get('/api/research/literature/search?q=test', headers=headers)).status_code, 403)
                    self.assertEqual((await client.get('/api/research/watch', headers={'Authorization': 'Bearer invalid'})).status_code, 401)


if __name__ == '__main__':
    unittest.main()
