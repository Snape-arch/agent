"""Reading-pack provenance/phase boundaries; never expert semantic gold labels."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from services import research_domains as domains
from services.research_watch_api import research_watch_router

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from research_domain_capture import Page


class DomainTests(unittest.TestCase):
    def test_real_pack_has_initial_supplement_and_external_survey_separated(self):
        p = domains.library()
        self.assertEqual(sum(len(d['papers']) for d in p['domains']), 24)
        self.assertEqual(sum(len(d['supplements']) for d in p['domains']), 6)
        self.assertFalse(p['audit']['semantic_validation_passed'])
        for d in p['domains']:
            self.assertEqual(d['survey']['status'], 'published_record_verified')
            self.assertEqual(len(d['validation']), 6)
            self.assertTrue(any(c['initial_status']=='gap' for c in d['validation']))

    def test_unknown_primary_reference_and_unverified_lineage_rejected(self):
        p = domains.library(); p['domains'][0]['overview'][0]['papers'] = ['invented']
        with self.assertRaisesRegex(ValueError, 'overview'): domains.validate(p)
        p = domains.library(); p['domains'][0]['paths'][0]['kind'] = 'confirmed_extends'
        with self.assertRaisesRegex(ValueError, 'lineage'): domains.validate(p)

    def test_supplement_cannot_be_used_as_initial_overview_evidence(self):
        p = domains.library(); p['domains'][0]['overview'][0]['papers'] = ['knnlm']
        with self.assertRaisesRegex(ValueError, 'not initial'): domains.validate(p)
        p = domains.library(); p['domains'][0]['supplements'][0]['phase'] = 'initial'
        with self.assertRaisesRegex(ValueError, 'phase'): domains.validate(p)

    def test_gap_cannot_be_silently_counted_as_initial_coverage(self):
        p = domains.library(); c = next(c for c in p['domains'][0]['validation'] if c['initial_status']=='gap'); c['papers'] = ['dpr']
        with self.assertRaisesRegex(ValueError, 'gap'): domains.validate(p)

    def test_author_described_relation_cannot_be_promoted_or_rebound(self):
        p = domains.library(); r = p['domains'][1]['declared_relations'][0]
        r['status'] = 'confirmed'
        with self.assertRaisesRegex(ValueError, 'author relation'): domains.validate(p)
        p = domains.library(); p['domains'][1]['declared_relations'][0]['target'] = 'lora'
        with self.assertRaisesRegex(ValueError, 'source mismatch'): domains.validate(p)

    def test_quote_and_survey_fingerprint_tampering_rejected(self):
        p = domains.library(); p['domains'][0]['papers'][0]['evidence']['quote'] += '!'
        with self.assertRaises(ValueError): domains.validate(p)
        p = domains.library(); p['domains'][0]['validation'][0]['evidence']['raw_sha256'] = 'a'*64
        with self.assertRaisesRegex(ValueError, 'survey fingerprint'): domains.validate(p)

    def test_initial_draft_cannot_be_rewritten_after_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('research_domains.json','research_domain_initial.json'): (root/name).write_bytes((domains.ROOT/name).read_bytes())
            p = json.loads((root/'research_domains.json').read_text(encoding='utf-8')); p['domains'][0]['overview'][0]['text'] = 'rewritten after survey'
            (root/'research_domains.json').write_text(json.dumps(p), encoding='utf-8')
            with patch.object(domains, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'material changed'): domains.library()

    def test_windows_checkout_line_endings_preserve_frozen_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'research_domains.json').write_bytes((domains.ROOT/'research_domains.json').read_bytes())
            raw = (domains.ROOT/'research_domain_initial.json').read_text(encoding='utf-8').encode()
            (root/'research_domain_initial.json').write_bytes(raw.replace(b'\n', b'\r\n'))
            with patch.object(domains, 'ROOT', root): self.assertEqual(len(domains.library()['domains']), 3)

    def test_arxiv_generic_meta_description_is_not_author_abstract(self):
        p = Page(); p.feed('<meta name="description" content="Abstract page, not abstract"><blockquote class="abstract"><span>Abstract:</span> Actual <b>author</b> text.</blockquote><p>navigation</p>')
        self.assertEqual(''.join(p.abstract), 'Abstract: Actual author text.')
        self.assertNotIn('navigation', ''.join(p.abstract))
        self.assertNotEqual(p.meta['description'][0], ''.join(p.abstract))

    def test_numeric_comparisons_survive_metadata_markup_cleanup(self):
        from services.research_watch_sources import clean
        text = 'robust with small (<50k) and large (>1m) datasets'
        self.assertEqual(clean(text), text)
        self.assertEqual(clean('<jats:p>2 < 3 and 5 > 1 &amp; <b>evidence</b></jats:p>'), '2 < 3 and 5 > 1 & evidence')

    def test_exports_are_standalone_and_do_not_claim_quality_acceptance(self):
        text = domains.markdown('rag')
        for term in ('冻结初稿', '对照后新增2篇', '初稿遗漏', '独立真人评审0次', '方法继承'): self.assertIn(term, text)
        self.assertIn('https://arxiv.org/abs/1911.00172v2', text)
        with self.assertRaises(LookupError): domains.get('../../private')

    def test_api_requires_identity_and_library_reads_never_touch_user_store(self):
        class Identity:
            def identity(self, request):
                if request.headers.get('x-test-user') != 'reader': raise HTTPException(401, 'identity required')
                return dict(id='reader')
        app = FastAPI()
        def forbidden_service(): raise AssertionError('read-only library accessed user DB')
        app.include_router(research_watch_router(forbidden_service, Identity, lambda:{}))
        with TestClient(app) as c:
            self.assertEqual(c.get('/api/research/watch/domains').status_code, 401)
            headers = {'x-test-user':'reader'}
            self.assertEqual(len(c.get('/api/research/watch/domains', headers=headers).json()['domains']), 3)
            result = c.get('/api/research/watch/domains/peft/export', headers=headers)
            self.assertEqual(result.status_code, 200); self.assertIn('markdown', result.json())
            self.assertEqual(c.get('/api/research/watch/domains/unknown', headers=headers).status_code, 404)
