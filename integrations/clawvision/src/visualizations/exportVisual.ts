/** Standalone chart exports retain resolved theme styles and original data text. */
const styleProperties=['fill','stroke','stroke-width','stroke-dasharray','stroke-linecap','stroke-linejoin','font-family','font-size','font-weight','opacity','fill-opacity','stroke-opacity','text-anchor'];
export function serializeVisualSvg(svg:SVGSVGElement,provenance?:unknown){
  const clone=svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
  const originals=[svg,...svg.querySelectorAll('*')],copies=[clone,...clone.querySelectorAll('*')];
  originals.forEach((element,i)=>{const computed=getComputedStyle(element),copy=copies[i] as SVGElement;for(const property of styleProperties){const value=computed.getPropertyValue(property);if(value)copy.style.setProperty(property,value);}});
  if(provenance!==undefined){const metadata=document.createElementNS('http://www.w3.org/2000/svg','metadata');metadata.textContent=JSON.stringify(provenance);clone.prepend(metadata);}
  return new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml;charset=utf-8'});
}
export async function pngFromSvg(blob:Blob,width=1280,ratio=.5){
  const url=URL.createObjectURL(blob);
  try{
    const image=new Image();await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(Error('图形转换失败'));image.src=url;});
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=Math.max(200,Math.round(width*ratio));
    const context=canvas.getContext('2d');if(!context)throw Error('浏览器没有图像导出上下文');
    context.fillStyle='#fffefb';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
    const result=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/png'));if(!result)throw Error('PNG导出未完成');return result;
  }finally{URL.revokeObjectURL(url);}
}
export function csvText(rows:Record<string,unknown>[],fields:string[]){
  const cell=(value:unknown)=>{const text=value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);return /[,"\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;};
  return '\ufeff'+[fields.map(cell).join(','),...rows.map(row=>fields.map(field=>cell(row[field])).join(','))].join('\r\n')+'\r\n';
}
