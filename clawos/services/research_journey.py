"""One source-bound dossier shared by research, education, Vision and Reflection."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from services.research_watch import fingerprint, packed
from services.research_learning import Conflict
from services.pdf_page_renderer import PdfPageRenderer

_pages=PdfPageRenderer()

UNITS=[
    dict(id='question',title='先提出一个可核查的问题',lesson='rag',minutes=5,papers=['rag-original'],
         explanation='把“介绍RAG”改成能回到原文的问题。先写预测，再区分论文作者的结论与你自己的推断。',prompt='你准备核查什么问题？什么证据能够改变你的预测？',view='rag-lab'),
    dict(id='representation',title='关键词、向量与相似度',lesson='embedding',minutes=10,papers=['dpr','hyde'],
         explanation='本实践实际运行BM25词法检索；向量表示是阅读和机制实验的学习对象，不能把词法分数当成真实向量效果。',prompt='关键词重叠为什么可能找错段落？向量相似为什么也不能直接证明答案正确？',view='visuals'),
    dict(id='evidence',title='版本、切分与原文定位',lesson='rag',minutes=10,papers=['realm','rag-original'],
         explanation='打开候选片段，核对版本、页码和引用区间。跨页片段连续展示，摘要与全文分别保存。',prompt='引用能打开以后，还要核对哪些条件和版本信息？',view='rag-lab'),
    dict(id='compare',title='只改变一个检索因素',lesson='rag',minutes=10,papers=['fid','retro','knnlm'],
         explanation='固定文献、问题和候选数，只改变可检索范围；同时记录噪声和上下文成本。短语覆盖不是答案准确率。',prompt='你会固定什么条件？怎样解释覆盖增加而答案仍然错误？',view='rag-lab'),
    dict(id='generate',title='让生成回答接受证据检查',lesson='rag',minutes=10,papers=['self-rag','ragas'],
         explanation='显式调用已配置本地模型，对摘要和全文候选分别生成带引用的回答。契约检查只能拒绝部分错误，语义仍需人工复核。',prompt='何时应拒答？怎样区分模型格式正确、引用可定位和语义受支持？',view='journey'),
    dict(id='transfer',title='换一个情境，再解释设计',lesson='rag',minutes=10,papers=['rest','ragas'],
         explanation='独立回答迁移问题，保留反思版本并进入现有评审流程。自述完成不等于掌握，也不会自动变成Agent策略奖励。',prompt='面对新的资料版本冲突，你怎样设计验证和拒答规则？',view='rag-lab'),
]


class ResearchJourney:
    def __init__(self, learning, *, importer=None):
        self.learning=learning;self.watch=learning.watch;self.store=learning.store;self.importer=importer
        with self.store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_journey_notes(case_id TEXT,paper_id TEXT,version INTEGER,payload TEXT,hash TEXT,PRIMARY KEY(case_id,paper_id));
            CREATE TABLE IF NOT EXISTS research_journey_checkpoints(case_id TEXT,unit TEXT,version INTEGER,payload TEXT,hash TEXT,PRIMARY KEY(case_id,unit));
            CREATE TABLE IF NOT EXISTS research_journey_imports(digest TEXT PRIMARY KEY,status TEXT,token TEXT,lease REAL,payload TEXT,hash TEXT);
            ''')

    def case(self,actor,cid):
        if actor!='local-user':raise PermissionError('研究学习计划目前仅供本机所有者使用')
        return self.learning._case(actor,cid)

    @staticmethod
    def decoded(row):
        value=json.loads(row['payload'])
        if fingerprint(value)!=row['hash']:raise ValueError('研究学习记录完整性校验失败')
        return value

    def dashboard(self,actor,cid):
        case,h=self.case(actor,cid)
        with self.store._conn() as c:
            notes={r['paper_id']:dict(version=r['version'],**self.decoded(r)) for r in c.execute('SELECT * FROM research_journey_notes WHERE case_id=?',(cid,))}
            checkpoints={r['unit']:dict(version=r['version'],**self.decoded(r)) for r in c.execute('SELECT * FROM research_journey_checkpoints WHERE case_id=?',(cid,))}
            imports={r['digest']:dict(status=r['status'],**self.decoded(r)) for r in c.execute('SELECT * FROM research_journey_imports')}
        papers=[]
        for p in case['papers']:
            stored=imports.get(p['raw_sha256'],{});item={k:v for k,v in p.items() if k not in ('text','page_spans')}
            item.update(note=notes.get(p['id'],dict(version=0,status='unread',folder='',tags=[],note='')),import_record=stored,
                pdf_url=f'/api/vision/research/cases/{cid}/papers/{p["id"]}/pdf',
                source_role='fixed_public_capture',recommendation='助手整理的代表文献，非个性化效果证明')
            papers.append(item)
        return dict(case_id=cid,case_hash=h,overview_id=case['overview_id'],subscription_id=case['subscription_id'],papers=papers,
            units=[dict(u,checkpoint=checkpoints.get(u['id']),teacher_verified=False) for u in UNITS],
            links=dict(overview='/academy/research?report='+case['overview_id'],course='/academy/lab?lesson=rag&researchCase='+cid,
                       practice='/academy/vision/?ragCase='+cid+'#rag-lab',mechanism='/academy/vision/?domain=rag&ragCase='+cid+'#visuals',
                       review='/academy/research',agent='/console#reflection'),
            relationship=dict(execution='ClawOS owns identity, model calls, storage and task evidence; Vision renders teaching observations.',
                evolution='Only explicitly submitted, mechanically observed Agent contract failures enter existing Reflection. Reviewed replay/shadow/canary gates remain unchanged.',
                learner_reflection_is_agent_reward=False,runtime_promotion_evidence=False),
            boundary='同一冻结研究计划贯穿文献、课程、实验和评审。阅读标记和解释是本人记录，不认证教师身份、掌握度或学习收益。')

    def paper(self,actor,cid,pid):
        case,h=self.case(actor,cid);paper=next((p for p in case['papers'] if p['id']==pid),None)
        if paper is None:raise LookupError('论文不在该研究学习计划')
        return paper,h

    def pdf(self,actor,cid,pid):
        p,_=self.paper(actor,cid,pid);version=p['version']
        if not re.fullmatch(r'\d{4}\.\d{4,5}v\d+',version):raise ValueError('论文固定版本无效')
        root=(self.learning.root/'sources').resolve();path=root/version/'paper.pdf'
        if not path.resolve().is_relative_to(root) or not path.is_file():raise LookupError('已捕获的PDF缺失，请核对原件，不自动替换')
        if path.stat().st_size>16_000_000:raise ValueError('PDF超出本实践预算')
        raw=path.read_bytes()
        if not raw.startswith(b'%PDF') or hashlib.sha256(raw).hexdigest()!=p['raw_sha256']:raise ValueError('已捕获PDF摘要与冻结计划不一致')
        return version+'.pdf',raw

    def save_note(self,actor,cid,pid,data):
        _,h=self.paper(actor,cid,pid)
        if not isinstance(data,dict) or set(data)!={'case_hash','version','status','folder','tags','note'}:raise ValueError('论文整理字段无效')
        if data['case_hash']!=h:raise Conflict('论文计划来源摘要变化')
        if type(data['version']) is not int or data['version']<0 or data['status'] not in ('unread','reading','read'):raise ValueError('阅读状态或版本无效')
        if any(not isinstance(data[k],str) or len(data[k])>limit for k,limit in [('folder',80),('note',3000)]):raise ValueError('资料夹或笔记超过预算')
        if not isinstance(data['tags'],list) or len(data['tags'])>8 or any(not isinstance(t,str) or not 1<=len(t.strip())<=30 for t in data['tags']):raise ValueError('标签最多8个，每个1–30字')
        value={k:data[k] for k in ('status','folder','tags','note')};value['tags']=list(dict.fromkeys(t.strip() for t in value['tags']))
        with self.store.transaction() as c:
            old=c.execute('SELECT * FROM research_journey_notes WHERE case_id=? AND paper_id=?',(cid,pid)).fetchone();version=old['version'] if old else 0
            if version!=data['version']:
                if old and self.decoded(old)==value:return dict(version=version,**value)
                raise Conflict('整理记录已更新，当前输入保留，请刷新核对')
            c.execute('INSERT OR REPLACE INTO research_journey_notes VALUES(?,?,?,?,?)',(cid,pid,version+1,packed(value),fingerprint(value)))
        return dict(version=version+1,**value)

    def pdf_page(self,actor,cid,pid,page):
        _,raw=self.pdf(actor,cid,pid);paper,h=self.paper(actor,cid,pid)
        value=_pages.render_bytes(raw,page)
        if value['pages']!=paper['page_count']:raise ValueError('PDF页数与冻结计划不一致')
        return dict(value,case_hash=h,raw_sha256=paper['raw_sha256'])

    def checkpoint(self,actor,cid,unit,data):
        _,h=self.case(actor,cid)
        if unit not in {u['id'] for u in UNITS}:raise ValueError('课程单元不存在')
        if not isinstance(data,dict) or set(data)!={'case_hash','version','explanation'} or data['case_hash']!=h:raise Conflict('课程来源或字段不一致')
        if type(data['version']) is not int or data['version']<0 or not isinstance(data['explanation'],str) or not 10<=len(data['explanation'].strip())<=3000:raise ValueError('请保存10–3000字的本人解释和有效版本')
        value=dict(explanation=data['explanation'].strip(),kind='learner_self_report',mastery_updated=False,teacher_verified=False)
        with self.store.transaction() as c:
            old=c.execute('SELECT * FROM research_journey_checkpoints WHERE case_id=? AND unit=?',(cid,unit)).fetchone();version=old['version'] if old else 0
            if version!=data['version']:
                if old and self.decoded(old)==value:return dict(version=version,**value)
                raise Conflict('学习解释已更新，请核对旧版本')
            c.execute('INSERT OR REPLACE INTO research_journey_checkpoints VALUES(?,?,?,?,?)',(cid,unit,version+1,packed(value),fingerprint(value)))
        return dict(version=version+1,**value)

    def import_paper(self,actor,cid,pid,data):
        paper,h=self.paper(actor,cid,pid)
        if data!={'case_hash':h,'confirmed':True}:raise ValueError('请明确导入当前固定PDF到论文库与教材学习')
        if self.importer is None:raise ValueError('当前服务未接入共享论文和教材存储')
        name,raw=self.pdf(actor,cid,pid);key=paper['raw_sha256'];token=uuid.uuid4().hex;now=self.watch.clock()
        with self.store.transaction() as c:
            old=c.execute('SELECT * FROM research_journey_imports WHERE digest=?',(key,)).fetchone()
            if old and old['status']=='completed':return self.decoded(old)
            if old and old['status']=='importing' and old['lease']>now:raise Conflict('同一原件正在导入，请稍后恢复')
            value=dict(source_digest=key,filename=name)
            c.execute('INSERT OR REPLACE INTO research_journey_imports VALUES(?,?,?,?,?,?)',(key,'importing',token,now+240,packed(value),fingerprint(value)))
        try:
            imported=self.importer(paper,raw)
            if not isinstance(imported,dict) or not imported.get('document_id') or not imported.get('material_id'):raise ValueError('共享库与教材导入回执不完整')
            self.case(actor,cid);value=dict(imported,source_digest=key,filename=name)
            with self.store.transaction() as c:
                if not c.execute("UPDATE research_journey_imports SET status='completed',lease=0,payload=?,hash=? WHERE digest=? AND token=? AND status='importing' AND lease>?",(packed(value),fingerprint(value),key,token,self.watch.clock())).rowcount:raise Conflict('导入租约已过期；共享库原件保留，重试会按原件去重')
            return value
        except BaseException as exc:
            value=dict(source_digest=key,error_type=type(exc).__name__,partial_records_may_exist=True)
            with self.store._conn() as c:c.execute("UPDATE research_journey_imports SET status='failed',lease=0,payload=?,hash=? WHERE digest=? AND token=?",(packed(value),fingerprint(value),key,token))
            raise
