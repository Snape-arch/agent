"use strict";
(() => {
  const main=document.getElementById('main');
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let state, busy=false, hints={};
  async function api(path='',body){
    const response=await fetch('/api/academy/learning/rag'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    let data;try{data=await response.json();}catch{throw Error('学习服务暂不可用，请重新连接。');}
    if(!response.ok)throw Error(data.detail||'请求未完成');return data;
  }
  function notify(message){const node=document.getElementById('notice');node.textContent=message;node.classList.add('visible');setTimeout(()=>node.classList.remove('visible'),5000);}
  function questions(rows,prefix,saved={}){return rows.map((q,i)=>`<fieldset class="diagnostic-question"><legend>${i+1}. ${esc(q.prompt)}</legend>${q.options.map((option,j)=>`<label><input type="radio" name="${prefix}-${q.id}" value="${j}" ${saved[q.id]===j?'checked':''}>${esc(option)}</label>`).join('')}</fieldset>`).join('');}
  function answers(rows,prefix){const data={};for(const q of rows){const el=main.querySelector(`input[name="${prefix}-${q.id}"]:checked`);if(!el)throw Error('请先回答全部题目。');data[q.id]=Number(el.value);}return data;}
  function feedback(result){return `<div class="rag-feedback"><b>${result.passed} / ${result.total} 题判断正确</b>${result.rows.map(r=>`<p>${r.passed?'✓':'待补学'} ${esc(r.feedback)} ${r.passed?'':`<a class="text-button" href="/academy#lesson/${r.topic}">补学对应知识 →</a>`}</p>`).join('')}</div>`;}
  function render(){
    const latest=state.runs[0],config=latest?.data.config||state.default_config,diagnosis=state.diagnosis?.data;
    main.innerHTML=`<header class="page-head"><div><span class="eyebrow">BUILD A GROUNDED ANSWER</span><h1>做出一个能解释失败的 RAG 助手。</h1><p>先判断自己的误区，再运行、修复和验收。这里的资料都是教学用合成数据，不写入你的正式知识库。</p></div></header>
    <section id="diagnosis" class="workshop-section card"><span class="eyebrow">01 / DIAGNOSE</span><h2>先看你怎么判断，而不是先背术语</h2>${questions(state.diagnostic,'diagnosis',Object.fromEntries((diagnosis?.rows||[]).map(r=>[r.id,r.choice])))}<button data-action="diagnose" class="primary">${diagnosis?'重新诊断':'提交诊断'}</button><div id="diagnosis-result">${diagnosis?feedback(diagnosis):''}</div></section>
    <section id="learn" class="workshop-section"><span class="eyebrow">02 / UNDERSTAND</span><h2>从原文到答案，逐步留下证据</h2><div class="twocol"><article class="card"><ol class="rag-steps"><li><b>切分：</b>长文切成可检索片段，同时保留文档 ID 与字符位置。切断数量和单位会使片段失去意义。</li><li><b>召回：</b>先用字符二元组重叠率建立可解释基线。分数衡量字面相似，不等于语义正确。</li><li><b>回答：</b>先观察摘录首个片段的简单策略，再选择已有模型生成，比较哪一步引入错误。</li><li><b>核验：</b>引用必须来自本次召回；还要检查版本、具体事实和无答案时的拒答。</li></ol><p class="small">注意：这个实验是教学检索器，未替代正式知识库的 embedding / rerank 服务。模型模式复用系统已配置的模型路由。</p><a class="text-button" href="/academy#lesson/rag">回到 RAG 学习室 →</a></article><article class="card rag-sources"><h3>本次资料集 · ${state.documents.length} 份</h3>${state.documents.map(d=>`<details><summary>${esc(d.title)} <span class="badge ${d.current?'green':'amber'}">${d.current?'现行':'已停用'}</span></summary><p>${esc(d.text)}</p><small>文档 ID：${esc(d.id)}</small></details>`).join('')}</article></div></section>
    <section id="experiment" class="workshop-section card"><span class="eyebrow">03 / EXPERIMENT</span><h2>提出一个修改，再运行对照实验</h2><p>建议先保留默认配置运行一次，再每次只改变一个参数。观察正常问答、过期来源和无答案问题的变化。</p><div class="rag-controls"><label>片段长度（字符）<input id="chunk-size" type="number" min="8" max="160" value="${config.chunk_size}"></label><label>召回数量 top-k<select id="top-k">${[1,2,3,4].map(n=>`<option ${config.top_k===n?'selected':''}>${n}</option>`).join('')}</select></label><label>最低匹配分数<input id="min-score" type="number" step="0.01" min="0" max="1" value="${config.min_score}"></label><label class="check"><input id="current-only" type="checkbox" ${config.current_only?'checked':''}>只检索现行资料</label><label>回答方式<select id="run-mode"><option value="extractive">摘录基线 · 无需模型</option value="model">已有模型 · 生成带引用回答</option></select></label></div><p class="rag-note">模型模式会把这套合成问题与片段发给系统已配置的模型服务；不读取个人文件。不启用工具调用，最长等待 90 秒。</p><button class="primary" data-action="run">运行并检查 6 个问题</button><p id="run-status" role="status"></p></section>
    <section id="results" class="workshop-section"><span class="eyebrow">04 / FEEDBACK & REPAIR</span><h2>把错误拆开，才知道该改哪里</h2><div id="run-results"></div><div class="card" style="margin-top:16px"><h3>运行对照</h3><div style="overflow:auto"><table class="rag-history"><thead><tr><th>运行</th><th>模式</th><th>片段 / k / 阈值</th><th>现行资料</th><th>通过</th></tr></thead><tbody>${state.runs.map(e=>`<tr><td>#${e.id}</td><td>${e.data.mode==='model'?'模型':'摘录'}</td><td>${e.data.config.chunk_size} / ${e.data.config.top_k} / ${e.data.config.min_score}</td><td>${e.data.config.current_only?'是':'否'}</td><td>${e.data.passed}/${e.data.total}</td></tr>`).join('')||'<tr><td colspan="5">还没有运行记录</td></tr>'}</tbody></table></div></div></section>
    <section id="acceptance" class="workshop-section card"><span class="eyebrow">05 / TRANSFER & DELIVER</span><h2>换一份资料，你还能判断吗？</h2><p>验收要求：先完成诊断，最新实验 6 项通过，再完成下面三个迁移判断。检查记录会绑定本次运行的结果摘要。</p>${questions(state.transfer,'transfer')}<button data-action="accept" class="primary">提交迁移验收</button><div id="acceptance-result">${state.acceptance?acceptance(state.acceptance.data):''}</div></section>`;
    renderRun(latest?.data);
    const saved=state.tutor?.data;
    if(saved && saved.run_id===latest?.id){document.getElementById('tutor-question').value=saved.question;const output=document.getElementById('tutor-answer');output.hidden=false;output.textContent=saved.answer;}
  }
  function acceptance(data){return `<div class="rag-feedback"><h3>${data.passed?'本次教学任务验收通过':'还有需要补救的环节'}</h3><p>绑定运行 #${data.run_id}。${esc(data.boundary)}</p>${feedback(data.transfer)}<p>建议复习日期：${esc(data.review_at.slice(0,10))}。回想版本、证据支持和拒答三种判断。</p></div>`;}
  function renderRun(run){const target=document.getElementById('run-results');if(!run){target.innerHTML='<div class="empty">运行后会展示真实召回片段、回答、引用与逐题结果。</div>';return;}
    const failures=[...new Set(run.rows.flatMap(r=>r.evaluation.failures))];
    target.innerHTML=`<div class="card"><div class="rag-summary"><strong>${run.passed} / ${run.total}</strong><span>固定教学检查通过 · ${run.mode==='model'?'模型生成':'摘录基线'}</span><a class="text-button" href="/api/academy/learning/rag/runs/${run.id||state.runs[0].id}/export">下载可复现项目 ZIP ↓</a><a class="text-button" href="${state.code_url}">带运行上下文进入代码工作区 →</a></div><p class="small">检查覆盖既定事实字符串、引用来源和拒答。即使全部通过，也不代表生成文本的每一个语义主张都已验证。</p>${run.rows.map(r=>`<details class="rag-result"><summary><span class="${r.evaluation.passed?'pass':'fail'}">${r.evaluation.passed?'✓':'!'} ${r.evaluation.passed?'通过':'待修复'}</span><b>${esc(r.query)}</b><span class="badge">${esc(r.kind)}</span></summary><h4>实际回答</h4><pre>${esc(r.response.answer)}</pre><p class="small">引用：${esc(r.response.citations.join('、')||'无')} · ${r.response.abstain?'拒答':'作答'}</p><h4>本次召回的原文</h4>${r.chunks.map(c=>`<blockquote><b>${esc(c.id)} · 分数 ${c.score} · ${c.current?'现行':'旧版'}</b><br>${esc(c.text)}<br><small>原文字符 ${c.start}–${c.end}</small></blockquote>`).join('')||'<p>无匹配片段</p>'}<p>${r.evaluation.failures.map(f=>esc(state.guides[f].title)).join('；')||'固定检查均通过。请继续人工核对语义。'}</p></details>`).join('')}</div>${failures.map(key=>`<article class="rag-hint"><b>${esc(state.guides[key].title)}</b><div id="hint-${key}"><p>${esc(state.guides[key].hints[0])}</p></div><button data-action="hint" data-key="${key}">再给一步提示</button> <a class="text-button" href="/academy#lesson/${state.guides[key].topic}">补学相关知识 →</a></article>`).join('')}<article class="card" style="margin-top:16px"><h3>围绕本次运行追问导师</h3><label class="note-label" for="tutor-question">我的具体疑问</label><textarea id="tutor-question" maxlength="1200" placeholder="例如：为什么提高阈值后，无答案问题正确了，但打印问题反而失败？"></textarea><button class="primary" data-action="tutor">请导师给一个排查步骤</button><p class="small">将当前合成实验结果与这段问题交给系统已配置的模型；回复是指导建议，不会更改成绩。</p><div id="tutor-answer" class="rag-feedback" hidden></div></article>`;
  }
  main.addEventListener('click',async event=>{
    const button=event.target.closest('button[data-action]');if(!button||busy)return;
    const action=button.dataset.action;
    if(action==='hint'){const key=button.dataset.key;hints[key]=Math.min(2,(hints[key]||0)+1);document.getElementById(`hint-${key}`).innerHTML=state.guides[key].hints.slice(0,hints[key]+1).map(h=>`<p>${esc(h)}</p>`).join('');button.disabled=hints[key]===2;return;}
    busy=true;button.disabled=true;
    try{
      if(action==='diagnose'){const result=await api('/diagnose',{answers:answers(state.diagnostic,'diagnosis')});state=await api();document.getElementById('diagnosis-result').innerHTML=feedback(result);notify('诊断已保存。薄弱环节已给出对应补学入口。');}
      else if(action==='run'){
        const config={chunk_size:Number(document.getElementById('chunk-size').value),top_k:Number(document.getElementById('top-k').value),min_score:Number(document.getElementById('min-score').value),current_only:document.getElementById('current-only').checked};
        document.getElementById('run-status').textContent='正在运行实际检索与回答检查，请稍候…';
        await api('/run',{config,mode:document.getElementById('run-mode').value});state=await api();hints={};render();document.getElementById('results').scrollIntoView({block:'start'});notify('运行结果和配置已保存。');
      }else if(action==='tutor'){
        const response=await api('/tutor',{run_id:state.runs[0].id,question:document.getElementById('tutor-question').value});const output=document.getElementById('tutor-answer');output.hidden=false;output.textContent=response.answer;
      }else if(action==='accept'){
        if(!state.runs.length)throw Error('请先运行实验。');
        const result=await api('/accept',{run_id:state.runs[0].id,answers:answers(state.transfer,'transfer')});document.getElementById('acceptance-result').innerHTML=acceptance(result);state=await api();
      }
    }catch(error){notify(error.message);const status=document.getElementById('run-status');if(action==='run'&&status)status.textContent=error.message;}
    finally{busy=false;button.disabled=false;}
  });
  api().then(data=>{state=data;render();const section=document.getElementById(location.hash.slice(1));if(section)section.scrollIntoView({block:'start'});}).catch(error=>{main.innerHTML=`<div class="empty"><h2>暂时无法读取工作室</h2><p>${esc(error.message)}</p><button onclick="location.reload()">重新连接</button></div>`;});
})();
