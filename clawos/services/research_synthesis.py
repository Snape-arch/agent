"""Frozen, evidence-led research overviews. Similarity is never lineage proof."""
import json
import re
import uuid
from datetime import date

from services.research_watch import doi, fingerprint, normalized, packed


CUES = {
    'problem': r'\b(problem|challenge|aim|investigate|study|address)\b|问题|挑战|研究目标',
    'method': r'\b(propose|present|introduce|method|framework|algorithm|approach)\b|提出|方法|框架|算法',
    'evidence': r'\b(experiment|evaluate|dataset|benchmark|baseline|participants)\b|实验|评测|数据集|样本',
    'finding': r'\b(results?|find|show|improv\w*|outperform\w*|achiev\w*)\b|结果|发现|提升|优于',
    'limitation': r'\b(limit\w*|however|cannot|fail\w*|future work)\b|局限|限制|不足|未能',
}
LABELS = dict(problem='研究问题', method='方法路线', evidence='评测依据', finding='作者报告的发现', limitation='局限与缺口')
RELATIONS = {'related': '相关工作', 'compares': '比较', 'extends': '扩展', 'contradicts': '结论冲突'}


def extracts(text, reference, field):
    found = {key: [] for key in CUES}
    # Preserve exact source offsets, including decimals and original whitespace.
    for match in re.finditer(r'[^\n。！？!?]+[。！？!?]?|[^\n]+', text):
        fragment = match.group()
        for sentence in re.finditer(r'.+?(?:\.(?=\s+[A-Z]|$)|$)', fragment):
            quote = sentence.group().strip()
            if not 12 <= len(quote) <= 1200:
                continue
            start = match.start() + sentence.start() + len(sentence.group()) - len(sentence.group().lstrip())
            for key, pattern in CUES.items():
                if len(found[key]) < 2 and re.search(pattern, quote, re.I):
                    found[key].append(dict(text=quote, evidence=dict(reference, field=field, start=start, end=start+len(quote), quote=quote)))
    return found


def publication(value):
    """Partial publication dates remain partial. No synthetic January 1 dates."""
    value = str(value or '')
    match = re.match(r'^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?(?:T.*)?$', value)
    if not match:
        return dict(value='', precision='unknown', sort='9999')
    year, month, day = match.groups()
    try:
        date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return dict(value='', precision='unknown', sort='9999')
    actual = '-'.join(v for v in (year, month, day) if v)
    return dict(value=actual, precision='day' if day else 'month' if month else 'year', sort=actual)


class ResearchSynthesis:
    def __init__(self, watch):
        self.watch, self.store = watch, watch.store
        with self.store._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_synthesis_reports(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_synthesis_reviews(
                report_id TEXT NOT NULL,edge_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,
                PRIMARY KEY(report_id,edge_id));
            ''')

    def create(self, owner, data):
        if not isinstance(data, dict) or set(data)-{'subscription_id', 'paper_ids', 'title', 'documents'}:
            raise ValueError('综述请求字段无效')
        sid, ids = data.get('subscription_id', ''), data.get('paper_ids', [])
        title = data.get('title', '研究方向综述')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError('标题应为1–120字')
        if not isinstance(sid, str) or not isinstance(ids, list) or len(ids)>100 or any(not isinstance(x, str) for x in ids):
            raise ValueError('每份综述最多选择100篇文献')
        bindings = data.get('documents', {})
        if not isinstance(bindings, dict) or len(bindings)>5 or any(not isinstance(k, str) or type(v) is not int or v<=0 for k,v in bindings.items()):
            raise ValueError('每份综述最多绑定5份已解析全文，格式为论文ID与文档ID')
        if bindings and owner!='local-user':
            raise PermissionError('全局本地PDF仅允许本机所有者显式绑定；协作账户不获得其读取权限')
        with self.store._conn() as c:
            if sid:
                self.watch.owned(c, owner, sid)
            candidates = c.execute('''SELECT DISTINCT p.id FROM research_watch_papers p
                JOIN research_watch_discoveries d ON d.paper_id=p.id JOIN research_subscriptions s ON s.id=d.subscription_id
                WHERE p.owner=? AND s.owner=? AND (?='' OR s.id=?) ORDER BY p.id LIMIT 101''', (owner,owner,sid,sid)).fetchall()
            if ids:
                # Explicit IDs may be outside the first 101 matching rows, but must belong to the selection scope.
                chosen=[]
                for pid in dict.fromkeys(ids):
                    if not c.execute('''SELECT 1 FROM research_watch_discoveries d JOIN research_subscriptions s ON s.id=d.subscription_id
                        WHERE d.paper_id=? AND s.owner=? AND (?='' OR s.id=?)''', (pid,owner,sid,sid)).fetchone():
                        raise LookupError('文献不在你的所选研究范围内')
                    chosen.append(pid)
            else:
                if len(candidates)>100:
                    raise ValueError('文献超过100篇，请显式勾选或缩小订阅范围；不会静默截断')
                chosen=[r['id'] for r in candidates]
            if not chosen:
                raise ValueError('请先采集文献或选择已有论文')
            if set(bindings)-set(chosen):
                raise ValueError('全文绑定必须属于本次选择')
            papers=[]
            for pid in chosen:
                rows=c.execute('''SELECT * FROM research_watch_snapshots WHERE owner=? AND paper_id=? ORDER BY captured DESC,id''',(owner,pid)).fetchall()
                best=max(rows,key=lambda r:(bool(json.loads(r['payload']).get('abstract')),r['captured']))
                p=json.loads(best['payload'])
                if fingerprint(p)!=best['hash']:
                    raise ValueError('来源快照完整性校验失败，拒绝生成综述')
                classes=c.execute('''SELECT d.classification FROM research_watch_discoveries d JOIN research_subscriptions s ON s.id=d.subscription_id
                                     WHERE s.owner=? AND d.paper_id=? AND (?='' OR s.id=?)''',(owner,pid,sid,sid)).fetchall()
                groups=sorted({v['name'] for r in classes for v in json.loads(r['classification'])})
                reference=dict(snapshot_id=best['id'],sha256=best['hash'],source_url=p['url'],basis='abstract')
                sections=extracts(p.get('abstract',''),reference,'abstract')
                evidence_sources=[dict(reference,field='abstract',text=p.get('abstract',''))]
                full=False
                if pid in bindings:
                    did=bindings[pid]; document=self.store.get_document(did)
                    if not document:
                        raise LookupError('全文文档不存在')
                    chunks=self.store.get_document_chunks(did,201)
                    if len(chunks)>200 or sum(len(ch['content']) for ch in chunks)>200000:
                        raise ValueError('全文超过200片段或20万字符，请先缩小文档；不会静默截断')
                    if not chunks:
                        raise ValueError('全文尚无解析片段')
                    metadata=document.get('metadata') or {}
                    doi_match=bool(p['doi'] and isinstance(metadata,dict) and doi(metadata.get('doi'))==p['doi'])
                    if not doi_match and normalized(document['title'])!=normalized(p['title']):
                        raise ValueError('全文DOI或文档标题与论文不匹配，拒绝绑定')
                    for chunk in chunks:
                        content=chunk['content']
                        ref=dict(document_id=did,chunk_id=chunk['id'],citation=chunk['citation'],sha256=fingerprint(content),basis='parsed_full_text')
                        extra=extracts(content,ref,'content')
                        evidence_sources.append(dict(ref,field='content',text=content))
                        for k in sections:
                            sections[k]=(sections[k]+extra[k])[:6]
                    full=True
                papers.append(dict(id=pid,title=p['title'],doi=p['doi'],arxiv_id=p['arxiv_id'],url=p['url'],source=p['source'],
                    date=publication(p['published']),groups=groups,sections=sections,sources=evidence_sources,
                    full_text_bound=full,missing=[LABELS[k] for k,v in sections.items() if not v],
                    references=p.get('references',[])))
            created=self.watch.clock()
            rid=uuid.uuid4().hex
            report=self.compose(rid,title.strip(),created,sid,papers)
            c.execute('INSERT INTO research_synthesis_reports VALUES (?,?,?,?,?)',(rid,owner,created,packed(report),fingerprint(report)))
        return dict(id=rid,report=report,hash=fingerprint(report))

    @staticmethod
    def compose(rid,title,created,sid,papers):
        timeline=[dict(paper_id=p['id'],title=p['title'],date=p['date'],groups=p['groups']) for p in sorted(papers,key=lambda p:(p['date']['sort'],p['id']))]
        edges=[]
        for i,left in enumerate(papers):
            for right in papers[i+1:]:
                shared=sorted(set(left['groups'])&set(right['groups'])-{'待归类'})
                if shared and len(edges)<200:
                    edges.append(dict(id=uuid.uuid4().hex,source=left['id'],target=right['id'],kind='related',status='proposed',
                        reason='同属方向：'+'、'.join(shared),basis='classification_overlap',
                        boundary='分类重叠仅提示相关性，不证明引用、继承、优劣或冲突。'))
        groups=[]
        for name in sorted({n for p in papers for n in p['groups']}):
            members=[p for p in papers if name in p['groups']]
            groups.append(dict(name=name,paper_ids=[p['id'] for p in members],
                sections={k:[dict(paper_id=p['id'],**claim) for p in members for claim in p['sections'][k]] for k in CUES},
                gaps=[dict(paper_id=p['id'],missing=p['missing']) for p in members if p['missing']]))
        return dict(id=rid,title=title,created=created,subscription_id=sid,algorithm='evidence-overview.v1',papers=papers,groups=groups,timeline=timeline,edges=edges,
            coverage=dict(papers=len(papers),with_abstract=sum(bool(p['sources'][0]['text']) for p in papers),full_text_bound=sum(p['full_text_bound'] for p in papers),
                relationship_candidates=len(edges),relationship_cap=200),
            boundary='这是所选已采集文献的证据型综述草稿，非系统综述或领域全量结论。规则提取可能漏检；作者声称不等于独立验证。时间先后不证明因果或方法继承；缺少局限摘录不代表没有局限。全文依据为显式绑定的本地解析片段，未进行独立版面或来源认证。')

    def get(self,owner,rid):
        with self.store._conn() as c:
            row=c.execute('SELECT * FROM research_synthesis_reports WHERE id=? AND owner=?',(rid,owner)).fetchone()
            if not row:raise LookupError('综述不存在')
            report=json.loads(row['payload'])
            if fingerprint(report)!=row['hash']:raise ValueError('综述完整性校验失败')
            reviews={r['edge_id']:dict(version=r['version'],**json.loads(r['payload'])) for r in c.execute('SELECT * FROM research_synthesis_reviews WHERE report_id=?',(rid,))}
        return dict(id=rid,report=report,hash=row['hash'],reviews=reviews)

    def list(self,owner):
        with self.store._conn() as c:
            return dict(items=[dict(id=r['id'],created=r['created'],title=json.loads(r['payload'])['title'],hash=r['hash']) for r in c.execute('SELECT * FROM research_synthesis_reports WHERE owner=? ORDER BY created DESC,id LIMIT 50',(owner,))])

    def review(self,owner,rid,edge_id,data):
        current=self.get(owner,rid); report=current['report']
        edge=next((e for e in report['edges'] if e['id']==edge_id),None)
        if not edge:raise LookupError('关系不存在')
        if not isinstance(data,dict) or set(data)-{'status','kind','reason','evidence','version','direction'}:raise ValueError('复核字段无效')
        status,kind,reason=data.get('status'),data.get('kind'),data.get('reason')
        if status not in ('confirmed','rejected') or kind not in RELATIONS or not isinstance(reason,str) or not 8<=len(reason.strip())<=1000:
            raise ValueError('请选择关系类型、确认/拒绝并填写至少8字的复核理由')
        version=data.get('version',0)
        direction=data.get('direction','forward')
        if direction not in ('forward','reverse'):raise ValueError('关系方向无效')
        if type(version) is not int or version<0:raise ValueError('复核版本无效')
        evidences=data.get('evidence',[])
        if not isinstance(evidences,list) or len(evidences)>2:raise ValueError('证据字段无效')
        checked=[]
        for e in evidences:
            if not isinstance(e,dict) or set(e)!={'paper_id','source_index','quote'}:raise ValueError('证据格式无效')
            paper=next((p for p in report['papers'] if p['id']==e['paper_id'] and p['id'] in (edge['source'],edge['target'])),None)
            index=e['source_index'];quote=e['quote']
            if not paper or type(index) is not int or not 0<=index<len(paper['sources']) or not isinstance(quote,str) or not 12<=len(quote)<=1200:
                raise ValueError('请选择两篇论文中的有效原文证据')
            source=paper['sources'][index];start=source['text'].find(quote)
            if start<0:raise ValueError('复核引用不在冻结来源中')
            checked.append(dict(paper_id=paper['id'],source_index=index,quote=quote,start=start,end=start+len(quote),sha256=source['sha256']))
        if status=='confirmed' and {e['paper_id'] for e in checked}!={edge['source'],edge['target']}:
            raise ValueError('确认关系需要两端各一条可定位的来源证据')
        source,target=(edge['source'],edge['target']) if direction=='forward' else (edge['target'],edge['source'])
        value=dict(status=status,kind=kind,direction=direction,source=source,target=target,reason=reason.strip(),evidence=checked,reviewed=self.watch.clock(),boundary='人工判断，引用存在性校验不代表学术论证正确；扩展关系的目标论文扩展来源论文。')
        with self.store._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT version FROM research_synthesis_reviews WHERE report_id=? AND edge_id=?',(rid,edge_id)).fetchone()
            if (old['version'] if old else 0)!=version:raise ValueError('复核版本冲突，请刷新后重试')
            c.execute('INSERT INTO research_synthesis_reviews VALUES (?,?,?,?) ON CONFLICT(report_id,edge_id) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                (rid,edge_id,version+1,packed(value)))
        return dict(version=version+1,**value)

    def export(self,owner,rid):
        value=self.get(owner,rid);r=value['report']
        # JSON export preserves all evidence; Markdown treats untrusted text literally.
        def literal(text):return str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('[','\\[').replace(']','\\]').replace('*','\\*').replace('_','\\_').replace('`','\\`').replace('#','\\#')
        lines=['# '+literal(r['title']),'',r['boundary'],'',f"范围：{r['coverage']['papers']}篇；绑定全文{r['coverage']['full_text_bound']}篇。",'']
        for g in r['groups']:
            lines+=['## '+literal(g['name']),'']
            for key,label in LABELS.items():
                lines+=['### '+label,'']
                if not g['sections'][key]:lines+=['所选来源未提取到该项；不能据此认定领域没有相关证据。','']
                for claim in g['sections'][key]:
                    e=claim['evidence'];lines+=['- '+literal(claim['text']),f"  依据：{claim['paper_id']} / {e.get('snapshot_id',e.get('citation',''))} / {e['field']}[{e['start']}:{e['end']}] / SHA256 {e['sha256']}",'']
        lines+=['## 发表/投稿时间线','']
        for t in r['timeline']:lines+=['- '+(t['date']['value'] or '日期未知')+' · '+literal(t['title'])]
        lines+=['','## 关系复核','']
        for e in r['edges']:
            review=value['reviews'].get(e['id']);a,b=(review['source'],review['target']) if review else (e['source'],e['target'])
            lines+=['- '+literal(a+' → '+b)+'：'+(RELATIONS[review['kind']]+' / '+review['status'] if review else '相关候选 / 待复核')]
            if review:
                lines+=['  人工理由：'+literal(review['reason'])]
                for evidence in review['evidence']:lines+=['  原文：'+literal(evidence['quote'])+' / '+evidence['paper_id']+' / SHA256 '+evidence['sha256']]
        lines+=['','## 文献与原始来源','']
        for p in r['papers']:lines+=['- '+literal(p['title'])+' · '+literal(p['url'])+' · ID '+p['id']]
        return dict(markdown='\n'.join(lines),data=value)
