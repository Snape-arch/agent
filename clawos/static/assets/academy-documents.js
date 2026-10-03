/* Structured document editor: stored text is never treated as trusted HTML. */
(function(){
"use strict";
const $=id=>document.getElementById(id), base="/api/academy/learning/documents";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clone=v=>structuredClone(v), id=()=>crypto.randomUUID(), rich=window.ClawRichText;
const inline=window.markdownit({html:false,linkify:false,breaks:true});
new ResizeObserver(entries=>document.documentElement.style.setProperty('--doc-toolbar-height',entries[0].target.getBoundingClientRect().height+'px')).observe($('docInsert').closest('.doc-toolbar'));
inline.renderer.rules.image=(tokens,index)=>esc(tokens[index]?.content||"图片");
let me=null,doc=null,selected=null,undo=[],redo=[],dirty=false,saving=null,timer=null,conflict=false,reading=false,suggestion="",suggestionAnchor=null;
let strokes=[],activeStroke=null,drawingId=null;
let cacheTimer=null,outlineTimer=null,lastInput=0,inputTarget=null,remotePending=false;
const block=(type="paragraph",text="")=>({id:id(),type,text,...(type==="heading"?{level:2}:type==="code"?{language:"python"}:type==="table"?{cells:[["项目","观察","依据"],["","",""],["","",""]]}:type==="drawing"?{strokes:[]}:type==="todo"?{checked:false}:{})});
function status(s){if($("docStatus").textContent!==s)$("docStatus").textContent=s;}
async function api(path="",data,method){const r=await fetch(base+path,{method:method||(data?"POST":"GET"),headers:data?{"Content-Type":"application/json"}:{},body:data?JSON.stringify(data):undefined});const v=await r.json();if(!r.ok){const e=Error(v.detail||"请求失败");e.status=r.status;throw e;}return v;}
function draftKey(nid=doc?.id){return "clawos_document_draft_"+(me?.id||"local-user")+"_"+(nid||"new");}
function legacyDraftKey(nid){return "clawos_document_draft_"+(nid||"new");}
function readDraft(nid){try{return JSON.parse(localStorage.getItem(draftKey(nid))||((me?.id||'local-user')==='local-user'?localStorage.getItem(legacyDraftKey(nid)):null)||"null");}catch(e){return null;}}
function cache(){try{localStorage.setItem(draftKey(),JSON.stringify(doc));return true;}catch(e){status("设备草稿空间不足，请立即保存或导出文档。");return false;}}
function weight(d){return (d?.blocks||[]).reduce((n,b)=>n+(b.text?.length||0)*3+(b.data?.length||0)+(b.inline?.length||0)*160+(b.strokes||[]).reduce((a,s)=>a+s.points.length*32,0)+(b.cells||[]).flat().reduce((a,c)=>a+c.length*2,0),0);}
function checkpoint(){if(!doc)return;undo.push(clone(doc));let total=undo.reduce((n,d)=>n+weight(d),0);while(undo.length>1&&(undo.length>40||total>24*1024*1024))total-=weight(undo.shift());redo=[];lastInput=0;}
function inputCheckpoint(e){if(reading||!editable())return;const key=e.target.closest('[data-block]')?.dataset.block||e.target.id,now=performance.now();if(key!==inputTarget||now-lastInput>800)checkpoint();inputTarget=key;lastInput=now;}
function changed(){dirty=true;clearTimeout(cacheTimer);cacheTimer=setTimeout(cache,250);status("编辑中 · 等待保存");clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),900);clearTimeout(outlineTimer);outlineTimer=setTimeout(outline,400);}
async function save(){
 clearTimeout(timer);if(!doc)return;if(conflict)throw Error("请先处理版本冲突");if(saving){await saving;if(dirty)return save();return doc;}
 if(!dirty&&doc.id)return doc;
 if(doc.role&&!editable())throw Error("当前权限不能保存修改；可导出设备草稿。");
 const before=clone(doc);before.merge=true;dirty=false;cache();status("保存中…");
 saving=(async()=>{try{const result=await api(before.id?"/"+before.id:"",before,before.id?"PUT":"POST");
 const oldKey=draftKey(before.id);
 const concurrent=JSON.stringify(result.blocks)!==JSON.stringify(before.blocks)||result.title!==before.title||result.context!==before.context;
 if(dirty&&concurrent){doc.id=result.id;if(!before.id)doc.version=result.version;remotePending=true;cache();status('保存已合并，但仍有新输入；保留草稿并再次合并。');return doc;}
 if(!dirty){const prior=doc;doc=result;if(concurrent){undo=[];redo=[];}patchDocument(prior);}
 else{doc.id=result.id;doc.version=result.version;doc.updated_at=result.updated_at;}
 remotePending=false;connectLive(true);
 localStorage.removeItem(oldKey);if((me?.id||'local-user')==='local-user')localStorage.removeItem(legacyDraftKey(before.id));if(dirty)cache();else localStorage.removeItem(draftKey());
 const u=new URL(location.href);u.searchParams.set("document",doc.id);history.replaceState(null,"",u);
 status((concurrent?"已合并并保存":"已保存")+" · 版本 "+doc.version);await library();return doc;
 }catch(e){dirty=true;if(e.status===409){conflict=true;$("docCopy").hidden=false;$("docReload").hidden=false;}cache();status(e.message);throw e;}finally{saving=null;}})();
 return saving;
}
async function library(){try{const r=await api();$("docLibrary").innerHTML=r.documents.map(d=>'<button data-document="'+esc(d.id)+'" class="'+(doc?.id===d.id?"active":"")+'">'+esc(d.title)+'</button>').join("");}catch(e){status("文档列表读取失败："+e.message);}}
async function open(nid){
 if(doc&&(dirty||saving))await save();
 window.ClawDocumentLive.close();liveId=null;const loaded=await api("/"+nid);const draft=readDraft(nid);
 doc=draft||loaded;doc.role=loaded.role;reading=!!doc.role&&!['owner','editor'].includes(doc.role);dirty=!!draft&&!reading;conflict=!!draft&&draft.version!==loaded.version;
 undo=[];redo=[];selected=null;$("docCopy").hidden=!conflict;$("docReload").hidden=!conflict;
 history.replaceState(null,"","?document="+nid);render();connectLive();await library();
 status(conflict?"已恢复设备草稿；服务器版本已变化，请另存或载入最新。":draft?"已恢复未保存草稿。":"已保存 · 版本 "+doc.version);
}
async function newDoc(){
 if(doc&&(dirty||saving))await save();
 const params=new URLSearchParams(location.search);
 window.ClawDocumentLive.close();liveId=null;doc={title:params.get("title")?.slice(0,200)||"我的学习文档",context:params.get("source")?.slice(0,1000)||"",blocks:[block("heading","核心问题"),block("paragraph",""),block("heading","我的解释与证据"),block("quote",""),block("heading","下一步验证"),block("todo","")]};
 undo=[];redo=[];conflict=false;selected=doc.blocks[1].id;dirty=true;render();cache();await save();
}
function tools(b){return '<div class="block-tools"><button class="block-drag" data-op="drag" draggable="'+(!reading&&editable())+'" aria-label="拖动内容块；也可使用上移或下移按钮">移动</button><button data-op="up" aria-label="上移内容块">↑</button><button data-op="down" aria-label="下移内容块">↓</button><button data-op="duplicate">复制块</button><button data-op="delete" aria-label="删除内容块">删除</button>'+(b.type==="heading"?'<select data-field="level" aria-label="标题级别">'+[1,2,3].map(x=>'<option '+(x===b.level?"selected":"")+'>'+x+'</option>').join("")+'</select>':"")+'</div>';}
function edit(text,label="内容",field="text",runs){return '<div class="block-edit" contenteditable="'+!reading+'" role="textbox" aria-multiline="true" aria-label="'+label+'" data-field="'+field+'" data-placeholder="写下你的理解，输入 / 插入…">'+(runs?rich.render(runs):inline.renderInline(String(text||'')))+'</div>';}

function serializeInline(element){return rich.markdown(rich.spans(element));}
let textRange=null;
function sourceLabel(){const value=doc?.context||'';$('docSourceLabel').textContent=value.startsWith('meeting:')?'会议原文 · '+(value.match(/version=(\d+)/)?.[1]?'版本 '+value.match(/version=(\d+)/)[1]:'来源快照'):value?value.split(/[?#]/)[0].slice(0,90):'添加原文定位';}
function requestLink(){return new Promise(resolve=>{const dialog=$('linkDialog');$('selectionToolbar').hidden=true;$('linkError').textContent='';$('linkUrl').value='';let answer=null;dialog.onclose=()=>resolve(answer);$('linkCancel').onclick=()=>dialog.close();$('linkForm').onsubmit=e=>{e.preventDefault();const value=$('linkUrl').value.trim();if(!/^(https?:\/\/|mailto:)/i.test(value)){$('linkError').textContent='请输入 HTTP、HTTPS 或 mailto 链接。';return;}answer=value;dialog.close();};dialog.showModal();$('linkUrl').focus();});}
function insertChoices(){const search=$('insertSearch').value.trim().toLowerCase();const types=[...$('docInsert').options].filter(o=>o.value&&o.textContent.toLowerCase().includes(search));$('insertResults').innerHTML=types.map(o=>'<button data-insert-type="'+o.value+'">'+esc(o.textContent)+'<small>Enter 插入</small></button>').join('')||'<p>没有匹配的内容块。</p>';}
function openInsert(){if(reading||!editable())return;$('insertSearch').value='';insertChoices();$('insertDialog').showModal();$('insertSearch').focus();}
$('insertSearch').oninput=insertChoices;
$('insertSearch').onkeydown=e=>{if(e.key==='Enter'){const first=$('insertResults').querySelector('button');if(first){e.preventDefault();first.click();}}};
$('insertResults').onclick=e=>{const type=e.target.closest('[data-insert-type]')?.dataset.insertType;if(type){$('insertDialog').close();insert(type);}};
$('insertClose').onclick=()=>$('insertDialog').close();
for(const [key,bodyClass] of [['docOutlineToggle','doc-outline-open'],['docAssistToggle','doc-assist-open']])$(key).onclick=()=>{document.body.classList.remove('doc-focus');$('docFocus').textContent='专注写作';$(key).setAttribute('aria-expanded',document.body.classList.toggle(bodyClass)?'true':'false');};
function updateSelectionToolbar(){const s=window.getSelection(),bar=$('selectionToolbar');bar.hidden=true;if(s?.rangeCount){const r=s.getRangeAt(0),host=r.commonAncestorContainer.nodeType===1?r.commonAncestorContainer:r.commonAncestorContainer.parentElement;if(host?.closest?.(".block-edit")){textRange=r.cloneRange();if(!r.collapsed&&!reading&&editable()&&!document.querySelector('dialog[open]')){const rect=r.getBoundingClientRect();bar.hidden=false;bar.style.left=Math.max(8,Math.min(innerWidth-260,rect.left))+'px';bar.style.top=Math.max(58,rect.top-46)+'px';}}}}
document.addEventListener('selectionchange',updateSelectionToolbar);
document.querySelectorAll('[role=toolbar]').forEach(toolbar=>toolbar.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)||!e.target.matches('button,select'))return;const controls=[...toolbar.querySelectorAll('button:not(:disabled),select:not(:disabled)')].filter(c=>!c.hidden),index=controls.indexOf(document.activeElement);if(index<0||!controls.length)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?controls.length-1:(index+(e.key==='ArrowRight'?1:controls.length-1))%controls.length;controls[next].focus();}));
document.addEventListener('scroll',updateSelectionToolbar,true);
document.querySelectorAll("[data-format]").forEach(b=>{b.addEventListener("mousedown",e=>e.preventDefault());b.onclick=()=>format(b.dataset.format);});
function selectOffsets(host,start,end){
 const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT,{acceptNode(n){return n.nodeType===3||n.tagName==='BR'?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP;}});const units=[];let n,total=0;while(n=walker.nextNode()){units.push({node:n,start:total,length:n.nodeType===3?n.nodeValue.length:1});total+=units.at(-1).length;}
 function point(offset){for(const unit of units){if(offset<=unit.start+unit.length){if(unit.node.nodeType===3)return [unit.node,Math.max(0,offset-unit.start)];const parent=unit.node.parentNode,index=[...parent.childNodes].indexOf(unit.node);return [parent,index+(offset>unit.start?1:0)];}}return [host,host.childNodes.length];}
 const range=document.createRange();range.setStart(...point(start));range.setEnd(...point(end));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);textRange=range.cloneRange();
}
async function format(kind){
 const currentSelection=window.getSelection();if(currentSelection?.rangeCount){const currentRange=currentSelection.getRangeAt(0),container=currentRange.commonAncestorContainer.nodeType===1?currentRange.commonAncestorContainer:currentRange.commonAncestorContainer.parentElement;if(container?.closest('.block-edit'))textRange=currentRange.cloneRange();}
 if(reading||!editable()||!textRange||textRange.collapsed){status('请先选择正文中的文字，再设置格式。');return;}
 const host=(textRange.commonAncestorContainer.nodeType===1?textRange.commonAncestorContainer:textRange.commonAncestorContainer.parentElement).closest('.block-edit');
 if(!host||!host.isConnected||!host.isContentEditable||!host.contains(textRange.startContainer)||!host.contains(textRange.endContainer)){status('跨块文字请分块设置格式，当前内容未修改。');return;}if(!['paragraph','heading','quote','callout','bullet','numbered','todo'].includes(doc.blocks.find(b=>b.id===host.closest('[data-block]').dataset.block)?.type)){status('该内容块的说明暂不支持富文本格式。');return;}
 let href;if(kind==='link'){href=await requestLink();if(!href||reading||!editable()||!host.isConnected)return;}
 const before=textRange.cloneRange();before.selectNodeContents(host);before.setEnd(textRange.startContainer,textRange.startOffset);const holder=document.createElement('div');holder.append(before.cloneContents());const start=rich.spans(holder,false).reduce((n,s)=>n+s.text.length,0);holder.replaceChildren(textRange.cloneContents());const length=rich.spans(holder,false).reduce((n,s)=>n+s.text.length,0),end=start+length;
 const runs=rich.spans(host),parts=[];let offset=0;for(const run of runs){const a=offset,z=a+run.text.length;offset=z;const left=Math.max(a,start),right=Math.min(z,end);if(left>=right){parts.push({...run,selected:false});continue;}if(left>a)parts.push({...run,text:run.text.slice(0,left-a),selected:false});parts.push({...run,text:run.text.slice(left-a,right-a),selected:true});if(right<z)parts.push({...run,text:run.text.slice(right-a),selected:false});}
 const type=kind==='inlinecode'?'code':kind,remove=kind!=='link'&&parts.filter(p=>p.selected).every(p=>p.marks.some(m=>m.type===type));checkpoint();
 const inlineRuns=parts.map(({selected,...part})=>{if(!selected)return part;let marks=kind==='clear'?[]:part.marks.filter(m=>m.type!==type);if(kind!=='clear'&&!remove)marks.push(href?{type:'link',href}:{type});return {...part,marks};});
 const b=doc.blocks.find(b=>b.id===host.closest('[data-block]').dataset.block);b.inline=inlineRuns;b.text=rich.markdown(inlineRuns);host.innerHTML=rich.render(inlineRuns);selectOffsets(host,start,end);changed();
}

function renderBlock(b){
 let body="";
 if(b.type==="code")body='<div class="code-head"><input aria-label="代码语言" data-field="language" value="'+esc(b.language)+'" '+(reading?'readonly':'')+'><button data-op="copy-code">复制代码</button></div><textarea aria-label="代码内容" data-field="text" maxlength="30000" spellcheck="false" '+(reading?"readonly":"")+'>'+esc(b.text)+'</textarea>'+(reading?'<pre class="code-highlight" aria-label="代码阅读"><code>'+rich.highlight(b.text,b.language)+'</code></pre>':'');
 else if(b.type==="table")body='<div class="table-scroll"><table><tbody>'+b.cells.map((r,i)=>'<tr>'+r.map((c,j)=>'<td contenteditable="'+!reading+'" role="textbox" aria-label="第'+(i+1)+'行第'+(j+1)+'列" data-cell="'+i+','+j+'">'+esc(c)+'</td>').join("")+'</tr>').join("")+'</tbody></table></div><div class="table-actions">'+[["row","＋ 行"],["column","＋ 列"],["remove-row","－ 行"],["remove-column","－ 列"]].map(([op,t])=>'<button data-op="'+op+'">'+t+'</button>').join("")+'</div>';
 else if(b.type==="drawing")body='<canvas width="900" height="480" role="'+(reading?'img':'button')+'" tabindex="'+(reading?-1:0)+'" aria-label="'+(reading?'文档绘图':'编辑绘图')+'" data-op="drawing"></canvas>'+edit(b.text,"绘图说明");
 else if(b.type==="image")body='<img loading="lazy" decoding="async" src="'+esc(b.data)+'" alt="'+esc(b.text||"文档插图")+'">'+edit(b.text,"图片说明");
 else if(b.type==="divider")body="<hr>";
 else body=(b.type==="bullet"?'<span class="list-marker">•</span>':b.type==="numbered"?'<span class="list-marker">'+(doc.blocks.filter(x=>x.type==="numbered").findIndex(x=>x.id===b.id)+1)+'.</span>':"")+(b.type==="todo"?'<input type="checkbox" aria-label="待办完成状态" data-field="checked" '+(b.checked?"checked":"")+' '+(reading?"disabled":"")+'>':"")+(reading?'<div class="block-edit" '+(b.type==='heading'?'role="heading" aria-level="'+b.level+'"':'')+'>'+(b.inline?rich.render(b.inline):ClawChatContent.render(b.text))+'</div>':edit(b.text,b.type==="heading"?"章节标题":"内容",'text',b.inline));
 return '<section class="doc-block '+b.type+(selected===b.id?" selected":"")+'" data-block="'+b.id+'" data-indent="'+(b.indent||0)+'" data-level="'+(b.level||2)+'">'+tools(b)+body+'</section>';
}
function patchDocument(prior){
 const active=document.activeElement,focusId=active?.closest('[data-block]')?.dataset.block;
 const old=new Map((prior?.blocks||[]).map(b=>[b.id,b])),nodes=new Map([...$('docBlocks').children].map(n=>[n.dataset.block,n]));
 for(const [index,b] of doc.blocks.entries()){let node=nodes.get(b.id);if(!node||JSON.stringify(old.get(b.id))!==JSON.stringify(b)){const template=document.createElement('template');template.innerHTML=renderBlock(b);const next=template.content.firstElementChild;if(node)node.replaceWith(next);node=next;if(b.type==='drawing')draw(node.querySelector('canvas'),b.strokes);}if($('docBlocks').children[index]!==node)$('docBlocks').insertBefore(node,$('docBlocks').children[index]||null);nodes.delete(b.id);}
 nodes.forEach(n=>n.remove());if(active?.id==='docTitle'){}else $('docTitle').value=doc.title;if(active?.id!=='docContext')$('docContext').value=doc.context||'';sourceLabel();outline();permissions();
 if(focusId&&!document.contains(active)){$('docBlocks').querySelector('[data-block="'+focusId+'"] [contenteditable=true], [data-block="'+focusId+'"] textarea')?.focus();}
}
let liveId=null,liveConnected=false;
function connectLive(force=false){if(!doc?.id||(!force&&liveId===doc.id))return;liveId=doc.id;liveConnected=false;
 window.ClawDocumentLive.connect({id:doc.id,version:doc.version,status(message){liveConnected=message==='实时协作已连接';$('docLiveStatus').textContent=message;if(liveConnected&&dirty&&!conflict&&!saving&&editable()){clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),500);}},presence(r){if(doc.role!==r.role){if(dirty)cache();doc.role=r.role;reading=!editable();if(reading)clearTimeout(timer);render();}collabRender(r);},denied(error){liveConnected=false;doc.role='viewer';reading=true;clearTimeout(timer);cache();render();$('docLiveStatus').textContent=error.message;},document(update){if(!doc||update.id!==doc.id||update.version<=doc.version)return;if(dirty||saving||conflict){remotePending=true;return;}const prior=doc,map=new Map(doc.blocks.map(b=>[b.id,b]));for(const b of update.blocks)map.set(b.id,b);if(update.order.some(id=>!map.has(id))){liveId=null;connectLive();return;}doc={...doc,...update,blocks:update.order.map(id=>map.get(id))};undo=[];redo=[];lastInput=0;patchDocument(prior);status('已实时同步 · 版本 '+doc.version);}});
}
function render(){if(!doc)return;$('selectionToolbar').hidden=true;permissions();$("docTitle").value=doc.title;$("docContext").value=doc.context||"";sourceLabel();$("docBlocks").innerHTML=doc.blocks.map(renderBlock).join("");for(const b of doc.blocks.filter(b=>b.type==="drawing"))draw($("docBlocks").querySelector('[data-block="'+b.id+'"] canvas'),b.strokes);outline();$("docUndo").disabled=reading||!editable()||!undo.length;$("docRedo").disabled=reading||!editable()||!redo.length;}
function outline(){$("docOutline").innerHTML=(doc?.blocks||[]).filter(b=>b.type==="heading").map(b=>'<button data-outline="'+b.id+'">'+esc(b.text||"无标题")+'</button>').join("");}
function insert(type,extra={}){
 if(reading)return;if(type==="image"){$("docImageFile").click();return;}if(type==="drawing"){openDrawing();return;}
 mutate(()=>{const b={...block(type),...extra};const i=doc.blocks.findIndex(b=>b.id===selected);doc.blocks.splice(i<0?doc.blocks.length:i+1,0,b);selected=b.id;});
 $("docBlocks").querySelector('[data-block="'+selected+'"] [data-field="text"]')?.focus();
}
function mutate(fn){if(reading)return;checkpoint();fn();changed();render();}
function draw(canvas,list){
 if(!canvas)return;const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);
 for(const s of list){const p=s.points;if(p.length<2)continue;ctx.strokeStyle=s.color;ctx.lineWidth=3;ctx.lineCap="round";ctx.beginPath();const a=[p[0][0]*w,p[0][1]*h],z=[p.at(-1)[0]*w,p.at(-1)[1]*h];ctx.moveTo(...a);
 if(s.tool==="rect")ctx.rect(a[0],a[1],z[0]-a[0],z[1]-a[1]);else if(s.tool==="arrow"){ctx.lineTo(...z);const angle=Math.atan2(z[1]-a[1],z[0]-a[0]);for(const d of [-.45,.45]){ctx.moveTo(...z);ctx.lineTo(z[0]-16*Math.cos(angle+d),z[1]-16*Math.sin(angle+d));}}
 else for(const q of p.slice(1))ctx.lineTo(q[0]*w,q[1]*h);ctx.stroke();}
}
function openDrawing(b){if(reading)return;drawingId=b?.id||null;strokes=clone(b?.strokes||[]);activeStroke=null;$("drawCaption").value=b?.text||"";$("drawDialog").showModal();draw($("drawCanvas"),strokes);}
function point(e){const r=$("drawCanvas").getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
const canvas=$("drawCanvas");
canvas.addEventListener("pointerdown",e=>{if(strokes.length>=500)return;activeStroke={tool:$("drawTool").value,color:$("drawColor").value,points:[point(e)]};canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener("pointermove",e=>{if(!activeStroke)return;if(activeStroke.tool==="pen"){if(activeStroke.points.length<4000)activeStroke.points.push(point(e));}else activeStroke.points[1]=point(e);draw(canvas,[...strokes,activeStroke]);});
function endDraw(e){if(!activeStroke)return;if(activeStroke.points.length===1)activeStroke.points.push(point(e));strokes.push(activeStroke);activeStroke=null;draw(canvas,strokes);}
canvas.addEventListener("pointerup",endDraw);canvas.addEventListener("pointercancel",()=>{activeStroke=null;draw(canvas,strokes);});
$('drawAddShape').onclick=()=>{const fields=['drawStartX','drawStartY','drawEndX','drawEndY'].map($);if(fields.some(n=>!n.checkValidity())||strokes.length>=500){$('drawCoordinateStatus').textContent='坐标需在 0–100 之间，最多 500 笔。';return;}const [x,y,a,b]=fields.map(n=>Number(n.value)/100);strokes.push({tool:$('drawTool').value,color:$('drawColor').value,points:[[x,y],[a,b]]});draw(canvas,strokes);$('drawCoordinateStatus').textContent='图形已添加，可撤销后重新输入。';};
$("drawUndo").onclick=()=>{strokes.pop();draw(canvas,strokes);};$("drawClear").onclick=()=>{strokes=[];draw(canvas,strokes);};
$("drawInsert").onclick=()=>{if(activeStroke){status("请先结束当前笔迹");return;}mutate(()=>{let b=doc.blocks.find(b=>b.id===drawingId);if(!b){b=block("drawing");const i=doc.blocks.findIndex(b=>b.id===selected);doc.blocks.splice(i<0?doc.blocks.length:i+1,0,b);}b.strokes=clone(strokes);b.text=$("drawCaption").value;selected=b.id;});$("drawDialog").close();};
$("docBlocks").addEventListener("focusin",e=>{const node=e.target.closest("[data-block]");if(node){selected=node.dataset.block;if(doc?.id){clearTimeout(presenceTimer);presenceTimer=setTimeout(()=>collaboration(cp()+'/presence',{block_id:selected}).catch(()=>{}),250);}document.querySelectorAll(".doc-block").forEach(n=>n.classList.toggle("selected",n===node));}});
let presenceTimer=null;
let draggedBlock=null;
function clearDrag(){draggedBlock=null;document.querySelectorAll('.drag-over,.dragging').forEach(n=>n.classList.remove('drag-over','dragging'));}
$('docBlocks').addEventListener('dragstart',e=>{const handle=e.target.closest('.block-drag');if(!handle||reading||!editable()){e.preventDefault();return;}draggedBlock=handle.closest('[data-block]').dataset.block;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',draggedBlock);handle.closest('[data-block]').classList.add('dragging');});
$('docBlocks').addEventListener('dragover',e=>{const target=e.target.closest('[data-block]');if(!draggedBlock||!target||reading||!editable())return;e.preventDefault();document.querySelectorAll('.drag-over').forEach(n=>n.classList.remove('drag-over'));target.classList.add('drag-over');e.dataTransfer.dropEffect='move';});
$('docBlocks').addEventListener('drop',e=>{const target=e.target.closest('[data-block]'),source=draggedBlock;clearDrag();if(!source||!target||reading||!editable())return;e.preventDefault();const targetId=target.dataset.block;if(source===targetId)return;mutate(()=>{const from=doc.blocks.findIndex(b=>b.id===source);if(from<0)return;const [moved]=doc.blocks.splice(from,1);const to=doc.blocks.findIndex(b=>b.id===targetId);doc.blocks.splice(to<0?doc.blocks.length:to,0,moved);selected=source;});status('内容块已移动，支持撤销。');});
$('docBlocks').addEventListener('dragend',clearDrag);
$('docBlocks').addEventListener('beforeinput',e=>{const limit=e.target.dataset.cell?2000:30000;if(e.target.isContentEditable&&typeof e.data==='string'&&e.target.textContent.length-(window.getSelection()?.toString().length||0)+e.data.length>limit){e.preventDefault();status('当前内容超过 '+limit+' 字，请拆成多个内容块。');return;}inputCheckpoint(e);});
$("docBlocks").addEventListener("input",e=>{if(reading)return;const b=doc.blocks.find(b=>b.id===e.target.closest("[data-block]")?.dataset.block);if(!b)return;if(e.target.dataset.cell){const [r,c]=e.target.dataset.cell.split(",").map(Number);b.cells[r][c]=e.target.innerText;}else{const field=e.target.dataset.field;if(field){if(e.target.isContentEditable){if(['paragraph','heading','quote','callout','bullet','numbered','todo'].includes(b.type)){b.inline=rich.spans(e.target);b.text=rich.markdown(b.inline);}else b.text=serializeInline(e.target);}else b[field]=e.target.type==="checkbox"?e.target.checked:field==="level"?Number(e.target.value):e.target.value;}}changed();$("docUndo").disabled=reading||!editable()||!undo.length;$("docRedo").disabled=reading||!editable()||!redo.length;});
$("docBlocks").addEventListener("change",e=>{if(e.target.dataset.field==="level"){const b=doc.blocks.find(b=>b.id===e.target.closest("[data-block]")?.dataset.block);mutate(()=>{b.level=Number(e.target.value);});}});
$("docBlocks").addEventListener("click",async e=>{const node=e.target.closest("[data-block]"),button=e.target.closest("[data-op]");if(!node||!button)return;selected=node.dataset.block;const i=doc.blocks.findIndex(b=>b.id===selected),b=doc.blocks[i],op=button.dataset.op;
 if(op==="copy-code"){try{await navigator.clipboard.writeText(b.text);status("代码已复制");}catch(e){status("复制不可用，请选择代码后手动复制");}return;}if(reading||op==='drag')return;if(op==="drawing"){openDrawing(b);return;}
 mutate(()=>{if(op==="delete"){doc.blocks.splice(i,1);if(!doc.blocks.length)doc.blocks.push(block());selected=doc.blocks[Math.min(i,doc.blocks.length-1)].id;}
 if(op==="up"&&i>0)[doc.blocks[i-1],doc.blocks[i]]=[doc.blocks[i],doc.blocks[i-1]];
 if(op==="down"&&i<doc.blocks.length-1)[doc.blocks[i+1],doc.blocks[i]]=[doc.blocks[i],doc.blocks[i+1]];
 if(op==="duplicate"){const copy={...clone(b),id:id()};doc.blocks.splice(i+1,0,copy);selected=copy.id;}
 if(op==="row"&&b.cells.length<50)b.cells.push(b.cells[0].map(()=>""));if(op==="column"&&b.cells[0].length<12)b.cells.forEach(r=>r.push(""));
 if(op==="remove-row"&&b.cells.length>1)b.cells.pop();if(op==="remove-column"&&b.cells[0].length>1)b.cells.forEach(r=>r.pop());});
});
$("docBlocks").addEventListener("keydown",e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'&&e.target.isContentEditable){e.preventDefault();const range=document.createRange();range.selectNodeContents(e.target);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);textRange=range.cloneRange();updateSelectionToolbar();return;}
 if(reading)return;if(e.key==="/"&&e.target.isContentEditable&&!e.target.innerText.trim()){e.preventDefault();openInsert();return;}
 if(e.key==="Tab"&&e.target.tagName==="TEXTAREA"){e.preventDefault();checkpoint();const t=e.target,a=t.selectionStart,z=t.selectionEnd;t.setRangeText("  ",a,z,"end");doc.blocks.find(b=>b.id===t.closest("[data-block]").dataset.block).text=t.value;changed();}
 if(e.key==="Enter"&&e.target.dataset.op==="drawing")openDrawing(doc.blocks.find(b=>b.id===e.target.closest("[data-block]").dataset.block));
});
$("docBlocks").addEventListener("paste",e=>{
 if(reading||!editable()||!e.target.isContentEditable)return;e.preventDefault();
 try{const selection=window.getSelection();if(!selection.rangeCount)return;const range=selection.getRangeAt(0),host=e.target.closest('.block-edit,[data-cell]');if(!host||!host.contains(range.startContainer)||!host.contains(range.endContainer))throw Error('请在同一内容块内粘贴。');
 const text=e.clipboardData.getData('text/plain'),html=e.clipboardData.getData('text/html');const rows=host.dataset.cell?null:rich.clipboard(html,text,block,document);
 if(rows&&rows.some(b=>b.text.length>30000||(b.inline?.length||0)>4000||(b.cells||[]).flat().some(c=>c.length>2000)))throw Error('粘贴的块或表格单元格过长，请拆分内容');if(rows&&(rows.length>1||rows[0].type!=='paragraph')){if(doc.blocks.length+rows.length-1>300)throw Error('文档最多 300 个块');const current=doc.blocks.find(b=>b.id===host.closest('[data-block]').dataset.block);const before=document.createElement('div'),after=document.createElement('div'),left=range.cloneRange(),right=range.cloneRange();left.selectNodeContents(host);left.setEnd(range.startContainer,range.startOffset);right.selectNodeContents(host);right.setStart(range.endContainer,range.endOffset);before.append(left.cloneContents());after.append(right.cloneContents());
 mutate(()=>{const index=doc.blocks.indexOf(current),prefix=rich.spans(before),suffix=rich.spans(after),parts=[];if(prefix.length)parts.push({...current,inline:prefix,text:rich.markdown(prefix)});parts.push(...rows);if(suffix.length)parts.push({...block('paragraph'),inline:suffix,text:rich.markdown(suffix)});if(doc.blocks.length-1+parts.length>300)throw Error('文档最多 300 个块');doc.blocks.splice(index,1,...parts);selected=parts.at(-1).id;});$('docBlocks').querySelector('[data-block="'+selected+'"] [contenteditable=true]')?.focus();
 }else{if(host.textContent.length-range.toString().length+(rows?.[0]?.inline?rows[0].inline.reduce((n,s)=>n+s.text.length,0):text.length)>(host.dataset.cell?2000:30000))throw Error('粘贴内容超过当前块长度限制');checkpoint();range.deleteContents();let fragment;if(rows?.[0]?.inline){const holder=document.createElement('template');holder.innerHTML=rich.render(rows[0].inline);fragment=holder.content;}else fragment=document.createTextNode(rows?.[0]?.text||text);const last=fragment.lastChild||fragment;range.insertNode(fragment);range.setStartAfter(last);range.collapse(true);selection.removeAllRanges();selection.addRange(range);host.dispatchEvent(new Event('input',{bubbles:true}));}
 status('已粘贴并保留支持的格式；外部图片与脚本不会插入。');}catch(error){status('粘贴失败：'+error.message);}
});
$("docTitle").addEventListener("beforeinput",inputCheckpoint);$("docContext").addEventListener("beforeinput",inputCheckpoint);
$("docTitle").oninput=()=>{doc.title=$("docTitle").value;changed();};$("docContext").oninput=()=>{doc.context=$("docContext").value;sourceLabel();changed();};
$("docInsert").onchange=e=>{const type=e.target.value;e.target.value="";if(type)insert(type);};
$("docAdd").onclick=()=>insert("paragraph");$("docFocus").onclick=()=>{const on=document.body.classList.toggle("doc-focus");$("docFocus").textContent=on?"退出专注":"专注写作";$('docOutlineToggle').setAttribute('aria-expanded',String(!on&&document.body.classList.contains('doc-outline-open')));$('docAssistToggle').setAttribute('aria-expanded',String(!on&&document.body.classList.contains('doc-assist-open')));};
$("docPreview").onclick=()=>{reading=!reading;document.body.classList.toggle("doc-reading",reading);$("docPreview").textContent=reading?"继续编辑":"阅读预览";$("docTitle").readOnly=reading;$("docContext").readOnly=reading;for(const nid of ["docInsert","docTemplate","docImport","docAdd"]){$(nid).disabled=reading;}render();$("docBlocks").querySelectorAll('input[data-field="language"]').forEach(n=>n.readOnly=reading);};
$("docUndo").onclick=()=>{if(!undo.length)return;redo.push(clone(doc));const meta={id:doc.id,version:doc.version};doc={...undo.pop(),...meta};changed();render();};
$("docRedo").onclick=()=>{if(!redo.length)return;undo.push(clone(doc));const meta={id:doc.id,version:doc.version};doc={...redo.pop(),...meta};changed();render();};
$("docSave").onclick=()=>save().catch(e=>status(e.message));$("docNew").onclick=()=>newDoc().catch(e=>status(e.message));
$("docLibrary").onclick=e=>{const nid=e.target.closest("[data-document]")?.dataset.document;if(nid)open(nid).catch(e=>status(e.message));};
$("docOutline").onclick=e=>{const bid=e.target.closest("[data-outline]")?.dataset.outline;if(bid)$("docBlocks").querySelector('[data-block="'+bid+'"]')?.scrollIntoView({behavior:"smooth",block:"center"});if(bid)$('docBlocks').querySelector('[data-block="'+bid+'"] [contenteditable=true]')?.focus({preventScroll:true});};
$("docTemplate").onchange=e=>{const key=e.target.value;e.target.value="";const titles={cornell:["线索与问题","自己的解释","例子与反例","一句话总结","复盘问题"],concept:["定义","机制与条件","一个例子","反例与边界","原文依据"],experiment:["假设","方法与变量","实际结果","失败与限制","下一步验证"]}[key];if(titles)mutate(()=>{for(const title of titles)doc.blocks.push(block("heading",title),block(title==="原文依据"?"quote":"paragraph",""));});};
$("docImageFile").onchange=async e=>{const file=e.target.files[0];e.target.value="";if(!file)return;if(file.size>2*1024*1024){status("图片需小于 2 MB");return;}try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});mutate(()=>{const b={...block("image",file.name),data};const i=doc.blocks.findIndex(b=>b.id===selected);doc.blocks.splice(i<0?doc.blocks.length:i+1,0,b);selected=b.id;});}catch(e){status("图片读取失败");}};
function markdownBlocks(text){const rows=[];let code=null,lines=[];for(const line of text.split(/\r?\n/)){const fence=line.match(/^(\x60{3,}|~{3,})([\w+#.-]*)/);if(fence){if(code&&line.startsWith(code.fence)){rows.push({...block("code",lines.join("\n")),language:code.language||"text"});code=null;lines=[];}else if(!code){code={fence:fence[1],language:fence[2]};}else lines.push(line);continue;}if(code){lines.push(line);continue;}const heading=line.match(/^(#{1,3})\s+(.+)/),todo=line.match(/^- \[([ xX])\]\s*(.*)/);if(heading)rows.push({...block("heading",heading[2]),level:heading[1].length});else if(todo)rows.push({...block("todo",todo[2]),checked:todo[1].toLowerCase()==="x"});else if(line.startsWith("> "))rows.push(block("quote",line.slice(2)));else if(line.trim())rows.push(block("paragraph",line));}if(code)rows.push({...block("code",lines.join("\n")),language:code.language||"text"});return rows;}
$("docImport").onclick=()=>$("docImportFile").click();
$("docImportFile").onchange=async e=>{const file=e.target.files[0];e.target.value="";if(!file)return;try{if(file.size>8*1024*1024)throw Error("导入文件需小于 8 MB");const text=await file.text();let blocks=file.name.endsWith(".json")?JSON.parse(text).blocks:markdownBlocks(text);if(!Array.isArray(blocks)||!blocks.length||blocks.length+doc.blocks.length>300)throw Error("导入内容块格式或数量无效");
 const validated=await api("",{title:"导入 · "+file.name.slice(0,100),context:"",blocks:blocks.map(b=>({...b,id:id()}))});
 mutate(()=>{doc.blocks.push(...validated.blocks);});status("已导入；保留了原始文档。");
 }catch(err){status("导入失败："+err.message);}};
$("docExport").onchange=async e=>{const format=e.target.value;e.target.value="";if(!format)return;try{await save();const a=document.createElement("a");a.href=base+"/"+doc.id+"/export?format="+format;a.click();}catch(err){status(err.message);}};
$("docHistory").onclick=async()=>{try{await save();const r=await api("/"+doc.id+"/history");if(!document.body.classList.contains('doc-assist-open'))$('docAssistToggle').click();$("docVersions").hidden=false;$("docVersions").innerHTML=r.versions.map(v=>'<button data-version="'+v.version+'">版本 '+v.version+' · '+esc(v.created_at)+'</button>').join("");$("docVersions").onclick=e=>{const n=Number(e.target.dataset.version),v=r.versions.find(v=>v.version===n);if(v)mutate(()=>{doc.title=v.title;doc.context=v.context;doc.blocks=clone(v.blocks);});};status("选择历史版本可恢复为新版本，当前内容仍可撤销。");}catch(e){status(e.message);}};
$("docCopy").onclick=async()=>{try{const before=clone(doc),old=draftKey();delete before.id;delete before.version;before.title=(before.title+" · 草稿副本").slice(0,200);const result=await api("",before);localStorage.removeItem(old);doc=result;dirty=false;conflict=false;$("docCopy").hidden=true;$("docReload").hidden=true;history.replaceState(null,"","?document="+doc.id);render();await library();status("草稿已另存为副本。");}catch(e){status(e.message);}};
$("docReload").onclick=async()=>{try{const latest=await api("/"+doc.id);checkpoint();doc=latest;dirty=false;conflict=false;$("docCopy").hidden=true;$("docReload").hidden=true;localStorage.removeItem(draftKey());render();status("已载入最新版本；原草稿可撤销恢复。");}catch(e){status(e.message);}};
document.querySelectorAll("[data-assist]").forEach(button=>button.onclick=async()=>{const b=doc.blocks.find(b=>b.id===selected);if(!b?.text?.trim()){$("docAssistStatus").textContent="请先选择一个有文字的内容块。";return;}button.disabled=true;suggestionAnchor=b.id;$("docAssistStatus").textContent="正在请求导写建议…";try{const r=await api("/assist",{text:b.text.slice(0,12000),mode:button.dataset.assist,document_id:doc.id});suggestion=r.draft;$("docSuggestion").textContent=suggestion;$("docSuggestion").hidden=false;$("docAccept").hidden=false;$("docAssistStatus").textContent=r.boundary;}catch(e){$("docAssistStatus").textContent=e.message;}finally{button.disabled=false;}});
$("docAccept").onclick=()=>{selected=suggestionAnchor;insert("quote",{text:"导写建议（待复核）\n"+suggestion});$("docAccept").hidden=true;};
document.addEventListener("keydown",e=>{if(e.ctrlKey||e.metaKey){if(["b","i"].includes(e.key.toLowerCase())){e.preventDefault();format(e.key.toLowerCase()==="b"?"bold":"italic");}if(e.key.toLowerCase()==="s"){e.preventDefault();save().catch(e=>status(e.message));}if(e.key.toLowerCase()==="z"){e.preventDefault();(e.shiftKey?$("docRedo"):$("docUndo")).click();}}if(e.key==="Escape"&&!$("drawDialog").open&&document.body.classList.contains("doc-focus"))$("docFocus").click();});
function editable(){return !doc?.role||['owner','editor'].includes(doc.role);}
function permissions(){
 const can=editable();if(!can)reading=true;
 document.body.classList.toggle('doc-reading',reading);
 for(const key of ['docTitle','docContext'])$(key).readOnly=reading||!can;
 $('docSave').disabled=!can;$('docPreview').disabled=!can;
 for(const key of ['docInsert','docTemplate','docImport','docAdd','docAccept'])$(key).disabled=reading||!can;
 $('docUndo').disabled=reading||!can||!undo.length;$('docRedo').disabled=reading||!can||!redo.length;
 $('docNew').disabled=!!me&&me.id!=='local-user';
 document.querySelectorAll('[data-format]').forEach(b=>b.disabled=reading||!can);document.querySelectorAll('[data-assist]').forEach(b=>b.disabled=!can);
 $('collabOwner').hidden=doc?.role!=='owner';$('collabFeishu').disabled=doc?.role!=='owner';
 $('collabSend').disabled=doc?.role==='viewer';$('collabComment').disabled=doc?.role==='viewer';
}
async function collaboration(path,data){
 const r=await fetch('/api/collaboration'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});
 const v=await r.json();if(!r.ok){const e=Error(v.detail||'协作请求失败');e.status=r.status;throw e;}return v;
}
const cp=()=>'/documents/'+doc.id;
function localTime(value){const date=new Date(String(value).replace(' ','T')+'Z');return Number.isNaN(date.getTime())?value:date.toLocaleString('zh-CN',{hour12:false});}
function collabRender(r){
 document.querySelectorAll('.remote-presence').forEach(n=>n.remove());
 for(const person of r.online){if(person.user_id===me?.id||!person.block_id)continue;const target=$('docBlocks').querySelector('[data-block="'+CSS.escape(person.block_id)+'"]');if(target){const badge=document.createElement('span');badge.className='remote-presence';badge.textContent=person.name+' 正在此处';badge.setAttribute('aria-label',person.name+' 正在编辑此内容块');target.append(badge);}}

 $('collabPeople').textContent=({owner:'所有者',editor:'可编辑',commenter:'可评论',viewer:'仅阅读'}[r.role])+' · 在线：'+(r.online.map(p=>p.name).join('、')||'暂无');
 $('collabComments').innerHTML=r.comments.map(c=>'<article class="collab-comment '+(c.resolved?'resolved':'')+'"><b>'+esc(c.name)+'</b><small>版本 '+c.version+' · '+esc(localTime(c.created_at))+(c.version<doc.version?' · 请对照该历史版本':'')+(c.block_id&&!doc.blocks.some(b=>b.id===c.block_id)?' · 原内容块已移除':'')+'</small><p>'+esc(c.text)+'</p>'+(c.block_id?'<button data-comment-anchor="'+esc(c.block_id)+'">定位内容块</button>':'')+(!c.resolved&&(c.user_id===me?.id||r.role==='owner')?'<button data-resolve="'+esc(c.id)+'">标为已解决</button>':'')+'</article>').join('')||'<p>暂无评论，选择一个内容块开始讨论。</p>';
 $('collabMembers').innerHTML=r.members.map(m=>'<div class="collab-member"><strong>'+esc(m.name)+'</strong><span class="role-chip">'+esc({owner:'所有者',editor:'可编辑',commenter:'可评论',viewer:'仅阅读'}[m.role]||m.role)+'</span>'+(m.role!=='owner'?'<button data-revoke="'+esc(m.user_id)+'">撤销访问</button>':'')+'</div>').join('');
 const actions={invite:'生成邀请',join:'加入协作',edit:'保存文档',revoke:'撤销访问',comment:'发表评论',resolve:'解决评论'};
 $('collabAudit').innerHTML=r.audit.map(a=>'<p>'+esc(actions[a.action]||a.action)+' · '+esc(localTime(a.created_at))+'</p>').join('')||'<p>仅所有者可查看协作记录。</p>';
}
async function syncCollaboration(){
 if(!doc?.id||document.hidden)return;const nid=doc.id;
 try{await collaboration(cp()+'/presence',{block_id:selected||''});const r=await collaboration(cp());if(doc?.id!==nid)return;
 const identityChanged=r.viewer_id&&r.viewer_id!==me?.id,roleChanged=doc.role!==r.role;
 if(identityChanged){if(dirty)cache();me=await collaboration('/me');undo=[];redo=[];clearTimeout(timer);if(dirty){conflict=true;$('docReload').hidden=false;status('协作身份已切换；原身份草稿已保留，请导出或载入最新。');}await library();}
 doc.role=r.role;if(identityChanged||roleChanged){reading=!editable();render();}permissions();collabRender(r);
 if(r.version!==doc.version&&!saving&&!liveConnected){
   if(dirty){remotePending=true;status('协作者已更新，保存时将尝试合并独立修改。');}
   else{const latest=await api('/'+nid);if(doc?.id!==nid||dirty||saving)return;doc=latest;undo=[];redo=[];render();status('已同步协作者修改 · 版本 '+doc.version);}
 }
 }catch(e){if([401,403].includes(e.status)){doc.role='viewer';reading=true;render();clearTimeout(timer);status('协作访问已过期或撤销；设备草稿仍可导出。');}else if($('collabPanel').open)status(e.message);}
}
$('docCollab').onclick=()=>{const b=doc?.blocks.find(b=>b.id===selected);$('collabAnchorHint').textContent=b?'评论位置：'+(b.text||({table:'表格',drawing:'绘图',image:'图片'}[b.type]||'内容块')).slice(0,80):'本次评论针对整篇文档；选择正文块可保留具体位置。';$('collabPanel').showModal();syncCollaboration();};
$('collabClose').onclick=()=>$('collabPanel').close();
$('collabInvite').onclick=async()=>{try{await save();const r=await collaboration(cp()+'/invite',{role:$('collabRole').value});$('collabCode').hidden=false;$('collabCode').value=r.code;$('collabInviteHint').textContent=r.boundary;$('collabCode').select();}catch(e){status(e.message);}};
$('collabRevokeInvites').onclick=async()=>{try{await collaboration(cp()+'/revoke',{user_id:''});$('collabCode').hidden=true;status('所有未使用邀请已撤销。');}catch(e){status(e.message);}};
$('collabMembers').onclick=async e=>{if(!e.target.dataset.revoke)return;try{await collaboration(cp()+'/revoke',{user_id:e.target.dataset.revoke});await syncCollaboration();status('成员访问与待用邀请已撤销。');}catch(e){status(e.message);}};
$('collabSend').onclick=async()=>{try{if(editable())await save();await collaboration(cp()+'/comments',{block_id:selected||'',version:doc.version,text:$('collabComment').value});$('collabComment').value='';await syncCollaboration();}catch(e){status(e.message);}};
$('collabComments').onclick=async e=>{try{if(e.target.dataset.resolve){await collaboration(cp()+'/comments/'+e.target.dataset.resolve+'/resolve',{});await syncCollaboration();}if(e.target.dataset.commentAnchor){const b=doc.blocks.find(b=>b.id===e.target.dataset.commentAnchor);if(!b){status('原内容块已移除，请从版本记录查看。');return;}selected=b.id;render();$('collabPanel').close();$('docBlocks').querySelector('[data-block="'+b.id+'"]')?.scrollIntoView({block:'center',behavior:'smooth'});}}catch(err){status(err.message);}};
$('collabDraft').onclick=()=>{if(!doc)return;const url=URL.createObjectURL(new Blob([JSON.stringify(doc,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='document-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('collabFeishu').onclick=async()=>{try{await save();const r=await fetch('/api/feishu/documents/'+doc.id+'/draft',{method:'POST'});const v=await r.json();if(!r.ok)throw Error(v.detail||'飞书草稿失败');status('已生成飞书审批草稿 #'+v.id+'；请在飞书连接器预览并选择发送目标。');const a=document.createElement('a');a.href='/console?view=feishu&summary='+v.id;a.textContent='打开飞书草稿 #'+v.id;a.className='collab-link';$('collabInviteHint').replaceChildren(a);}catch(e){status(e.message);}};
$('docJoin').onclick=()=>$('joinDialog').showModal();$('joinClose').onclick=()=>$('joinDialog').close();
$('joinSubmit').onclick=async()=>{try{if(dirty||saving)await save();const u=await collaboration('/join',{code:$('joinCode').value.trim(),name:$('joinName').value.trim()});location.href='/academy/notes?document='+u.document_id;}catch(e){$('joinStatus').textContent=e.message;}};
$('collabLogout').onclick=async()=>{try{if(dirty||saving)await save();await collaboration('/logout',{});location.reload();}catch(e){status(e.message);}};
setInterval(syncCollaboration,12000);
window.addEventListener('offline',()=>{if(dirty)cache();clearTimeout(timer);$('docLiveStatus').textContent='离线编辑 · 设备草稿保留';});
window.addEventListener('online',()=>{connectLive(true);if(dirty&&!conflict&&editable()){clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),600);}});
window.addEventListener("beforeunload",e=>{if(dirty||saving){cache();e.preventDefault();e.returnValue="";}});
(async()=>{try{try{me=await collaboration("/me");}catch(e){}const nid=new URLSearchParams(location.search).get("document");if(nid)await open(nid);else{const draft=readDraft(null);if(draft){doc=draft;dirty=true;render();await save();}else{const list=await api();if(list.documents.length&&!new URLSearchParams(location.search).has("source"))await open(list.documents[0].id);else if(!me||me.id!=="local-user")status("请先加入协作，或打开已有授权文档。");else await newDoc();}}}catch(e){status("无法打开文档："+e.message);}})();
})();
