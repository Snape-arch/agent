import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from memoryos.memory_store import MemoryStore
from services.academy_documents import AcademyDocuments, DocumentConflict, validate_document
from services.collaboration import Collaboration, AuthorizedDocuments
from services.document_events import document_delta, document_events
from services.document_merge import merge_document, merge_text, MergeConflict


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=MemoryStore(str(Path(self.tmp.name)/'db.sqlite'))
        self.docs=AcademyDocuments(self.store);self.access=Collaboration(self.store)
        self.base=self.docs.save(dict(title='Concurrent notes',blocks=[dict(id='a',type='paragraph',text='source A'),dict(id='b',type='paragraph',text='source B')]))

    def test_many_editors_do_not_lose_independent_blocks(self):
        value=dict(title='Shared',blocks=[dict(id='block'+str(i),type='paragraph',text='original') for i in range(12)])
        base=self.docs.save(value)
        def save(i):
            edit=deepcopy(base);edit['merge']=True;edit['blocks'][i]['text']='writer '+str(i)
            return self.docs.save(edit,base['id'])
        with ThreadPoolExecutor(12) as pool:results=list(pool.map(save,range(12)))
        current=self.docs.get(base['id'])
        self.assertEqual(current['version'],13)
        self.assertEqual([b['text'] for b in current['blocks']],['writer '+str(i) for i in range(12)])
        self.assertEqual(len({r['version'] for r in results}),12)

    def test_same_text_disjoint_changes_and_unicode(self):
        self.assertEqual(merge_text('甲乙丙丁','甲新乙丙丁','甲乙丙丁末'),'甲新乙丙丁末')
        first=deepcopy(self.base);first['blocks'][0]['text']='source A tail';self.docs.save(first,self.base['id'])
        second=deepcopy(self.base);second['merge']=True;second['blocks'][0]['text']='head source A'
        current=self.docs.save(second,self.base['id'])
        self.assertEqual(current['blocks'][0]['text'],'head source A tail')

    def test_overlap_conflict_keeps_server_and_draft(self):
        a=deepcopy(self.base);a['blocks'][0]['text']='source X';self.docs.save(a,self.base['id'])
        b=deepcopy(self.base);b['merge']=True;b['blocks'][0]['text']='source Y'
        with self.assertRaises(DocumentConflict):self.docs.save(b,self.base['id'])
        self.assertEqual(self.docs.get(self.base['id'])['blocks'][0]['text'],'source X')
        self.assertEqual(b['blocks'][0]['text'],'source Y')

    def test_delete_vs_edit_and_opposed_reorder_conflict(self):
        b=dict(title='x',blocks=[dict(id=x,type='paragraph',text=x) for x in 'abc'])
        l=deepcopy(b);r=deepcopy(b);l['blocks'].pop(0);r['blocks'][0]['text']='edited'
        with self.assertRaises(MergeConflict):merge_document(b,l,r)
        l=deepcopy(b);r=deepcopy(b);l['blocks'].reverse();r['blocks']=[r['blocks'][1],r['blocks'][0],r['blocks'][2]]
        with self.assertRaises(MergeConflict):merge_document(b,l,r)

    def test_two_insertions_survive_and_table_cells_merge(self):
        l=deepcopy(self.base);r=deepcopy(self.base)
        l['blocks'].insert(1,dict(id='new-l',type='paragraph',text='L'))
        r['blocks'].insert(1,dict(id='new-r',type='paragraph',text='R'))
        merged=merge_document(self.base,l,r)
        self.assertEqual({b['id'] for b in merged['blocks']},{'a','b','new-l','new-r'})
        base=dict(title='Table',blocks=[dict(id='t',type='table',text='',cells=[['a','b'],['1','2']])])
        l=deepcopy(base);r=deepcopy(base);l['blocks'][0]['cells'][1][0]='3';r['blocks'][0]['cells'][1][1]='4'
        self.assertEqual(merge_document(base,l,r)['blocks'][0]['cells'][1],['3','4'])

    def test_expired_history_cannot_rebase(self):
        current=self.base
        for i in range(51):current=self.docs.save({**current,'title':'v'+str(i)},current['id'])
        with self.assertRaises(DocumentConflict):self.docs.save({**self.base,'merge':True},self.base['id'])

    def test_rich_projection_and_code_backticks_are_preserved(self):
        b=dict(id='rich',type='paragraph',text='untrusted projection',inline=[dict(text='`x`',marks=[dict(type='code'),dict(type='bold')]),dict(text='证据',marks=[dict(type='link',href='https://example.org/a(b)'),dict(type='underline'),dict(type='highlight')])])
        d=self.docs.save(dict(title='Rich',blocks=[b]));saved=self.docs.get(d['id'])
        self.assertEqual(saved['blocks'][0]['inline'],b['inline'])
        self.assertIn('**`` `x` ``**',self.docs.markdown(saved))
        self.assertIn('a%28b%29',self.docs.markdown(saved))
        self.assertNotIn('untrusted projection',self.docs.markdown(saved))
        for marks in [[dict(type='html')],[dict(type='link',href='javascript:alert(1)')],[dict(type='link',href='https://example.org/\nattack')]]:
            with self.assertRaises(ValueError):validate_document(dict(title='x',blocks=[{**b,'inline':[dict(text='x',marks=marks)]}]))

    def test_rich_conflict_is_atomic_and_acl_cannot_be_bypassed(self):
        rich=self.docs.save(dict(title='Rich',blocks=[dict(id='r',type='paragraph',inline=[dict(text='original',marks=[])])]))
        invite=self.access.invite(rich['id'],'local-user','editor');_,u=self.access.join(invite['code'],'Editor')
        guest=AuthorizedDocuments(self.docs,self.access,u['id'])
        a=deepcopy(rich);a['blocks'][0]['inline'][0]['text']='first';guest.save(a,rich['id'])
        b=deepcopy(rich);b['merge']=True;b['blocks'][0]['inline'][0]['text']='second'
        with self.assertRaises(DocumentConflict):guest.save(b,rich['id'])
        self.access.revoke(rich['id'],'local-user',u['id'])
        with self.assertRaises(HTTPException):guest.save(b,rich['id'])
        self.assertEqual(self.docs.get(rich['id'])['version'],2)

    def test_same_rich_block_disjoint_edits_preserve_marks(self):
        base=self.docs.save(dict(title='Rich merge',blocks=[dict(id='r',type='paragraph',inline=[dict(text='甲乙丙丁',marks=[dict(type='bold')])])]))
        left=deepcopy(base);left['blocks'][0]['inline'][0]['text']='甲新乙丙丁';self.docs.save(left,base['id'])
        right=deepcopy(base);right['merge']=True;right['blocks'][0]['inline'][0]['text']='甲乙丙丁末'
        merged=self.docs.save(right,base['id'])
        self.assertEqual(merged['blocks'][0]['inline'],[dict(text='甲新乙丙丁末',marks=[dict(type='bold')])])
        self.assertEqual(merged['blocks'][0]['text'],'**甲新乙丙丁末**')

    def test_delta_and_stream_reconnect_revocation(self):
        async def exercise():
            class Request:
                async def is_disconnected(self):return False
            denied=False
            def read(seen):
                if denied:raise HTTPException(403,'revoked')
                current=self.docs.get(self.base['id'])
                return current if current['version']!=seen else None
            stream=document_events(Request(),read,None,since=self.base['version'],interval=.001)
            self.assertIn('event: ready',await anext(stream))
            edit=deepcopy(self.base);edit['blocks'][1]['text']='updated';fresh=self.docs.save(edit,self.base['id'])
            packet=await anext(stream);self.assertIn('event: document',packet);self.assertIn('id: 2',packet)
            delta=document_delta(self.base,fresh);self.assertEqual([b['id'] for b in delta['blocks']],['b'])
            await stream.aclose()
            reconnect=document_events(Request(),read,None,since=1,interval=.001)
            self.assertIn('updated',await anext(reconnect))
            denied=True
            packet=await anext(reconnect)
            if packet.startswith(':'):packet=await anext(reconnect)
            self.assertIn('revoked',packet)
            with self.assertRaises(StopAsyncIteration):await anext(reconnect)
        asyncio.run(exercise())

if __name__=='__main__':unittest.main()
