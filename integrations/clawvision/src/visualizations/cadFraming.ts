/** Normalize imported coordinates without changing relative geometry or clipping tall assets. */
export function normalizedModelBounds(min:number[],max:number[]){
  if(min.length!==3||max.length!==3||![...min,...max].every(Number.isFinite)||min.some((v,i)=>v>max[i]))throw Error('模型边界无效');
  const size=max.map((v,i)=>v-min[i]),diagonal=Math.hypot(...size);
  if(diagonal<=0)throw Error('模型没有可显示的尺寸');
  const scale=3.8/diagonal;
  return {scale,position:[-(min[0]+max[0])/2*scale,-min[1]*scale,-(min[2]+max[2])/2*scale],target:[0,size[1]*scale/2,0],radius:diagonal*scale/2};
}
export function modelFrameDistance(radius:number,aspect:number,fovDegrees=46){
  if(![radius,aspect,fovDegrees].every(Number.isFinite)||radius<=0||aspect<=0||fovDegrees<=0||fovDegrees>=180)throw Error('模型取景参数无效');
  const vertical=fovDegrees*Math.PI/360,horizontal=Math.atan(Math.tan(vertical)*aspect);
  return radius/Math.sin(Math.min(vertical,horizontal))*1.15;
}
