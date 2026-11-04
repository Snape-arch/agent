"""Real-paper research -> frozen overview -> visual retrieval -> transfer practice."""
import json
from pathlib import Path
import re
import time
import uuid
import hashlib
from datetime import datetime,timezone,timedelta
from services.research_watch import fingerprint,packed
from services.research_synthesis import ResearchSynthesis,extracts,publication,LABELS
from services.research_bibliography import source_records
from services.research_domains import get as domain_pack
from services.research_learning_engine import VERSION,TRANSFER,experiment
from services.research_learning_sources import paper_source

class Conflict(ValueError):pass

def implementation_hashes():
    from services import research_learning_engine,research_learning_sources
    paths=[Path(__file__),Path(research_learning_engine.__file__),Path(research_learning_sources.__file__)]
    return {p.name:hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in paths}

class ResearchLearning:
    def __init__(self,watch,root,fetch=None):
        self.watch=watch;self.store=watch.store;self.root=Path(root);self.fetch=fetch or paper_source
        self.synthesis=ResearchSynthesis(watch)
        with self.store._conn() as c:c.executescript('''
          CREATE TABLE IF NOT EXISTS rag_learning_jobs(id TEXT PRIMARY KEY,actor TEXT NOT NULL,request_id TEXT NOT NULL,
            status TEXT NOT NULL,token TEXT NOT NULL,lease REAL NOT NULL,completed INTEGER NOT NULL,error TEXT NOT NULL,case_id TEXT,UNIQUE(actor,request_id));
          CREATE TABLE IF NOT EXISTS rag_learning_cases(id TEXT PRIMARY KEY,actor TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS rag_learning_runs(id TEXT PRIMARY KEY,actor TEXT NOT NULL,case_id TEXT NOT NULL,request_id TEXT NOT NULL,input_hash TEXT NOT NULL,
            created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,UNIQUE(actor,request_id));
          CREATE TABLE IF NOT EXISTS rag_learning_attempts(run_id TEXT NOT NULL,version INTEGER NOT NULL,input_hash TEXT NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,PRIMARY KEY(run_id,version));
          CREATE TABLE IF NOT EXISTS rag_learning_views(id TEXT PRIMARY KEY,actor TEXT NOT NULL,run_id TEXT NOT NULL,request_id TEXT NOT NULL,input_hash TEXT NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,UNIQUE(actor,request_id));
        ''')

    @staticmethod
    def request_id(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',value):raise ValueError('请求编号无效')
        return value

    def catalog(self,actor):
        pack=domain_pack('rag')['domain']
        with self.store._conn() as c:
            c.execute("UPDATE rag_learning_jobs SET status='failed',error='LeaseExpired' WHERE actor=? AND status='preparing' AND lease<=?",(actor,self.watch.clock()))
            cases=[dict(id=r['id'],created=r['created'],hash=r['hash']) for r in c.execute('SELECT id,created,hash FROM rag_learning_cases WHERE actor=? ORDER BY created DESC,id LIMIT 20',(actor,))]
            active=c.execute("SELECT request_id,status,completed,error,lease,case_id FROM rag_learning_jobs WHERE actor=? ORDER BY rowid DESC LIMIT 1",(actor,)).fetchone()
        return dict(version=VERSION,papers=[{k:p[k] for k in ('id','name','title','version','url')} for p in pack['papers']+pack['supplements']],cases=cases,
            preparation=dict(active) if active else None,transfer_questions=TRANSFER,
            boundary='固定10篇代表文献的全文检索实践；准备时访问公开arXiv，已捕获版本可复用。不会调用模型或自动认证教师/学习收益。')

    def prepare(self,actor,data):
        if actor!='local-user':raise PermissionError('公开全文准备仅本机所有者可操作')
        if not isinstance(data,dict) or set(data)!={'request_id'}:raise ValueError('准备请求字段无效')
        request=self.request_id(data['request_id']);now=self.watch.clock();job=uuid.uuid4().hex;token=uuid.uuid4().hex
        source_hashes=implementation_hashes()
        if source_hashes!=IMPLEMENTATION_AT_LOAD:raise Conflict('服务源码已变化，请正常重启应用后再准备资料')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');prior=c.execute('SELECT * FROM rag_learning_jobs WHERE actor=? AND request_id=?',(actor,request)).fetchone()
            if prior:
                if prior['status']=='completed':return self.get_case(actor,prior['case_id'])
                raise Conflict('该准备请求仍在运行或已失败；查看进度后可另发请求')
            c.execute("UPDATE rag_learning_jobs SET status='failed',error='LeaseExpired' WHERE status='preparing' AND lease<=?",(now,))
            if c.execute("SELECT 1 FROM rag_learning_jobs WHERE status='preparing' AND lease>?",(now,)).fetchone():raise Conflict('已有全文准备正在进行')
            if c.execute('SELECT COUNT(*) FROM rag_learning_cases WHERE actor=?',(actor,)).fetchone()[0]>=20:raise ValueError('实践计划最多保留20份；本轮不会自动覆盖旧计划')
            if c.execute('SELECT COUNT(*) FROM rag_learning_jobs WHERE actor=? AND lease>?',(actor,now-86400)).fetchone()[0]>=20:raise ValueError('每日最多20次资料准备请求')
            c.execute('INSERT INTO rag_learning_jobs VALUES(?,?,?,?,?,?,0,?,?)',(job,actor,request,'preparing',token,now+600,'',None))
        try:
            pack=domain_pack('rag')['domain'];papers=[];started=time.monotonic()
            for spec in pack['papers']+pack['supplements']:
                paper=self.fetch(spec,self.root/'sources')
                if paper['id']!=spec['id'] or paper['version']!=spec['version'] or fingerprint(paper['text'])!=paper['source_text_fingerprint']:
                    raise ValueError('全文准备的来源身份或文本摘要不一致')
                papers.append(paper)
                if sum(len(p['text']) for p in papers)>2_000_000 or time.monotonic()-started>550:raise ValueError('全文准备超出总字符或时间预算')
                with self.store._conn() as c:
                    if not c.execute("UPDATE rag_learning_jobs SET completed=? WHERE id=? AND token=? AND status='preparing' AND lease>?",(len(papers),job,token,self.watch.clock())).rowcount:raise Conflict('准备任务已过期')
            # Validate all declared exercise anchors before publishing a research plan.
            experiment(papers,3)
            if implementation_hashes()!=source_hashes:raise Conflict('准备期间源码变化，未发布计划')
            case_id=self._publish(actor,job,token,pack,papers)
            return self.get_case(actor,case_id)
        except BaseException as exc:
            with self.store._conn() as c:c.execute("UPDATE rag_learning_jobs SET status='failed',error=? WHERE id=? AND token=? AND status='preparing'",(type(exc).__name__,job,token))
            raise

    def _publish(self,actor,job,token,pack,papers):
        now=self.watch.clock();cid=uuid.uuid4().hex;sid=uuid.uuid4().hex;rid=uuid.uuid4().hex
        # English author titles/abstracts cannot match Chinese display labels.
        # Keep these explainable keyword candidates separate from scholarly taxonomy.
        terms={'realm':['knowledge retrieval','dense passage retrieval'],
               'rag-original':['retrieval-augmented','retrieval augmented','fusion-in-decoder'],
               'hyde':['hypothetical document','query rewriting'],
               'ragas':['faithfulness','self-reflection','retrieval augmented generation assessment'],
               'knnlm':['nearest neighbor language models','nearest-neighbor language models'],
               'rest':['speculative decoding','retrieval-based speculative']}
        directions=[]
        for name in sorted({p['category'] for p in papers}):
            members=[p for p in papers if p['category']==name]
            keywords=list(dict.fromkeys(term for p in members for term in [*terms.get(p['id'],[]),p['title'][:80]]))
            directions.append(dict(name=name,terms=keywords[:12]))
        report_papers=[]
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM rag_learning_jobs WHERE id=? AND token=? AND status='preparing' AND lease>?",(job,token,now)).fetchone():raise Conflict('准备已失效，未发布计划')
            if c.execute('SELECT COUNT(*) FROM research_subscriptions WHERE owner=?',(actor,)).fetchone()[0]>=20 or c.execute('SELECT COUNT(*) FROM research_subscriptions').fetchone()[0]>=100:raise ValueError('研究订阅数量已达上限')
            c.execute('INSERT INTO research_subscriptions VALUES(?,?,?,?,?,?,?,0,?,1)',(sid,actor,'RAG全文实践','retrieval augmented generation',packed(directions),packed(['arxiv']),6,now))
            c.execute("INSERT INTO research_watch_jobs(subscription_id,source,next_due,status) VALUES(?,'arxiv',?,'paused')",(sid,now))
            found=[]
            for paper in papers:
                raw=dict(title=paper['title'],abstract=paper['abstract'],arxiv_id=paper['version'],source_id=paper['version'],authors=paper['authors'],
                    published=paper['date'],updated='',url=paper['metadata_url'],categories=[],references=[],references_available=False,doi='')
                item=self.watch._ingest(c,dict(owner=actor,subscription_id=sid,source='arxiv',directions=packed(directions)),raw)
                if not item:raise ValueError('实践文献身份重复，未发布部分计划')
                found.append(item);paper['research_paper_id']=item['paper_id']
                full=dict(source_url=paper['url'],sha256=fingerprint(paper['text']),field='content',text=paper['text'],basis='captured_public_pdf_normalized_text',
                          raw_sha256=paper['raw_sha256'],text_sha256=paper['text_sha256'],captured=paper['captured'])
                abstract=dict(source_url=paper['metadata_url'],sha256=fingerprint(paper['abstract']),field='abstract',text=paper['abstract'],basis='author_abstract',
                              raw_sha256=paper['metadata_sha256'],snapshot_id=item['snapshot_id'])
                sections=extracts(paper['text'],{k:v for k,v in full.items() if k not in ('text','field')},'content')
                snap=c.execute('SELECT * FROM research_watch_snapshots WHERE id=?',(item['snapshot_id'],)).fetchone()
                report_papers.append(dict(id=item['paper_id'],title=paper['title'],doi='',arxiv_id=paper['version'],url=paper['url'],source='arxiv',authors=paper['authors'],
                    categories=[],date=publication(paper['date']),groups=[paper['category']],sections=sections,sources=[abstract,full],full_text_bound=True,
                    missing=[LABELS[k] for k,v in sections.items() if not v],bibliography=source_records([snap],budget=dict(records=200,references=5000,relations=1000))))
            overview=self.synthesis.compose(rid,'RAG：十篇全文证据实践',now,sid,report_papers)
            overview['selection']=dict(mode='explicit',subscription_id=sid,paper_ids=[x['paper_id'] for x in found],documents={},external_full_text=dict(case_id=cid,refresh='explicit_recapture_required'))
            overview['boundary']+=' 本实践全文来自固定版本公开PDF的自动解析文本；版面/公式及学术语义仍待人工核对。'
            c.execute('INSERT INTO research_synthesis_reports VALUES(?,?,?,?,?)',(rid,actor,now,packed(overview),fingerprint(overview)))
            day=datetime.fromtimestamp(now,timezone(timedelta(hours=8))).date().isoformat()
            c.execute('INSERT OR IGNORE INTO research_watch_digests VALUES(?,?,?,?,?)',(uuid.uuid4().hex,actor,day,now,now))
            did=c.execute('SELECT id FROM research_watch_digests WHERE owner=? AND day=?',(actor,day)).fetchone()['id']
            for item in found:c.execute('INSERT INTO research_watch_digest_entries VALUES(?,?,?,?)',(did,sid,item['paper_id'],item['snapshot_id']))
            c.execute('INSERT INTO research_watch_notifications VALUES(?,?,?,?,?,?,0)',(uuid.uuid4().hex,actor,did,sid,len(found),now))
            value=dict(id=cid,created=now,version=VERSION,subscription_id=sid,overview_id=rid,overview_hash=fingerprint(overview),papers=papers,
                reading_paths=pack['paths'],overview=pack['overview'],prerequisites=pack['prerequisites'],survey_reference=pack['survey'],source_hashes=implementation_hashes(),
                teaching_graph=dict(nodes=[
                    dict(id='representation',title='检索表示',papers=['dpr'],explanation='先理解问题与段落如何映射到可比较的表示。'),
                    dict(id='memory',title='外部记忆',papers=['realm','retro','knnlm'],explanation='比较检索如何参与预训练、语言建模和分布组合。'),
                    dict(id='fusion',title='检索与生成',papers=['rag-original','fid'],explanation='观察文档条件化及多段落融合发生在什么位置。'),
                    dict(id='query',title='查询构造',papers=['hyde'],explanation='区分假设文档、编码器与真实检索证据。'),
                    dict(id='decision',title='检索决策',papers=['self-rag'],explanation='理解何时检索及如何检查生成内容。'),
                    dict(id='evaluation',title='证据评估',papers=['ragas'],explanation='把检索相关性、答案忠实性和任务效果分开检验。'),
                    dict(id='decoding',title='推理解码',papers=['rest'],explanation='观察检索如何参与草稿构造与推理加速。')],
                    edges=[dict(source=a,target=b,status='pending_teacher_review') for a,b in [('representation','fusion'),('memory','fusion'),('representation','query'),('fusion','decision'),('fusion','evaluation'),('fusion','decoding')]],
                    relation='assistant_designed_teaching_prerequisites_not_scholarly_lineage',teacher_verified=False),
                boundary='10篇固定代表文献的研究学习计划；订阅默认暂停，可在研究页显式启用6小时采集。阅读路径和问题由助手设计，非教师核准或领域全量结论。')
            c.execute('INSERT INTO rag_learning_cases VALUES(?,?,?,?,?)',(cid,actor,now,packed(value),fingerprint(value)))
            c.execute("UPDATE rag_learning_jobs SET status='completed',case_id=? WHERE id=? AND token=?",(cid,job,token))
        return cid

    def _case(self,actor,cid):
        with self.store._conn() as c:r=c.execute('SELECT * FROM rag_learning_cases WHERE id=? AND actor=?',(cid,actor)).fetchone()
        if not r:raise LookupError('实践计划不存在')
        v=json.loads(r['payload'])
        if fingerprint(v)!=r['hash']:raise ValueError('实践计划完整性校验失败')
        return v,r['hash']

    def get_case(self,actor,cid):
        value,h=self._case(actor,cid);value=dict(value,papers=[{k:v for k,v in p.items() if k not in ('text','page_spans')} for p in value['papers']])
        overview=self.synthesis.get(actor,value['overview_id'])
        if overview['hash']!=value['overview_hash']:raise Conflict('实践综述摘要不一致')
        preview=dict(id=overview['id'],hash=overview['hash'],coverage=overview['report']['coverage'],boundary=overview['report']['boundary'],
            groups=[dict(name=g['name'],sections={k:rows[:2] for k,rows in g['sections'].items()}) for g in overview['report']['groups']])
        with self.store._conn() as c:runs=[dict(id=r['id'],created=r['created'],hash=r['hash']) for r in c.execute('SELECT id,created,hash FROM rag_learning_runs WHERE actor=? AND case_id=? ORDER BY created DESC,id LIMIT 20',(actor,cid))]
        with self.store._conn() as c:total=c.execute('SELECT COUNT(*) FROM rag_learning_runs WHERE actor=? AND case_id=?',(actor,cid)).fetchone()[0]
        return dict(case=value,hash=h,runs=runs,runs_has_more=total>20,transfer_questions=TRANSFER,overview_preview=preview)

    def runs(self,actor,cid,page=1):
        self._case(actor,cid)
        if type(page) is not int or not 1<=page<=10000:raise ValueError('页码无效')
        with self.store._conn() as c:
            total=c.execute('SELECT COUNT(*) FROM rag_learning_runs WHERE actor=? AND case_id=?',(actor,cid)).fetchone()[0]
            rows=c.execute('SELECT id,created,hash FROM rag_learning_runs WHERE actor=? AND case_id=? ORDER BY created DESC,id LIMIT 20 OFFSET ?',(actor,cid,(page-1)*20)).fetchall()
        return dict(items=[dict(r) for r in rows],has_more=page*20<total,page=page,total=total)

    def page(self,actor,cid,pid,page):
        value,h=self._case(actor,cid);paper=next((p for p in value['papers'] if p['id']==pid),None)
        if not paper:raise LookupError('文献不在本计划')
        if type(page) is not int or not 1<=page<=len(paper['page_spans']):raise ValueError('页码超出已捕获PDF范围')
        start,end=paper['page_spans'][page-1]
        return dict(paper_id=pid,page=page,pages=len(paper['page_spans']),text=paper['text'][start:end],start=start,end=end,
            raw_sha256=paper['raw_sha256'],text_sha256=paper['text_sha256'],source_url=paper['url'],case_hash=h,
            boundary='PDF归一提取文本，非原始版面；数学和列顺序需回原PDF核对。')

    def run(self,actor,cid,data):
        if not isinstance(data,dict) or set(data)!={'request_id','case_hash','hypothesis','top_k'}:raise ValueError('实验字段不完整')
        request=self.request_id(data['request_id'])
        if not isinstance(data['hypothesis'],str) or not 10<=len(data['hypothesis'].strip())<=2000:raise ValueError('实验前预测需10–2000字符')
        case,h=self._case(actor,cid)
        source_hashes=implementation_hashes()
        if source_hashes!=IMPLEMENTATION_AT_LOAD:raise Conflict('服务源码已变化，请正常重启应用后再执行实验')
        if data['case_hash']!=h:raise Conflict('实践来源已变化，未执行')
        ih=fingerprint(dict(data,case_id=cid))
        with self.store._conn() as c:
            old=c.execute('SELECT id,input_hash FROM rag_learning_runs WHERE actor=? AND request_id=?',(actor,request)).fetchone()
            if old:
                if old['input_hash']!=ih:raise Conflict('请求编号已用于另一实验')
                return self.get_run(actor,old['id'])
        result=experiment(case['papers'],data['top_k']);rid=uuid.uuid4().hex;now=self.watch.clock()
        payload=dict(id=rid,case_id=cid,case_hash=h,created=now,hypothesis=data['hypothesis'].strip(),result=result,model_calls=0,
                     learning_effect_verified=False,source_version=VERSION,source_hashes=source_hashes)
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT id,input_hash FROM rag_learning_runs WHERE actor=? AND request_id=?',(actor,request)).fetchone()
            if implementation_hashes()!=source_hashes:raise Conflict('计算期间源码变化，未保存实验')
            if old:
                if old['input_hash']!=ih:raise Conflict('请求编号已用于另一实验')
                rid=old['id']
            else:
                if c.execute('SELECT COUNT(*) FROM rag_learning_runs WHERE actor=? AND case_id=?',(actor,cid)).fetchone()[0]>=200:raise ValueError('本计划实验已达200份上限')
                c.execute('INSERT INTO rag_learning_runs VALUES(?,?,?,?,?,?,?,?)',(rid,actor,cid,request,ih,now,packed(payload),fingerprint(payload)))
        return self.get_run(actor,rid)

    def get_run(self,actor,rid):
        with self.store._conn() as c:
            r=c.execute('SELECT * FROM rag_learning_runs WHERE id=? AND actor=?',(rid,actor)).fetchone()
            if not r:raise LookupError('实验不存在')
            value=json.loads(r['payload']);attempts=[]
            if fingerprint(value)!=r['hash']:raise ValueError('实验完整性校验失败')
            for a in c.execute('SELECT payload,hash FROM rag_learning_attempts WHERE run_id=? ORDER BY version',(rid,)):
                v=json.loads(a['payload'])
                if fingerprint(v)!=a['hash']:raise ValueError('练习完整性校验失败')
                attempts.append(v)
        return dict(run=value,hash=r['hash'],attempts=attempts,version=len(attempts),transfer_questions=TRANSFER)

    def submit(self,actor,rid,data):
        if not isinstance(data,dict) or set(data)!={'version','run_hash','answers','reflection'}:raise ValueError('迁移练习字段不完整')
        if type(data['version']) is not int or not 0<=data['version']<20:raise ValueError('练习版本无效或已达上限')
        if not isinstance(data['answers'],dict) or set(data['answers'])!={q['id'] for q in TRANSFER}:raise ValueError('请回答三道迁移题')
        if any(not isinstance(s,str) or not 10<=len(s.strip())<=3000 for s in [*data['answers'].values(),data['reflection']]):raise ValueError('各回答及反思需10–3000字符')
        run=self.get_run(actor,rid)
        if run['hash']!=data['run_hash']:raise Conflict('实验来源摘要冲突')
        ih=fingerprint(data)
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');count=c.execute('SELECT COUNT(*) FROM rag_learning_attempts WHERE run_id=?',(rid,)).fetchone()[0]
            if count!=data['version']:
                old=c.execute('SELECT input_hash FROM rag_learning_attempts WHERE run_id=? AND version=?',(rid,data['version']+1)).fetchone()
                if count==data['version']+1 and old['input_hash']==ih:return self.get_run(actor,rid)
                raise Conflict('练习版本已变化，旧回答保留')
            value=dict(data,version=count+1,created=self.watch.clock(),review_status='pending_teacher_review',teacher_verified=False,mastery_updated=False,learning_effect_verified=False)
            c.execute('INSERT INTO rag_learning_attempts VALUES(?,?,?,?,?)',(rid,count+1,ih,packed(value),fingerprint(value)))
        return self.get_run(actor,rid)

    def export(self,actor,rid):
        run=self.get_run(actor,rid);case,h=self._case(actor,run['run']['case_id'])
        if h!=run['run']['case_hash']:raise Conflict('实验与来源计划不一致')
        return dict(schema='clawos.research-learning-export.v1',case=case,case_hash=h,**run)

    def save_view(self,actor,rid,data):
        if not isinstance(data,dict) or set(data)!={'request_id','run_hash','state'}:raise ValueError('视图字段不完整')
        key=self.request_id(data['request_id']);run=self.get_run(actor,rid);state=data['state']
        if data['run_hash']!=run['hash']:raise Conflict('视图实验来源冲突')
        if not isinstance(state,dict) or set(state)!={'arm','question_id'} or type(state['arm']) is not int or state['arm'] not in (0,1) or state['question_id'] not in [q['id'] for q in run['run']['result']['questions']]:raise ValueError('观察位置不属于这份实验')
        ih=fingerprint(dict(data,run_id=rid))
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM rag_learning_views WHERE actor=? AND request_id=?',(actor,key)).fetchone()
            if old:
                if old['input_hash']!=ih:raise Conflict('请求编号已用于另一视图')
                if fingerprint(json.loads(old['payload']))!=old['hash']:raise ValueError('观察完整性校验失败')
                return json.loads(old['payload'])
            if c.execute('SELECT COUNT(*) FROM rag_learning_views WHERE actor=? AND run_id=?',(actor,rid)).fetchone()[0]>=200:raise ValueError('每份实验最多200个观察')
            value=dict(id=uuid.uuid4().hex,run_id=rid,run_hash=run['hash'],state=state,created=self.watch.clock(),visibility='owner_only')
            c.execute('INSERT INTO rag_learning_views VALUES(?,?,?,?,?,?,?)',(value['id'],actor,rid,key,ih,packed(value),fingerprint(value)))
        return value

    def view(self,actor,vid):
        with self.store._conn() as c:r=c.execute('SELECT * FROM rag_learning_views WHERE id=? AND actor=?',(vid,actor)).fetchone()
        if not r:raise LookupError('观察不存在')
        value=json.loads(r['payload'])
        if fingerprint(value)!=r['hash']:raise ValueError('观察完整性校验失败')
        if self.get_run(actor,value['run_id'])['hash']!=value['run_hash']:raise Conflict('观察的实验来源不一致')
        return value

    def course_history(self,actor):
        with self.store._conn() as c:rows=c.execute('SELECT id,case_id,created,payload FROM rag_learning_runs WHERE actor=? ORDER BY created DESC,id LIMIT 20',(actor,)).fetchall()
        items=[]
        for row in rows:
            run=self.get_run(actor,row['id']);items.append(dict(id=row['id'],case_id=row['case_id'],created=row['created'],reflections=run['version'],mastery_updated=False))
        return dict(items=items,boundary='最近20份真实文献检索实践与自述，不代表教师评分或学习收益。')

IMPLEMENTATION_AT_LOAD=implementation_hashes()
