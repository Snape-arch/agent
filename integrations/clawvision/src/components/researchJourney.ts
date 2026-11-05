export const researchBase='/api/vision/research';
export async function researchApi<T>(path:string,body?:unknown,signal?:AbortSignal):Promise<T>{
  const response=await fetch(researchBase+path,{credentials:'same-origin',method:body===undefined?'GET':'POST',signal,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'操作未完成');return value;
}
export type ReadingNote={version:number;status:'unread'|'reading'|'read';folder:string;tags:string[];note:string};
export type Paper={id:string;name:string;title:string;version:string;date:string;category:string;abstract:string;raw_sha256:string;page_count:number;pdf_url:string;note:ReadingNote;import_record:{status?:string;reader_url?:string;material_url?:string;teacher_url?:string}};
export type Unit={id:string;title:string;lesson:string;minutes:number;papers:string[];explanation:string;prompt:string;view:'visuals'|'rag-lab'|'journey';checkpoint?:{version:number;explanation:string}};
export type Journey={case_id:string;case_hash:string;overview_id:string;subscription_id:string;papers:Paper[];units:Unit[];links:{overview:string;course:string;practice:string;mechanism:string;review:string;agent:string};boundary:string};
export type Question={id:string;label:string;query:string;kind:'fact'|'comparison'|'insufficiency'};
export type ModelJob={id:string;case_id:string;status:string;created:number;hash:string;result:{question:Question;top_k:number;error_type?:string;calls:{arm:string;provider:string;model:string;duration_ms:number|null;usage:Record<string,number>}[];arms:{scope:string;context_characters:number;references:{id:string;title:string;quote:string;page:number;paper_key:string;evidence:{source_url:string;raw_sha256:string;start:number;end:number}}[];answer:{outcome:string;reason:string;claims:{id:string;text:string;citations:string[]}[];withheld:{id:string;text:string;reason:string}[]}}[]}};
