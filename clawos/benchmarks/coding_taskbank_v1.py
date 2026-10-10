"""Maintainer-authored tasks on frozen project modules, not external blind tasks.

Reference implementations and post checks are evaluator data. Never include them
in model messages or the coding workspace during the proposal phase.
"""
SOURCE_REVISION = 'f3fbdab7e38b8e11ebcf7e67c0285ac83b2bda02'

TASKS = [
    dict(id='richtext-canonical-runs', module='document_richtext', function='validate_inline',
        objective='Upgrade validate_inline into canonical rich-text normalization after its existing validation. '
        'Drop empty text spans, sort marks by type name in ascending lexicographic order, and merge adjacent spans whose complete normalized marks '
        '(including link href) are identical, regardless of whether their text is equal. Concatenate their text. Preserve every character, link, validation limit and input object; '
        'all existing malformed inputs must still raise ValueError before normalization. Return fresh objects.',
        public="""from services.document_richtext import validate_inline
assert validate_inline([{'text':'a'}, {'text':'b'}]) == [{'text':'ab','marks':[]}]
assert validate_inline([{'text':''}]) == []
""",
        post="""from services.document_richtext import validate_inline
import copy
x=[{'text':'甲','marks':[{'type':'italic'},{'type':'bold'}]}, {'text':'乙','marks':[{'type':'bold'},{'type':'italic'}]}]
old=copy.deepcopy(x); y=validate_inline(x)
assert y == [{'text':'甲乙','marks':[{'type':'bold'},{'type':'italic'}]}] and x == old
y[0]['marks'][0]['type']='changed'; assert x == old
links=[{'text':'a','marks':[{'type':'link','href':'https://a.test'}]}, {'text':'b','marks':[{'type':'link','href':'https://b.test'}]}]
assert len(validate_inline(links)) == 2
for bad in ([{'text':'','marks':[{'type':'unknown'}]}], [{'text':'','marks':[{'type':'bold'},{'type':'bold'}]}], [{'text':'x'*30001}], [{'text':'x'}]*4001):
    try: validate_inline(bad)
    except ValueError: pass
    else: raise AssertionError('validation weakened')
for i in range(100):
    value=[{'text':str(j),'marks':[]} for j in range(i)]
    result=validate_inline(value)
    assert ''.join(r['text'] for r in result) == ''.join(r['text'] for r in value)
    assert validate_inline(result) == result
from itertools import permutations
types=('bold','italic','strike','code','underline','highlight','link')
for order in permutations(types):
    marks=[dict(type=kind, **({'href':'https://a.test/x'} if kind=='link' else {})) for kind in order]
    spans=[{'text':'A','marks':copy.deepcopy(marks)}, {'text':'B','marks':list(reversed(copy.deepcopy(marks)))}]
    old=copy.deepcopy(spans)
    answer=validate_inline(spans)
    assert answer==[{'text':'AB','marks':sorted(marks,key=lambda mark:mark['type'])}]
    assert spans==old
""",
        reference_suffix="""    canonical = []
    for span in result:
        span['marks'].sort(key=lambda mark: mark['type'])
        if not span['text']:
            continue
        if canonical and canonical[-1]['marks'] == span['marks']:
            canonical[-1]['text'] += span['text']
        else:
            canonical.append(span)
    return canonical
"""),
    dict(id='table-shape-contract', module='document_merge', function='merge_table',
        objective='Validate all three table cell matrices before every merge_table fast path. '
        'Each matrix must be a nonempty list of nonempty equal-width row lists of string cells '
        '(subclasses accepted). Invalid matrices raise MergeConflict, not IndexError/TypeError. '
        'A well-formed unchanged branch can still accept a well-formed resize from the other branch. '
        'Keep existing conflict, nonoverlapping cell merge and deep-copy behavior.',
        public="""from services.document_merge import merge_table, MergeConflict
bad={'cells':[]}
try: merge_table(bad,bad,bad)
except MergeConflict: pass
else: raise AssertionError('empty table accepted')
""",
        post="""from services.document_merge import merge_table, MergeConflict
import copy
valid={'cells':[['a','b'],['c','d']]}
for cells in ([],[[]],[['a'],['b','c']],None,'x',[[1]],[['a'],None]):
    for index in range(3):
        branches=[copy.deepcopy(valid) for _ in range(3)]; branches[index]={'cells':cells}
        try: merge_table(*branches)
        except MergeConflict: pass
        else: raise AssertionError('invalid branch accepted')
resize={'cells':[['a']]}; assert merge_table(valid,valid,resize)==resize
local=copy.deepcopy(valid); remote=copy.deepcopy(valid)
local['cells'][0][0]='L'; remote['cells'][1][1]='R'
old=copy.deepcopy([valid,local,remote]); result=merge_table(valid,local,remote)
assert result['cells']==[['L','b'],['c','R']] and [valid,local,remote] == old
result['cells'][0][0]='mutated'; assert [valid,local,remote] == old
remote['cells'][0][0]='X'
try: merge_table(valid,local,remote)
except MergeConflict: pass
else: raise AssertionError('conflict overwritten')
class S(str): pass
assert merge_table({'cells':[[S('a')]]},{'cells':[[S('a')]]},{'cells':[[S('a')]]})['cells']==[['a']]
""",
        reference_prefix="""    for table in (base, local, remote):
        cells = table.get('cells') if isinstance(table, dict) else None
        if (not isinstance(cells, list) or not cells or any(not isinstance(row, list) or not row for row in cells)
                or any(len(row) != len(cells[0]) for row in cells)
                or any(not isinstance(cell, str) for row in cells for cell in row)):
            raise MergeConflict('invalid table matrix')
"""),
    dict(id='paper-citation-boundary', module='grounded_paper_report', function='_canonical_citation',
        objective='Harden _canonical_citation for both canonical doc citations and legacy URL fragments. '
        'document_id must be a positive int or a decimal-digit string representing a positive int; '
        'reject bool, float and invalid IDs with an empty string. Canonical IDs compare numerically. '
        'Legacy #page= and optional &chunk=/#chunk= values must be positive decimal integers, '
        'with no duplicate page/chunk parameters; omitted chunk defaults to 1. Normalize accepted '
        'numbers without leading zeros; a valid fragment emits doc:<id>#page=<page>&chunk=<chunk>. '
        'Preserve non-doc strings with no page/chunk markers unchanged; never invent a citation for invalid fragments.',
        public="""from services.grounded_paper_report import _canonical_citation as cite
assert cite('https://a.test#page=0',1)==''
assert cite('doc:001#page=02&chunk=03',1)=='doc:1#page=2&chunk=3'
""",
        post="""from services.grounded_paper_report import _canonical_citation as cite
for identity in (True,False,0,-1,1.0,'x','-1','0',None):
    assert cite('https://a.test#page=2',identity)==''
for text in ('x#page=-2','x#page=2x','x#page=2&chunk=0','x#page=2#chunk=-1','x#page=2&chunk=3&chunk=4','x#page=2&page=3','doc:2#page=1&chunk=1','doc:1#page=0&chunk=1'):
    assert cite(text,1)==''
assert cite('ordinary citation',1)=='ordinary citation'
assert cite('x#page=2','001')=='doc:1#page=2&chunk=1'
assert cite('x#page=02#chunk=003',1)=='doc:1#page=2&chunk=3'
for page in range(1,80):
    assert cite('doc:001#page='+str(page)+'&chunk=1','1') == 'doc:1#page='+str(page)+'&chunk=1'
""",
        reference="""def _canonical_citation(citation: str, document_id: Any) -> str:
    if isinstance(document_id, bool) or not (isinstance(document_id, int) or isinstance(document_id, str) and re.fullmatch(r'[0-9]+', document_id)):
        return ''
    identity = int(document_id)
    if identity <= 0:
        return ''
    value = str(citation or '').strip()
    if value.startswith('doc:'):
        match = re.fullmatch(r'doc:([0-9]+)#page=([0-9]+)&chunk=([0-9]+)', value)
        if not match or int(match[1]) != identity or int(match[2]) <= 0 or int(match[3]) <= 0:
            return ''
        return f'doc:{identity}#page={int(match[2])}&chunk={int(match[3])}'
    if not re.search(r'[#&](?:page|chunk)=', value):
        return value
    pages = re.findall(r'[#&]page=([^#&]*)', value)
    chunks = re.findall(r'[#&]chunk=([^#&]*)', value)
    if len(pages) != 1 or len(chunks) > 1 or '#page=' not in value:
        return ''
    page, chunk = pages[0], chunks[0] if chunks else '1'
    if not re.fullmatch(r'[0-9]+', page) or not re.fullmatch(r'[0-9]+', chunk) or int(page) <= 0 or int(chunk) <= 0:
        return ''
    return f'doc:{identity}#page={int(page)}&chunk={int(chunk)}'
"""),
    dict(id='history-character-budget', module='response_contract', function='request_history',
        objective='Extend request_history(messages, *, max_characters=24000) with a Unicode character '
        'budget. max_characters must be an int excluding bool, positive, otherwise ValueError. '
        'Preserve current role/content filtering and exclusion of the final user message and later rows. '
        'Choose the longest contiguous suffix of complete prior messages whose sum of len(content) '
        'is within budget; never truncate, skip an oversized newest message, or mutate input. '
        'Return None if there is no usable suffix. Strings and int subclasses retain normal semantics.',
        public="""from services.response_contract import request_history
rows=[{'role':'user','content':'aaaa'}, {'role':'assistant','content':'bb'}, {'role':'user','content':'now'}]
assert request_history(rows,max_characters=2)==[{'role':'assistant','content':'bb'}]
""",
        post="""from services.response_contract import request_history
import copy
for invalid in (True,False,0,-1,None,1.5,'2'):
    try: request_history([],max_characters=invalid)
    except ValueError: pass
    else: raise AssertionError('invalid budget accepted')
rows=[{'role':'system','content':'ignored'}, {'role':'user','content':'甲乙'}, {'role':'assistant','content':'🙂'}, {'role':'user','content':'now'}, {'role':'assistant','content':'future'}]
old=copy.deepcopy(rows)
assert request_history(rows,max_characters=3)==[{'role':'user','content':'甲乙'},{'role':'assistant','content':'🙂'}]
assert request_history(rows,max_characters=1)==[{'role':'assistant','content':'🙂'}] and rows==old
assert request_history([{'role':'user','content':'a'}, {'role':'assistant','content':'oversized'}, {'role':'user','content':'now'}],max_characters=1) is None
assert request_history([{'role':'assistant','content':'x'}]) is None
assert request_history(None) is None
class I(int): pass
assert request_history(rows,max_characters=I(1))==[{'role':'assistant','content':'🙂'}]
for budget in range(1,40):
    x=[{'role':'user','content':'a'*n} for n in range(1,8)]+[{'role':'user','content':'current'}]
    answer=request_history(x,max_characters=budget)
    expected=[]; total=0
    for row in reversed(x[:-1]):
        if total+len(row['content']) > budget: break
        expected.insert(0,row); total+=len(row['content'])
    assert answer==(expected or None)
""",
        reference="""def request_history(messages, *, max_characters=24000):
    if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters <= 0:
        raise ValueError('max_characters must be positive integer')
    rows = [dict(role=m.get('role'), content=m['content']) for m in messages or []
            if isinstance(m, dict) and m.get('role') in {'user', 'assistant'} and isinstance(m.get('content'), str)]
    last_user = next((i for i in range(len(rows)-1,-1,-1) if rows[i]['role']=='user'), -1)
    kept, used = [], 0
    for row in reversed(rows[:last_user] if last_user > 0 else []):
        if used + len(row['content']) > max_characters:
            break
        kept.append(row); used += len(row['content'])
    return list(reversed(kept)) or None
"""),
    dict(id='evidence-document-review', module='document_evidence_policy', function='source_usable',
        objective='source_usable must enforce authoritative document-level review_required in metadata '
        'as well as current per-chunk checks. For doc: sources, malformed/non-object document metadata '
        'must fail closed, and document states failed/deleted/needs_ocr/needs_review must be unusable. '
        'Keep legacy other states compatible, non-doc source behavior, exact fragment matching, and '
        'independent usable chunks in ready_with_exclusions. Missing documents/chunks still return False. '
        'No writes to SQLite or mutation of stored metadata.',
        public="""import sqlite3,json
from services.document_evidence_policy import source_usable
c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
c.executescript('CREATE TABLE documents(id INTEGER,status TEXT,metadata TEXT); CREATE TABLE document_chunks(document_id INTEGER,citation TEXT,metadata TEXT);')
c.execute('INSERT INTO documents VALUES(1,?,?)',('ready',json.dumps({'review_required':True})))
c.execute('INSERT INTO document_chunks VALUES(1,?,?)',('doc:1#page=1&chunk=1','{}'))
assert source_usable(c,'doc:1#page=1&chunk=1') is False
""",
        post="""import sqlite3,json
from services.document_evidence_policy import source_usable
c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
c.executescript('CREATE TABLE documents(id INTEGER,status TEXT,metadata TEXT); CREATE TABLE document_chunks(document_id INTEGER,citation TEXT,metadata TEXT);')
c.execute('INSERT INTO documents VALUES(1,?,?)',('ready','{}'))
c.execute('INSERT INTO document_chunks VALUES(1,?,?)',('doc:1#page=1&chunk=1','{}'))
c.execute('INSERT INTO document_chunks VALUES(1,?,?)',('doc:1#page=1&chunk=2','{"review_required":true}'))
for metadata in ('bad','[]','null','1','{"review_required":true}'):
    c.execute('UPDATE documents SET metadata=?',(metadata,)); before=c.total_changes
    assert source_usable(c,'doc:1#page=1&chunk=1') is False and c.total_changes==before
c.execute('UPDATE documents SET metadata=?',('{}',))
for state in ('failed','deleted','needs_ocr','needs_review'):
    c.execute('UPDATE documents SET status=?',(state,)); assert not source_usable(c,'doc:1#page=1&chunk=1')
c.execute('UPDATE documents SET status=?',('ready_with_exclusions',))
assert source_usable(c,'doc:1#page=1&chunk=1') and not source_usable(c,'doc:1#page=1&chunk=2')
assert not source_usable(c,'doc:1') and not source_usable(c,'doc:1#page=9&chunk=9')
assert source_usable(c,'external citation') and not source_usable(c,'doc:9')
""",
        reference_insertion="""    try:
        metadata = json.loads(document['metadata'])
    except (ValueError, TypeError):
        return False
    if not isinstance(metadata, dict) or metadata.get('review_required') or document['status'] in {'failed','deleted','needs_ocr','needs_review'}:
        return False
"""),
    dict(id='learning-health-telemetry', module='learning_governance', function='runtime_health_passed',
        objective='runtime_health_passed must fail closed on missing live telemetry rather than default '
        'to healthy. Require newest applicable values for user_retry_rate, cancel_rate, '
        'long_task_failure_rate and retrieval_hit_rate. Skip control and runtime_snapshot/offline_replay/'
        'policy_materialization rows as before. Applicable values must be finite numbers in [0,1], '
        'accept numeric subclasses but reject bool, strings, NaN/Infinity, missing or malformed metadata. '
        'Only newest applicable rows per signal count: older conflicting or invalid values cannot override them. '
        'Ignore unrelated signal types. Keep existing <=0.20, <=0.15, <=0.10 and >=0.80 thresholds; never mutate rows.',
        public="""from services.learning_governance import runtime_health_passed
assert runtime_health_passed([]) is False
assert runtime_health_passed([{'signal_type':'retrieval_hit_rate','value':.9}]) is False
""",
        post="""from services.learning_governance import runtime_health_passed
import copy
def rows(): return [{'signal_type':k,'value':v,'metadata':{}} for k,v in [('user_retry_rate',.2),('cancel_rate',.15),('long_task_failure_rate',.1),('retrieval_hit_rate',.8)]]
x=rows(); old=copy.deepcopy(x); assert runtime_health_passed(x) and x==old
for i in range(4): assert not runtime_health_passed(rows()[:i]+rows()[i+1:])
for value in (True,False,'0',None,float('nan'),float('inf'),-.1,1.1):
    x=rows(); x[0]['value']=value; assert runtime_health_passed(x) is False
for metadata in (None,[],42,'bad'):
    x=rows(); x[0]['metadata']=metadata; assert runtime_health_passed(x) is False
for source in ('runtime_snapshot','offline_replay','policy_materialization'):
    x=rows(); x[0]['metadata']={'source':source}; assert not runtime_health_passed(x)
x=rows(); x[0]['metadata']={'variant':'control'}; assert not runtime_health_passed(x)
assert runtime_health_passed(rows()+[{'signal_type':'user_retry_rate','value':'bad','metadata':{}}])
assert runtime_health_passed([{'signal_type':'unrelated','value':'bad','metadata':None}]+rows())
for i,v in enumerate((.21,.16,.11,.79)):
    x=rows(); x[i]['value']=v; assert not runtime_health_passed(x)
class F(float): pass
x=rows();x[0]['value']=F(.1);assert runtime_health_passed(x)
""",
        reference="""def runtime_health_passed(rows):
    limits = {'user_retry_rate': .20, 'cancel_rate': .15, 'long_task_failure_rate': .10}
    required = set(limits) | {'retrieval_hit_rate'}
    latest = {}
    for row in rows:
        key = row.get('signal_type')
        if key not in required or key in latest:
            continue
        meta = row.get('metadata')
        if not isinstance(meta, dict):
            return False
        if meta.get('variant') == 'control' or meta.get('source') in {'runtime_snapshot','offline_replay','policy_materialization'}:
            continue
        value = row.get('value')
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
            return False
        latest[key] = value
    return set(latest) == required and all(latest[key] <= limit for key,limit in limits.items()) and latest['retrieval_hit_rate'] >= .8
"""),
]
