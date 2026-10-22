"""Source-bound meeting review and versioned follow-through, built on WorkspaceServices."""
import hashlib
import json
from datetime import date
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from .knowledge_core_service import KnowledgeCoreService


class MeetingWorkbench:
    def __init__(self,workspace):
        self.workspace=workspace;self.store=workspace.store
        self.knowledge=KnowledgeCoreService(self.store)
        with self.store._conn() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS meeting_review_state(meeting_id INTEGER PRIMARY KEY,version INTEGER NOT NULL,source_hash TEXT NOT NULL,reviewed_hash TEXT NOT NULL DEFAULT '',knowledge_id INTEGER,reviewer TEXT NOT NULL DEFAULT '',review_note TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS meeting_document_links(meeting_id INTEGER NOT NULL,version INTEGER NOT NULL,document_id TEXT NOT NULL,PRIMARY KEY(meeting_id,version));
            CREATE TABLE IF NOT EXISTS meeting_workbench_events(id INTEGER PRIMARY KEY,meeting_id INTEGER NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT (datetime('now')));''')

    @staticmethod
    def fingerprint(m):
        payload={k:m[k] for k in ('title','transcript','summary','decisions','risks')}
        payload['actions']=[{k:a[k] for k in ('description','owner','due_date','evidence')} for a in m['actions']]
        return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def _sync(self,nid,c):
        m=self.workspace.get_meeting(nid)
        if not m:raise HTTPException(404,'会议不存在')
        sha=self.fingerprint(m);row=c.execute('SELECT * FROM meeting_review_state WHERE meeting_id=?',(nid,)).fetchone()
        if not row:
            c.execute('INSERT INTO meeting_review_state(meeting_id,version,source_hash) VALUES (?,1,?)',(nid,sha))
        elif row['source_hash']!=sha:
            if row['knowledge_id']:self.knowledge.expire(row['knowledge_id'],'会议原文或纪要已更新，重新复核后发布',changed_by='user')
            c.execute("UPDATE meeting_review_state SET version=version+1,source_hash=?,reviewed_hash='',knowledge_id=NULL,reviewer='',review_note='' WHERE meeting_id=?",(sha,nid))
        state=dict(c.execute('SELECT * FROM meeting_review_state WHERE meeting_id=?',(nid,)).fetchone())
        state['review_required']=state['reviewed_hash']!=state['source_hash']
        m['review']=state
        today=date.today().isoformat()
        for a in m['actions']:
            a['overdue']=bool(a['due_date'] and a['due_date']<today and a['status'] not in ('done','cancelled'))
            a['unassigned']=not a['owner'].strip()
        m['metrics']=dict(total=len(m['actions']),done=sum(a['status']=='done' for a in m['actions']),overdue=sum(a['overdue'] for a in m['actions']),unassigned=sum(a['unassigned'] for a in m['actions']))
        return m

    def get(self,nid):
        with self.store.transaction() as c:return self._sync(nid,c)

    def index(self):
        with self.store._conn() as c:ids=[r['id'] for r in c.execute('SELECT id FROM meetings ORDER BY id DESC LIMIT 100')]
        return dict(meetings=[self.get(n) for n in ids])

    def draft(self,title,transcript,nid=None,version=None):
        if not isinstance(title,str) or not 1<=len(title.strip())<=200 or not isinstance(transcript,str) or not 1<=len(transcript.strip())<=200000:raise ValueError('标题需要 1–200 字，转写需要 1–200,000 字')
        with self.store.transaction() as c:
            prior={}
            if nid:
                m=self._sync(nid,c)
                if m['review']['version']!=version:raise HTTPException(409,'会议版本已变化，请刷新后编辑')
                prior={a['evidence']:a['status'] for a in m['actions']}
                c.execute('UPDATE meetings SET title=? WHERE id=?',(title.strip(),nid))
            else:nid=self.workspace.create_meeting(title.strip())['id']
            self.workspace.process_meeting_transcript(nid,transcript,publish_memory=False)
            c.execute("UPDATE meetings SET status='needs_review' WHERE id=?",(nid,))
            for evidence,status in prior.items():c.execute('UPDATE meeting_actions SET status=? WHERE meeting_id=? AND evidence=?',(status,nid,evidence))
            m=self._sync(nid,c);self.event(c,nid,m['review']['version'],'draft',{})
            return m

    @staticmethod
    def event(c,nid,version,action,detail):
        c.execute('INSERT INTO meeting_workbench_events(meeting_id,version,action,detail) VALUES (?,?,?,?)',(nid,version,action,json.dumps(detail,ensure_ascii=False)))

    def action(self,nid,aid,version,data):
        status=data.get('status');owner=data.get('owner');due=data.get('due_date')
        if status not in ('open','in_progress','blocked','done','cancelled') or not isinstance(owner,str) or len(owner)>100 or not isinstance(due,str):raise ValueError('行动项字段无效')
        if due:
            try:date.fromisoformat(due)
            except ValueError:raise ValueError('截止日期需为 YYYY-MM-DD')
        with self.store.transaction() as c:
            m=self._sync(nid,c)
            if type(version) is not int or version!=m['review']['version']:raise HTTPException(409,'会议已更新，请刷新')
            if status=='done' and not owner.strip():raise ValueError('完成行动项前请确认负责人')
            if not c.execute("UPDATE meeting_actions SET status=?,owner=?,due_date=?,updated_at=datetime('now') WHERE id=? AND meeting_id=?",(status,owner.strip(),due,aid,nid)).rowcount:raise HTTPException(404,'行动项不存在')
            updated=self._sync(nid,c)
            if updated['review']['version']==version:c.execute('UPDATE meeting_review_state SET version=version+1 WHERE meeting_id=?',(nid,))
            self.event(c,nid,version+1,'action',dict(action_id=aid,status=status,owner=owner,due_date=due))
            return self._sync(nid,c)

    def review(self,nid,version,note):
        if not isinstance(note,str) or not 4<=len(note.strip())<=2000:raise ValueError('请填写复核说明（4–2000 字）')
        with self.store.transaction() as c:
            m=self._sync(nid,c);r=m['review']
            if type(version) is not int or r['version']!=version:raise HTTPException(409,'会议内容已变化，请重新复核')
            if not m['transcript'].strip():raise ValueError('没有转写原文可复核')
            if not r['review_required']:return m
            published={k:m[k] for k in ('title','summary','decisions','risks')}
            published['actions']=[{k:a[k] for k in ('description','owner','due_date','evidence')} for a in m['actions']]
            content=json.dumps(published,ensure_ascii=False)
            item=self.knowledge.absorb(title=f'会议 {nid} · {m["title"]} · {r["source_hash"][:12]}',statement=content,category='meeting',source_ref=f'meeting:{nid}#sha256={r["source_hash"]}',source_type='manual',excerpt=m['transcript'][:1200],confidence=.85,metadata=dict(review_required=False,reviewer='local-user',review_note=note.strip(),source_hash=r['source_hash']),changed_by='user')
            c.execute("UPDATE meeting_review_state SET reviewed_hash=source_hash,knowledge_id=?,reviewer='local-user',review_note=?,version=version+1 WHERE meeting_id=?",(item['id'],note.strip(),nid))
            c.execute("UPDATE meetings SET status='reviewed' WHERE id=?",(nid,))
            self.event(c,nid,version+1,'review',dict(knowledge_id=item['id']))
            return self._sync(nid,c)

    def document(self,nid):
        """An explicit versioned snapshot becomes shareable, never an implicit ACL grant."""
        from .academy_documents import AcademyDocuments
        import uuid
        documents=AcademyDocuments(self.store)
        with self.store.transaction() as c:
            m=self._sync(nid,c);version=m['review']['version']
            prior=c.execute('SELECT document_id FROM meeting_document_links WHERE meeting_id=? AND version=?',(nid,version)).fetchone()
            if prior:return dict(document_id=prior['document_id'],meeting_version=version)
            blocks=[]
            def add(kind,text):blocks.append(dict(id=uuid.uuid4().hex,type=kind,text=text,**({'level':2} if kind=='heading' else {})))
            add('quote',('待复核草稿' if m['review']['review_required'] else '已复核')+f' · 会议版本 {version} · 此文档为独立快照，后续修改不回写会议。')
            add('heading','纪要');add('paragraph',m['summary'])
            for label,rows in [('决策',m['decisions']),('风险',m['risks'])]:
                add('heading',label)
                for row in rows:add('paragraph',row)
            add('heading','行动项')
            for a in m['actions']:add('paragraph',f'{a["description"]} · {a["owner"] or "未分配"} · {a["due_date"] or "无日期"} · {a["status"]}\n原文依据：{a["evidence"]}')
            add('heading','转写原文')
            # Document paragraphs have a bounded size; keep the full accepted transcript.
            for offset in range(0,len(m['transcript']),18000):add('quote',m['transcript'][offset:offset+18000])
            doc=documents.save(dict(title=m['title'],context=f'meeting:{nid}#version={version}&sha256={m["review"]["source_hash"]}',blocks=blocks))
            c.execute('INSERT INTO meeting_document_links VALUES (?,?,?)',(nid,version,doc['id']))
            self.event(c,nid,version,'document',dict(document_id=doc['id']))
            return dict(document_id=doc['id'],meeting_version=version)


def meeting_router(factory,access_factory,feishu_factory=None):
    router=APIRouter(prefix='/api/meeting-workbench')
    def guard(request):
        if access_factory().identity(request)['id']!='local-user':raise HTTPException(403,'会议工作台仅向本机所有者开放')
    @router.get('')
    def index(request:Request):guard(request);return factory().index()
    @router.get('/{nid}')
    def get(nid:int,request:Request):guard(request);return factory().get(nid)
    @router.post('')
    async def create(request:Request):return await draft(request)
    @router.put('/{nid}')
    async def update(nid:int,request:Request):return await draft(request,nid)
    async def draft(request,nid=None):
        guard(request)
        try:
            if len(await request.body())>900000:raise ValueError('转写内容过大')
            d=await request.json()
            return await run_in_threadpool(factory().draft,d.get('title'),d.get('transcript'),nid,d.get('version'))
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    @router.put('/{nid}/actions/{aid}')
    async def action(nid:int,aid:int,request:Request):
        guard(request)
        try:d=await request.json();return await run_in_threadpool(factory().action,nid,aid,d.get('version'),d)
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    @router.post('/{nid}/review')
    async def review(nid:int,request:Request):
        guard(request)
        try:d=await request.json();return await run_in_threadpool(factory().review,nid,d.get('version'),d.get('note'))
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    @router.post('/{nid}/document')
    async def document(nid:int,request:Request):
        guard(request)
        try:return await run_in_threadpool(factory().document,nid)
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    if feishu_factory:
        @router.post('/{nid}/feishu-draft')
        def feishu_draft(nid:int,request:Request):
            guard(request);m=factory().get(nid)
            if m['review']['review_required']:raise HTTPException(409,'请先复核会议，再生成飞书审批草稿')
            text=m['summary']+'\n\n决策：\n'+'\n'.join(m['decisions'])+'\n\n风险：\n'+'\n'.join(m['risks'])+'\n\n行动项：\n'+'\n'.join(f'{a["owner"] or "未分配"} | {a["description"]} | {a["due_date"] or "无日期"}' for a in m['actions'])
            if len(text)>20000:raise HTTPException(400,'纪要超过飞书草稿长度上限，请在文档中筛选')
            return feishu_factory().document_draft(m['title'],text,f'meeting:{nid}#version={m["review"]["version"]}&sha256={m["review"]["source_hash"]}')
    @router.get('/{nid}/export')
    def export(nid:int,request:Request):
        guard(request);m=factory().get(nid)
        text=f'# {m["title"]}\n\n'+('待复核草稿' if m['review']['review_required'] else '已复核')+f' · 版本 {m["review"]["version"]}\n\n'+m['summary']+'\n\n## 决策\n'+ '\n'.join('- '+x for x in m['decisions'])+'\n\n## 风险\n'+'\n'.join('- '+x for x in m['risks'])+'\n\n## 行动项\n'+'\n'.join(f'- [{"x" if a["status"]=="done" else " "}] {a["description"]} · {a["owner"] or "未分配"} · {a["due_date"] or "无日期"} · {a["status"]}' for a in m['actions'])+'\n\n## 转写原文\n'+m['transcript']+f'\n\n来源 SHA-256：{m["review"]["source_hash"]}\n'
        return Response(text,media_type='text/markdown',headers={'Content-Disposition':f'attachment; filename="meeting-{nid}.md"'})
    return router
