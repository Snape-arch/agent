/* Structured document editor: stored text is never treated as trusted HTML. */
(function(){
"use strict";
const $=id=>document.getElementById(id), base="/api/academy/learning/documents";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clone=v=>JSON.parse(JSON.stringify(v)), id=()=>crypto.randomUUID();
const inline=window.markdownit({html:false,linkify:false,breaks:true});
inline.renderer.rules.image=(tokens,index)=>esc(tokens[index]?.content||"图片");
let doc=null,selected=null,undo=[],redo=[],dirty=false,saving=null,timer=null,conflict=false,reading=false,suggestion="",suggestionAnchor=null;
let strokes=[],activeStroke=null,drawingId=null;
const block=(type="paragraph",text="")=>({id:id(),type,text,...(type==="heading"?{level:2}:type==="code"?{language:"python"}:type==="table"?{cells:[["项目","观察","依据"],["","",""],["","",""]]}:type==="drawing"?{strokes:[]}:type==="todo"?{checked:false}:{})});
function status(s){$("docStatus").textContent=s;}
async function api(path="",data,method){const r=await fetch(base+path,{method:method||(data?"POST":"GET"),headers:data?{"Content-Type":"application/json"}:{},body:data?JSON.stringify(data):undefined});const v=await r.json();if(!r.ok){const e=Error(v.detail||"请求失败");e.status=r.status;throw e;}return v;}
function draftKey(nid=doc?.id){return "clawos_document_draft_"+(nid||"new");}
function cache(){try{localStorage.setItem(draftKey(),JSON.stringify(doc));return true;}catch(e){status("设备草稿空间不足，请立即保存或导出文档。");return false;}}
function checkpoint(){undo.push(clone(doc));undo=undo.slice(-60);redo=[];}
function changed(){dirty=true;cache();status("草稿已保留 · 等待保存");clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),1300);outline();}
async function save(){
 clearTimeout(timer);if(!doc)return;if(conflict)throw Error("请先处理版本冲突");if(saving){await saving;if(dirty)return save();return doc;}
 if(!dirty&&doc.id)return doc;
 const before=clone(doc);dirty=false;status("保存中…");
 saving=(async()=>{try{const result=await api(before.id?"/"+before.id:"",before,before.id?"PUT":"POST");
 const oldKey=draftKey(before.id);doc.id=result.id;doc.version=result.version;doc.updated_at=result.updated_at;
 localStorage.removeItem(oldKey);if(dirty)cache();else localStorage.removeItem(draftKey());
 const u=new URL(location.href);u.searchParams.set("document",doc.id);history.replaceState(null,"",u);
 status("已保存 · 版本 "+doc.version);await library();return doc;
 }catch(e){dirty=true;if(e.status===409){conflict=true;$("docCopy").hidden=false;$("docReload").hidden=false;}cache();status(e.message);throw e;}finally{saving=null;}})();
 return saving;
}
async function library(){try{const r=await api();$("docLibrary").innerHTML=r.documents.map(d=>'<button data-document="'+esc(d.id)+'" class="'+(doc?.id===d.id?"active":"")+'">'+esc(d.title)+'</button>').join("");}catch(e){status("文档列表读取失败："+e.message);}}
async function open(nid){
 if(doc&&(dirty||saving))await save();
 const loaded=await api("/"+nid);let draft;try{draft=JSON.parse(localStorage.getItem(draftKey(nid))||"null");}catch(e){}
 doc=draft||loaded;dirty=!!draft;conflict=!!draft&&draft.version!==loaded.version;
 undo=[];redo=[];selected=null;$("docCopy").hidden=!conflict;$("docReload").hidden=!conflict;
 history.replaceState(null,"","?document="+nid);render();await library();
 status(conflict?"已恢复设备草稿；服务器版本已变化，请另存或载入最新。":draft?"已恢复未保存草稿。":"已保存 · 版本 "+doc.version);
}
async function newDoc(){
 if(doc&&(dirty||saving))await save();
 const params=new URLSearchParams(location.search);
 doc={title:params.get("title")?.slice(0,200)||"我的学习文档",context:params.get("source")?.slice(0,1000)||"",blocks:[block("heading","核心问题"),block("paragraph",""),block("heading","我的解释与证据"),block("quote",""),block("heading","下一步验证"),block("todo","")]};
 undo=[];redo=[];conflict=false;selected=doc.blocks[1].id;dirty=true;render();cache();await save();
}
function tools(b){return '<div class="block-tools"><button data-op="up" aria-label="上移内容块">↑</button><button data-op="down" aria-label="下移内容块">↓</button><button data-op="duplicate">复制块</button><button data-op="delete" aria-label="删除内容块">删除</button>'+(b.type==="heading"?'<select data-field="level" aria-label="标题级别">'+[1,2,3].map(x=>'<option '+(x===b.level?"selected":"")+'>'+x+'</option>').join("")+'</select>':"")+'</div>';}
function edit(text,label="内容",field="text"){return '<div class="block-edit" contenteditable="'+!reading+'" role="textbox" aria-multiline="true" aria-label="'+label+'" data-field="'+field+'" data-placeholder="写下你的理解，输入 / 插入…">'+inline.renderInline(String(text||''))+'</div>';}

function serializeInline(element){
 function walk(n){
  if(n.nodeType===3)return n.nodeValue.replace(/([\\*_\x60~\[\]])/g,"\\$1");
  if(n.nodeType!==1)return "";
  const text=Array.from(n.childNodes,walk).join("");
  if(n.tagName==="BR")return "\n";
  if(["STRONG","B"].includes(n.tagName))return "**"+text+"**";
  if(["EM","I"].includes(n.tagName))return "*"+text+"*";
  if(["S","DEL"].includes(n.tagName))return "~~"+text+"~~";
  if(n.tagName==="CODE")return String.fromCharCode(96)+n.textContent.replace(/\x60/g,"")+String.fromCharCode(96);
  if(n.tagName==="A"){const href=n.getAttribute("href")||"";return /^(https?:|mailto:)/i.test(href)?"["+text+"]("+href.replace(/[()\\\s]/g,encodeURIComponent)+")":text;}
  return text+(["DIV","P"].includes(n.tagName)?"\n":"");
 }
 return Array.from(element.childNodes,walk).join("").replace(/\n$/,"");
}
let textRange=null;
document.addEventListener("selectionchange",()=>{const s=window.getSelection();if(s?.rangeCount){const r=s.getRangeAt(0),host=r.commonAncestorContainer.nodeType===1?r.commonAncestorContainer:r.commonAncestorContainer.parentElement;if(host?.closest?.(".block-edit"))textRange=r.cloneRange();}});
document.querySelectorAll("[data-format]").forEach(b=>{b.addEventListener("mousedown",e=>e.preventDefault());b.onclick=()=>format(b.dataset.format);});
function format(kind){
 if(reading||!textRange||textRange.collapsed){status("请先选择正文中的文字，再设置格式。");return;}
 const host=(textRange.commonAncestorContainer.nodeType===1?textRange.commonAncestorContainer:textRange.commonAncestorContainer.parentElement).closest(".block-edit");
 if(!host||!host.isContentEditable||!host.contains(textRange.startContainer)||!host.contains(textRange.endContainer))return;
 let href;
 if(kind==="link"){href=window.prompt("输入 HTTPS / HTTP / mailto 链接");if(!href)return;if(!/^(https?:\/\/|mailto:)/i.test(href)){status("链接仅支持 HTTP、HTTPS 或 mailto");return;}}
 checkpoint();const node=document.createElement({bold:"strong",italic:"em",strike:"s",inlinecode:"code",link:"a"}[kind]);
 node.textContent=textRange.toString();if(href){node.href=href;node.target="_blank";node.rel="noopener noreferrer";}
 textRange.deleteContents();textRange.insertNode(node);textRange.selectNodeContents(node);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(textRange);
 const b=doc.blocks.find(b=>b.id===host.closest("[data-block]").dataset.block);b.text=serializeInline(host);changed();
}

function renderBlock(b){
 let body="";
 if(b.type==="code")body='<div class="code-head"><input aria-label="代码语言" data-field="language" value="'+esc(b.language)+'"><button data-op="copy-code">复制代码</button></div><textarea aria-label="代码内容" data-field="text" spellcheck="false" '+(reading?"readonly":"")+'>'+esc(b.text)+'</textarea>';
 else if(b.type==="table")body='<div class="table-scroll"><table><tbody>'+b.cells.map((r,i)=>'<tr>'+r.map((c,j)=>'<td contenteditable="'+!reading+'" role="textbox" aria-label="第'+(i+1)+'行第'+(j+1)+'列" data-cell="'+i+','+j+'">'+esc(c)+'</td>').join("")+'</tr>').join("")+'</tbody></table></div><div class="table-actions">'+[["row","＋ 行"],["column","＋ 列"],["remove-row","－ 行"],["remove-column","－ 列"]].map(([op,t])=>'<button data-op="'+op+'">'+t+'</button>').join("")+'</div>';
 else if(b.type==="drawing")body='<canvas width="900" height="480" role="button" tabindex="0" aria-label="编辑绘图" data-op="drawing"></canvas>'+edit(b.text,"绘图说明");
 else if(b.type==="image")body='<img src="'+esc(b.data)+'" alt="'+esc(b.text||"文档插图")+'">'+edit(b.text,"图片说明");
 else if(b.type==="divider")body="<hr>";
 else body=(b.type==="bullet"?'<span class="list-marker">•</span>':b.type==="numbered"?'<span class="list-marker">'+(doc.blocks.filter(x=>x.type==="numbered").findIndex(x=>x.id===b.id)+1)+'.</span>':"")+(b.type==="todo"?'<input type="checkbox" aria-label="待办完成状态" data-field="checked" '+(b.checked?"checked":"")+' '+(reading?"disabled":"")+'>':"")+(reading&&window.ClawChatContent?'<div class="block-edit">'+ClawChatContent.render(b.text)+'</div>':edit(b.text,b.type==="heading"?"章节标题":"内容"));
 return '<section class="doc-block '+b.type+(selected===b.id?" selected":"")+'" data-block="'+b.id+'" data-level="'+(b.level||2)+'">'+tools(b)+body+'</section>';
}
function render(){if(!doc)return;$("docTitle").value=doc.title;$("docContext").value=doc.context||"";$("docBlocks").innerHTML=doc.blocks.map(renderBlock).join("");for(const b of doc.blocks.filter(b=>b.type==="drawing"))draw($("docBlocks").querySelector('[data-block="'+b.id+'"] canvas'),b.strokes);outline();$("docUndo").disabled=!undo.length;$("docRedo").disabled=!redo.length;}
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
$("drawUndo").onclick=()=>{strokes.pop();draw(canvas,strokes);};$("drawClear").onclick=()=>{strokes=[];draw(canvas,strokes);};
$("drawInsert").onclick=()=>{if(activeStroke){status("请先结束当前笔迹");return;}mutate(()=>{let b=doc.blocks.find(b=>b.id===drawingId);if(!b){b=block("drawing");const i=doc.blocks.findIndex(b=>b.id===selected);doc.blocks.splice(i<0?doc.blocks.length:i+1,0,b);}b.strokes=clone(strokes);b.text=$("drawCaption").value;selected=b.id;});$("drawDialog").close();};
$("docBlocks").addEventListener("focusin",e=>{const node=e.target.closest("[data-block]");if(node){selected=node.dataset.block;document.querySelectorAll(".doc-block").forEach(n=>n.classList.toggle("selected",n===node));}});
$("docBlocks").addEventListener("beforeinput",e=>{if(!reading)checkpoint();});
$("docBlocks").addEventListener("input",e=>{if(reading)return;const b=doc.blocks.find(b=>b.id===e.target.closest("[data-block]")?.dataset.block);if(!b)return;if(e.target.dataset.cell){const [r,c]=e.target.dataset.cell.split(",").map(Number);b.cells[r][c]=e.target.innerText;}else{const field=e.target.dataset.field;if(field)b[field]=e.target.type==="checkbox"?e.target.checked:field==="level"?Number(e.target.value):e.target.isContentEditable?serializeInline(e.target):e.target.value;}changed();$("docUndo").disabled=!undo.length;$("docRedo").disabled=!redo.length;});
$("docBlocks").addEventListener("change",e=>{if(e.target.dataset.field==="level"){const b=doc.blocks.find(b=>b.id===e.target.closest("[data-block]")?.dataset.block);mutate(()=>{b.level=Number(e.target.value);});}});
$("docBlocks").addEventListener("click",async e=>{const node=e.target.closest("[data-block]"),button=e.target.closest("[data-op]");if(!node||!button)return;selected=node.dataset.block;const i=doc.blocks.findIndex(b=>b.id===selected),b=doc.blocks[i],op=button.dataset.op;
 if(op==="copy-code"){try{await navigator.clipboard.writeText(b.text);status("代码已复制");}catch(e){status("复制不可用，请选择代码后手动复制");}return;}if(reading)return;if(op==="drawing"){openDrawing(b);return;}
 mutate(()=>{if(op==="delete"){doc.blocks.splice(i,1);if(!doc.blocks.length)doc.blocks.push(block());selected=doc.blocks[Math.min(i,doc.blocks.length-1)].id;}
 if(op==="up"&&i>0)[doc.blocks[i-1],doc.blocks[i]]=[doc.blocks[i],doc.blocks[i-1]];
 if(op==="down"&&i<doc.blocks.length-1)[doc.blocks[i+1],doc.blocks[i]]=[doc.blocks[i],doc.blocks[i+1]];
 if(op==="duplicate"){const copy={...clone(b),id:id()};doc.blocks.splice(i+1,0,copy);selected=copy.id;}
 if(op==="row"&&b.cells.length<50)b.cells.push(b.cells[0].map(()=>""));if(op==="column"&&b.cells[0].length<12)b.cells.forEach(r=>r.push(""));
 if(op==="remove-row"&&b.cells.length>1)b.cells.pop();if(op==="remove-column"&&b.cells[0].length>1)b.cells.forEach(r=>r.pop());});
});
$("docBlocks").addEventListener("keydown",e=>{
 if(reading)return;if(e.key==="/"&&e.target.isContentEditable&&!e.target.innerText.trim()){e.preventDefault();$("docInsert").focus();return;}
 if(e.key==="Tab"&&e.target.tagName==="TEXTAREA"){e.preventDefault();checkpoint();const t=e.target,a=t.selectionStart,z=t.selectionEnd;t.setRangeText("  ",a,z,"end");doc.blocks.find(b=>b.id===t.closest("[data-block]").dataset.block).text=t.value;changed();}
 if(e.key==="Enter"&&e.target.dataset.op==="drawing")openDrawing(doc.blocks.find(b=>b.id===e.target.closest("[data-block]").dataset.block));
});
$("docBlocks").addEventListener("paste",e=>{if(!e.target.isContentEditable)return;e.preventDefault();const text=e.clipboardData.getData("text/plain");const selection=window.getSelection();if(!selection.rangeCount)return;checkpoint();const range=selection.getRangeAt(0);range.deleteContents();const n=document.createTextNode(text);range.insertNode(n);range.setStartAfter(n);range.collapse(true);selection.removeAllRanges();selection.addRange(range);e.target.dispatchEvent(new Event("input",{bubbles:true}));});
$("docTitle").addEventListener("beforeinput",checkpoint);$("docContext").addEventListener("beforeinput",checkpoint);
$("docTitle").oninput=()=>{doc.title=$("docTitle").value;changed();};$("docContext").oninput=()=>{doc.context=$("docContext").value;changed();};
$("docInsert").onchange=e=>{const type=e.target.value;e.target.value="";if(type)insert(type);};
$("docAdd").onclick=()=>insert("paragraph");$("docFocus").onclick=()=>{const on=document.body.classList.toggle("doc-focus");$("docFocus").textContent=on?"退出专注":"专注写作";};
$("docPreview").onclick=()=>{reading=!reading;document.body.classList.toggle("doc-reading",reading);$("docPreview").textContent=reading?"继续编辑":"阅读预览";$("docTitle").readOnly=reading;$("docContext").readOnly=reading;for(const nid of ["docInsert","docTemplate","docImport","docAdd"]){$(nid).disabled=reading;}render();$("docBlocks").querySelectorAll('input[data-field="language"]').forEach(n=>n.readOnly=reading);};
$("docUndo").onclick=()=>{if(!undo.length)return;redo.push(clone(doc));const meta={id:doc.id,version:doc.version};doc={...undo.pop(),...meta};changed();render();};
$("docRedo").onclick=()=>{if(!redo.length)return;undo.push(clone(doc));const meta={id:doc.id,version:doc.version};doc={...redo.pop(),...meta};changed();render();};
$("docSave").onclick=()=>save().catch(e=>status(e.message));$("docNew").onclick=()=>newDoc().catch(e=>status(e.message));
$("docLibrary").onclick=e=>{const nid=e.target.closest("[data-document]")?.dataset.document;if(nid)open(nid).catch(e=>status(e.message));};
$("docOutline").onclick=e=>{const bid=e.target.closest("[data-outline]")?.dataset.outline;if(bid)$("docBlocks").querySelector('[data-block="'+bid+'"]')?.scrollIntoView({behavior:"smooth",block:"center"});};
$("docTemplate").onchange=e=>{const key=e.target.value;e.target.value="";const titles={cornell:["线索与问题","自己的解释","例子与反例","一句话总结","复盘问题"],concept:["定义","机制与条件","一个例子","反例与边界","原文依据"],experiment:["假设","方法与变量","实际结果","失败与限制","下一步验证"]}[key];if(titles)mutate(()=>{for(const title of titles)doc.blocks.push(block("heading",title),block(title==="原文依据"?"quote":"paragraph",""));});};
$("docImageFile").onchange=async e=>{const file=e.target.files[0];e.target.value="";if(!file)return;if(file.size>2*1024*1024){status("图片需小于 2 MB");return;}try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});mutate(()=>{const b={...block("image",file.name),data};const i=doc.blocks.findIndex(b=>b.id===selected);doc.blocks.splice(i<0?doc.blocks.length:i+1,0,b);selected=b.id;});}catch(e){status("图片读取失败");}};
function markdownBlocks(text){const rows=[];let code=null,lines=[];for(const line of text.split(/\r?\n/)){const fence=line.match(/^(\x60{3,}|~{3,})([\w+#.-]*)/);if(fence){if(code&&line.startsWith(code.fence)){rows.push({...block("code",lines.join("\n")),language:code.language||"text"});code=null;lines=[];}else if(!code){code={fence:fence[1],language:fence[2]};}else lines.push(line);continue;}if(code){lines.push(line);continue;}const heading=line.match(/^(#{1,3})\s+(.+)/),todo=line.match(/^- \[([ xX])\]\s*(.*)/);if(heading)rows.push({...block("heading",heading[2]),level:heading[1].length});else if(todo)rows.push({...block("todo",todo[2]),checked:todo[1].toLowerCase()==="x"});else if(line.startsWith("> "))rows.push(block("quote",line.slice(2)));else if(line.trim())rows.push(block("paragraph",line));}if(code)rows.push({...block("code",lines.join("\n")),language:code.language||"text"});return rows;}
$("docImport").onclick=()=>$("docImportFile").click();
$("docImportFile").onchange=async e=>{const file=e.target.files[0];e.target.value="";if(!file)return;try{if(file.size>8*1024*1024)throw Error("导入文件需小于 8 MB");const text=await file.text();let blocks=file.name.endsWith(".json")?JSON.parse(text).blocks:markdownBlocks(text);if(!Array.isArray(blocks)||!blocks.length||blocks.length+doc.blocks.length>300)throw Error("导入内容块格式或数量无效");
 const validated=await api("",{title:"导入 · "+file.name.slice(0,100),context:"",blocks:blocks.map(b=>({...b,id:id()}))});
 mutate(()=>{doc.blocks.push(...validated.blocks);});status("已导入；保留了原始文档。");
 }catch(err){status("导入失败："+err.message);}};
$("docExport").onchange=async e=>{const format=e.target.value;e.target.value="";if(!format)return;try{await save();const a=document.createElement("a");a.href=base+"/"+doc.id+"/export?format="+format;a.click();}catch(err){status(err.message);}};
$("docHistory").onclick=async()=>{try{await save();const r=await api("/"+doc.id+"/history");$("docVersions").hidden=false;$("docVersions").innerHTML=r.versions.map(v=>'<button data-version="'+v.version+'">版本 '+v.version+' · '+esc(v.created_at)+'</button>').join("");$("docVersions").onclick=e=>{const n=Number(e.target.dataset.version),v=r.versions.find(v=>v.version===n);if(v)mutate(()=>{doc.title=v.title;doc.context=v.context;doc.blocks=clone(v.blocks);});};status("选择历史版本可恢复为新版本，当前内容仍可撤销。");}catch(e){status(e.message);}};
$("docCopy").onclick=async()=>{try{const before=clone(doc),old=draftKey();delete before.id;delete before.version;before.title=(before.title+" · 草稿副本").slice(0,200);const result=await api("",before);localStorage.removeItem(old);doc=result;dirty=false;conflict=false;$("docCopy").hidden=true;$("docReload").hidden=true;history.replaceState(null,"","?document="+doc.id);render();await library();status("草稿已另存为副本。");}catch(e){status(e.message);}};
$("docReload").onclick=async()=>{try{const latest=await api("/"+doc.id);checkpoint();doc=latest;dirty=false;conflict=false;$("docCopy").hidden=true;$("docReload").hidden=true;localStorage.removeItem(draftKey());render();status("已载入最新版本；原草稿可撤销恢复。");}catch(e){status(e.message);}};
document.querySelectorAll("[data-assist]").forEach(button=>button.onclick=async()=>{const b=doc.blocks.find(b=>b.id===selected);if(!b?.text?.trim()){$("docAssistStatus").textContent="请先选择一个有文字的内容块。";return;}button.disabled=true;suggestionAnchor=b.id;$("docAssistStatus").textContent="正在请求导写建议…";try{const r=await api("/assist",{text:b.text.slice(0,12000),mode:button.dataset.assist});suggestion=r.draft;$("docSuggestion").textContent=suggestion;$("docSuggestion").hidden=false;$("docAccept").hidden=false;$("docAssistStatus").textContent=r.boundary;}catch(e){$("docAssistStatus").textContent=e.message;}finally{button.disabled=false;}});
$("docAccept").onclick=()=>{selected=suggestionAnchor;insert("quote",{text:"导写建议（待复核）\n"+suggestion});$("docAccept").hidden=true;};
document.addEventListener("keydown",e=>{if(e.ctrlKey||e.metaKey){if(["b","i"].includes(e.key.toLowerCase())){e.preventDefault();format(e.key.toLowerCase()==="b"?"bold":"italic");}if(e.key.toLowerCase()==="s"){e.preventDefault();save().catch(e=>status(e.message));}if(e.key.toLowerCase()==="z"){e.preventDefault();(e.shiftKey?$("docRedo"):$("docUndo")).click();}}if(e.key==="Escape"&&!$("drawDialog").open&&document.body.classList.contains("doc-focus"))$("docFocus").click();});
window.addEventListener("beforeunload",e=>{if(dirty||saving){cache();e.preventDefault();e.returnValue="";}});
(async()=>{try{const nid=new URLSearchParams(location.search).get("document");if(nid)await open(nid);else{let draft;try{draft=JSON.parse(localStorage.getItem(draftKey(null))||"null");}catch(e){}if(draft){doc=draft;dirty=true;render();await save();}else{const list=await api();if(list.documents.length&&!new URLSearchParams(location.search).has("source"))await open(list.documents[0].id);else await newDoc();}}}catch(e){status("无法打开文档："+e.message);}})();
})();
