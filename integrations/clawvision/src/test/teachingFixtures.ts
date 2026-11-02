/** Explicitly constructed test evidence; never imported by the product. */
import type { Direction, TeachingArm, TeachingRecord } from '../visualizations/teachingData';
export function teachingFixture(topic:Direction):TeachingRecord {
  const arm=(i:number):TeachingArm=>{
    if(topic==='rag')return {config:{current_only:!!i},metric:4+i,metrics:{passed:4+i,total:6},curve:[],evidence:{rows:[{case_id:'loan',query:'器材借用期限是多少天？',chunks:[{id:'loan:'+i,title:i?'现行规定':'旧版规定',text:i?'器材借用期限为7天。':'器材借用期限为14天。',score:.5,current:!!i,start:0,end:12}],response:{answer:i?'器材借用期限为7天。':'器材借用期限为14天。',abstain:false,citations:['loan:'+i]},evaluation:{passed:!!i,failures:i?[]:['citation']}},{case_id:'missing',query:'停车价格是多少？',chunks:[],response:{answer:'资料不足，无法回答。',abstain:true,citations:[]},evaluation:{passed:true,failures:[]}}]}};
    if(topic==='peft'){const rank=i+1;return {config:{rank},metric:i?.1:.3,metrics:{trainable_parameters:12*rank,full_layer_parameters:36},curve:[{step:0,test:.8},{step:10,test:i?.1:.3}],evidence:{adapter_a:Array.from({length:rank},(_,r)=>Array.from({length:6},(_,c)=>r===c?1:0)),adapter_b:Array.from({length:6},(_,r)=>Array.from({length:rank},(_,c)=>r===0?c+2:0))}};}
    return {config:{steps:i?2:1},metric:i?.1:.2,metrics:{score_evaluations:i?384:256},curve:[{step:0,time:1,mean:0,variance:1},...(i?[{step:1,time:.5,mean:1,variance:.5}]:[]),{step:i?2:1,time:0,mean:1.9,variance:.3}],evidence:{final_quantiles:[1,1.5,2,2.5],target_quantiles:[1.1,1.6,2.1,2.6]}};
  };
  return {hash:'test-only-'+topic,reflection_version:0,report:{id:({rag:'a',peft:'b',diffusion:'c'})[topic].repeat(32),created:'2026-11-02T01:00:00Z',hypothesis:'Synthetic prediction for UI mechanism checks.',lesson:{id:topic==='peft'?'finetune':topic,title:'合成测试课程'},result:{template:{id:topic,title:'合成测试 · '+topic,unit:'测试单位'},arms:[arm(0),arm(1)],boundary:'合成测试夹具，不是论文或真实学习验证。',execution:'real_cpu_synthetic_fixture',paper_reproduction_verified:false}}};
}
