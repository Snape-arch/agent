from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from memoryos.memory_store import MemoryStore
from services.academy_documents import AcademyDocuments,validate_document,DocumentConflict
from services.collaboration import Collaboration


class AdvancedDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=MemoryStore(str(Path(self.tmp.name)/'db.sqlite'));self.docs=AcademyDocuments(self.store);self.access=Collaboration(self.store)
        self.doc=self.docs.save(dict(title='Shared table',blocks=[dict(id='t',type='table',text='',cells=[['2','3'],['=SUM(A1:B1)','tail']]),dict(id='p',type='paragraph',text='A😀BC')]))

    def test_table_format_survives_roundtrip_and_different_cell_migration_merges(self):
        left=deepcopy(self.doc);right=deepcopy(self.doc)
        for edit in (left,right):edit['merge']=True;edit['blocks'][0]['cell_inline']=[[None,None],[None,None]]
        left['blocks'][0]['cell_inline'][0][0]=[dict(text='2',marks=[dict(type='bold')])]
        right['blocks'][0]['cell_inline'][0][1]=[dict(text='3',marks=[dict(type='italic')])]
        self.docs.save(left,self.doc['id']);saved=self.docs.save(right,self.doc['id'])
        self.assertEqual(saved['blocks'][0]['cells'][0],['**2**','*3*'])
        self.assertIn('**2**',self.docs.markdown(saved))

    def test_rich_cell_overlap_rejected_and_shape_changes_preserve_conflict(self):
        left=deepcopy(self.doc);right=deepcopy(self.doc)
        for edit in (left,right):edit['merge']=True
        left['blocks'][0]['cells'][0][0]='left';right['blocks'][0]['cells'][0][0]='right'
        self.docs.save(left,self.doc['id'])
        with self.assertRaises(DocumentConflict):self.docs.save(right,self.doc['id'])
        self.assertEqual(self.docs.get(self.doc['id'])['blocks'][0]['cells'][0][0],'left')

    def test_invalid_cell_shapes_urls_and_math_limits(self):
        for runs in ([[[]]],[[[dict(text='x',marks=[dict(type='link',href='javascript:x')])],None],[None,None]]):
            edit=deepcopy(self.doc);edit['blocks'][0]['cell_inline']=runs
            with self.assertRaises(ValueError):validate_document(edit)
        value=dict(title='Math',blocks=[dict(id='math',type='math',text=r'\frac{a}{b}',caption='a divided by b')])
        saved=self.docs.save(value);self.assertIn('$$',self.docs.markdown(saved))
        value['blocks'][0]['text']='x'*2001
        with self.assertRaises(ValueError):validate_document(value)

    def test_cursor_unicode_cell_version_and_revocation(self):
        guest=self.access.join(self.access.invite(self.doc['id'],'local-user','editor')['code'],'Guest')[1]
        uid=guest['id'];self.access.presence(self.doc['id'],uid,dict(block_id='p',cursor=dict(version=1,anchor=1,focus=3)))
        cursor=self.access.cursors(self.doc['id'],'local-user')['cursors'][0]
        self.assertEqual((cursor['anchor'],cursor['focus']),(1,3))
        for cursor in (dict(version=1,anchor=0,focus=6),dict(version=99,anchor=0,focus=0),dict(version=1,anchor=True,focus=0),dict(version=1,anchor=0,focus=1,cell=[99,0])):
            with self.assertRaises(HTTPException):self.access.presence(self.doc['id'],uid,dict(block_id='p',cursor=cursor))
        self.access.revoke(self.doc['id'],'local-user',uid)
        self.assertEqual(self.access.cursors(self.doc['id'],'local-user')['cursors'],[])
        with self.assertRaises(HTTPException):self.access.presence(self.doc['id'],uid,dict(block_id='p'))

    def test_long_rich_projection_revalidates_without_losing_inline(self):
        value=dict(title='Projection',blocks=[dict(id='p',type='paragraph',text='',inline=[dict(text='*'*20000,marks=[dict(type='bold')])])])
        saved=self.docs.save(value);saved['title']='Saved again';self.assertEqual(self.docs.save(saved,saved['id'])['blocks'][0]['inline'],value['blocks'][0]['inline'])

    def test_cross_block_cursor_and_cell_focus_validate_both_ends(self):
        guest=self.access.join(self.access.invite(self.doc['id'],'local-user','editor')['code'],'Guest')[1]
        cursor=dict(version=1,anchor=3,focus=1,focus_block='t',focus_cell=[0,1])
        self.access.presence(self.doc['id'],guest['id'],dict(block_id='p',cursor=cursor))
        saved=self.access.cursors(self.doc['id'],'local-user')['cursors'][0]
        self.assertEqual((saved['block_id'],saved['focus_block'],saved['focus_cell']),('p','t',[0,1]))
        for edit in (dict(cursor,focus=2),dict(cursor,focus_block='missing'),dict(cursor,focus_cell=[False,1])):
            with self.assertRaises(HTTPException):self.access.presence(self.doc['id'],guest['id'],dict(block_id='p',cursor=edit))


if __name__=='__main__':unittest.main()
