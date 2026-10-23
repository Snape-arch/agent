import unittest
import json
from services.grounded_paper_report import GroundedPaperReport,REPORT_SECTION_KEYS
from services.paper_numeric_evidence import audit_numeric_support


class PaperNumericEvidenceTests(unittest.TestCase):
    def test_realistic_thousands_scales_and_multiplier_notation(self):
        audit=audit_numeric_support('GPT-3模型有1750亿参数，可训练参数减少1万倍，GPU显存减少3倍。',
                                    ['GPT-3 175B reduces trainable parameters by 10,000 times and GPU memory by 3 times.'])
        self.assertFalse(audit['review_required'],audit)
        self.assertFalse(audit['semantic_entailment_verified'])

    def test_numbers_from_other_fragments_do_not_support_a_cited_claim(self):
        audit=audit_numeric_support('Accuracy is 99.9 percent.',['The measured accuracy is 85 percent.'])
        self.assertTrue(audit['review_required']);self.assertEqual(['99.9 percent'],audit['unsupported_quantities'])

    def test_percent_and_unconverted_ratio_cannot_be_substituted(self):
        self.assertTrue(audit_numeric_support('准确率百分之85',['BLEU is 85.'])['review_required'])
        self.assertTrue(audit_numeric_support('Accuracy is 0.85',['Accuracy is 85 percent.'])['review_required'])
        self.assertFalse(audit_numeric_support('准确率８５％',['Accuracy is 85 percent.'])['review_required'])

    def test_extreme_exponent_and_condition_mismatch_require_review(self):
        self.assertTrue(audit_numeric_support('Result 1e9999999',['Result 1.'])['review_required'])
        self.assertTrue(audit_numeric_support('Result 1e-9999999',['Result 0.'])['review_required'])
        self.assertTrue(audit_numeric_support('Accuracy 85%; tested on 200 samples.',['Accuracy 85%.'])['review_required'])

    def test_legitimate_citation_cannot_launder_wrong_numbers_or_missing_conditions(self):
        a='doc:1#page=1&chunk=1';b='doc:1#page=2&chunk=1';c='doc:1#page=3&chunk=1'
        bundle=dict(document=dict(id=1),allowed_citations={a:'Accuracy is 85 percent.',b:'We used 200 samples.',c:'A different setup reports 99.9 percent.'})
        payload=dict(findings=[dict(text='Accuracy is 99.9 percent.',citations=[a]),
                               dict(text='Accuracy is 85 percent.',conditions=['200 samples'],citations=[a]),
                               dict(text='Accuracy is 85 percent.',conditions=['200 samples'],citations=[a,b])])
        report=GroundedPaperReport.normalize(payload,bundle,mode='model_assisted')
        self.assertEqual(['review_required','review_required','supported'],[r['status'] for r in report['findings']])
        self.assertEqual(2,report['citation_audit']['review_required_items'])
        self.assertIn('所引片段未覆盖',GroundedPaperReport.render_markdown(report))

    def test_summary_and_verdict_do_not_hide_unmatched_numbers(self):
        citation='doc:1#page=1&chunk=1';bundle=dict(document=dict(id=1),allowed_citations={citation:'Accuracy is 85 percent.'})
        payload=dict(summary='Accuracy is 99.9%.',summary_citations=[citation],research_problem='Evaluate accuracy.',research_problem_citations=[citation],verdict='Reliable at 99.9%.')
        report=GroundedPaperReport.normalize(payload,bundle,mode='model_assisted')
        self.assertTrue(report['summary_audit']['review_required']);self.assertTrue(report['verdict_audit']['review_required'])
        self.assertIn('**待核查**：Accuracy is 99.9%.',GroundedPaperReport.render_markdown(report))

    def test_empty_or_incomplete_model_json_is_rejected(self):
        citation='doc:1#page=1&chunk=1';bundle=dict(document=dict(id=1),allowed_citations={citation:'Accuracy is 85 percent.'})
        self.assertIsNone(GroundedPaperReport.parse_model_output('{}',bundle))
        payload=dict(summary='Accuracy 85%.',research_problem='Evaluate accuracy.')
        self.assertIsNone(GroundedPaperReport.parse_model_output(json.dumps(payload),bundle))
        payload.update({key:[] for key in REPORT_SECTION_KEYS})
        payload['findings']=[dict(text='Accuracy 85%.',citations=[citation])]
        self.assertIsNotNone(GroundedPaperReport.parse_model_output(json.dumps(payload),bundle))

    def test_model_input_is_bounded_and_excludes_geometry_and_unseen_citations(self):
        citations={f'doc:1#page={i}&chunk=1':f'We achieved accuracy {i} percent in the stated experiment. '+('Evidence context. '*100) for i in range(1,50)}
        bundle=dict(document=dict(id=1,title='Study'),allowed_citations=citations,tables=[dict(geometry='x'*1_000_000)])
        messages=GroundedPaperReport.prompt(bundle)
        self.assertLess(sum(len(m['content'].encode('utf-8')) for m in messages),11000)
        self.assertNotIn('geometry',messages[1]['content'])
        selected=GroundedPaperReport.model_evidence(bundle)
        self.assertLess(selected['selection']['included'],selected['selection']['available'])
        unseen=next(c for c in citations if c not in {r['citation'] for r in selected['evidence']})
        payload=dict(summary='Experimental result.',research_problem='Evaluate accuracy.',summary_citations=[unseen])
        payload.update({key:[] for key in REPORT_SECTION_KEYS})
        payload['findings']=[dict(text='Accuracy 20 percent.',citations=[unseen])]
        report=GroundedPaperReport.parse_model_output(json.dumps(payload),bundle)
        self.assertEqual([],report['summary_citations'])
        self.assertEqual('review_required',report['findings'][0]['status'])


if __name__=='__main__':unittest.main()
