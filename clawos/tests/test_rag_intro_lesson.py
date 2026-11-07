"""Deterministic contract and persistence tests with labelled source fixtures."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryos.memory_store import MemoryStore
from services.rag_intro_content import QUOTE
from services.rag_intro_lesson import RagIntroLesson
from services.research_journey import ResearchJourney
from services.research_learning import Conflict, ResearchLearning
from services.research_watch import ResearchWatch, fingerprint
from services.vision_api import vision_router
from test_research_learning import fake_source


RAW = b'%PDF-synthetic-rag-intro-source-fixture'
AID = 'a' * 32
PRE = {'representation': 0, 'version': 0, 'support': 0}
POST = {'representation': 0, 'version': 1, 'support': 2}


def source(spec, root):
    paper = fake_source(spec, root)
    paper['abstract'] += ' ' + QUOTE
    paper['raw_sha256'] = hashlib.sha256(RAW).hexdigest()
    folder = root / spec['version']
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'paper.pdf').write_bytes(RAW)
    return paper


class IntroLessonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = self.open()
        case = self.service.journey.learning.prepare('local-user', {'request_id': 'rag-intro-fixture-1'})
        self.cid = case['case']['id']
        self.case_hash = case['hash']

    def open(self):
        store = MemoryStore(str(self.root / 'test.sqlite'))
        return RagIntroLesson(ResearchJourney(ResearchLearning(ResearchWatch(store), self.root / 'learning', source)))

    def start(self, aid=AID):
        return self.service.start('local-user', self.cid, {'case_hash': self.case_hash, 'attempt_id': aid})

    def step(self, revision, action, value):
        return self.service.advance('local-user', self.cid, AID, dict(revision=revision, action=action, value=value))['attempt']

    def test_complete_receipt_preserves_actual_evidence_and_separates_blind_review(self):
        self.assertIsNone(self.service.state('local-user', self.cid)['attempt'])
        first = self.start()
        self.assertEqual(first, self.start())
        self.assertEqual(set(first['attempt']['questions'][0]), {'id', 'prompt', 'options'})
        with self.assertRaises(Conflict):
            self.service.export('local-user', self.cid, AID)
        guide = self.step(0, 'submit', PRE)
        self.assertNotIn('result', guide)
        self.assertEqual(guide['source']['quote'], QUOTE)
        self.step(1, 'predict', 'Synthetic prediction for the isolated test.')
        with self.assertRaises(Conflict):
            self.step(2, 'observe', 'A run must exist before an observation.')
        experiment = self.step(2, 'run', True)['experiment']
        self.assertEqual(experiment, self.step(2, 'run', True)['experiment'])
        self.assertEqual([a['config']['current_only'] for a in experiment['arms']], [False, True])
        loan, missing = zip(*(a['rows'] for a in experiment['arms']))
        self.assertEqual([r['chunks'][0]['document_id'] for r in loan], ['loan-old', 'loan'])
        self.assertEqual(loan[0]['chunks'][0]['score'], loan[1]['chunks'][0]['score'])
        self.assertTrue(all(not r['evaluation']['passed'] for r in missing))
        self.service = self.open()
        self.assertEqual(self.service.state('local-user', self.cid, AID)['attempt']['experiment'], experiment)
        post = self.step(3, 'observe', 'Synthetic observation for the isolated test.')
        self.assertNotEqual(post['questions'], first['attempt']['questions'])
        self.assertNotIn('result', self.step(4, 'submit', POST))
        done = self.step(5, 'submit', 'Synthetic transfer response for persistence, not a learner.')
        self.assertEqual((done['result']['pre']['score'], done['result']['post']['score']), (1, 3))
        self.assertEqual(self.open().state('local-user', self.cid, AID)['attempt'], done)
        full = self.service.export('local-user', self.cid, AID)
        self.assertEqual(full['sha256'], fingerprint(full['receipt']))
        review = self.service.export('local-user', self.cid, AID, True)['receipt']
        self.assertEqual(review['transfer']['review_status'], 'pending')
        self.assertFalse(set(review) & {'pre', 'post', 'timestamps', 'prediction', 'observation'})
        self.assertTrue(all(not review[k] for k in ('teacher_verified', 'mastery_updated', 'agent_reward', 'learning_effect_verified')))
        second = self.start('b' * 32)
        self.assertEqual(second['attempt']['questions'], post['questions'])
        self.assertEqual(self.service.state('local-user', self.cid, AID)['attempt'], done)

    def test_new_attempt_fails_closed_for_missing_original_and_owner(self):
        with self.assertRaises(PermissionError):
            self.service.state('other', self.cid)
        with self.assertRaises(LookupError):
            self.service.state('local-user', self.cid, AID)
        (self.root / 'learning' / 'sources' / '2004.04906v3' / 'paper.pdf').unlink()
        with self.assertRaises(LookupError):
            self.start()
        self.assertIsNone(self.service.state('local-user', self.cid)['attempt'])

    def test_stale_and_concurrent_writes_cannot_overwrite_assessment(self):
        self.start()
        with self.assertRaises(Conflict):
            self.start('b' * 32)
        with self.assertRaises(ValueError):
            self.step(0, 'submit', {**PRE, 'version': True})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.step, 0, 'submit', answers) for answers in (PRE, POST)]
        self.assertEqual(sum(isinstance(f.exception(), Conflict) for f in futures), 1)
        self.assertEqual(sum(f.exception() is None for f in futures), 1)
        self.assertEqual(self.service.state('local-user', self.cid, AID)['attempt']['revision'], 1)

    def test_http_owner_same_origin_and_invalid_phase(self):
        class Collaboration:
            def identity(self, request):
                return {'id': 'local-user'}

        app = FastAPI()
        app.include_router(vision_router(None, Collaboration, self.root,
                          journey=lambda: self.service.journey, grounded=object, model_ready=dict))
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as client:
            path = f'/api/vision/research/cases/{self.cid}/intro'
            data = {'case_hash': self.case_hash, 'attempt_id': AID}
            self.assertEqual(client.post(path, json=data, headers={'Origin':'https://foreign.invalid'}).status_code, 403)
            self.assertEqual(client.get(path).headers['Cache-Control'], 'no-store')
            self.assertEqual(client.post(path, json=data).json()['attempt']['phase'], 'pre')
            self.assertEqual(client.post(path+'/'+AID, json=dict(revision=0, action='run', value=True)).status_code, 409)
            self.assertEqual(client.get(path+'/'+AID+'/export?review=true').status_code, 409)
