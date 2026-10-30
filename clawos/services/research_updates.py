"""Versioned evidence deltas and transactional, opt-in overview notifications."""
import json
import uuid

from services.research_watch import fingerprint,packed
from services.research_synthesis import ResearchSynthesis

BOUNDARY='仅比较两份冻结报告的已采集证据。新增摘录是作者原文，不自动成立为新结论；当前范围未包含不表示撤稿或反证。旧AI正文和人工复核不迁移，新版本需重新复核。'


def identity_keys(p):
    keys={(k,p[k]) for k in ('doi','arxiv_id') if p.get(k)}
    return keys or {('id',p['id'])}


def paper_ref(p,with_evidence=False):
    return dict(paper_id=p['id'],title=p['title'],doi=p.get('doi',''),arxiv_id=p.get('arxiv_id',''),
        authors=p.get('authors',[]),categories=p.get('categories',[]),
        date=p['date'],groups=p['groups'],sections=p['sections'] if with_evidence else {},sources=[{k:v for k,v in s.items() if k!='text'} for s in p['sources']])


def evidence_delta(before,after):
    old={p['id']:p for p in before['papers']};new={p['id']:p for p in after['papers']};pairs=[];used=set()
    for oid,p in old.items():
        if oid in new:pairs.append((p,new[oid]));used.add(oid)
    for oid,p in old.items():
        if oid in new:continue
        matches=[n for n in new.values() if n['id'] not in used and (n['id']==oid or identity_keys(n)&identity_keys(p))
            and not (n.get('doi') and p.get('doi') and n['doi']!=p['doi'])]
        if len(matches)==1:pairs.append((p,matches[0]));used.add(matches[0]['id'])
    matched={p['id'] for p,_ in pairs}
    added=[paper_ref(p,True) for p in new.values() if p['id'] not in used]
    merged=[];removed=[]
    for p in old.values():
        if p['id'] in matched:continue
        candidates=[n for n in new.values() if identity_keys(n)&identity_keys(p) and not(p.get('doi') and n.get('doi') and p['doi']!=n['doi'])]
        if len(candidates)==1:merged.append(dict(before=paper_ref(p),after=paper_ref(candidates[0]),boundary='稳定标识归并，原版本仍保留；不是论文消失或撤稿。'))
        else:removed.append(paper_ref(p,True))
    changed=[]
    for left,right in pairs:
        fields=[k for k in ('title','doi','arxiv_id','date','groups','authors','categories') if left.get(k)!=right.get(k)]
        sections={}
        for key in right['sections']:
            a={v['text']:v for v in left['sections'].get(key,[])};b={v['text']:v for v in right['sections'][key]}
            sections[key]=dict(added=[b[t] for t in sorted(b.keys()-a.keys())],removed=[a[t] for t in sorted(a.keys()-b.keys())])
        def texts(p):return [(s.get('basis'),s.get('document_id'),s.get('citation'),s['text']) for s in p['sources']]
        text_changed=texts(left)!=texts(right)
        def bibliography(p):
            return sorted([fingerprint({k:v for k,v in r.items() if k not in ('snapshot_id','sha256','captured','updated','arxiv_version_field')}) for r in p.get('bibliography',{}).get('records',[])])
        bibliography_changed=bibliography(left)!=bibliography(right)
        if fields or text_changed or bibliography_changed:
            changed.append(dict(before=paper_ref(left),after=paper_ref(right),fields=fields,text_changed=text_changed,
                bibliography_changed=bibliography_changed,sections=sections))
    def edges(r):
        graph=r.get('bibliography_graph',{});nodes={n['id']:n for n in graph.get('nodes',[])}
        def label(key):
            n=nodes.get(key,{})
            return n.get('title',key)+(' · v'+str(n['version']) if n.get('version') else '')
        return {(e['source'],e['target'],e['kind']):dict(e,source_label=label(e['source']),target_label=label(e['target'])) for e in graph.get('edges',[])}
    a,b=edges(before),edges(after)
    relations=dict(added=[b[k] for k in sorted(b.keys()-a.keys())],removed=[a[k] for k in sorted(a.keys()-b.keys())])
    coverage_before=before.get('bibliography_graph',{}).get('coverage',{});coverage_after=after.get('bibliography_graph',{}).get('coverage',{})
    counts=dict(added_papers=len(added),removed_papers=len(removed),merged_papers=len(merged),changed_papers=len(changed),added_relations=len(relations['added']),removed_relations=len(relations['removed']),
        added_excerpts=sum(len(s['added']) for p in changed for s in p['sections'].values())+sum(len(s) for p in added for s in p['sections'].values()),
        removed_excerpts=sum(len(s['removed']) for p in changed for s in p['sections'].values())+sum(len(s) for p in removed for s in p['sections'].values()))
    return dict(changed=any(counts.values()) or coverage_before!=coverage_after,counts=counts,added=added,removed=removed,merged=merged,papers=changed,relations=relations,
        coverage_before=coverage_before,coverage_after=coverage_after,boundary=BOUNDARY)


class ResearchUpdates:
    def __init__(self,watch):
        self.watch,self.store=watch,watch.store
        self.synthesis=ResearchSynthesis(watch)
        with self.store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_synthesis_tracks(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,root_id TEXT NOT NULL,head_id TEXT NOT NULL,
                enabled INTEGER NOT NULL,interval_hours INTEGER NOT NULL,next_due REAL NOT NULL,checked REAL NOT NULL,
                last_error TEXT NOT NULL,version INTEGER NOT NULL,UNIQUE(owner,root_id));
            CREATE TABLE IF NOT EXISTS research_synthesis_updates(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,track_id TEXT NOT NULL,base_id TEXT NOT NULL,report_id TEXT NOT NULL,
                created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,UNIQUE(track_id,base_id));
            CREATE TABLE IF NOT EXISTS research_synthesis_update_notifications(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,update_id TEXT NOT NULL UNIQUE,created REAL NOT NULL,read_at REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS research_synthesis_due ON research_synthesis_tracks(enabled,next_due);
            CREATE INDEX IF NOT EXISTS research_synthesis_history ON research_synthesis_updates(track_id,created);
            CREATE INDEX IF NOT EXISTS research_synthesis_notice_owner ON research_synthesis_update_notifications(owner,created);
            ''')

    @staticmethod
    def report(c,owner,rid):
        r=c.execute('SELECT * FROM research_synthesis_reports WHERE id=? AND owner=?',(rid,owner)).fetchone()
        if not r:raise LookupError('综述不存在')
        value=json.loads(r['payload'])
        if fingerprint(value)!=r['hash']:raise ValueError('综述完整性校验失败')
        return value

    @staticmethod
    def track(c,owner,rid):
        return c.execute('''SELECT t.* FROM research_synthesis_tracks t WHERE t.owner=? AND
            (t.root_id=? OR t.head_id=? OR EXISTS(SELECT 1 FROM research_synthesis_updates u WHERE u.track_id=t.id AND u.report_id=?))''',(owner,rid,rid,rid)).fetchone()

    def status(self,owner,rid):
        with self.store._conn() as c:
            self.report(c,owner,rid);track=self.track(c,owner,rid)
            updates=[] if not track else [dict(id=r['id'],base_id=r['base_id'],report_id=r['report_id'],created=r['created']) for r in c.execute('SELECT * FROM research_synthesis_updates WHERE track_id=? ORDER BY created DESC,id LIMIT 50',(track['id'],))]
            def adjacent(column):
                r=None if not track else c.execute(f'SELECT id,base_id,report_id FROM research_synthesis_updates WHERE track_id=? AND {column}=?',(track['id'],rid)).fetchone()
                return dict(r) if r else None
            previous,next_update=adjacent('report_id'),adjacent('base_id')
        return dict(track=dict(track) if track else None,updates=updates,previous=previous,next=next_update,boundary=BOUNDARY)

    def _ensure(self,c,owner,rid,version):
        if type(version) is not int or version<0:raise ValueError('更新版本无效')
        self.report(c,owner,rid);track=self.track(c,owner,rid)
        if track:
            if track['version']!=version:raise ValueError('跟踪版本已变化，请刷新后重试')
            if track['head_id']!=rid:raise ValueError('请选择此更新链的最新综述后操作')
            return track
        if version!=0:raise ValueError('跟踪版本无效')
        if c.execute('SELECT COUNT(*) FROM research_synthesis_tracks WHERE owner=?',(owner,)).fetchone()[0]>=20 or c.execute('SELECT COUNT(*) FROM research_synthesis_tracks').fetchone()[0]>=100:raise ValueError('综述更新跟踪达到上限（每人20/全站100）')
        tid=uuid.uuid4().hex
        c.execute('INSERT INTO research_synthesis_tracks VALUES (?,?,?,?,0,6,0,0,\'\',0)',(tid,owner,rid,rid))
        return c.execute('SELECT * FROM research_synthesis_tracks WHERE id=?',(tid,)).fetchone()

    def configure(self,owner,rid,data):
        if not isinstance(data,dict) or set(data)!={'enabled','interval_hours','version'} or type(data['enabled']) is not bool or type(data['interval_hours']) is not int or data['interval_hours'] not in (6,12,24,48,168):raise ValueError('请选择有效自动检查开关和间隔')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');t=self._ensure(c,owner,rid,data['version'])
            c.execute('UPDATE research_synthesis_tracks SET enabled=?,interval_hours=?,next_due=?,last_error=\'\',version=version+1 WHERE id=?',
                (int(data['enabled']),data['interval_hours'],self.watch.clock()+data['interval_hours']*3600,t['id']))
        return self.status(owner,rid)

    def _request(self,c,owner,base):
        selection=base.get('selection') or dict(mode='explicit',paper_ids=[p['id'] for p in base['papers']],subscription_id=base.get('subscription_id',''),documents={})
        ids=[];mapping={}
        for p in base['papers']:
            if c.execute('SELECT 1 FROM research_watch_papers WHERE id=? AND owner=?',(p['id'],owner)).fetchone():mapping[p['id']]=p['id'];continue
            found=set()
            for kind in ('doi','arxiv_id'):
                if p.get(kind):found.update(r[0] for r in c.execute('SELECT paper_id FROM research_watch_aliases WHERE owner=? AND kind=? AND value=?',(owner,kind,p[kind])))
            if len(found)!=1:raise ValueError('原文献身份无法唯一恢复，请新建综述明确范围')
            mapping[p['id']]=next(iter(found))
        if selection['mode']=='explicit':ids=list(dict.fromkeys(mapping[p] for p in selection['paper_ids']))
        bindings=selection.get('documents',{})
        if not bindings:
            bindings={p['id']:s['document_id'] for p in base['papers'] for s in p['sources'] if s.get('document_id')}
        return dict(title=base['title'],subscription_id=selection.get('subscription_id',''),paper_ids=ids,documents={mapping[p]:v for p,v in bindings.items()})

    def _check(self,c,t):
        owner=t['owner'];now=self.watch.clock();base=self.report(c,owner,t['head_id'])
        candidate=self.synthesis.create(owner,self._request(c,owner,base),_conn=c)
        delta=evidence_delta(base,candidate['report'])
        update=None
        if delta['changed']:
            generation=c.execute('SELECT COUNT(*) FROM research_synthesis_updates WHERE track_id=?',(t['id'],)).fetchone()[0]+2
            candidate['report']['lineage']=dict(track_id=t['id'],root_report_id=t['root_id'],parent_report_id=t['head_id'],generation=generation)
            c.execute('UPDATE research_synthesis_reports SET payload=?,hash=? WHERE id=?',(packed(candidate['report']),fingerprint(candidate['report']),candidate['id']))
            uid=uuid.uuid4().hex
            value=dict(id=uid,track_id=t['id'],base_id=base['id'],report_id=candidate['id'],created=now,delta=delta)
            c.execute('INSERT INTO research_synthesis_updates VALUES (?,?,?,?,?,?,?,?)',(uid,owner,t['id'],base['id'],candidate['id'],now,packed(value),fingerprint(value)))
            c.execute('INSERT INTO research_synthesis_update_notifications VALUES (?,?,?,?,0)',(uuid.uuid4().hex,owner,uid,now))
            update=value
        else:c.execute('DELETE FROM research_synthesis_reports WHERE id=?',(candidate['id'],))
        c.execute('UPDATE research_synthesis_tracks SET head_id=?,checked=?,next_due=?,last_error=\'\',version=version+1 WHERE id=?',
            (candidate['id'] if update else t['head_id'],now,now+t['interval_hours']*3600,t['id']))
        return dict(changed=bool(update),update=update,head_id=candidate['id'] if update else t['head_id'],boundary=BOUNDARY)

    def check(self,owner,rid,data):
        if not isinstance(data,dict) or set(data)!={'version'}:raise ValueError('更新请求字段无效')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE');t=self._ensure(c,owner,rid,data['version'])
            if t['checked'] and self.watch.clock()-t['checked']<60:raise ValueError('每条综述链至少间隔60秒检查')
            result=self._check(c,t)
        return result

    def tick(self,limit=2):
        results=[]
        for _ in range(max(1,min(limit,2))):
            with self.store._conn() as c:
                c.execute('BEGIN IMMEDIATE')
                t=c.execute('SELECT * FROM research_synthesis_tracks WHERE enabled=1 AND next_due<=? ORDER BY next_due,id LIMIT 1',(self.watch.clock(),)).fetchone()
                if not t:break
                # Savepoint preserves the head/outbox on failed generation.
                c.execute('SAVEPOINT update_check')
                try:results.append(self._check(c,t));c.execute('RELEASE update_check')
                except Exception as exc:
                    c.execute('ROLLBACK TO update_check');c.execute('RELEASE update_check')
                    c.execute('UPDATE research_synthesis_tracks SET next_due=?,last_error=?,version=version+1 WHERE id=?',(self.watch.clock()+900,type(exc).__name__,t['id']))
                    results.append(dict(error=type(exc).__name__))
        return results

    def get(self,owner,uid):
        with self.store._conn() as c:
            r=c.execute('SELECT * FROM research_synthesis_updates WHERE id=? AND owner=?',(uid,owner)).fetchone()
            if not r:raise LookupError('更新记录不存在')
            value=json.loads(r['payload'])
            if fingerprint(value)!=r['hash']:raise ValueError('增量报告完整性校验失败')
            self.report(c,owner,value['base_id']);self.report(c,owner,value['report_id'])
            return value

    def notifications(self,owner):
        with self.store._conn() as c:
            rows=[dict(r) for r in c.execute('''SELECT n.*,u.base_id,u.report_id,p.payload AS report FROM research_synthesis_update_notifications n
                JOIN research_synthesis_updates u ON u.id=n.update_id JOIN research_synthesis_reports p ON p.id=u.report_id
                WHERE n.owner=? ORDER BY n.created DESC,n.id LIMIT 50''',(owner,))]
            for r in rows:r['title']=json.loads(r.pop('report'))['title']
            unread=c.execute('SELECT COUNT(*) FROM research_synthesis_update_notifications WHERE owner=? AND read_at=0',(owner,)).fetchone()[0]
        return dict(items=rows,unread=unread)

    def read(self,owner,nid):
        with self.store._conn() as c:
            if not c.execute('UPDATE research_synthesis_update_notifications SET read_at=? WHERE owner=? AND id=?',(self.watch.clock(),owner,nid)).rowcount:raise LookupError('通知不存在')
        return dict(read=True)

    def export(self,owner,uid):
        value=self.get(owner,uid);delta=value['delta']
        def literal(text):
            value=str(text)
            for a,b in [('&','&amp;'),('<','&lt;'),('>','&gt;'),('[','\\['),(']','\\]'),('*','\\*'),('_','\\_'),('`','\\`'),('#','\\#')]:value=value.replace(a,b)
            return value
        lines=['# 综述证据更新','',BOUNDARY,'','基线：'+value['base_id'],'新版本：'+value['report_id'],'','计数：'+json.dumps(delta['counts'],ensure_ascii=False),'']
        def claims(items):
            for claim in items:
                e=claim['evidence'];lines.extend(['- '+literal(claim['text']),'  依据：'+e.get('snapshot_id',e.get('citation',''))+' / '+e['field']+f"[{e['start']}:{e['end']}] / SHA256 "+e['sha256']])
        for key,label in [('added','新增论文'),('removed','当前范围未包含的原论文')]:
            lines+=['## '+label,'']
            for p in delta[key]:
                lines+=['### '+literal(p['title']),'ID：'+p['paper_id']]
                for kind,items in p['sections'].items():
                    if items:lines+=['依据类型：'+kind];claims(items)
        for p in delta['papers']:
            lines+=['## 变化：'+literal(p['after']['title']),'元数据字段：'+', '.join(p['fields'])]
            for kind,section in p['sections'].items():
                for key,label in [('added','新版本新增摘录'),('removed','原版本摘录（本版未提取）')]:
                    if section[key]:lines+=['### '+label+' / '+kind];claims(section[key])
        for p in delta.get('merged',[]):lines+=['## 稳定标识归并',literal(p['before']['title'])+' → '+literal(p['after']['title']),p['boundary']]
        for key,label in [('added','新增来源关系'),('removed','本版未包含的原来源关系')]:
            lines+=['## '+label,'']
            for e in delta['relations'][key]:
                lines+=['- '+literal(e['source']+' → '+e['target'])+' / '+e['kind']]
                for ref in e['evidence']:lines+=['  来源：'+ref['snapshot_id']+' / '+ref['field']+' / SHA256 '+ref['sha256']]
        lines+=['','覆盖变化：'+json.dumps(dict(before=delta['coverage_before'],after=delta['coverage_after']),ensure_ascii=False)]
        return dict(data=value,markdown='\n'.join(lines))
