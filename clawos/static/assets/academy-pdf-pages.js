/* Controlled PDF pages keep annotations in document coordinates, independent of native viewer scroll. */
(function(){
const $=id=>document.getElementById(id);
if(!$("academyPdfPage"))return;
let requestId=0,current=null;
function position(){
 if(!academyPaperState.document?.id)return;
 const url=new URL(location.href);url.searchParams.set('document',academyPaperState.document.id);url.searchParams.set('page',academyPaperState.currentPage||1);
 if(document.body.classList.contains('reader-window'))url.searchParams.set('reader','window');else url.searchParams.delete('reader');
 if(document.querySelector('.paper-reader-workspace').classList.contains('notes-collapsed'))url.searchParams.set('notes','collapsed');else url.searchParams.delete('notes');
 history.replaceState(null,'',url);
}
const renderChunks=academyRenderPaperChunks,setSource=academySetPdfSource,refresh=academyRefreshPdfView;
function tools(enabled){["academyPenToggle","academyHighlightToggle","academyClearInk","academySaveAnnotation"].forEach(id=>$(id).disabled=!enabled);}
function detach(){
 ++requestId;
 const surface=$("academyPdfPage");surface.hidden=true;
 $("academyPaperViewer").appendChild($("academyInkCanvas"));
 academyPaperState.controlledPage=false;current=null;tools(false);
}
function layout(){
 const surface=$("academyPdfPage");surface.style.width=(academyReaderScale*100)+"%";
 window.requestAnimationFrame(academyResizeInkCanvas);
}
async function page(){
 const doc=academyPaperState.document;
 if(!doc?.id||!academyPreviewablePaperSource(doc)){detach();return;}
 const number=academyPaperState.currentPage||1,token=++requestId,revision=doc.file_hash||doc.metadata?.revision||"";
 $("academyInkCanvas").classList.remove("active");tools(false);
 try{
  const data=await academyApi("/api/documents/"+doc.id+"/page?page="+number);
  if(token!==requestId||doc.id!==academyPaperState.document?.id||number!==academyPaperState.currentPage)return;
  current={id:doc.id,page:number,revision};academyPaperState.controlledPage=true;academyPaperState.pageCount=data.pages;
  academyPaperState.frameSource='/api/documents/'+doc.id+'/source';position();
  const surface=$("academyPdfPage");surface.hidden=false;surface.style.aspectRatio=data.width+"/"+data.height;
  $("academyPdfFrame").hidden=true;$("academyPaperText").hidden=true;$("academyReaderEmpty").hidden=true;
  const image=$("academyPdfPageImage");image.src=data.image;image.alt="PDF 原文第 "+data.page+" 页，共 "+data.pages+" 页";
  image.width=Math.round(data.width);image.height=Math.round(data.height);
  const layer=$("academyPdfTextLayer");layer.replaceChildren();
  for(const t of data.text){
   const span=document.createElement("span");span.textContent=t.text;
   span.style.left=t.x*100+"%";span.style.top=t.y*100+"%";span.style.width=t.width*100+"%";span.style.height=t.height*100+"%";
   span.style.fontSize=(t.size*100)+"cqw";layer.appendChild(span);
  }
  surface.appendChild($("academyInkCanvas"));layout();tools(true);
  if(academyPaperState.penEnabled)$("academyInkCanvas").classList.add("active");
  $("academyPageNumber").value=number;$("academyPageNumber").max=data.pages;
  $("academyPagePrevious").disabled=number===1;$("academyPageNext").disabled=number===data.pages;
  academySetText("academyReaderProgress","第 "+number+" / "+data.pages+" 页");
  if(data.toc.length){
   const nav=document.querySelector(".reader-outline-list");nav.replaceChildren();
   for(const row of data.toc){const b=document.createElement("button");b.type="button";b.textContent=row.title+" · "+row.page;b.style.paddingLeft=Math.min(3,row.level)*8+"px";b.onclick=()=>academyJumpPaperSection(row.page,b);nav.appendChild(b);}
  }
 }catch(error){
  if(token!==requestId)return;
  detach();$("academyPdfFrame").hidden=false;
  academySetText("academyPaperStatus","按页阅读不可用，保留原文预览："+error.message);
 }
}
academySetPdfSource=function(source,number=1,mode="fit"){
 detach();setSource(source,number,mode);
 if(academyPaperState.document?.id&&source.startsWith("/api/documents/"))page();
};
academyRefreshPdfView=function(mode="zoom"){
 if(academyPaperState.controlledPage){if(mode==="page")page();else layout();return;}
 refresh(mode);
};
academyRenderPaperChunks=function(){renderChunks();if(academyPaperState.document?.id&&academyPreviewablePaperSource(academyPaperState.document))page();else detach();};
$("academyPdfPageImage").addEventListener("load",()=>{if(academyPaperState.controlledPage)academyResizeInkCanvas();});
$("academyPdfTextLayer").addEventListener("mouseup",()=>{
 const text=window.getSelection()?.toString().trim();
 if(text)academyPaperState.selectedQuote=text.slice(0,4000);
});
$("academyTextNoteToggle")?.addEventListener("click",()=>{
 if(academyPaperState.selectedQuote){
  const input=$("academyReaderNote");
  input.value=(input.value?input.value+"\n\n":"")+"> "+academyPaperState.selectedQuote+"\n\n我的解释：";
  input.dispatchEvent(new Event("input",{bubbles:true}));input.focus();academyPaperState.selectedQuote="";
 }
});
window.addEventListener("resize",()=>{if(current)layout();});
$('academyReaderFullscreen').addEventListener('click',position);
$('academyReaderSideToggle').addEventListener('click',position);
const params=new URLSearchParams(location.search),wanted=Number(params.get('document'));
if(Number.isInteger(wanted)&&wanted>0){
 academyPaperState.currentPage=Math.max(1,Math.min(10000,Math.floor(Number(params.get('page'))||1)));
 if(params.get('reader')==='window')academyToggleReaderFullscreen();
 if(params.get('notes')==='collapsed'&&!document.querySelector('.paper-reader-workspace').classList.contains('notes-collapsed'))$('academyReaderSideToggle').click();
 academyOpenPaperDocument(wanted,academyPaperState.currentPage).catch(e=>academySetText('academyPaperStatus','文献恢复失败：'+e.message));
}
tools(false);
})();
