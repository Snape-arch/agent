/// <reference lib="webworker" />

type ImportRequest={files:File[]};

function encode(bytes:Uint8Array):string{
  const chunk=0x8000;let binary='';
  for(let offset=0;offset<bytes.length;offset+=chunk) binary+=String.fromCharCode(...bytes.subarray(offset,Math.min(bytes.length,offset+chunk)));
  return btoa(binary);
}

self.onmessage=async(event:MessageEvent<ImportRequest>)=>{
  try{
    const files=event.data.files;const main=files.find((file)=>/\.(glb|gltf|obj|stl|ply|step|stp|iges|igs|brep|brp)$/i.test(file.name));
    if(!main) throw new Error('请选择 GLB、GLTF、OBJ、STL、PLY、STEP、IGES 或 BREP 主文件');
    const results:Array<{name:string;mimeType:string;base64:string}>=[];
    for(let index=0;index<files.length;index++){
      const file=files[index];const buffer=new Uint8Array(await file.arrayBuffer());results.push({name:file.name,mimeType:file.type||'application/octet-stream',base64:encode(buffer)});
      self.postMessage({type:'progress',progress:Math.round((index+1)/files.length*100),name:file.name});
    }
    const primary=results.find((item)=>item.name===main.name)!;const rawFormat=main.name.split('.').pop()!.toLowerCase();const format=rawFormat==='stp'?'step':rawFormat==='igs'?'iges':rawFormat==='brp'?'brep':rawFormat;self.postMessage({type:'complete',main:primary,format,resources:results.filter((item)=>item!==primary)});
  }catch(error){self.postMessage({type:'error',message:error instanceof Error?error.message:'模型文件处理失败'});}
};

export {};
