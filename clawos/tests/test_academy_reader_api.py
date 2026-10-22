"""Reader HTTP boundaries, complete text pagination and persisted reading position."""
from pathlib import Path
import base64
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
import fitz


class AcademyReaderApiTests(unittest.TestCase):
    def setUp(self):
        import clawos_server as server
        self.server=server
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'paper.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((70,80),'Source-bound reader fixture.')
            pdf.new_page().insert_text((70,80),'Second page.');pdf.save(self.source)
        self.store=MemoryStore(str(self.root/'memory.db'))
        self.doc=self.store.add_document('Reader fixture','paper.pdf',str(self.source),'revision-1','application/pdf')
        self.did=self.doc['id']
        for i in range(105):self.store.add_document_chunk(self.did,i,'Evidence '+str(i)+' '+'x'*900,citation=f'doc:{self.did}#chunk={i}')
        app=FastAPI()
        paths={'/api/documents/{document_id}/page','/api/documents/{document_id}/chunks',
            '/api/academy/paper/annotations','/api/academy/paper/checkpoint','/api/academy/paper/checkpoints/{run_id}'}
        for route in server.app.routes:
            if route.path in paths:app.router.routes.append(route)
        for name,value in [('g_memory_store',self.store),('UPLOAD_DIR',self.root),('OUTPUT_ROOT',self.root/'output')]:
            p=patch.object(server,name,value);p.start();self.addCleanup(p.stop)
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def test_complete_chunk_pagination_and_page_root_bounds(self):
        first=self.client.get(f'/api/documents/{self.did}/chunks?limit=100').json()
        self.assertTrue(first['has_more']);self.assertEqual(first['next_offset'],100)
        last=self.client.get(f'/api/documents/{self.did}/chunks?limit=100&offset=100').json()
        self.assertEqual(len(last['chunks']),5);self.assertFalse(last['has_more'])
        self.assertGreater(len(last['chunks'][0]['content']),900)
        self.assertEqual(self.client.get(f'/api/documents/{self.did}/page?page=2').json()['page'],2)
        self.assertEqual(self.client.get(f'/api/documents/{self.did}/page?page=3').status_code,400)
        outside=self.store.add_document('Outside','outside.pdf',str(self.root.parent/'outside.pdf'))
        self.assertEqual(self.client.get(f"/api/documents/{outside['id']}/page").status_code,403)

    def test_annotation_revision_coordinate_scope_and_unique_artifacts(self):
        pix=fitz.Pixmap(fitz.csRGB,(0,0,2,2),False);pix.clear_with(255)
        data=dict(document_id=self.did,page=2,source_revision='revision-1',coordinate_space='pdf_page',
            image_data='data:image/png;base64,'+base64.b64encode(pix.tobytes('png')).decode())
        self.assertEqual(self.client.post('/api/academy/paper/annotations',json={**data,'source_revision':'stale'}).status_code,409)
        self.assertEqual(self.client.post('/api/academy/paper/annotations',json={**data,'coordinate_space':'unknown'}).status_code,400)
        a=self.client.post('/api/academy/paper/annotations',json=data).json()
        b=self.client.post('/api/academy/paper/annotations',json=data).json()
        self.assertNotEqual(a['artifact']['path'],b['artifact']['path'])
        self.assertEqual(a['run']['inputs']['page'],2)
        self.assertEqual(a['run']['inputs']['source_revision'],'revision-1')

    def test_checkpoint_position_and_same_second_save_survive(self):
        data=dict(document_id=self.did,reading=dict(page=2))
        a=self.client.post('/api/academy/paper/checkpoint',json=data).json()
        b=self.client.post('/api/academy/paper/checkpoint',json=data).json()
        self.assertNotEqual(a['run']['run_id'],b['run']['run_id'])
        reopened=self.client.get('/api/academy/paper/checkpoints/'+a['run']['run_id']).json()['checkpoint']
        self.assertEqual(reopened['reading'],dict(page=2,source_revision='revision-1'))
        self.assertEqual(self.client.post('/api/academy/paper/checkpoint',json={**data,'reading':{'page':0}}).status_code,400)


if __name__=='__main__':unittest.main()
