"""Immutable private teaching views, validated against saved numerical evidence."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.vision_api import vision_router
from services.vision_teaching import VisionTeaching, Conflict


def experiment(template='rag'):
    return dict(request_id='report-test-'+template,template=template,value=True if template=='rag' else 2 if template=='peft' else 32,
                seed=42,hypothesis='Synthetic fixture: compare the bounded paired mechanisms.',binding=None)


def state(template):
    return dict(kind='rag-source',arm=1,case_id='loan') if template=='rag' else dict(kind='low-rank',arm=1,matrix='update',row=1,column=2) if template=='peft' else dict(kind='diffusion-timeline',arm=1,frame=12)


class VisualEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.service=VisionTeaching(self.root/'teaching.sqlite')

    @staticmethod
    def view(record,template='rag',key='view-request-001'):
        return dict(request_id=key,name='Synthetic private observation',report_hash=record['hash'],state=state(template))

    def test_all_three_views_restore_exact_state_and_original_report(self):
        for template in ('rag','peft','diffusion'):
            record=self.service.create('owner',experiment(template));rid=record['report']['id']
            view=self.service.save_visualization('owner',rid,self.view(record,template,key='view-request-'+template))
            restored=VisionTeaching(self.service.path).visualization('owner',view['id'])
            self.assertEqual(restored['view']['state'],state(template));self.assertEqual(restored['record'],record)
            self.assertEqual(view['visibility'],'owner_only')

    def test_invalid_positions_unknown_fields_and_boolean_indices_are_rejected(self):
        bad=[('rag',dict(kind='rag-source',arm=1,case_id='invented')),
             ('rag',dict(kind='rag-source',arm=True,case_id='loan')),
             ('peft',dict(kind='low-rank',arm=1,matrix='a',row=2,column=0)),
             ('peft',dict(kind='low-rank',arm=1,matrix='update',row=0,column=6)),
             ('diffusion',dict(kind='diffusion-timeline',arm=0,frame=9)),
             ('diffusion',dict(kind='diffusion-timeline',arm=1,frame=True)),
             ('diffusion',dict(kind='diffusion-timeline',arm=1,frame=0,rendererSource='not-accepted'))]
        for template,value in bad:
            record=self.service.create('owner',experiment(template));data=self.view(record,template);data['state']=value
            with self.assertRaises(ValueError):self.service.save_visualization('owner',record['report']['id'],data)

    def test_source_hash_conflict_idempotence_and_no_overwrite(self):
        record=self.service.create('owner',experiment());rid=record['report']['id'];data=self.view(record)
        saved=self.service.save_visualization('owner',rid,data)
        self.assertEqual(saved,self.service.save_visualization('owner',rid,data))
        altered=copy.deepcopy(data);altered['state']['case_id']='missing'
        with self.assertRaises(Conflict):self.service.save_visualization('owner',rid,altered)
        altered['request_id']='another-view-key';altered['report_hash']='different'
        with self.assertRaises(Conflict):self.service.save_visualization('owner',rid,altered)
        self.assertEqual(self.service.get('owner',rid),record)
        self.assertEqual(self.service.visualizations('owner',rid)['total'],1)

    def test_views_do_not_cross_owner_boundaries(self):
        record=self.service.create('owner',experiment());rid=record['report']['id']
        saved=self.service.save_visualization('owner',rid,self.view(record))
        for action,args in [('visualization',(saved['id'],)),('visualizations',(rid,)),('save_visualization',(rid,self.view(record)))]:
            with self.assertRaises(LookupError):getattr(self.service,action)('guest',*args)

    def test_view_corruption_is_not_rendered_as_an_alternate_state(self):
        record=self.service.create('owner',experiment());saved=self.service.save_visualization('owner',record['report']['id'],self.view(record))
        with self.service.connect() as c:c.execute('UPDATE teaching_visualizations SET hash=? WHERE id=?',('corrupted',saved['id']))
        with self.assertRaises(ValueError):self.service.visualization('owner',saved['id'])
        with self.assertRaises(ValueError):self.service.visualizations('owner',record['report']['id'])

    def test_cross_instance_concurrent_retry_creates_one_view(self):
        record=self.service.create('owner',experiment());other=VisionTeaching(self.service.path)
        with ThreadPoolExecutor(2) as pool:
            rows=list(pool.map(lambda s:s.save_visualization('owner',record['report']['id'],self.view(record)),[self.service,other]))
        self.assertEqual(rows[0]['id'],rows[1]['id']);self.assertEqual(self.service.visualizations('owner',record['report']['id'])['total'],1)

    def test_views_are_paginated_and_quota_is_explicit(self):
        record=self.service.create('owner',experiment());rid=record['report']['id']
        for i in range(200):self.service.save_visualization('owner',rid,self.view(record,key=f'view-page-{i:03}'))
        first=self.service.visualizations('owner',rid);second=self.service.visualizations('owner',rid,2)
        self.assertEqual(len(first['items']),20);self.assertTrue(first['has_more']);self.assertEqual(first['total'],200)
        self.assertFalse({v['id'] for v in first['items']} & {v['id'] for v in second['items']})
        with self.assertRaises(ValueError):self.service.save_visualization('owner',rid,self.view(record,key='over-quota-request'))


class VisualApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.service=VisionTeaching(root/'teaching.sqlite')
        class Identity:
            def identity(self,request):return dict(id='local-user')
        app=FastAPI();app.include_router(vision_router(lambda:None,Identity,root,teaching=lambda:self.service))
        self.client=TestClient(app,client=('127.0.0.1',40000));self.addCleanup(self.client.close)

    def test_actual_save_reopen_invalid_state_and_conflict_status(self):
        base='/api/vision/teaching';record=self.client.post(base+'/reports',json=experiment()).json();rid=record['report']['id']
        data=VisualEvidenceTests.view(record);response=self.client.post(base+'/reports/'+rid+'/visualizations',json=data)
        self.assertEqual(response.status_code,200);vid=response.json()['id']
        self.assertEqual(self.client.get(base+'/visualizations/'+vid).json()['record'],record)
        self.assertEqual(self.client.get(base+'/reports/'+rid+'/visualizations').json()['total'],1)
        data['report_hash']='wrong';self.assertEqual(self.client.post(base+'/reports/'+rid+'/visualizations',json=data).status_code,409)
        data['report_hash']=record['hash'];data['state']['case_id']='invented';self.assertEqual(self.client.post(base+'/reports/'+rid+'/visualizations',json=data).status_code,400)

    def test_foreign_origin_or_guest_session_never_saves_a_view(self):
        base='/api/vision/teaching';record=self.client.post(base+'/reports',json=experiment()).json();rid=record['report']['id']
        for headers in ({'Origin':'https://foreign.invalid'},{'Authorization':'Bearer synthetic-guest'},{'X-Forwarded-For':'127.0.0.1'}):
            self.assertEqual(self.client.post(base+'/reports/'+rid+'/visualizations',json=VisualEvidenceTests.view(record),headers=headers).status_code,403)
        self.assertEqual(self.service.visualizations('local-user',rid)['total'],0)


if __name__=='__main__':unittest.main()
