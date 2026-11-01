/** Course-scoped immutable experiment records. No mastery or grade writes. */
export async function mountExperimentRecords(host, lesson) {
  const template=({rag:'rag',finetune:'peft',diffusion:'diffusion'})[lesson];
  if(!template)return;
  const section=document.createElement('section');section.className='course-experiment-records';
  const heading=document.createElement('h3');heading.textContent='实验与反思记录';section.append(heading);
  const note=document.createElement('p');note.className='muted';note.textContent='保存的机制实验与个人解释，不计入掌握度或真人学习效果。';section.append(note);host.append(section);
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
