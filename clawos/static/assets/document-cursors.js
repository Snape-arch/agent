/* Positions are UTF-16 offsets bound to one saved version, never guessed on a dirty draft. */
(function(){'use strict';
window.ClawDocumentCursors=function(options){
 let people=[],scheduled=false,timer=null;
 const hostOf=node=>(node?.nodeType===1?node:node?.parentElement)?.closest('.block-edit,[data-cell]');
 function offset(host,node,position){const range=document.createRange();range.selectNodeContents(host);range.setEnd(node,position);const holder=document.createElement('div');holder.append(range.cloneContents());return ClawDocumentTransactions.length(ClawRichText.spans(holder,false));}
 function payload(){const doc=options.document(),selection=getSelection();if(!doc?.id)return null;
  const host=hostOf(selection?.focusNode),anchorHost=hostOf(selection?.anchorNode),bid=host?.closest('[data-block]')?.dataset.block;
  if(options.dirty()||!host||!anchorHost||!document.querySelector('#docBlocks').contains(host)||!document.querySelector('#docBlocks').contains(anchorHost))return {block_id:bid||''};
  const b=doc.blocks.find(b=>b.id===bid);if(!host.dataset.cell&&!['paragraph','heading','quote','callout','bullet','numbered','todo'].includes(b?.type))return {block_id:bid||''};
  return {block_id:anchorHost.closest('[data-block]').dataset.block,cursor:{version:doc.version,anchor:offset(anchorHost,selection.anchorNode,selection.anchorOffset),focus:offset(host,selection.focusNode,selection.focusOffset),cell:anchorHost.dataset.cell?anchorHost.dataset.cell.split(',').map(Number):null,focus_block:bid,focus_cell:host.dataset.cell?host.dataset.cell.split(',').map(Number):null}};
 }
 async function publish(){const doc=options.document(),data=payload();if(doc?.id&&data)await options.send(doc.id,data).catch(()=>{});}
 function point(host,position){const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT,{acceptNode(n){return n.nodeType===3||n.tagName==='BR'?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP;}});let n,offset=0;while(n=walker.nextNode()){const size=n.nodeType===3?n.nodeValue.length:1;if(position<=offset+size){if(n.nodeType===3)return [n,position-offset];return [n.parentNode,[...n.parentNode.childNodes].indexOf(n)+(position>offset?1:0)];}offset+=size;}return [host,host.childNodes.length];}
 function paint(){scheduled=false;document.querySelectorAll('.remote-caret,.remote-selection').forEach(n=>n.remove());const doc=options.document();if(!doc||options.dirty())return;
  for(const person of people){if(person.user_id===options.identity()?.id||person.version!==doc.version)continue;const block=document.querySelector('[data-block="'+CSS.escape(person.block_id)+'"]');if(!block)continue;
   const host=person.cell?block.querySelector('[data-cell="'+person.cell.join(',')+'"]'):block.querySelector('.block-edit');if(!host)continue;
   const focusBlock=document.querySelector('[data-block="'+CSS.escape(person.focus_block||person.block_id)+'"]'),focusHost=person.focus_cell?focusBlock?.querySelector('[data-cell="'+person.focus_cell.join(',')+'"]'):focusBlock?.querySelector('.block-edit');if(!focusHost)continue;
   if(person.anchor>ClawDocumentTransactions.length(ClawRichText.spans(host))||person.focus>ClawDocumentTransactions.length(ClawRichText.spans(focusHost)))continue;
   const range=document.createRange(),forward=host===focusHost?person.anchor<=person.focus:!!(host.compareDocumentPosition(focusHost)&Node.DOCUMENT_POSITION_FOLLOWING);range.setStart(...point(forward?host:focusHost,forward?person.anchor:person.focus));range.setEnd(...point(forward?focusHost:host,forward?person.focus:person.anchor));const color=['#17634f','#7354aa','#aa4d28','#2566a0'][[...person.user_id].reduce((n,c)=>n+c.charCodeAt(0),0)%4];
   if(!range.collapsed)for(const textHost of document.querySelectorAll('#docBlocks .block-edit,#docBlocks [data-cell]')){if(!range.intersectsNode(textHost))continue;const bounds=textHost.getBoundingClientRect();if(bounds.bottom<52||bounds.top>innerHeight)continue;const part=range.cloneRange();if(!textHost.contains(range.startContainer))part.setStart(textHost,0);if(!textHost.contains(range.endContainer))part.setEnd(textHost,textHost.childNodes.length);for(const rect of part.getClientRects()){if(!rect.width||rect.bottom<52||rect.top>innerHeight)continue;const n=document.createElement('span');n.className='remote-selection';n.setAttribute('aria-hidden','true');Object.assign(n.style,{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px',background:color});document.body.append(n);}}
   range.setStart(...point(focusHost,person.focus));range.collapse(true);let rect=range.getBoundingClientRect();if(!rect.height){const p=focusHost.getBoundingClientRect();rect={left:p.left,top:p.top,height:parseFloat(getComputedStyle(focusHost).lineHeight)||24};}
   if(rect.top+rect.height<52||rect.top>innerHeight)continue;
   const caret=document.createElement('span');caret.className='remote-caret';caret.setAttribute('aria-hidden','true');Object.assign(caret.style,{left:rect.left+'px',top:rect.top+'px',height:rect.height+'px',color});const label=document.createElement('span');label.textContent=person.name;caret.append(label);document.body.append(caret);
  }
 }
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(paint);}}
 document.addEventListener('selectionchange',()=>{clearTimeout(timer);timer=setTimeout(publish,180);});document.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);
 return {update(value){people=value.cursors||[];schedule();},refresh:schedule,publish,payload,clear(){people=[];schedule();}};
};
})();
