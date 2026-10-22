/* Immutable text transactions shared by formatting, split/join and cross-block edits. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ClawDocumentTransactions=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const length=runs=>runs.reduce((n,r)=>n+r.text.length,0);
function slice(runs,start,end=length(runs)){let offset=0;return runs.flatMap(run=>{const a=Math.max(0,start-offset),z=Math.min(run.text.length,end-offset);offset+=run.text.length;return z>a?[{text:run.text.slice(a,z),marks:(run.marks||[]).map(m=>({...m}))}]:[];});}
function normalize(runs){const result=[];for(const r of runs){if(!r.text)continue;const prior=result.at(-1);if(prior&&JSON.stringify(prior.marks)===JSON.stringify(r.marks))prior.text+=r.text;else result.push({text:r.text,marks:(r.marks||[]).map(m=>({...m}))});}return result;}
function selected(runs,start,end){return slice(runs,start,end);}
function format(runs,start,end,type,remove=false,href){const middle=selected(runs,start,end).map(r=>({text:r.text,marks:type==='clear'?[]:[...(r.marks||[]).filter(m=>m.type!==type),...(!remove?[href?{type,href}:{type}]:[])]}));return normalize([...slice(runs,0,start),...middle,...slice(runs,end)]);}
function replace(runs,start,end,insert=[]){return normalize([...slice(runs,0,start),...insert,...slice(runs,end)]);}
return {length,slice,normalize,selected,format,replace};
});
