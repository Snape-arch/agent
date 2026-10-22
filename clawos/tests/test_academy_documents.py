import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.academy_documents import AcademyDocuments, DocumentConflict, documents_router, validate_document

class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'memory.db';self.s=AcademyDocuments(MemoryStore(str(self.path)))
        self.value=dict(title='研究笔记',context='文献 #1 · 第 2 页',blocks=[dict(id='p1',type='paragraph',text='<script>alert(1)</script>'),dict(id='code',type='code',language='python',text='print("evidence")\n# '+chr(96)*3+' preserved'),dict(id='table',type='table',text='',cells=[['name','value'],['a|b','line\nbreak']]),dict(id='drawing',type='drawing',text='机制图',strokes=[dict(tool='arrow',color='#315cf5',points=[[.1,.2],[.8,.7]])])])
    def test_roundtrip(self):
        d=self.s.save(self.value);fresh=AcademyDocuments(MemoryStore(str(self.path)))
        self.assertEqual(fresh.get(d['id'])['blocks'],self.value['blocks'])
        md=fresh.markdown(d);self.assertIn(chr(96)*4+'python',md);self.assertIn('a\\|b',md);self.assertIn('line<br>break',md)
    def test_conflict_and_history(self):
        d=self.s.save(self.value);updated=self.s.save({**d,'title':'新版'},d['id'])
        with self.assertRaises(DocumentConflict):self.s.save(d,d['id'])
        self.assertEqual(self.s.get(d['id'])['title'],'新版')
        self.assertEqual([v['version'] for v in self.s.history(d['id'])['versions']],[2,1])
        old=self.s.history(d['id'])['versions'][1];self.s.save({**old,'version':updated['version']},d['id'])
        self.assertEqual(self.s.get(d['id'])['title'],'研究笔记')
    def test_parallel_one_winner(self):
        d=self.s.save(self.value)
        def update(i):
            service=AcademyDocuments(MemoryStore(str(self.path)))
            try:service.save({**d,'title':'writer'+str(i)},d['id']);return 'ok'
            except DocumentConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(update,range(6)))
        self.assertEqual(results.count('ok'),1);self.assertEqual(self.s.get(d['id'])['version'],2)
    def test_invalid_blocks(self):
        for b in [dict(id='bad',type='html',text='x'),dict(id='bad',type='image',text='',data='data:image/svg+xml;base64,PHN2Zz4='),dict(id='bad',type='image',text='',data='data:image/png;base64,PHN2Zz4='),dict(id='bad',type='drawing',strokes=[dict(tool='pen',color='#315cf5',points=[[0,0],[float('nan'),1]])])]:
            with self.assertRaises(ValueError):validate_document({**self.value,'blocks':[b]})
        with self.assertRaises(ValueError):validate_document({**self.value,'blocks':[self.value['blocks'][0]]*2})
    def test_learner_scope(self):
        d=self.s.save(self.value,learner='alice')
        with self.assertRaises(ValueError):self.s.get(d['id'],'bob')
        with self.assertRaises(DocumentConflict):self.s.save(d,d['id'],'bob')
        with self.assertRaises(ValueError):self.s.save({**d,'version':True},d['id'],'alice')
    def test_http_export_and_model_failure(self):
        app=FastAPI();app.include_router(documents_router(lambda:self.s,AsyncMock(side_effect=RuntimeError('offline'))))
        with TestClient(app) as client:
            d=client.post('/api/academy/learning/documents',json=self.value).json();path='/api/academy/learning/documents/'+d['id']
            self.assertEqual(client.put(path,json=d).status_code,200)
            self.assertEqual(client.put(path,json=d).status_code,409)
            self.assertIn('print("evidence")',client.get(path+'/export').text)
            self.assertEqual(client.get(path+'/export?format=json').json()['blocks'],self.value['blocks'])
            self.assertEqual(client.post('/api/academy/learning/documents/assist',json=dict(mode='polish',text='some evidence')).status_code,502)
            self.assertEqual(self.s.get(d['id'])['version'],2)
    def test_history_bounded(self):
        d=self.s.save(self.value)
        for i in range(55):d=self.s.save({**d,'title':'version'+str(i)},d['id'])
        self.assertEqual(len(self.s.history(d['id'])['versions']),50)
if __name__=='__main__':unittest.main()
