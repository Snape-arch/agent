"""Source-reported citations and manifestations, never similarity-derived lineage."""
import re
from urllib.parse import unquote


RELATIONS={'is-preprint-of','has-preprint','is-version-of','has-version','is-identical-to'}


def identifier_doi(value):
    value=re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)','',str(value or '').strip(),flags=re.I).lower()
    return value if re.fullmatch(r'10\.\d{4,9}/\S{1,500}',value) else ''


def arxiv_parts(value):
    value=unquote(str(value or '').strip()).lower()
    value=re.sub(r'^https?://(?:export\.)?arxiv\.org/abs/','',value)
    match=re.fullmatch(r'(\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v([1-9]\d{0,3}))?',value)
    return (match[1],int(match[2]) if match[2] else None) if match else ('',None)


def metadata_fields(raw):
    base,version=arxiv_parts(raw.get('arxiv_id'))
    if type(raw.get('arxiv_version')) is int and 1<=raw['arxiv_version']<=9999:version=raw['arxiv_version']
    refs=raw.get('references') or []
    if not isinstance(refs,list):raise ValueError('invalid reference list')
    references=[]
    for index,r in enumerate(refs[:500]):
        if not isinstance(r,dict):raise ValueError('invalid reference record')
        references.append(dict(doi=identifier_doi(r.get('doi')),key=str(r.get('key') or index)[:120],unstructured=str(r.get('unstructured') or '')[:1200]))
    relations=[]
    for r in (raw.get('relations') or [])[:100]:
        if not isinstance(r,dict):raise ValueError('invalid relation record')
        if r.get('kind') not in RELATIONS:continue
        target_doi=identifier_doi(r.get('doi'));ax,v=arxiv_parts(r.get('arxiv_id'))
        if target_doi or ax:relations.append(dict(kind=r['kind'],doi=target_doi,arxiv_id=ax+('v'+str(v) if v else '') if ax else '',asserted_by=str(r.get('asserted_by') or '')[:100]))
    count=raw.get('reference_count_reported')
    count=count if type(count) is int and count>=0 else None
    return dict(arxiv_version=version if base else None,publication_type=str(raw.get('publication_type') or '')[:80],
        journal_ref=str(raw.get('journal_ref') or '')[:1000],references=references,reference_count_reported=count,
        references_available=raw.get('references_available') is True,
        references_truncated=bool(raw.get('references_truncated')) or len(refs)>500 or (count is not None and count>len(references)),
        relations=relations,relations_truncated=bool(raw.get('relations_truncated')) or len(raw.get('relations') or [])>100)


def source_records(rows,limit=20,budget=None):
    """Latest metadata per observed artifact; retain explicit omissions, not fabricated history."""
    from services.research_watch import fingerprint
    selected=[];keys=set();available=0
    for row in rows:
        import json
        p=json.loads(row['payload']);base,version=arxiv_parts(p.get('arxiv_id'))
        version=p.get('arxiv_version') or version
        version_field='arxiv_version' if p.get('arxiv_version') else 'arxiv_id'
        if base and version is None:
            other,v=arxiv_parts(p.get('source_id'))
            if other==base and v:version=v;version_field='source_id'
        key=(p['source'],base,version) if base else (p['source'],p.get('doi'),p.get('source_id'))
        if key in keys:continue
        keys.add(key);available+=1
        if len(selected)>=limit or budget is not None and budget['records']<=0:continue
        if fingerprint(p)!=row['hash']:raise ValueError('版本来源快照完整性校验失败')
        fields=metadata_fields(p)
        if budget is not None:
            budget['records']-=1
            for name,flag in [('references','references_truncated'),('relations','relations_truncated')]:
                allowance=budget[name];items=fields[name];fields[name]=items[:allowance]
                fields[flag]=fields[flag] or len(items)>allowance
                budget[name]-=len(fields[name])
        fields['arxiv_version']=version
        selected.append(dict(snapshot_id=row['id'],sha256=row['hash'],captured=row['captured'],source=p['source'],title=p['title'],doi=p.get('doi',''),
            arxiv_id=base,arxiv_version_field=version_field,source_url=p.get('url',''),published=p.get('published',''),updated=p.get('updated',''),**fields))
    return dict(records=selected,available_artifacts=available,omitted_artifacts=max(0,available-len(selected)))


def build_graph(papers,max_edges=2000,max_nodes=1500):
    nodes={};edges={};omitted=0;unresolved=0;unidentified=0;partial=0;missing=0;partial_relations=0
    def node(key,kind,title,observed=False,**extra):
        if key not in nodes:
            if len(nodes)>=max_nodes:return None
            nodes[key]=dict(id=key,kind=kind,title=title,observed=observed,**extra)
        elif observed:nodes[key].update(observed=True,title=title,kind=kind,**extra)
        return key
    def link(a,b,kind,evidence,**extra):
        nonlocal omitted
        key=(a,b,kind)
        if not a or not b or len(edges)>=max_edges and key not in edges:omitted+=1;return
        if key not in edges:edges[key]=dict(source=a,target=b,kind=kind,status='source_reported',evidence=[],**extra)
        if evidence not in edges[key]['evidence']:edges[key]['evidence'].append(evidence)
    def evidence(record,field,index=None):return dict(snapshot_id=record['snapshot_id'],sha256=record['sha256'],field=field,index=index,source_url=record['source_url'])
    manifestations=[];work_members={}
    for paper in papers:
        records=paper.get('bibliography',{}).get('records',[])
        if not records:missing+=1
        for record in records:
            ax,version=record.get('arxiv_id'),record.get('arxiv_version')
            key='arxiv:'+ax+('v'+str(version) if version else '') if ax else 'doi:'+record['doi'] if record.get('doi') else 'record:'+record['snapshot_id']
            kind='arxiv_revision' if ax else 'publication' if record.get('publication_type') in ('journal-article','proceedings-article','book-chapter') else 'doi_record'
            nid=node(key,kind,record['title'],True,paper_id=paper['id'],arxiv_id=ax,version=version,doi=record.get('doi',''),published=record['published'],updated=record['updated'],publication_type=record.get('publication_type',''))
            work_members.setdefault(paper['id'],[]).append(key)
            manifestations.append((nid,record))
    for nid,record in manifestations:
        if not record['references_available']:missing+=1
        if record['references_truncated']:partial+=1
        if record.get('relations_truncated'):partial_relations+=1
        for i,ref in enumerate(record['references']):
            if not ref['doi']:unidentified+=1;continue
            target='doi:'+ref['doi'];observed=target in nodes and nodes[target]['observed']
            if not observed:unresolved+=1
            dest=node(target,'unresolved_doi',ref['doi'])
            link(nid,dest,'cites',evidence(record,'references',i),boundary='来源参考文献记录，不表示赞同、效果支持或方法继承。')
        ax=record.get('arxiv_id')
        if ax and record.get('doi'):
            target=node('doi:'+record['doi'],'doi_record',record['doi'])
            link(nid,target,'doi_association',evidence(record,'doi'),boundary='arXiv元数据关联DOI；不单凭此字段认证正式发表或同行评审。')
        for i,relation in enumerate(record['relations']):
            if relation['doi']:target=node('doi:'+relation['doi'],'unresolved_doi',relation['doi'])
            else:
                base,v=arxiv_parts(relation['arxiv_id']);target=node('arxiv:'+base+('v'+str(v) if v else ''),'arxiv_revision',relation['arxiv_id'])
            kind=relation['kind'];a,b=nid,target
            if kind in ('has-preprint','has-version'):a,b=target,nid
            normalized={'has-preprint':'is-preprint-of','has-version':'is-version-of'}.get(kind,kind)
            link(a,b,normalized,evidence(record,'relations',i),boundary='来源显式版本/预印本关联，不证明方法继承。')
    families={}
    for nid,record in manifestations:
        if record.get('arxiv_id') and record.get('arxiv_version'):
            families.setdefault(record['arxiv_id'],{})[record['arxiv_version']]=(nid,record)
    for family,versions in families.items():
        ordered=sorted(versions)
        for left,right in zip(ordered,ordered[1:]):
            a,ar=versions[left];b,br=versions[right]
            link(a,b,'observed_revision_order',evidence(br,br.get('arxiv_version_field','arxiv_version')),prior_evidence=evidence(ar,ar.get('arxiv_version_field','arxiv_version')),missing_intermediate_count=right-left-1,
                 boundary='仅排列已采集的明确版本号；缺失的中间版本未补造。')
    return dict(nodes=list(nodes.values()),edges=list(edges.values()),families=[dict(arxiv_id=k,observed_versions=sorted(v)) for k,v in sorted(families.items())],work_members=work_members,
        coverage=dict(observed_artifacts=len(manifestations),nodes=len(nodes),edges=len(edges),unresolved_reference_occurrences=unresolved,references_without_doi=unidentified,
            missing_reference_metadata_records=missing,partial_reference_records=partial,partial_relation_records=partial_relations,omitted_artifacts=sum(p.get('bibliography',{}).get('omitted_artifacts',0) for p in papers),
            omitted_edges=omitted,edge_limit=max_edges,node_limit=max_nodes),
        boundary='仅覆盖已采集来源元数据，未收录或受限参考文献不表示没有引用；未解析DOI为范围外节点。版本、元数据引用与人工学术关系分别展示。')
