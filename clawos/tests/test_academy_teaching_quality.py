import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_teaching_quality import AcademyTeachingQuality,DIMS
class TeachingQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=AcademyMaterials(MemoryStore(str(Path(self.tmp.name)/'db')),Path(self.tmp.name)/'materials')
        state=self.s.upload('test.md',b'# Evidence\nEvidence supports conclusions.\n# Conditions\nMissing evidence requires refusal.')
        self.mid=state['document']['id'];self.chapters=state['chapters'];self.q=AcademyTeachingQuality(self.s)
    def bank(self):
        c=self.chapters[0];quote='Evidence supports conclusions.'
        return dict(teacher='Fixture Teacher (synthetic test only)',reviewed_at='2026-01-01',human_reviewed=True,cases=[dict(id=str(i),split='anchor' if i<3 else 'holdout',chapter=c['id'],questions=[dict(dimension=d,question='Explain the source condition.',criterion='Explain the condition and mechanism.',quote=quote) for d in DIMS],answers=['A unique synthetic answer number '+str(i)]*3,scores={d:i%3 for d in DIMS},reason='Synthetic labels for infrastructure testing only.') for i in range(9)])
    def predictions(self,bank):
        return [dict(dimensions={d:dict(score=r['scores'][d],student_quote=r['answers'][i] if r['scores'][d] else '',source_quote='Evidence supports conclusions.' if r['scores'][d] else '') for i,d in enumerate(DIMS)}) for r in bank['cases'] if r['split']=='holdout' for _ in range(2)]
    def test_unlabelled(self):self.assertFalse(self.s.state(self.mid)['calibration']['validated'])
    def test_holdout_and_profile(self):
        b=self.bank();ev=self.q.import_bank(self.mid,b);bank,prompts=self.q.calibration_prompts(self.mid)
        self.assertEqual(len(prompts),12);content=json.loads(prompts[0][2][1]['content'])
        self.assertEqual(len(content['anchor_examples']),3)
        self.assertFalse(any(x['answers']==b['cases'][4]['answers'] for x in content['anchor_examples']))
        self.q.save_calibration(self.mid,ev['id'],self.predictions(b));self.assertTrue(self.q.status(self.mid)['validated'])
        self.assertFalse(AcademyTeachingQuality(self.s,'changed-model').status(self.mid)['validated'])
        self.q.import_bank(self.mid,b);self.assertFalse(self.q.status(self.mid)['validated'])
    def test_false_pass_gate(self):
        b=self.bank();ev=self.q.import_bank(self.mid,b);pred=self.predictions(b)
        for i,d in enumerate(DIMS):pred[0]['dimensions'][d]=dict(score=2,student_quote=b['cases'][3]['answers'][i],source_quote='Evidence supports conclusions.')
        r=self.q.save_calibration(self.mid,ev['id'],pred)['data']
        self.assertEqual(r['false_passes'],1);self.assertEqual(r['status'],'needs_calibration');self.assertEqual(sum(map(sum,r['confusion_matrix'])),36)
    def test_invalid_bank(self):
        for mutation in ('human','duplicate','source'):
            b=self.bank()
            if mutation=='human':b['human_reviewed']=False
            elif mutation=='duplicate':b['cases'][4]['answers']=b['cases'][1]['answers']
            else:b['cases'][0]['questions'][0]['quote']='Invented source'
            with self.assertRaises(ValueError):self.q.import_bank(self.mid,b)
    def test_cross_chapter(self):
        ids=[c['id'] for c in self.chapters]
        value=dict(title='How does evidence affect refusal?',synthesis='The source connects evidence to the condition for refusal.',
            questions=[dict(kind=k,prompt='Explain the mechanism and its boundary.') for k in ('connection','conflict','transfer')],
            sources=[dict(chapter=ids[0],quote='Evidence supports conclusions.',role='Evidence provides the positive condition.'),dict(chapter=ids[1],quote='Missing evidence requires refusal.',role='The second source limits unsupported conclusions.')])
        ev=self.q.save_seminar(self.mid,ids,value)
        claims=[dict(chapter=s['chapter'],quote=s['quote'],reason='This source supports or limits the stated condition.') for s in value['sources']]
        self.q.seminar_response(self.mid,ev['id'],['The condition depends on evidence and requires checking the original source.']*3,claims)
        with self.assertRaises(ValueError):self.q.seminar_response(self.mid,ev['id'],['A complete enough answer for the source.']*3,[claims[0]]*2)
        value['sources'][1]['quote']='Fabricated quotation'
        with self.assertRaises(ValueError):self.q.save_seminar(self.mid,ids,value)
    def test_duplicate_chapters(self):
        with self.assertRaises(ValueError):self.q.seminar_prompt(self.mid,[self.chapters[0]['id']]*2)
if __name__=='__main__':unittest.main()
