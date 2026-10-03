/* Typed inline spans. Clipboard HTML is parsed as inert data, never inserted. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ClawRichText=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tags={bold:'strong',italic:'em',strike:'s',code:'code',underline:'u',highlight:'mark',link:'a'};
const validLink=s=>typeof s==='string'&&/^(https?:\/\/|mailto:)\S+$/i.test(s)&&s.length<=2000&&!/[\u0000-\u001f]/.test(s);
function render(spans){return spans.map(s=>{let text=escape(s.text).replace(/\n/g,'<br>');for(const m of s.marks||[]){const tag=tags[m.type];if(!tag)continue;if(m.type==='link'){if(validLink(m.href))text='<a href="'+escape(m.href)+'" target="_blank" rel="noopener noreferrer">'+text+'</a>';}else text='<'+tag+'>'+text+'</'+tag+'>';}return text;}).join('');}
function markdown(spans){return spans.map(s=>{const types=new Map((s.marks||[]).map(m=>[m.type,m]));let text=s.text;if(types.has('code')){const fence='`'.repeat(Math.max(1,...(text.match(/`+/g)||[]).map(m=>m.length+1)));const pad=/^[` ]|[` ]$/.test(text)?' ':'';text=fence+pad+text.replace(/\n/g,' ')+pad+fence;}else text=text.replace(/([\\*_`~\[\]])/g,'\\$1');for(const [type,fence] of [['bold','**'],['italic','*'],['strike','~~']])if(types.has(type)&&text.trim())text=text.match(/^\s*/)[0]+fence+text.trim()+fence+text.match(/\s*$/)[0];if(types.has('link')&&validLink(types.get('link').href))text='['+text+']('+encodeURI(types.get('link').href).replace(/%25/g,'%').replace(/[()'\\]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase())+')';return text;}).join('');}
function spans(element,trim=true){const result=[];function push(text,marks){if(!text)return;const last=result.at(-1);if(last&&JSON.stringify(last.marks)===JSON.stringify(marks))last.text+=text;else result.push({text,marks:marks.map(m=>({...m}))});}
function walk(n,marks){if(n.nodeType===3){push(n.nodeValue,marks);return;}if(n.nodeType!==1||['SCRIPT','STYLE','IFRAME','OBJECT','TEMPLATE','SVG','IMG','INPUT','BUTTON'].includes(n.tagName))return;if(n.tagName==='BR'){push('\n',marks);return;}
let next=marks.slice(),type=({B:'bold',STRONG:'bold',I:'italic',EM:'italic',S:'strike',DEL:'strike',STRIKE:'strike',CODE:'code',U:'underline',MARK:'highlight'})[n.tagName];if(!type&&/^(bold|[6-9]00)$/.test(n.style?.fontWeight||''))type='bold';if(type&&!next.some(m=>m.type===type))next.push({type});if(n.tagName==='A'&&validLink(n.getAttribute('href')))next=[...next.filter(m=>m.type!=='link'),{type:'link',href:n.getAttribute('href')}];for(const child of n.childNodes)walk(child,next);if(['DIV','P'].includes(n.tagName))push('\n',marks);}
for(const n of element.childNodes)walk(n,[]);if(trim&&result.at(-1)?.text.endsWith('\n')){result.at(-1).text=result.at(-1).text.slice(0,-1);if(!result.at(-1).text)result.pop();}return result;}
function clipboard(html,plain,makeBlock,document){
if((html||plain||'').length>1000000)throw Error('一次粘贴请小于 1 MB');
if(!html)return null;
const inert=document.createElement('template');inert.innerHTML=html;const rows=[];
function paragraph(node,type='paragraph',extra={}){const runs=spans(node);if(runs.length)rows.push({...makeBlock(type,markdown(runs)),inline:runs,...extra});}
function visit(node,depth=0){if(node.nodeType===3){if(node.textContent.trim())rows.push({...makeBlock('paragraph',node.textContent),inline:[{text:node.textContent,marks:[]}]});return;}if(node.nodeType!==1||['SCRIPT','STYLE','IFRAME','OBJECT','TEMPLATE','SVG','IMG','META','LINK'].includes(node.tagName))return;
if(node.tagName==='PRE'){const code=node.querySelector('code');const language=(code?.className||'').match(/language-([\w+#.-]{1,30})/)?.[1]||'text';rows.push({...makeBlock('code',node.textContent),language});}
else if(node.tagName==='TABLE'){const trs=[...node.querySelectorAll('tr')].filter(r=>r.closest('table')===node);const cells=trs.map(r=>[...r.children].filter(c=>['TD','TH'].includes(c.tagName)).map(c=>c.textContent));if(!cells.length||cells.length>50||cells.some(r=>!r.length||r.length>12)||new Set(cells.map(r=>r.length)).size!==1)throw Error('粘贴表格需要规则的 1–50 行、1–12 列');rows.push({...makeBlock('table'),cells});}
else if(['UL','OL'].includes(node.tagName)){for(const li of node.children){if(li.tagName!=='LI')continue;const content=li.cloneNode(true);content.querySelectorAll('ul,ol').forEach(n=>n.remove());paragraph(content,node.tagName==='OL'?'numbered':'bullet',{indent:Math.min(depth,4)});for(const sub of li.children)if(['UL','OL'].includes(sub.tagName))visit(sub,depth+1);}}
else if(/^H[1-6]$/.test(node.tagName))paragraph(node,'heading',{level:Math.min(3,Number(node.tagName[1]))});
else if(node.tagName==='BLOCKQUOTE')paragraph(node,'quote');
else if(['P','LI'].includes(node.tagName))paragraph(node);
else if(node.tagName==='HR')rows.push(makeBlock('divider'));
else if(node.querySelector('p,div,h1,h2,h3,h4,h5,h6,ul,ol,pre,table,blockquote'))for(const child of node.childNodes)visit(child,depth);
else paragraph(node);
if(rows.length>300)throw Error('粘贴内容超过 300 个块');}
for(const node of inert.content.childNodes)visit(node);return rows.length?rows:null;}
function highlight(text,language){if(text.length>30000)return escape(text);const syntax=/^(python|py|javascript|js|typescript|ts|json|sql|bash|sh)$/i.test(language);if(!syntax)return escape(text);const pattern=/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#[^\n]*|\/\/[^\n]*|\b(?:def|class|return|import|from|if|else|elif|for|while|try|except|with|as|in|True|False|None|const|let|var|function|async|await|new|throw|SELECT|FROM|WHERE|JOIN|GROUP|BY|ORDER|NULL|true|false|null)\b|\b\d+(?:\.\d+)?\b)/g;let out='',start=0;for(const match of text.matchAll(pattern)){out+=escape(text.slice(start,match.index));const token=match[0],kind=/^["']/.test(token)?'string':/^(#|\/\/)/.test(token)?'comment':/^\d/.test(token)?'number':'keyword';out+='<span class="syntax-'+kind+'">'+escape(token)+'</span>';start=match.index+token.length;}return out+escape(text.slice(start));}
return {render,markdown,spans,clipboard,highlight,validLink};
});
