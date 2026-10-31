"""Read-only, short-quote public reading library. Never writes a user's database."""
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / 'benchmarks/fixtures'
KINDS = {'reading_order': '阅读顺序', 'problem_progression': '问题演进', 'parallel_approaches': '并行路线'}
STATUSES = {'covered': '有代表入口', 'partial': '部分覆盖', 'gap': '初稿遗漏', 'out_of_scope': '初稿范围外'}
DECLARED = {'author_described_simplification':'作者称其为简化形式', 'author_described_builds_on':'作者称其基于前者', 'author_described_shared_training':'作者称训练过程相同'}


def digest(raw): return hashlib.sha256(raw).hexdigest()


def validate(pack):
    """Check referential integrity/provenance shape; NOT scholarly entailment."""
    if len(pack['domains']) != 3 or pack['audit']['semantic_validation_passed'] is not False:
        raise ValueError('reading pack scope/validation boundary invalid')
    all_ids = set()
    if len({d['id'] for d in pack['domains']}) != 3: raise ValueError('duplicate domain identity')
    for d in pack['domains']:
        if not re.fullmatch('[a-z-]+', d['id']): raise ValueError('invalid domain id')
        initial = {p['id'] for p in d['papers']}; extra = {p['id'] for p in d['supplements']}
        ids = initial | extra
        if len(initial) != 8 or len(extra) != 2 or initial & extra or ids & all_ids:
            raise ValueError('duplicate or missing paper identity')
        all_ids |= ids
        survey = d['survey']
        if survey['status'] != 'published_record_verified' or survey['publication']['DOI'].lower() != survey['doi']:
            raise ValueError('survey publication record mismatch')
        for p in d['papers'] + d['supplements']:
            if p['arxiv_id'] == survey.get('arxiv_id', '').split('v')[0]: raise ValueError('survey contaminated primary corpus')
            if not re.fullmatch(re.escape(p['arxiv_id']) + r'v[1-9]\d*', p['version']): raise ValueError('version mismatch')
            if p['url'] != 'https://arxiv.org/abs/' + p['version']: raise ValueError('source URL mismatch')
            if p['phase'] != ('initial' if p['id'] in initial else 'after_survey'): raise ValueError('phase mismatch')
            evidence(p['evidence'])
        for p in d['papers']:
            if p['category'] not in d['categories']: raise ValueError('unknown initial category')
        for claim in d['overview']:
            if not claim['papers'] or set(claim['papers']) - initial: raise ValueError('overview evidence not initial')
        for path in d['paths']:
            if path['kind'] not in KINDS or len(path['papers']) < 2 or set(path['papers']) - initial:
                raise ValueError('unsupported lineage or reading path')
        by_id = {p['id']:p for p in d['papers']+d['supplements']}
        for rel in d.get('declared_relations', []):
            if rel['source'] not in ids or rel['target'] not in ids or rel['kind'] not in DECLARED or rel['status'] != 'author_statement_not_independently_proven':
                raise ValueError('unsupported author relation')
            evidence(rel['evidence']); target = by_id[rel['target']]
            if rel['evidence']['source_url'] != target['url'] or rel['evidence']['text_sha256'] != target['evidence']['text_sha256']:
                raise ValueError('author relation source mismatch')
        for check in d['validation']:
            if check['initial_status'] not in STATUSES or set(check['papers']) - initial or set(check['supplements']) - extra:
                raise ValueError('invalid survey comparison')
            if check['initial_status'] == 'gap' and check['papers']: raise ValueError('gap cannot count initial coverage')
            evidence(check['evidence'])
            if check['evidence']['source_url'] != survey['url']: raise ValueError('wrong survey source')
            if check['evidence']['raw_sha256'] != survey['body_raw_sha256'] or check['evidence']['text_sha256'] != survey['body_text_sha256']:
                raise ValueError('survey fingerprint mismatch')
    return pack


def evidence(e):
    if e['verified'] is not True or e['end'] - e['start'] != len(e['quote']) or e['start'] < 0:
        raise ValueError('invalid source fragment')
    if not e['quote'] or len(e['quote'].split()) > 24 or digest(e['quote'].encode()) != e['quote_sha256']:
        raise ValueError('source quote integrity mismatch')
    for key in ('raw_sha256', 'text_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', e[key]): raise ValueError('missing source fingerprint')


def library():
    pack = validate(json.loads((ROOT / 'research_domains.json').read_text(encoding='utf-8')))
    # Git on Windows may check JSON out with CRLF. The frozen draft was UTF-8
    # LF; normalize only line endings, never JSON content or scholarly text.
    initial = (ROOT / 'research_domain_initial.json').read_text(encoding='utf-8').encode()
    if digest(initial) != pack['audit']['initial_freeze']['sha256']: raise ValueError('initial draft fingerprint mismatch')
    frozen = json.loads(initial)
    for d, original in zip(pack['domains'], frozen['domains']):
        for key in ('id','name','categories','prerequisites','paths','overview','limits'):
            if d[key] != original[key]: raise ValueError('initial draft material changed')
        for p, before in zip(d['papers'], original['papers']):
            if any(p[k] != before[k] for k in ('id','arxiv_id','name','category','summary')): raise ValueError('initial paper selection changed')
    return pack


def catalog():
    p = library()
    return dict(version=p['version'], scope=p['scope'], protocol=p['protocol'], audit=p['audit'],
                domains=[dict(id=d['id'], name=d['name'], initial_papers=len(d['papers']), supplements=len(d['supplements'])) for d in p['domains']])


def get(domain_id):
    p = library()
    d = next((d for d in p['domains'] if d['id'] == domain_id), None)
    if d is None: raise LookupError('领域阅读包不存在')
    return dict(domain=d, scope=p['scope'], protocol=p['protocol'], audit=p['audit'])


def markdown(domain_id):
    value = get(domain_id); d = value['domain']; papers = {p['id']:p for p in d['papers']+d['supplements']}
    def refs(ids): return '、'.join(f"[{papers[x]['name']}]({papers[x]['url']})" for x in ids)
    lines = ['# '+d['name']+'：文献分类、初稿与综述对照', '', value['scope'], '', value['protocol'], '',
             '整理者：助手。真实模型调用0次，独立真人评审0次。不是领域质量认证。', '',
             '## 阅读准备', '', ' → '.join(d['prerequisites']), '', '## 初始8篇与分类', '']
    for category in d['categories']:
        lines += ['### '+category, '']
        for p in d['papers']:
            if p['category'] == category: lines += [f"- [{p['name']} · {p['date']} · {p['version']}]({p['url']})：{p['summary']}"]
        lines += ['']
    lines += ['## 阅读与问题链条', '', '箭头表示下述阅读/问题组织关系，不代表来源引用、方法继承或因果证明。', '']
    for path in d['paths']: lines += ['- '+path['name']+'（'+KINDS[path['kind']]+'）：'+refs(path['papers'])+'。'+path['reason']]
    if d.get('declared_relations'):
        lines += ['', '### 作者原文明确描述的关系', '', '这些是目标论文作者的表述，不等于独立考证或实验复现；与阅读顺序分开。', '']
        for r in d['declared_relations']: lines += ['- '+refs([r['source'],r['target']])+'：'+DECLARED[r['kind']]+'。依据见目标论文摘要，片段及版本位置保存在JSON。']
    lines += ['', '## 冻结初稿', '']
    for claim in d['overview']: lines += [claim['text'], '', '依据：'+refs(claim['papers']), '']
    survey = d['survey']
    lines += ['## 外部综述对照', '', f"[{survey['title']}]({survey['url']}) · {survey['venue']} · DOI {survey['doi']}", '',
              '全文对照版本：'+survey['body_basis']+'。正式发表记录与修订全文版本分别留证。', '',
              '| 对照维度 | 初稿状态 | 初稿入口 | 对照后的补充 | 判断 |', '| --- | --- | --- | --- | --- |']
    for c in d['validation']: lines += ['| '+' | '.join([c['axis'], STATUSES[c['initial_status']], refs(c['papers']) or '无', refs(c['supplements']) or '无', c['assessment']])+' |']
    lines += ['', '覆盖判断为助手拟定；综述分节作为外部参照，不能证明主张正确，也不计算领域准确率。', '', '## 对照后新增2篇', '', d['follow_up'], '']
    for p in d['supplements']: lines += [f"- [{p['name']} · {p['version']}]({p['url']})（{p['category']}）：{p['summary']}"]
    lines += ['', '## 初稿边界与后续扩展', '', '以下保留初稿的范围记录。补读增加了代表入口，并未完整覆盖这些方向。', ''] + ['- '+x for x in d['limits']]
    lines += ['', '## 可复核来源', '', '以下保留捕获时间、摘要/规范化全文位置和SHA256；短引文见JSON及站内来源展开。', '']
    for p in d['papers']+d['supplements']:
        e = p['evidence']; lines += [f"- {p['name']}：{e['captured']} / abstract[{e['start']}:{e['end']}] / text SHA256 {e['text_sha256']} / raw SHA256 {e['raw_sha256']}"]
    for c in d['validation']:
        e = c['evidence']; lines += [f"- 综述§{c['section']} {c['axis']}：{e['captured']} / text[{e['start']}:{e['end']}] / raw SHA256 {e['raw_sha256']}"]
    return '\n'.join(lines)+'\n'
