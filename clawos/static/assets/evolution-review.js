'use strict';
(() => {
  const $=id=>document.getElementById(id), id=Number(new URLSearchParams(location.search).get('experiment'));
  let task=null,index=0,authorized=false,submitted=false,busy=false;
  const drafts=new Map();
  function status(text){$('status').textContent=text;}
  async function request(path,body){
    const response=await fetch(`/api/evolution-review/${id}/${path}`,body===undefined?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok){if(response.status===401||response.status===403){authorized=false;controls();}throw Error(data.detail||`请求失败 ${response.status}`);}
    return data;
  }
  function controls(){
    $('ratingForm').querySelectorAll('input,textarea,button').forEach(node=>node.disabled=!authorized||busy||submitted);
    if(task){$('previous').disabled=index===0||busy;$('next').disabled=index===task.packet.entries.length-1||busy;}
    $('next').textContent=submitted?'下一题':'保存草稿并下一题';
  }
  function remember(){
    const entry=task?.packet.entries[index];if(!entry)return;
    drafts.set(entry.entry_id,Object.fromEntries(['A','B'].map(label=>[label,{score:$('score'+label).value,rationale:$('rationale'+label).value,critical_error:$('critical'+label).checked,text_digest:entry.options[label].text_digest}])));
  }
  function complete(value){return value&&['A','B'].every(label=>value[label].score!==''&&Number.isFinite(Number(value[label].score))&&Number(value[label].score)>=0&&Number(value[label].score)<=1&&value[label].rationale.trim());}
  function show(focus=false){
    const entries=task.packet.entries,entry=entries[index];$('workspace').hidden=!entry;
    if(!entry){status(task.role==='adjudicator'?'当前没有待裁决分歧。':'评审包为空。');return;}
    $('mode').textContent=task.role==='adjudicator'?'分歧裁决':'成对盲评';$('question').textContent=entry.query;
    $('navigator').replaceChildren(...entries.map((item,i)=>{const option=document.createElement('option');option.value=i;option.textContent=`第 ${i+1} 题${complete(drafts.get(item.entry_id))?(submitted?' · 已冻结':' · 草稿完整'):''}`;return option;}));$('navigator').value=index;
    for(const label of ['A','B']){const value=drafts.get(entry.entry_id)?.[label];$('answer'+label).textContent=entry.options[label].text;$('score'+label).value=value?.score??'';$('rationale'+label).value=value?.rationale??'';$('critical'+label).checked=value?.critical_error??false;}
    $('prior').hidden=task.role!=='adjudicator';$('priorContent').replaceChildren();
    for(const review of task.packet.prior_ratings||[]){const rating=review.ratings.find(item=>item.entry_id===entry.entry_id);if(!rating)continue;for(const label of ['A','B']){const p=document.createElement('p'),value=rating.options[label];p.textContent=`评审 ${review.reviewer} · ${label} · ${value.score}${value.critical_error?' · 严重错误':''}\n${value.rationale}`;$('priorContent').append(p);}}
    $('progress').textContent=`${index+1} / ${entries.length} 题 · ${entries.filter(item=>complete(drafts.get(item.entry_id))).length} 份${submitted?'已冻结判断':'完整草稿'}`;
    $('submit').textContent=task.role==='adjudicator'?'提交当前题裁决':'提交整份评审';controls();if(focus)$('question').focus();
  }
  async function load(){
    if(!Number.isSafeInteger(id)||id<1){status('链接缺少有效实验编号。请使用组织者提供的评审链接。');return;}
    remember();busy=true;controls();
    try{const nextTask=await request('packet');if(task&&task.viewer.id!==nextTask.viewer.id)drafts.clear();task=nextTask;authorized=true;submitted=task.role==='reviewer'&&task.summary.submitted;
      if(submitted)for(const rating of task.packet.own_ratings||[])drafts.set(rating.entry_id,rating.options);
      for(const key of drafts.keys())if(!task.packet.entries.some(entry=>entry.entry_id===key))drafts.delete(key);
      index=Math.min(index,Math.max(0,task.packet.entries.length-1));$('identity').textContent=`${task.viewer.name} · 实验 #${id} · ${task.role==='adjudicator'?'裁决者':'评审者'}`;status(submitted?'你的评审已经提交，原始判断已冻结。':`${task.summary.provider_execution_verified?'应用已捕获模型调用':'外部提供的答案，执行来源未验证'}。请独立评分并说明依据。`);show();}
    catch(error){status(`${error.message} 当前页面内存草稿保留；恢复授权后可重新核对权限。`);}
    finally{busy=false;controls();}
  }
  function move(next){remember();index=next;show(true);}
  $('refresh').addEventListener('click',load);$('navigator').addEventListener('change',event=>move(Number(event.target.value)));$('previous').addEventListener('click',()=>move(Math.max(0,index-1)));$('next').addEventListener('click',()=>move(Math.min(task.packet.entries.length-1,index+1)));
  $('ratingForm').addEventListener('input',()=>{remember();$('progress').textContent=`${index+1} / ${task.packet.entries.length} 题 · ${task.packet.entries.filter(item=>complete(drafts.get(item.entry_id))).length} 份完整草稿`;});
  $('ratingForm').addEventListener('submit',async event=>{
    event.preventDefault();if(!authorized||busy||submitted)return;remember();
    const entries=task.role==='adjudicator'?[task.packet.entries[index]]:task.packet.entries;
    const missing=entries.find(entry=>!complete(drafts.get(entry.entry_id)));if(missing){index=task.packet.entries.indexOf(missing);show(true);status('请完成每题两个答案的评分和依据后提交。');return;}
    const ratings=entries.map(entry=>({entry_id:entry.entry_id,options:Object.fromEntries(Object.entries(drafts.get(entry.entry_id)).map(([label,value])=>[label,{...value,score:Number(value.score)}]))}));
    busy=true;controls();
    try{const body={packet_digest:task.packet.packet_digest};if(task.role==='adjudicator'){Object.assign(body,ratings[0],{review_set_digest:task.summary.authenticated_review_set_digest});await request('adjudication',body);drafts.delete(entries[0].entry_id);busy=false;await load();}else{await request('ratings',{...body,ratings});submitted=true;status('整份评审已提交并冻结。后续分歧由另一位授权会话用户裁决。');}}
    catch(error){status(`提交未完成：${error.message}。当前草稿保留，请核对权限或评审版本后重试。`);}
    finally{busy=false;controls();}
  });
  window.addEventListener('beforeunload',event=>{if(!submitted&&drafts.size){event.preventDefault();event.returnValue='';}});
  load();
})();
