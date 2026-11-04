"""Source-bound lexical retrieval lesson on real papers, not model or learning scores."""
import collections
import hashlib
import math
import re
import unicodedata

VERSION='rag-literature.v1'
QUESTIONS=[
 ('realm','REALM把哪一类可检索知识引入预训练？','latent knowledge retriever language model pre training','latent knowledge retriever'),
 ('dpr','DPR怎样计算问题向量和段落向量的相似度？','question passage vectors similarity dot product','dot product'),
 ('rag-original','RAG-Token在每个目标词上怎样选择文档？','RAG Token predict target token different document','RAG-Token'),
 ('fid','FiD在哪个阶段独立处理段落、在哪个阶段融合？','encoder passages independently jointly decoder','independently'),
 ('retro','RETRO的检索上下文以什么单位组织？','document chunks retrieved local similarity preceding tokens','chunks'),
 ('hyde','HyDE中假设文档与编码器分别承担什么角色？','hypothetical document encoder dense bottleneck incorrect details','dense bottleneck'),
 ('ragas','RAGAS怎样讨论生成内容的忠实性？','estimating faithfulness generated responses hallucinations','faithfulness'),
 ('self-rag','Self-RAG用什么标记连接检索和自我检查？','reflection tokens retrieved passages generation inference','reflection tokens'),
 ('knnlm','kNN-LM如何把邻居分布和语言模型结合？','nearest neighbors language model linearly interpolating','interpolating'),
 ('rest','REST用什么替代参数化草稿模型？','parametric draft model non parametric retrieval datastore','datastore'),
]
TRANSFER=[
 dict(id='version-policy',question='开源库两版参数说明相互矛盾。请设计来源版本规则、引用展示和证据不足时的拒答条件，并说明如何验证。'),
 dict(id='retrieval-vs-answer',question='增加检索数量后，答案反而出现无依据陈述。你会怎样区分检索覆盖和回答忠实性，并设计一次只改一个因素的对照？'),
 dict(id='budgeted-design',question='在严格延迟和上下文预算下，如何公平比较查询改写与按需检索？列出需固定的条件、观测指标和不能推出的结论。'),
]
STOP=set('a an and are as at be been but by can do for from has have how in into is it its may model of on or our that the their these this to use using was we what when which with'.split())

def normalized_pages(pages):
    result=[]
    for page in pages:
        text=unicodedata.normalize('NFKC',page)
        text=re.sub(r'(?<=\w)-[ \t]*\n[ \t]*(?=\w)','',text)
        result.append(re.sub(r'\s+',' ',text).strip())
    return result

def tokens(text):return [w for w in re.findall(r'[a-z0-9]+',text.lower()) if w not in STOP and len(w)>1]

def abstract_span(text):
    start=re.search(r'\babstract\b',text[:8000],re.I)
    if not start:raise ValueError('PDF abstract heading not found; no title fallback')
    end=re.search(r'\b(?:1\s*\.?\s*)?introduction\b',text[start.end():start.end()+7000],re.I)
    if not end:raise ValueError('PDF abstract end not found; no guessed replacement')
    a=start.end();b=a+end.start()
    if not 80<=b-a<=7000:raise ValueError('PDF abstract region outside bounds')
    return a,b

def chunks(papers,scope):
    result=[]
    for paper in papers:
        text=paper['text'] if scope=='full_text' else paper['abstract'];a,b=0,len(text)
        words=list(re.finditer(r'\S+',text[a:b]))
        for index in range(0,len(words),140):
            part=words[index:index+180]
            if not part:continue
            start=a+part[0].start();end=a+part[-1].end()
            page=next((i+1 for i,v in enumerate(paper['page_spans']) if v[0]<=start<v[1]),1) if scope=='full_text' else 1
            result.append(dict(paper_id=paper['id'],paper_name=paper['name'],page=page,start=start,end=end,
                text=text[start:end],source_url=paper['url'] if scope=='full_text' else paper['metadata_url'],field=scope,
                raw_sha256=paper['raw_sha256'] if scope=='full_text' else paper['metadata_sha256'],text_sha256=hashlib.sha256(text.encode()).hexdigest()))
            if index+180>=len(words):break
    if len(result)>5000:raise ValueError('Retrieval passage budget exceeded')
    return result

def retrieve(passages,query,k):
    bags=[collections.Counter(tokens(p['text'])) for p in passages];lengths=[sum(b.values()) for b in bags]
    # Stable accumulation order is required for exact replay across processes.
    avg=sum(lengths)/max(len(lengths),1);terms=sorted(set(tokens(query)));df={t:sum(t in b for b in bags) for t in terms};scores=[]
    for index,(bag,length) in enumerate(zip(bags,lengths)):
        score=0.
        for term in terms:
            count=bag.get(term,0)
            if not count:continue
            idf=math.log(1+(len(bags)-df[term]+.5)/(df[term]+.5))
            score+=idf*(count*2.2)/(count+1.2*(.25+.75*length/max(avg,1)))
        if score>0:scores.append((score,index))
    scores.sort(key=lambda v:(-v[0],passages[v[1]]['paper_id'],passages[v[1]]['start']))
    return [dict(passages[index],score=score,rank=rank+1) for rank,(score,index) in enumerate(scores[:k])]

def experiment(papers,k=3):
    if type(k) is not int or k not in (1,3,5):raise ValueError('top-k must be 1, 3 or 5')
    lookup={p['id']:p for p in papers};questions=[]
    for sid,label,query,needle in QUESTIONS:
        text=lookup[sid]['text'];match=re.search(re.escape(needle),text,re.I)
        if not match:raise ValueError('Declared teaching anchor absent from the captured PDF')
        questions.append(dict(id=sid,label=label,query=query,expected=dict(paper_id=sid,start=match.start(),end=match.end(),
            text_sha256=lookup[sid]['text_sha256']),annotation='assistant_authored_anchor_not_independent_gold'))
    arms=[]
    for scope in ('abstract','full_text'):
        passages=chunks(papers,scope);rows=[]
        for question in questions:
            hits=retrieve(passages,question['query'],k);e=question['expected']
            needle=next(q[3] for q in QUESTIONS if q[0]==question['id'])
            for hit in hits:hit['anchor_overlap']=hit['paper_id']==e['paper_id'] and needle.lower() in hit['text'].lower()
            rows.append(dict(question_id=question['id'],hits=hits,anchor_hit=any(h['anchor_overlap'] for h in hits)))
        arms.append(dict(scope=scope,top_k=k,passages=len(passages),indexed_characters=sum(len(p['text']) for p in passages),
            returned_characters=sum(len(h['text']) for r in rows for h in r['hits']),anchor_hits=sum(r['anchor_hit'] for r in rows),rows=rows))
    return dict(algorithm=VERSION,method='BM25 k1=1.2, b=0.75; same fixed English queries, 180-word passages/40-word overlap; only accessible source scope changes',
        questions=questions,arms=arms,boundary='真实公开论文上的词法检索机制对照；关键短语候选覆盖仅对助手预声明的10个问题/短语计数，不是答案正确率、独立金标准、模型推理或学习收益。同一短语在不同上下文出现也可能被计入，必须阅读原文核查。PDF采用NFKC/去断行归一文本，区间定位于该文本而非PDF版面坐标；摘要区间定位于单独捕获的作者摘要。')
