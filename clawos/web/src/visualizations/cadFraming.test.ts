import {describe,it,expect} from 'vitest';
import {modelFrameDistance,normalizedModelBounds} from './cadFraming';
describe('Imported model framing',()=>{
  it('scales the translation with off-origin millimeter coordinates',()=>{
    const min=[1000,-200,500],max=[1200,1800,900],v=normalizedModelBounds(min,max);
    expect(min[1]*v.scale+v.position[1]).toBeCloseTo(0);
    expect((min[0]+max[0])/2*v.scale+v.position[0]).toBeCloseTo(0);
    expect((min[2]+max[2])/2*v.scale+v.position[2]).toBeCloseTo(0);
    expect(Math.hypot(...max.map((x,i)=>(x-min[i])*v.scale))).toBeCloseTo(3.8);
  });
  it('fits every bounding-box corner in wide and narrow perspective viewports',()=>{
    const v=normalizedModelBounds([-1,0,-1],[1,9,1]);
    for(const aspect of [.35,1,2.5]){
      const distance=modelFrameDistance(v.radius,aspect);
      const limiting=Math.min(23*Math.PI/180,Math.atan(Math.tan(23*Math.PI/180)*aspect));
      expect(Math.asin(v.radius/distance)).toBeLessThan(limiting);
    }
    expect(modelFrameDistance(v.radius,.35)).toBeGreaterThan(modelFrameDistance(v.radius,2.5));
  });
  it('accepts planar geometry and rejects empty, inverted and nonfinite bounds',()=>{
    expect(normalizedModelBounds([0,0,0],[1,0,1]).radius).toBeCloseTo(1.9);
    for(const [a,b] of [[[0,0,0],[0,0,0]],[[2,0,0],[1,1,1]],[[NaN,0,0],[1,1,1]]])expect(()=>normalizedModelBounds(a,b)).toThrow();
  });
});
