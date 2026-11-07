import { useEffect, useRef, useState, type FormEvent } from 'react';
import { CapturedPaperReader } from './CapturedPaperReader';
import { researchApi as api, researchBase } from './researchJourney';
import './research-journey.css';
import './rag-intro-lesson.css';

type Question = {id:string; prompt:string; options:string[]};
type Score = {score:number; total:number; rows:(Question & {choice:number; correct:number; passed:boolean; feedback:string})[]};
type Source = {id:string; name:string; title:string; version:string; page:number; page_count:number; raw_sha256:string; quote:string; pdf_url:string; metadata_url:string};
type Candidate = {title:string; text:string; score:number; current:boolean};
type Row = {case_id:string; query:string; chunks:Candidate[]; evaluation:{passed:boolean}};
type Experiment = {arms:{config:{current_only:boolean}; rows:Row[]}[]};
type Rubric = {id:string; title:string; scores:string[]};
type Attempt = {id:string; revision:number} & (
  {phase:'pre'|'post'; questions:Question[]} |
  {phase:'guide'; source:Source} |
  {phase:'lab'; prediction:string; experiment:Experiment|null} |
  {phase:'transfer'; prompt:string} |
  {phase:'done'; result:{pre:Score; post:Score; transfer:{answer:string}}; rubric:Rubric[]}
);
type Lesson = {case_id:string; case_hash:string; source_version:string; attempt:Attempt|null};
const steps = [
  ['pre','课前自测'], ['guide','论文导读'], ['lab','对照实验'], ['post','课后自测'], ['transfer','迁移题'],
] as const;

function Questions({questions, busy, submit}:{questions:Question[]; busy:boolean; submit:(answers:Record<string,number>)=>void}) {
  const [answers, setAnswers] = useState<Record<string,number>>({});
  return <form onSubmit={event=>{event.preventDefault();submit(answers);}}>
    {questions.map((q,index)=><fieldset key={q.id} disabled={busy}>
      <legend>{index+1}. {q.prompt}</legend>
      {q.options.map((option,i)=><label className="intro-option" key={option}>
        <input type="radio" name={q.id} required checked={answers[q.id]===i} onChange={()=>setAnswers({...answers,[q.id]:i})}/>{option}
      </label>)}
    </fieldset>)}
    <button className="visual-primary" disabled={busy}>提交并继续</button>
  </form>;
}

function Explanation({label,action,busy,submit}:{label:string;action:string;busy:boolean;submit:(answer:string)=>void}) {
  const [answer,setAnswer]=useState('');
  function save(event:FormEvent) {event.preventDefault();submit(answer.trim());}
  return <form onSubmit={save}>
    <label className="intro-text">{label}<textarea required minLength={8} maxLength={1500} value={answer} disabled={busy} onChange={e=>setAnswer(e.target.value)}/></label>
    <button className="visual-primary" disabled={busy||answer.trim().length<8}>{action}</button>
  </form>;
}

function EvidenceComparison({experiment}:{experiment:Experiment}) {
  const [question,setQuestion]=useState('loan');
  const rows=experiment.arms.map(arm=>arm.rows.find(row=>row.case_id===question)!);
  return <section className="intro-observation" aria-label="实验结果">
    <div className="intro-switch" role="group" aria-label="选择对照问题">
      <button aria-pressed={question==='loan'} onClick={()=>setQuestion('loan')}>借用期限</button>
      <button aria-pressed={question==='missing'} onClick={()=>setQuestion('missing')}>停车价格</button>
    </div>
    <p className="intro-query">{rows[0].query}</p>
    <div className="intro-arms">
      {experiment.arms.map((arm,i)=>{
        const row=rows[i], hit=row.chunks[0];
        return <article key={String(arm.config.current_only)}>
          <h3>{arm.config.current_only?'B · 只检索现行资料':'A · 检索全部资料'}</h3>
          {hit?<><p><strong>{hit.title}</strong> · {hit.current?'现行':'已停用'}</p>
            <div className="intro-meter"><meter min={0} max={1} value={hit.score} aria-label="词项匹配分"/>
              <span>匹配分 {hit.score.toFixed(2)}</span></div><blockquote>{hit.text}</blockquote></>:<p>没有召回片段。</p>}
          <p className={row.evaluation.passed?'intro-pass':'intro-miss'}>{row.evaluation.passed?'首条片段支持回答':'首条片段无法支持回答'}</p>
        </article>;
      })}
    </div>
    <p>{question==='loan'?'两条规则的匹配分相同，能用哪条取决于它是否仍有效。':'两组都找到了开放时间。只检索现行资料解决不了内容缺失，应暂不回答价格。'}</p>
  </section>;
}

export function RagIntroLesson() {
  const [lesson,setLesson]=useState<Lesson|null>(), [loading,setLoading]=useState(true), [busy,setBusy]=useState(false);
  const [error,setError]=useState(''), [reading,setReading]=useState(false), [refresh,setRefresh]=useState(0);
  const heading=useRef<HTMLHeadingElement>(null), openOriginal=useRef<HTMLButtonElement>(null), pendingStart=useRef('');
  const attempt=lesson?.attempt;
  const activeStep=attempt?.phase==='done'?steps.length:steps.findIndex(([phase])=>phase===(attempt?.phase||'pre'));

  useEffect(()=>{
    const controller=new AbortController();
    const query=new URLSearchParams(location.search);
    const load=async()=>{
      const catalog=query.has('ragCase')?null:await api<{cases:{id:string}[]}>('/catalog',undefined,controller.signal);
      const cid=query.get('ragCase')||catalog?.cases[0]?.id;
      const selected=query.get('introAttempt');
      const view=cid?await api<Lesson>(`/cases/${encodeURIComponent(cid)}/intro${selected?'?attempt='+encodeURIComponent(selected):''}`,undefined,controller.signal):null;
      if(!controller.signal.aborted)setLesson(view);
    };
    setError('');setLoading(true);
    void load().catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[refresh]);
  useEffect(()=>{if(attempt){heading.current?.focus();heading.current?.scrollIntoView?.({block:'nearest'});}},[attempt?.id,attempt?.phase]);

  async function write(path:string, data:unknown) {
    setBusy(true);setError('');
    try {
      const view=await api<Lesson>(path,data);
      const url=new URL(location.href);
      url.searchParams.set('ragCase',view.case_id);
      if(view.attempt)url.searchParams.set('introAttempt',view.attempt.id);
      history.replaceState(history.state,'',url);
      setLesson(view);pendingStart.current='';
    } catch(e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  const path=lesson&&`/cases/${encodeURIComponent(lesson.case_id)}/intro`;
  function start() {
    if(!lesson||!path)return;
    pendingStart.current ||= crypto.randomUUID().replaceAll('-','');
    void write(path,{attempt_id:pendingStart.current,case_hash:lesson.case_hash});
  }
  function next(action:string,value:unknown) {
    if(path&&attempt)void write(`${path}/${attempt.id}`,{revision:attempt.revision,action,value});
  }

  return <div className="rag-intro visual-studio">
    <header className="visual-studio-header"><div>
      <span className="visual-kicker">RAG 入门 · 约 15 分钟</span>
      <h1>为什么检索会找错资料？</h1>
      <p>读一段论文，做一次检索对照，学会判断排在第一的片段能不能回答问题。</p>
    </div></header>
    <ol className="intro-steps" aria-label="学习进度">{steps.map(([phase,title],i)=><li key={phase} aria-current={i===activeStep?'step':undefined}>
      <span aria-hidden="true">{i<activeStep?'✓':String(i+1).padStart(2,'0')}</span>{title}
    </li>)}</ol>
    {error&&<div className="intro-error"><p role="alert">{error}</p><button onClick={()=>setRefresh(n=>n+1)} disabled={busy||loading}>读取已保存进度</button></div>}
    {loading&&<p role="status">正在读取课程资料和已保存进度…</p>}
    <section className="intro-sheet" aria-busy={busy||loading}>
      {!loading&&lesson===null&&<><h2>先准备固定版本的论文</h2>
        <p>这节课以 DPR 作者摘要和原文第 1 页为导读材料。准备好公开资料后，这里会接上同一份学习计划。</p>
        <a href="/academy/vision/#rag-lab">去准备公开资料</a></>}
      {lesson&&!attempt&&<><h2>先做三道题，看看你已经知道什么</h2>
        <p>完成前测后进入导读。前测和后测使用不同情境，答案解析在整节课完成后显示。</p>
        <button className="visual-primary" disabled={busy||loading} onClick={start}>开始课前自测</button></>}
      {attempt&&<h2 ref={heading} tabIndex={-1}>{attempt.phase==='done'?'这节课已完成':steps[activeStep][1]}</h2>}
      {attempt&&(attempt.phase==='pre'||attempt.phase==='post')&&<Questions key={`${attempt.id}:${attempt.phase}`} questions={attempt.questions} busy={busy||loading} submit={v=>next('submit',v)}/>}
      {lesson&&attempt?.phase==='guide'&&<>
        <p>检索先从资料里挑出几段可能相关的文字，这些就是候选。向量把文字表示成一组数字，帮助系统把意思接近的段落排在前面。例如，提问写「归还器材」，手册里可能用的是「设备交回」。</p>
        <p>找到候选以后，再核对它对谁有效、是否过期，以及原句能否支持你要给的答案。</p>
        <div className="intro-source">
          <h3>{attempt.source.title}</h3>
          <p>DPR · arXiv {attempt.source.version} · 作者摘要</p>
          <blockquote lang="en">“{attempt.source.quote}”</blockquote>
          <p>导读问题：论文这句在说明如何表示和检索段落。它能告诉我们一份规定是否仍有效吗？</p>
          <div className="intro-actions"><button ref={openOriginal} aria-expanded={reading} onClick={()=>setReading(!reading)}>{reading?'收起 PDF':'查看原文第 1 页'}</button><a href={`${attempt.source.pdf_url}?download=true`}>下载固定版本 PDF</a></div>
        </div>
        {reading&&<CapturedPaperReader paper={attempt.source} journey={lesson} close={()=>{setReading(false);openOriginal.current?.focus();}}/>}
        <Explanation label="实验前预测：排除旧资料会改善什么？什么问题可能仍答不了？" action="保存预测，进入实验" busy={busy||loading} submit={v=>{setReading(false);next('predict',v);}}/>
      </>}
      {attempt?.phase==='lab'&&<>
        <p>同一批创客空间资料、同一问题、同一检索方法。只改变是否排除旧版，比较两组第一条候选。</p>
        <p className="intro-note"><strong>你的预测</strong> {attempt.prediction}</p>
        {!attempt.experiment?<button className="visual-primary" disabled={busy||loading} onClick={()=>next('run',true)}>运行 A/B 检索对照</button>:<>
          <EvidenceComparison experiment={attempt.experiment}/>
          <Explanation label="你的观察：两组在借用期限和停车价格上分别有什么变化？" action="保存观察，进入后测" busy={busy||loading} submit={v=>next('observe',v)}/>
        </>}
        <details><summary>实验方法</summary><p>这是用人工短文运行的字符二元组检索。片段上限 80 字，候选数 1，最低分 0.08。匹配分衡量词项重叠，本课没有运行向量模型，也不复现论文指标。</p></details>
      </>}
      {attempt?.phase==='transfer'&&<><p>{attempt.prompt}</p><Explanation label="写下你的回答和核查步骤" action="提交迁移题" busy={busy||loading} submit={v=>next('submit',v)}/></>}
      {attempt?.phase==='done'&&<>
        <dl className="intro-scores"><div><dt>课前自测</dt><dd>{attempt.result.pre.score} / {attempt.result.pre.total}</dd></div><div><dt>课后自测</dt><dd>{attempt.result.post.score} / {attempt.result.post.total}</dd></div><div><dt>迁移题</dt><dd>待人工复核</dd></div></dl>
        <p>前后测是课堂练习，两套题尚未验证等难。迁移题留给教师按量尺复核。</p>
        <details><summary>查看两次作答与解析</summary>{([['课前自测',attempt.result.pre],['课后自测',attempt.result.post]] as const).map(([label,score])=><section key={label}><h3>{label}</h3><ol>{score.rows.map(row=><li key={row.id}><strong>{row.prompt}</strong><p>{row.passed?'答对':'需复习'} · 你的选择：{row.options[row.choice]}</p><p>{row.feedback}</p></li>)}</ol></section>)}</details>
        <details><summary>查看迁移回答与教师量尺</summary><blockquote>{attempt.result.transfer.answer}</blockquote>{attempt.rubric.map(item=><section key={item.id}><h3>{item.title}</h3><ol start={0}>{item.scores.map(score=><li key={score}>{score}</li>)}</ol></section>)}</details>
        <div className="intro-actions"><a href={`${researchBase}${path}/${attempt.id}/export`}>下载完整学习记录</a><a href={`${researchBase}${path}/${attempt.id}/export?review=true`}>下载教师复核包</a>
          <a href={`/academy/vision/?ragCase=${encodeURIComponent(lesson!.case_id)}#journey`}>继续完整 RAG 学习计划</a></div>
        <details><summary>在这台电脑上开始另一份练习</summary><p>当前记录保留。可先下载记录，或保存本页地址以便恢复。</p><button disabled={busy||loading} onClick={start}>新建练习</button></details>
      </>}
    </section>
  </div>;
}
