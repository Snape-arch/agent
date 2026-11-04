/** Course-scoped immutable experiment records. No mastery or grade writes. */
export async function mountExperimentRecords(host, lesson) {
  const template=({rag:'rag',finetune:'peft',diffusion:'diffusion'})[lesson];
  if(!template)return;
  const section=document.createElement('section');section.className='course-experiment-records';
  const heading=document.createElement('h3');heading.textContent='实验与反思记录';section.append(heading);
  const note=document.createElement('p');note.className='muted';note.textContent='保存的机制实验与个人解释，不计入掌握度或真人学习效果。';section.append(note);host.append(section);
  if(lesson==='rag')void mountLiteratureRecords(host);
  try {
    const response=await fetch('/api/vision/teaching/reports?template='+template,{credentials:'same-origin'});
    if(!section.isConnected)return;
    if(response.status===403){note.textContent='机制实验当前限本机所有者；教材协作权限不包含实验访问。';return;}
    if(!response.ok)throw Error('无法读取实验记录，请稍后刷新。');
    const data=await response.json();if(!section.isConnected)return;
    if(!data.items.length){note.textContent+=' 完成配套实验后，可从这里重新打开。';return;}
    const list=document.createElement('ul');
    for(const item of data.items.slice(0,5)) {
      const li=document.createElement('li'),a=document.createElement('a');
      a.href='/academy/vision/?lesson='+encodeURIComponent(lesson)+'&teachingReport='+encodeURIComponent(item.id)+'#teaching';
      a.textContent=item.title+' · '+new Date(item.created).toLocaleString('zh-CN')+' · '+(item.reflections?'已写反思':'待反思');
      li.append(a);list.append(li);
    }
    section.append(list);
  }catch(error){if(section.isConnected)note.textContent=error.message;}
}

async function mountLiteratureRecords(host){
  const section=document.createElement('section');section.className='course-experiment-records';
  const heading=document.createElement('h3');heading.textContent='真实文献实践';section.append(heading);
  const note=document.createElement('p');note.className='muted';note.textContent='全文检索对照与独立迁移回答，等待教师复核。';section.append(note);host.append(section);
  try{
    const response=await fetch('/api/vision/research/history',{credentials:'same-origin'});
    if(!section.isConnected)return;
    if(response.status===403){note.textContent='文献实验当前仅本机所有者可访问。';return;}
    if(!response.ok)throw Error('文献实践记录暂时无法读取。');
    const value=await response.json();if(!section.isConnected)return;
    const list=document.createElement('ul');
    for(const item of value.items.slice(0,5)){
      const li=document.createElement('li'),a=document.createElement('a');a.href='/academy/vision/?ragCase='+encodeURIComponent(item.case_id)+'&ragRun='+encodeURIComponent(item.id)+'#rag-lab';
      a.textContent='全文范围对照 · '+new Date(item.created*1000).toLocaleString('zh-CN')+' · '+(item.reflections?'已保存迁移回答':'待迁移练习');li.append(a);list.append(li);
    }
    section.append(list);const start=document.createElement('a');start.href='/academy/vision/?domain=rag#rag-lab';start.textContent='打开RAG全文实践';section.append(start);
  }catch(error){if(section.isConnected)note.textContent=error.message;}
}
