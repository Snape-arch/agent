/** Restore only a valid, accessible plan. No model, import or policy side effects. */
(async()=>{
  const params=new URLSearchParams(location.search),cid=params.get('researchCase');
  const host=document.querySelector('main');if(!host)return;
  const nav=document.createElement('nav');nav.className='research-journey-context';nav.setAttribute('aria-label','研究与学习计划');
  const a=document.createElement('a');a.textContent='文献、可视化与课程，一起继续 →';a.href='/academy/vision/#journey';nav.append(a);
  if(cid&&/^[a-f0-9]{32}$/.test(cid)){
    try{const r=await fetch('/api/vision/research/cases/'+cid+'/journey',{credentials:'same-origin'});if(!r.ok)return;const value=await r.json();if(value.case_id!==cid)return;const unit=params.get('learnUnit'),allowed=['question','representation','evidence','compare','generate','transfer'],q=new URLSearchParams({ragCase:cid});if(allowed.includes(unit))q.set('learnUnit',unit);a.href='/academy/vision/?'+q+'#journey';a.textContent=allowed.includes(unit)?'返回当前学习步骤 →':'返回当前研究学习计划 →';
      const practice=document.createElement('a');practice.href=value.links.practice;if(allowed.includes(unit)){const u=new URL(practice.href,location.origin);u.searchParams.set('learnUnit',unit);practice.href=u.pathname+u.search+u.hash;}practice.textContent='继续文献检索实验';nav.append(practice);
    }catch{return;}
  }
  host.prepend(nav);
})();
