"""Held-out constructed transformations; no clinical or model quality claims."""
import asyncio
import json
import unittest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import test_research_synthesis as fixtures
from services.research_claim_guard import audit_claim_boundaries,VERSION
from services.research_ai import ResearchAI,SECTIONS,normalize
from services.research_review import ResearchReview
from services.grounded_paper_report import GroundedPaperReport
from services.collaboration import Collaboration


class BoundaryPatterns(unittest.TestCase):
    def audit(self,text,*quotes):return audit_claim_boundaries(text,quotes)

    def test_bilingual_negation_and_reverse_direction_require_review(self):
        for text,quote in [('该方法降低了疼痛。','The method did not reduce pain.'),('The method improves sleep.','No improvement in sleep was detected.'),('该方法未改善睡眠。','The method improved sleep.'),('The result is better.','No improvement was detected.')]:
            self.assertTrue(self.audit(text,quote)['review_required'])

    def test_retained_negation_uncertainty_and_separate_clauses_are_not_flipped(self):
        for text,quote in [('该方法未降低疼痛。','The method did not reduce pain.'),('该方法可能改善睡眠。','The method may improve sleep.'),('The method reduces pain.','It does not improve sleep but reduces pain.'),('The effect cannot be excluded.','An effect cannot be excluded.'),('The method improves sleep.','The method not only improves sleep but reduces pain.'),('该方法改善睡眠。','该方法不仅改善睡眠，而且减少疼痛。')]:
            self.assertFalse(self.audit(text,quote)['review_required'],(text,self.audit(text,quote)))

    def test_double_negation_is_not_proof_of_no_effect(self):
        self.assertTrue(self.audit('The intervention has no effect.','We cannot exclude small effects.')['review_required'])
        self.assertTrue(self.audit('该方案已证明完全无效。','The available evidence cannot rule out a small effect.')['review_required'])

    def test_null_result_is_not_equivalence_but_literal_reporting_is_preserved(self):
        self.assertTrue(self.audit('The treatment has no effect.','The result was not significant.')['review_required'])
        self.assertFalse(self.audit('The result was not significant.','The result was not significant.')['review_required'])

    def test_population_scope_and_negated_overgeneralization(self):
        self.assertTrue(self.audit('This result applies to every population.','We studied a specific group of older people.')['review_required'])
        self.assertFalse(self.audit('不能将结果推广到所有人群。','Only older people were studied.')['review_required'])

    def test_modality_is_preserved_instead_of_promoted_to_fact(self):
        self.assertTrue(self.audit('The method improves mobility.','The method may improve mobility.')['review_required'])
        self.assertFalse(self.audit('该方法可能提高移动能力。','The method may improve mobility.')['review_required'])

    def test_causal_assertion_requires_more_than_association(self):
        self.assertTrue(self.audit('The exposure causes the outcome.','The exposure was associated with the outcome in an observational study.')['review_required'])
        self.assertFalse(self.audit('The exposure may cause the outcome.','An association was observed.')['review_required'])

    def test_forecast_is_not_observation_and_qualified_estimate_is_retained(self):
        self.assertTrue(self.audit('We measured a value of 12 ppm.','A preliminary estimate is 12 ppm.')['review_required'])
        self.assertFalse(self.audit('初步估计浓度为12 ppm。','A preliminary estimate is 12 ppm.')['review_required'])

    def test_correction_does_not_establish_positive_or_negative_retraction_status(self):
        self.assertTrue(self.audit('The paper has been retracted.','The correction fixes an error in a reference.')['review_required'])
        self.assertTrue(self.audit('这篇论文从未被撤稿。','This correction concerns a reference.')['review_required'])
        self.assertTrue(self.audit('The paper was retracted.','This correction is not a retraction.')['review_required'])
        self.assertTrue(self.audit('The paper was never retracted.','This is a retraction of the paper.')['review_required'])
        self.assertFalse(self.audit('更正不代表撤稿。','This correction concerns a reference.')['review_required'])

    def test_unit_value_pair_cannot_borrow_another_number_in_same_fragment(self):
        self.assertTrue(self.audit('质量为7.2 Gt CO2。','Mass 7.2 Gt C; a separate quantity is 26.4 Gt CO2.')['review_required'])
        self.assertTrue(self.audit('7.2的单位为Gt CO2。','Mass 7.2 Gt C.')['review_required'])
        self.assertFalse(self.audit('质量为7.2 Gt C。','Mass 7.2 Gt C.')['review_required'])

    def test_physical_units_unicode_spacing_and_unsupported_conversion(self):
        self.assertFalse(self.audit('质量为7.2 Gt CO₂。','Mass 7.2 Gt CO2.')['review_required'])
        self.assertTrue(self.audit('剂量为5mg/kg。','Dose 5 mg/L.')['review_required'])
        self.assertTrue(self.audit('The mass is 3000 g.','The mass is 3 kg.')['review_required'])
        self.assertFalse(self.audit('质量为7.2GtC。','Mass 7.2 Gt C.')['review_required'])

    def test_missing_signal_never_sets_semantic_verified_or_uses_other_sources(self):
        audit=self.audit('A simple unrelated claim.','Other evidence.')
        self.assertFalse(audit['review_required']);self.assertFalse(audit['semantic_entailment_verified'])
        self.assertEqual(audit['version'],VERSION)

    def test_grounded_paper_report_uses_same_guard_for_findings_and_summary(self):
        citation='doc:1#page=1&chunk=1';bundle=dict(document=dict(id=1),allowed_citations={citation:'The method did not reduce pain.'})
        report=GroundedPaperReport.normalize(dict(summary='该方法降低了疼痛。',summary_citations=[citation],findings=[dict(text='该方法降低了疼痛。',citations=[citation])]),bundle,mode='model_assisted')
        self.assertEqual(report['findings'][0]['status'],'review_required');self.assertTrue(report['summary_audit']['review_required'])


class ReviewQueueTests(unittest.TestCase):
    setUp=fixtures.SynthesisTests.setUp
    subscription=fixtures.SynthesisTests.subscription
    run_page=fixtures.SynthesisTests.run_page

    def test_held_claim_stays_out_of_body_but_keeps_citations_and_can_be_reviewed(self):
        self.subscription();self.run_page(fixtures.page([fixtures.row(title='Boundary fixture',abstract='Results show the intervention did not reduce pain.')]))
        from services.research_synthesis import ResearchSynthesis
        synthesis=ResearchSynthesis(self.watch);report=synthesis.create('alice',{});ai=ResearchAI(self.watch);queued=ai.enqueue('alice',report['id']);job=ai.claim();calls=[]
        async def model(messages,*_,**__):
            calls.append(messages);data=json.loads(messages[-1]['content']);self.assertIn('evidence',data)
            result={k:[] for k in SECTIONS};result['overview']=[dict(text='该干预降低了疼痛。',citations=[data['evidence'][0]['id']],kind='reported')]
            return dict(choices=[dict(message=dict(content=json.dumps(result)),finish_reason='stop')])
        asyncio.run(ai.execute(job,model));value=ai.get('alice',queued['id'])['result']
        self.assertEqual(len(calls),1);self.assertEqual(value['outcome'],'insufficient_evidence');self.assertFalse(value['sections']['overview'])
        self.assertEqual(value['review_queue'][0]['reason'],'polarity_requires_review');self.assertEqual(value['review_queue'][0]['evidence_ids'],['E1'])
        self.assertEqual(value['guard_version'],VERSION)
        exported=synthesis.export('alice',report['id']);self.assertIn('暂缓主张与复核依据',exported['markdown']);self.assertIn('该干预降低了疼痛。',exported['markdown'])
        Collaboration(self.store)
        with self.store._conn() as c:c.executemany('INSERT INTO collaboration_users VALUES (?,?)',[(a,'Fixture') for a in ('r1','r2','j')])
        review=ResearchReview(self.watch);round=review.create('alice',dict(kind='ai',report_id=report['id'],job_id=queued['id'],reviewer_ids=['r1','r2'],adjudicator_id='j'))
        self.assertEqual(round['cases'][0]['origin'],'withheld_ai_claim')
        blind=review.get('r1',round['id'])['cases'][0];self.assertEqual(blind['origin'],'frozen_ai_job');self.assertNotIn('withheld_reason',blind);self.assertNotIn('boundary_audit',blind)
        self.assertFalse(review.get('alice',round['id'])['human_validation_complete'])
        self.assertFalse(synthesis.get('alice',report['id'])['report'].get('ai_synthesis'))

    def test_unknown_citation_is_retained_without_fabricating_references(self):
        value={k:[] for k in SECTIONS};value['overview']=[dict(text='A claim without an available source.',citations=['not-real'],kind='reported')]
        kept,held=normalize(value,[]);self.assertFalse(kept);self.assertEqual(held[0]['text'],value['overview'][0]['text'])


if __name__=='__main__':unittest.main()
