"""Version-bound UTF-16 selection positions; never client-provided identities."""
import json
import time
from fastapi import HTTPException


def heartbeat(access,nid,uid,data):
    if not isinstance(data,dict): raise HTTPException(400,'在线状态无效')
    with access.store._conn() as c:
        c.execute('BEGIN IMMEDIATE');access.require(nid,uid,conn=c)
        bid=str(data.get('block_id') or '')[:80]
        cursor=data.get('cursor')
        if cursor is not None:
            if not isinstance(cursor,dict): raise HTTPException(400,'光标无效')
            version=cursor.get('version');a=cursor.get('anchor');f=cursor.get('focus');cell=cursor.get('cell')
            if any(type(x) is not int or x<0 for x in (version,a,f)) or max(a,f)>30000: raise HTTPException(400,'光标坐标无效')
            row=c.execute('SELECT version,payload FROM academy_documents WHERE id=?',(nid,)).fetchone()
            snap=c.execute('SELECT payload FROM academy_document_versions WHERE document_id=? AND version=?',(nid,version)).fetchone()
            if version!=row['version'] and not snap: raise HTTPException(409,'光标基线已过期')
            source=json.loads(row['payload'] if version==row['version'] else snap['payload'])
            def length(block_id,where):
                b=next((b for b in source['blocks'] if b['id']==block_id),None)
                if not b: raise HTTPException(400,'光标内容块不存在')
                if where is not None:
                    if b['type']!='table' or not isinstance(where,list) or len(where)!=2 or any(type(x) is not int or x<0 for x in where) or where[0]>=len(b['cells']) or where[1]>=len(b['cells'][0]): raise HTTPException(400,'光标单元格不存在')
                    spans=b.get('cell_inline',[[None]*len(b['cells'][0]) for _ in b['cells']])[where[0]][where[1]]
                    text=''.join(s['text'] for s in spans) if spans is not None else b['cells'][where[0]][where[1]]
                else:
                    if b['type'] not in ('paragraph','heading','quote','callout','bullet','numbered','todo'): raise HTTPException(400,'该内容不支持文字光标')
                    text=''.join(s['text'] for s in b['inline']) if 'inline' in b else b['text']
                return len(text.encode('utf-16-le'))//2
            focus_block=cursor.get('focus_block',bid);focus_cell=cursor.get('focus_cell',cell)
            if not isinstance(focus_block,str) or len(focus_block)>80 or a>length(bid,cell) or f>length(focus_block,focus_cell): raise HTTPException(400,'光标超出文字范围')
            c.execute('INSERT INTO collaboration_cursors VALUES (?,?,?) ON CONFLICT(document_id,user_id) DO UPDATE SET payload=excluded.payload',(nid,uid,json.dumps(dict(block_id=bid,focus_block=focus_block,version=version,anchor=a,focus=f,cell=cell,focus_cell=focus_cell))))
        else:c.execute('DELETE FROM collaboration_cursors WHERE document_id=? AND user_id=?',(nid,uid))
        c.execute('INSERT INTO collaboration_presence VALUES (?,?,?,?) ON CONFLICT(document_id,user_id) DO UPDATE SET seen=excluded.seen,block_id=excluded.block_id',(nid,uid,int(time.time()),bid))
        c.execute('DELETE FROM collaboration_cursors WHERE (document_id,user_id) IN (SELECT document_id,user_id FROM collaboration_presence WHERE seen<?)',(int(time.time())-3600,))
        c.execute('DELETE FROM collaboration_presence WHERE seen<?',(int(time.time())-3600,))
    return dict(ok=True)
