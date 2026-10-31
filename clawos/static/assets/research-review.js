/* Private review packets share only explicitly assigned claims and excerpts. */
(() => {
  'use strict';
  const root=document.getElementById('review-app');if(!root)return;
  const labels={supported:'证据支持',contradicted:'证据反驳',insufficient:'证据不足',needs_full_text:'需要全文'};
  const issueLabels={quantity:'数值',unit:'单位',polarity:'否定与方向',scope:'范围',population:'研究人群',causality:'因果',uncertainty:'不确定性',version:'版本',correction:'更正与撤稿',time:'时间',comparison:'比较条件',citation:'引用依据',none:'未发现上述问题'};
  const statuses={awaiting_two_reviews:'等待双评',account_agreement:'双账户标签一致',needs_adjudication:'存在分歧，待仲裁',account_adjudicated:'已由仲裁账户记录判断',blind_review:'独立填写，暂不显示同伴判断'};
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  const message=el('p','', 'review-message');message.setAttribute('role','status');
  async function api(path='',data){const r=await fetch('/api/research/watch/reviews'+path,{credentials:'same-origin',method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});let v;try{v=await r.json();}catch(_){throw new Error('评审服务响应异常');}if(!r.ok)throw new Error(typeof v.detail==='string'?v.detail:'评审请求失败');return v;}
  function button(text,fn){const b=el('button',text);b.type='button';b.addEventListener('click',async()=>{b.disabled=true;try{await fn();}catch(e){message.textContent=e.message;}finally{b.disabled=false;}});return b;}
  function field(text,input){const l=el('label',text);l.append(input);return l;}
  function input(name,type='text'){const n=el('input');n.name=name;n.type=type;return n;}
  function option(select,value,text){const n=el('option',text);n.value=value;select.append(n);}
  function download(name,text,type){const u=URL.createObjectURL(new Blob([text],{type})),a=el('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
  const create=el('details',undefined,'review-create');create.append(el('summary','建立评审轮'));
  const form=el('form'),kind=el('select');kind.name='kind';kind.setAttribute('aria-label','评审资料来源');
  for(const [v,n] of [['benchmark','三领域公开文献候选集'],['report','已有冻结证据报告'],['ai','已完成的AI草稿']])option(kind,v,n);
  form.append(field('评审资料来源',kind));
  const report=input('report_id'),job=input('job_id'),domain=input('domain'),limit=input('limit','number');domain.value='AI方法';limit.value='20';limit.min='1';limit.max='40';limit.required=true;
  const reportLabel=field('冻结报告ID',report),jobLabel=field('AI任务ID',job),domainLabel=field('资料所属领域',domain);
  form.append(reportLabel,jobLabel,domainLabel,field('最多纳入主张数（1–40）',limit));
  const sharing=el('details');sharing.append(el('summary','分配独立评审账户（可选）'),el('p','留空时建立私人自评轮。分配时仅分享本轮主张和摘录，不授予原订阅、报告或本地全文权限；不会创建账户或发送消息。','muted'));
  const peer1=input('peer1'),peer2=input('peer2'),judge=input('judge'),share=input('share','checkbox');
  for(const [label,n] of [['评审账户一ID',peer1],['评审账户二ID',peer2],['仲裁账户ID',judge]])sharing.append(field(label,n));
  sharing.append(field('我确认将本轮主张与摘录授权给上述三个现有账户',share));form.append(sharing);
  const submit=el('button','建立冻结评审轮');submit.type='submit';form.append(submit);create.append(form);
  function sourceFields(){reportLabel.hidden=kind.value==='benchmark';jobLabel.hidden=kind.value!=='ai';domainLabel.hidden=kind.value==='benchmark';report.required=kind.value!=='benchmark';job.required=kind.value==='ai';}
  kind.addEventListener('change',sourceFields);sourceFields();
  const history=el('select');history.setAttribute('aria-label','已有评审轮');history.id='research-review-history';
  const output=el('div');output.id='research-review-output';root.append(create,field('已有评审轮',history),button('刷新评审列表',loadList),message,output);
  async function loadList(){const current=history.value,data=await api();history.replaceChildren();option(history,'','选择已有评审轮');for(const r of data.items)option(history,r.id,`${{benchmark:'三领域候选',report:'证据报告',ai:'AI草稿'}[r.kind]} · ${new Date(r.created*1000).toLocaleString('zh-CN')} · ${r.owned?'我的评审轮':'分配给我'} · ${r.id.slice(0,8)}`);history.value=current;}
  history.addEventListener('change',()=>{if(history.value)load(history.value).catch(e=>message.textContent=e.message);});
  form.addEventListener('submit',async e=>{e.preventDefault();submit.disabled=true;try{const data={kind:kind.value,limit:Number(limit.value)};if(kind.value!=='benchmark')Object.assign(data,{report_id:report.value.trim(),domain:domain.value.trim()});if(kind.value==='ai')data.job_id=job.value.trim();if(peer1.value.trim()||peer2.value.trim()||judge.value.trim()){if(!share.checked)throw new Error('请先确认此次摘录授权范围');data.reviewer_ids=[peer1.value.trim(),peer2.value.trim()];data.adjudicator_id=judge.value.trim();}const value=await api('',data);await loadList();history.value=value.id;render(value);message.textContent='冻结评审轮已建立。尚未形成独立真人评审结论。';}catch(err){message.textContent=err.message;}finally{submit.disabled=false;}});
  window.addEventListener('research-review-source',e=>{kind.value=e.detail.kind;report.value=e.detail.report_id || '';job.value=e.detail.job_id || '';peer1.value=peer2.value=judge.value='';share.checked=false;sourceFields();create.open=true;document.getElementById('review-workbench').scrollIntoView({behavior:'smooth',block:'start'});});
  async function load(id){render(await api('/'+encodeURIComponent(id)));}
  function render(value){
    output.replaceChildren(el('h3','逐主张核对'),el('p',value.boundary,'watch-policy'),el('p',`纳入 ${value.coverage.selected}/${value.coverage.available} 项；未纳入 ${value.coverage.omitted} 项。角色：${{owner:'创建者（自评不计双评）',reviewer:'独立评审账户',adjudicator:'分歧仲裁账户'}[value.role]}`,'muted'));
    if(value.summary){const s=value.summary;output.append(el('p',`等待有效评审 ${s.pending} 项 · 已双评 ${s.double_reviewed} 项 · 未解决分歧 ${s.unresolved_conflicts} 项`,'review-metrics'));output.append(el('p',s.agreement_rate===null?'尚无双评，一致率不计算。':`双账户标签一致率 ${(s.agreement_rate*100).toFixed(1)}%；这不是学术正确率。`,'muted'));for(const [name,m] of Object.entries(value.domains))output.append(el('p',`${name}：共 ${m.total} 项，已双评 ${m.double_reviewed}，待完成 ${m.pending}。`,'muted'));output.append(button('导出评审 JSON',async()=>{const v=await api('/'+value.id+'/export');download('literature-review.json',JSON.stringify(v.data,null,2),'application/json');}),button('导出评审 Markdown',async()=>{const v=await api('/'+value.id+'/export');download('literature-review.md',v.markdown,'text/markdown;charset=utf-8');}));
      if(value.assignments.length){const members=el('details');members.append(el('summary','本轮摘录授权'));for(const a of value.assignments){const row=el('p',`${a.actor} · ${a.role==='reviewer'?'评审':'仲裁'} `);row.append(button('撤销本轮授权',async()=>{if(!window.confirm('撤销该账户对本评审轮的读取与提交权限？原记录保留，但不再计入有效双评。'))return;render(await api('/'+value.id+'/revoke/'+encodeURIComponent(a.actor),{}));}));members.append(row);}output.append(members);}
    }
    const filter=el('select');filter.setAttribute('aria-label','评审领域筛选');option(filter,'','全部领域');for(const d of new Set(value.cases.map(c=>c.domain)))option(filter,d,d);
    const list=el('div'),pageLabel=el('p'),prev=el('button','上一组'),next=el('button','下一组');prev.type=next.type='button';let offset=0;
    prev.addEventListener('click',()=>{offset=Math.max(0,offset-5);draw();});next.addEventListener('click',()=>{offset+=5;draw();});
    output.append(field('评审领域筛选',filter),list,prev,pageLabel,next);filter.addEventListener('change',()=>{offset=0;draw();});
    function draw(){const cases=value.cases.filter(c=>!filter.value||c.domain===filter.value);list.replaceChildren();for(const c of cases.slice(offset,offset+5))list.append(card(c,value));prev.disabled=offset===0;next.disabled=offset+5>=cases.length;pageLabel.textContent=`第 ${Math.floor(offset/5)+1} 组 · 当前领域 ${cases.length} 项`;}
    draw();
  }
  function card(c,round){
    const detail=el('details',undefined,'review-case');detail.append(el('summary',`${c.id} · ${c.domain} · ${statuses[c.status] || c.status}`));let built=false;
    detail.addEventListener('toggle',()=>{if(!detail.open||built)return;built=true;detail.append(el('p',c.claim,'review-claim'));
      if(c.origin==='constructed_claim_control')detail.append(el('p','此主张是构造的评审控制样本，不能当作论文作者或真实模型说过的话。','muted'));
      const refs=el('div');for(const r of c.evidence){const box=el('article',undefined,'review-source');box.append(el('h4',r.title),el('blockquote',r.quote));const evidence=r.evidence || {},url=r.url || evidence.source_url;if(url){try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol)||parsed.username||parsed.password)throw new Error();const a=el('a','打开公开来源');a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';box.append(a);}catch(_){}}box.append(el('p',r.boundary || `${evidence.basis || '冻结摘录'} · 原文位置 ${evidence.start}–${evidence.end}`,'muted'),el('code',r.fragment_sha256 || evidence.sha256 || ''));if(r.capture)box.append(el('p',r.capture.verified ? `公开原文定位核对通过 · ${r.capture.captured}；不是专家语义验收。` : `公开原文抓取尚未核验${r.capture.http_status ? ' · HTTP '+r.capture.http_status : ''}，请核对来源。`,'review-capture'));refs.append(box);}detail.append(refs);
      if(c.curator_proposal){const proposal=el('details');proposal.append(el('summary','查看助手拟定的候选标签（非专家标准）'),el('p',`${labels[c.curator_proposal.verdict]}：${c.curator_proposal.reason}`));detail.append(proposal);}
      if(c.mechanical_check){const audit=el('details');audit.append(el('summary','查看机械检查边界（仅创建者可见）'),el('p',c.mechanical_check.kept?'现有机械守卫放行；仍需语义复核。':'现有机械守卫要求复核，不等于已判定学术错误。'),el('p',c.mechanical_check.boundary,'muted'));detail.append(audit);}
      for(const v of c.peer_votes){detail.append(el('p',`${v.actor}：${labels[v.verdict]} · ${v.reason}`,'review-judgment'));}
      if(c.adjudication)detail.append(el('p','仲裁记录：'+labels[c.adjudication.verdict]+' · '+c.adjudication.reason,'review-judgment'));
      if(c.own_vote){detail.append(el('p',`${c.own_vote.self_review?'我的自评（不计双评）':'我已提交'}：${labels[c.own_vote.verdict]} · ${c.own_vote.reason}`,'review-judgment'),el('p','该判断已冻结，不能在看到同伴结果后修改；更改需新建评审轮。','muted'));return;}
      if(round.role==='adjudicator'&&c.status!=='needs_adjudication'){detail.append(el('p','等待两名评审提交并形成分歧后，才开放仲裁。','muted'));return;}
      const form=el('form'),verdict=el('select');verdict.setAttribute('aria-label',c.id+' 判断');for(const [v,n] of Object.entries(labels))option(verdict,v,n);verdict.value='insufficient';form.append(field('证据判断',verdict));
      const issues=el('select');issues.multiple=true;issues.size=4;for(const [v,n] of Object.entries(issueLabels))option(issues,v,n);for(const o of issues.options)o.selected=c.tags.includes(o.value);form.append(field('重点核对项（可多选）',issues));
      const evidenceChecks=[];for(const r of c.evidence){const n=input('evidence','checkbox');n.value=r.id;evidenceChecks.push(n);form.append(field('采用依据：'+r.title,n));}
      const reason=el('textarea');reason.rows=3;reason.required=true;reason.minLength=12;reason.maxLength=1200;form.append(field('判断理由：说明原文如何支持、反驳或不足以判断',reason));
      const confirmed=input('confirmed','checkbox');confirmed.required=true;form.append(field('我已本人阅读这些依据；此声明不认证真实身份或独立性',confirmed));
      const save=el('button',round.role==='owner'?'保存自评（不计双评）':round.role==='adjudicator'?'提交仲裁判断':'提交独立判断');save.type='submit';form.append(save);
      form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{const result=await api('/'+round.id+'/cases/'+encodeURIComponent(c.id),{verdict:verdict.value,reason:reason.value,issues:[...issues.selectedOptions].map(o=>o.value),evidence_ids:evidenceChecks.filter(n=>n.checked).map(n=>n.value),human_confirmed:confirmed.checked});render(result);message.textContent='本轮判断已冻结保存。账户记录不自动构成学术验收。';}catch(err){message.textContent=err.message;save.disabled=false;}});detail.append(form);
    });return detail;
  }
  loadList().catch(e=>message.textContent=e.message);
})();
