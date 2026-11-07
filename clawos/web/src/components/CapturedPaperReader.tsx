import {useEffect,useState} from 'react';
import {researchApi as api,type Journey,type Paper} from './researchJourney';
type Page={page:number;pages:number;width:number;height:number;image:string;case_hash:string;raw_sha256:string;text:{text:string}[]};
/** Uses the same bounded PDF renderer as the original Paper Studio. No native PDF iframe dependency. */
export function CapturedPaperReader({paper,journey,close}:{paper:Pick<Paper,'id'|'name'|'raw_sha256'|'page_count'>;journey:Pick<Journey,'case_id'|'case_hash'>;close:()=>void}){
  const [page,setPage]=useState(1),[data,setData]=useState<Page>(),[message,setMessage]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;const controller=new AbortController();setData(undefined);setMessage('正在读取固定PDF原文…');
    api<Page>(`/cases/${journey.case_id}/papers/${paper.id}/pdf-page/${page}`,undefined,controller.signal).then(value=>{
      if(!active)return;if(value.case_hash!==journey.case_hash||value.raw_sha256!==paper.raw_sha256||value.page!==page||value.pages!==paper.page_count||!value.image.startsWith('data:image/png;base64,'))throw Error('PDF页面回执与固定来源不一致');setData(value);setMessage('');
    }).catch(e=>{if(active)setMessage((e as Error).message);});return()=>{active=false;controller.abort();};
  },[journey.case_id,paper.id,page,retry]);
  return <article className="journey-reader"><header><h3>{paper.name} · 固定原文</h3><div className="journey-actions"><button disabled={page<=1} onClick={()=>setPage(n=>n-1)}>上一页</button><label>原文页码<select value={page} onChange={e=>setPage(Number(e.target.value))}>{Array.from({length:paper.page_count},(_,i)=><option key={i+1} value={i+1}>第 {i+1} / {paper.page_count} 页</option>)}</select></label><button disabled={page>=paper.page_count} onClick={()=>setPage(n=>n+1)}>下一页</button><button onClick={close}>收起原文</button></div></header>
    {message&&<p role="status">{message} <button onClick={()=>setRetry(n=>n+1)}>重新读取页面</button></p>}
    {data&&<><div className="journey-page-canvas"><img src={data.image} width={data.width} height={data.height} alt={`${paper.name} PDF原文第${data.page}页，共${data.pages}页`} onError={()=>setMessage('原文图像未显示，请重试或下载固定PDF。')}/></div><details className="journey-page-text"><summary>复制或辅助阅读本页提取文字</summary><pre>{data.text.map(t=>t.text).join('\n')||'本页没有可提取文字，请核对原图。'}</pre></details></>}
    <p>当前为固定PDF的真实页面图像与提取文字。需要原有批注、报告和笔记时，导入共享论文库继续阅读；下载保留原文件。</p>
  </article>;
}
