"""Frozen review rounds, per-claim blind accounts, and explicit unresolved judgments."""
import json
import uuid
from services.research_watch import packed,fingerprint
from services.research_synthesis import ResearchSynthesis
from services.research_ai import ResearchAI,catalog,normalize,SECTIONS
from services.research_review_examples import candidate_suite
from services.research_claim_guard import VERSION as GUARD_VERSION

VERDICTS={'supported','contradicted','insufficient','needs_full_text'}
ISSUES={'quantity','unit','polarity','scope','population','causality','uncertainty','version','correction','time','comparison','citation','none'}
BOUNDARY='评审身份来自应用会话；账户不同不证明是真实独立专家。自评不计双评，参考候选标签不是专家金标准。未评、分歧及证据不足保持可见，不发布学术通过分数。'


class ResearchReview:
    def __init__(self,watch):
        self.watch,self.store=watch,watch.store
        self.synthesis=ResearchSynthesis(watch)
        with self.store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_review_rounds(id TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_review_assignments(round_id TEXT NOT NULL,actor TEXT NOT NULL,role TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(round_id,actor));
            CREATE TABLE IF NOT EXISTS research_review_votes(round_id TEXT NOT NULL,case_id TEXT NOT NULL,actor TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,PRIMARY KEY(round_id,case_id,actor));
            CREATE INDEX IF NOT EXISTS research_review_owner ON research_review_rounds(owner,created);
            ''')

    def create(self,owner,data):
        if not isinstance(data,dict) or set(data)-{'kind','report_id','job_id','reviewer_ids','adjudicator_id','limit','domain'}:raise ValueError('评审请求字段无效')
        kind=data.get('kind');reviewers=data.get('reviewer_ids',[]);judge=data.get('adjudicator_id','');limit=data.get('limit',20)
        if kind not in ('benchmark','report','ai') or type(limit) is not int or not 1<=limit<=40:raise ValueError('选择有效来源及1–40项评审预算')
        if not isinstance(reviewers,list) or len(reviewers) not in (0,2) or any(not isinstance(v,str) for v in reviewers) or not isinstance(judge,str):raise ValueError('可不分配独立评审；分配时需两名评审和一名仲裁的现有账户ID')
        actors=reviewers+([judge] if judge else [])
        if actors and (len(reviewers)!=2 or not judge or len(set(actors))!=3 or owner in actors):raise ValueError('两名评审和仲裁需三个不同的非创建者账户')
        source={};cases=[];domain=data.get('domain','未指定领域')
        if not isinstance(domain,str) or not 1<=len(domain)<=60:raise ValueError('领域名称无效')
        if kind=='benchmark':
            suite=candidate_suite();cases=suite['cases'][:limit];available=len(suite['cases']);source=dict(suite_version=suite['version'],suite_hash=fingerprint(suite),boundary=suite['boundary'])
            for case in cases:
                proposal={k:[] for k in SECTIONS}
                proposal['overview']=[dict(text=case['claim'],citations=[e['id'] for e in case['evidence']],kind='reported')]
                refs=[dict(e,paper_id=e['id']) for e in case['evidence']]
                kept,excluded=normalize(proposal,refs)
                case['mechanical_check']=dict(kept=bool(kept),reasons=[e['reason'] for e in excluded],semantic_entailment_verified=False,
                    guard_version=GUARD_VERSION,
                    boundary='只运行现有引用/数值/部分否定守卫；放行不代表语义成立，拟定标签仍待真人确认。')
        else:
            rid=data.get('report_id','');report=self.synthesis.get(owner,rid)
            source=dict(report_id=rid,report_hash=report['hash'])
            if kind=='ai':
                job=ResearchAI(self.watch).get(owner,data.get('job_id',''))
                if job['status']!='completed' or job['report_id']!=rid or job['report_hash']!=report['hash'] or not isinstance(job['result'],dict) or not job['result'].get('sections'):raise ValueError('需要属于该冻结综述的完整AI草稿')
                result=job['result'];refs={r['id']:r for r in result['references']};source['job_id']=job['id'];source['result_hash']=fingerprint(result)
                for section,claims in result['sections'].items():
                    for claim in claims:
                        cases.append(dict(id=claim['id'],domain=domain,claim=claim['text'],evidence=[dict(refs[cid]) for cid in claim['citations']],
                            tags=['citation'],origin='frozen_ai_job',section=section))
                for claim in result.get('review_queue',[]):
                    cases.append(dict(id=claim['id'],domain=domain,claim=claim['text'],evidence=[dict(refs[cid]) for cid in claim['evidence_ids']],
                        tags=['citation'],origin='withheld_ai_claim',section=claim['section'],withheld_reason=claim['reason'],boundary_audit=claim.get('boundary_audit')))
            else:
                refs,_=catalog(report['report'])
                cases=[dict(id='R'+str(i+1),domain=domain,claim=r['quote'],evidence=[r],tags=['citation'],origin='rule_extracted_quote') for i,r in enumerate(refs)]
            available=len(cases);cases=cases[:limit]
        if not cases:raise ValueError('没有可评审主张；先补证据或完成AI草稿')
        now=self.watch.clock();rid=uuid.uuid4().hex
        value=dict(id=rid,kind=kind,created=now,source=source,cases=cases,coverage=dict(available=available,selected=len(cases),omitted=available-len(cases)),rubric='claim-evidence-review.v1',boundary=BOUNDARY)
        if len(packed(value))>220000:raise ValueError('评审包超过22万字符，请缩小预算')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM research_review_rounds WHERE owner=? AND created>?',(owner,now-86400)).fetchone()[0]>=20:raise ValueError('每人每天最多20轮评审')
            for actor in actors:
                table=c.execute("SELECT 1 FROM sqlite_master WHERE name='collaboration_users'").fetchone()
                if not table or not c.execute('SELECT 1 FROM collaboration_users WHERE id=?',(actor,)).fetchone():raise ValueError('请填写已存在的协作账户ID；不会创建或发送邀请')
            c.execute('INSERT INTO research_review_rounds VALUES (?,?,?,?,?)',(rid,owner,now,packed(value),fingerprint(value)))
            for actor in reviewers:c.execute("INSERT INTO research_review_assignments VALUES (?,?,'reviewer',0)",(rid,actor))
            if judge:c.execute("INSERT INTO research_review_assignments VALUES (?,?,'adjudicator',0)",(rid,judge))
        return self.get(owner,rid)

    @staticmethod
    def load(c,actor,rid):
        row=c.execute('SELECT * FROM research_review_rounds WHERE id=?',(rid,)).fetchone()
        assignment=c.execute('SELECT role FROM research_review_assignments WHERE round_id=? AND actor=? AND revoked=0',(rid,actor)).fetchone()
        if not row or row['owner']!=actor and not assignment:raise LookupError('评审轮不存在或权限已撤销')
        payload=json.loads(row['payload'])
        if fingerprint(payload)!=row['hash']:raise ValueError('评审包完整性校验失败')
        return row,payload,'owner' if row['owner']==actor else assignment['role']

    @staticmethod
    def votes(c,rid):
        votes=[]
        for row in c.execute('SELECT * FROM research_review_votes WHERE round_id=? ORDER BY created,actor',(rid,)):
            value=json.loads(row['payload'])
            if fingerprint(value)!=row['hash']:raise ValueError('评审记录完整性校验失败')
            votes.append(dict(value,actor=row['actor'],case_id=row['case_id'],created=row['created']))
        return votes

    def list(self,actor):
        with self.store._conn() as c:
            rows=c.execute('''SELECT DISTINCT r.* FROM research_review_rounds r LEFT JOIN research_review_assignments a ON a.round_id=r.id AND a.actor=? AND a.revoked=0
                WHERE r.owner=? OR a.actor IS NOT NULL ORDER BY r.created DESC,r.id LIMIT 50''',(actor,actor)).fetchall()
            return dict(items=[dict(id=r['id'],created=r['created'],kind=json.loads(r['payload'])['kind'],owned=r['owner']==actor) for r in rows])

    def get(self,actor,rid):
        with self.store._conn() as c:
            row,payload,role=self.load(c,actor,rid);votes=self.votes(c,rid)
            active={r['actor']:r['role'] for r in c.execute('SELECT * FROM research_review_assignments WHERE round_id=? AND revoked=0',(rid,))}
        results=[];cases=[]
        for case in payload['cases']:
            peer=[v for v in votes if v['case_id']==case['id'] and active.get(v['actor'])=='reviewer']
            judge=next((v for v in votes if v['case_id']==case['id'] and active.get(v['actor'])=='adjudicator'),None)
            status='awaiting_two_reviews';verdict=None
            if len(peer)==2:
                if peer[0]['verdict']==peer[1]['verdict']:status='account_agreement';verdict=peer[0]['verdict']
                elif judge:status='account_adjudicated';verdict=judge['verdict']
                else:status='needs_adjudication'
            own=next((v for v in votes if v['case_id']==case['id'] and v['actor']==actor),None)
            # Once submitted, an assessment is immutable. No pre-submit peer hints.
            reveal=role=='owner' or role=='adjudicator' and len(peer)==2 or own is not None
            view=dict(case)
            if role!='owner':
                for private in ('curator_proposal','mechanical_check','boundary_audit','withheld_reason'):view.pop(private,None)
                if view['origin']=='withheld_ai_claim':view['origin']='frozen_ai_job'
            view.update(own_vote=own,peer_votes=peer if reveal else [],adjudication=judge if reveal else None,status=status if reveal else 'blind_review',verdict=verdict if reveal else None)
            cases.append(view);results.append(dict(case_id=case['id'],domain=case['domain'],status=status,verdict=verdict,paired=len(peer)==2,agreement=len(peer)==2 and peer[0]['verdict']==peer[1]['verdict']))
        def metrics(items):
            paired=sum(v['paired'] for v in items);resolved=sum(v['verdict'] is not None for v in items)
            return dict(total=len(items),double_reviewed=paired,account_resolved=resolved,pending=len(items)-resolved,agreements=sum(v['agreement'] for v in items),unresolved_conflicts=sum(v['status']=='needs_adjudication' for v in items),
                agreement_rate=sum(v['agreement'] for v in items)/paired if paired else None,supported=sum(v['verdict']=='supported' for v in items),human_independence_verified=False)
        summary=metrics(results) if role=='owner' else None
        domains={d:metrics([v for v in results if v['domain']==d]) for d in sorted({v['domain'] for v in results})} if role=='owner' else {}
        # Do not expose another owner's private report/job IDs to assigned reviewers.
        source=payload['source'] if role=='owner' else dict(boundary='只授权本评审包中的主张和摘录；不授予原订阅、报告或本地全文读取权限。')
        return dict(id=rid,kind=payload['kind'],created=payload['created'],role=role,source=source,cases=cases,coverage=payload['coverage'],rubric=payload['rubric'],summary=summary,domains=domains,
            assignments=[dict(actor=k,role=v) for k,v in active.items()] if role=='owner' else [],human_validation_complete=False,boundary=BOUNDARY)

    def vote(self,actor,rid,cid,data):
        if not isinstance(data,dict) or set(data)!={'verdict','reason','issues','evidence_ids','human_confirmed'}:raise ValueError('评审字段无效')
        if data['human_confirmed'] is not True:raise ValueError('请确认由你本人阅读证据后提交；自我声明不认证真实独立性')
        if data['verdict'] not in VERDICTS or not isinstance(data['reason'],str) or not 12<=len(data['reason'].strip())<=1200:raise ValueError('请选择判断并填写12–1200字的证据理由')
        if not isinstance(data['issues'],list) or not 1<=len(data['issues'])<=8 or any(i not in ISSUES for i in data['issues']):raise ValueError('请选择有效核对项')
        ids=data['evidence_ids']
        if not isinstance(ids,list) or len(ids)>6 or any(not isinstance(i,str) for i in ids):raise ValueError('依据ID无效')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');_,payload,role=self.load(c,actor,rid)
            self.votes(c,rid)  # Reject corrupted prior assessments before any new write.
            case=next((v for v in payload['cases'] if v['id']==cid),None)
            if not case:raise LookupError('主张不存在')
            if any(i not in {e['id'] for e in case['evidence']} for i in ids) or data['verdict'] in ('supported','contradicted') and not ids:raise ValueError('支持/反驳需选择该主张的实际依据，不能借用其他主张的引用')
            if role=='adjudicator':
                peer=c.execute("SELECT v.* FROM research_review_votes v JOIN research_review_assignments a ON a.round_id=v.round_id AND a.actor=v.actor WHERE v.round_id=? AND v.case_id=? AND a.role='reviewer' AND a.revoked=0",(rid,cid)).fetchall()
                if len(peer)!=2 or len({json.loads(v['payload'])['verdict'] for v in peer})!=2:raise ValueError('仲裁仅在两名评审已提交且判断分歧时开放')
            value=dict(verdict=data['verdict'],reason=data['reason'].strip(),issues=list(dict.fromkeys(data['issues'])),evidence_ids=list(dict.fromkeys(ids)),human_confirmed=True,case_hash=fingerprint(case),rubric=payload['rubric'],self_review=role=='owner')
            old=c.execute('SELECT payload FROM research_review_votes WHERE round_id=? AND case_id=? AND actor=?',(rid,cid,actor)).fetchone()
            if old:
                if json.loads(old['payload'])!=value:raise ValueError('该判断已冻结，不能在看到同伴结果后修改；需要更改请新建评审轮')
            else:c.execute('INSERT INTO research_review_votes VALUES (?,?,?,?,?,?)',(rid,cid,actor,self.watch.clock(),packed(value),fingerprint(value)))
        return self.get(actor,rid)

    def revoke(self,owner,rid,actor):
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');_,_,role=self.load(c,owner,rid)
            if role!='owner':raise PermissionError('仅创建者可以撤销本评审包权限')
            if not c.execute('UPDATE research_review_assignments SET revoked=1 WHERE round_id=? AND actor=? AND revoked=0',(rid,actor)).rowcount:raise LookupError('有效评审分配不存在')
        return self.get(owner,rid)

    def export(self,actor,rid):
        value=self.get(actor,rid)
        if value['role']!='owner':raise PermissionError('评审轮导出仅限创建者，防止盲评答案泄露')
        def literal(text):
            out=str(text)
            for a,b in [('&','&amp;'),('<','&lt;'),('>','&gt;'),('[','\\['),(']','\\]'),('*','\\*'),('_','\\_'),('`','\\`'),('#','\\#')]:out=out.replace(a,b)
            return out
        lines=['# 文献主张评审记录','',BOUNDARY,'',value['rubric'],'',json.dumps(value['summary'],ensure_ascii=False),'']
        for case in value['cases']:
            lines+=['## '+case['id']+' · '+literal(case['domain']),'',literal(case['claim']),'','状态：'+case['status'],'']
            for ref in case['evidence']:lines+=['- '+literal(ref['title'])+' / '+literal(ref.get('url',ref.get('evidence',{}).get('source_url',''))),'  '+literal(ref['quote'])]
            for vote in ([case['own_vote']] if case['own_vote'] else [])+case['peer_votes']+([case['adjudication']] if case['adjudication'] else []):
                lines+=['- '+literal(vote['actor'])+' / '+vote['verdict']+(' / 自评，不计双评' if vote['self_review'] else ''),'  '+literal(vote['reason'])]
        return dict(data=value,markdown='\n'.join(lines),boundary=BOUNDARY)
