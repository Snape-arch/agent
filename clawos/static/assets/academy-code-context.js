"use strict";
/* Explicit handoff from learning to the existing code workspace. No execution. */
if(new URLSearchParams(location.search).get('workshop')==='rag'){
  const host=document.createElement('section');host.className='academy-module-heading';
  const heading=document.createElement('h2');heading.textContent='来自 RAG 实战路径';host.append(heading);
  const status=document.createElement('p');status.textContent='正在读取同一学习者的运行上下文…';host.append(status);
  const back=document.createElement('a');back.href='/academy/rag#results';back.textContent='返回实验结果与验收 →';host.append(back);
  document.querySelector('main').prepend(host);
  fetch('/api/academy/learning/rag').then(r=>{if(!r.ok)throw Error();return r.json();}).then(state=>{
    const latest=state.runs[0];if(!latest){status.textContent='尚无实验运行，请先返回实战路径完成一次运行。';return;}
    status.textContent=`运行 #${latest.id}：${latest.data.passed}/${latest.data.total} 项固定检查通过。配置、资料摘要与逐题结果随项目包提供。下载后在本地运行并扩展；这里不会自动执行代码或修改掌握度。`;
    const download=document.createElement('a');download.href=`/api/academy/learning/rag/runs/${latest.id}/export`;download.textContent='下载本次项目包 ↓';download.style.marginLeft='20px';host.append(download);
  }).catch(()=>{status.textContent='运行上下文读取失败，请返回实战路径重试。';});
}

if(new URLSearchParams(location.search).has('material')){
  const params=new URLSearchParams(location.search),mid=params.get('material'),task=params.get('task');
  if(/^[a-f0-9]{32}$/.test(mid)&&/^\d+$/.test(task)){
    const host=document.createElement('section');host.className='academy-module-heading';
    const title=document.createElement('h2');title.textContent='来自我的学习材料';host.append(title);
    const status=document.createElement('p');status.textContent='正在核对教材版本与项目运行…';host.append(status);
    const back=document.createElement('a');back.href=`/academy/materials?material=${mid}&step=project`;back.textContent='返回材料与项目验收 →';host.append(back);document.querySelector('main').prepend(host);
    fetch(`/api/academy/learning/materials/${mid}`).then(r=>{if(!r.ok)throw Error();return r.json();}).then(state=>{
      const run=state.events.find(e=>e.kind==='project'&&String(e.data.task_id)===task)?.data;
      if(!run){status.textContent='未找到对应项目证据，请返回材料工作区核对。';return;}
      status.textContent=`${state.document.title} · 任务 #${task} · ${run.report.passed}/${run.report.total} 项测试通过。项目包包含代码、输入与真实报告，可在本地继续扩展。`;
      const download=document.createElement('a');download.href=`/api/academy/learning/materials/${mid}/projects/${task}/export`;download.textContent='下载已执行项目 ↓';download.style.marginLeft='20px';host.append(download);
    }).catch(()=>status.textContent='无法读取项目上下文，请返回材料重试。');
  }
}
