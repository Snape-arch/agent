import guides from '../../../../clawos/static/assets/learning-guides.json';
import './learning-course.css';

const params=()=>new URLSearchParams(location.search);
export function learningReturnUrl(){
  const p=params(),id=p.get('learnUnit'),cid=p.get('ragCase');
  if(!cid)return '/academy/lab?'+new URLSearchParams({lesson:p.get('lesson')||({peft:'finetune',diffusion:'diffusion'}[p.get('domain')||'']||'rag')});
  const out=new URLSearchParams({ragCase:cid});if(id&&Object.keys(guides.units).includes(id))out.set('learnUnit',id);
  return '/academy/vision/?'+out+'#journey';
}
export function withLearningContext(href:string){
  const current=params(),cid=current.get('ragCase'),unit=current.get('learnUnit');
  const url=new URL(href,location.origin);if(url.origin!==location.origin)return href;
  if(cid)url.searchParams.set(url.pathname.startsWith('/academy/vision/')?'ragCase':'researchCase',cid);
  if(unit&&Object.keys(guides.units).includes(unit))url.searchParams.set('learnUnit',unit);
  return url.pathname+url.search+url.hash;
}
export function LearningContext({mode}:{mode:'mechanism'|'papers'}){
  const p=params(),id=p.get('learnUnit'),guide=id&&Object.keys(guides.units).includes(id)?guides.units[id as keyof typeof guides.units]:undefined;
  if(!guide||mode==='mechanism'&&p.get('domain')&&p.get('domain')!=='rag')return null;
  const number=Object.keys(guides.units).indexOf(id!)+1;
  return <aside className="journey-purpose" aria-label="当前学习任务"><span className="visual-kicker">来自入门路线 · 第{number}步</span><h2>{guide.question}</h2><p><strong>这次要完成：</strong>{guide.goal}</p>{mode==='mechanism'?<><p><strong>怎么观察：</strong>先写一个预测，再运行默认对照。逐题切换“包含旧版资料”和“仅现行资料”，查看来源条件怎样改变候选；最后核对有没有答非所问。</p><p>这里使用合成教学资料做CPU机制演示，不是论文实验复现，也没有运行真实向量模型。</p></>:<><p><strong>怎么观察：</strong>{guide.steps.join(' ')}</p><p>第一次操作时，在“检索对照”写预测并运行，再点候选片段定位原文；有历史实验时可先打开记录。这里的BM25是词语匹配方法；分数表示本次检索的相对排序，不是答案正确率。</p></>}<a className="visual-primary" href={learningReturnUrl()}>看完结果，回第{number}步写解释</a></aside>;
}
