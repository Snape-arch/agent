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
