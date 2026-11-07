import { afterEach, describe, expect, it } from 'vitest';
import { integrated, researchContext, visionApiUrl, visionPayload } from './clawos';
import { getApiToken } from './api';
afterEach(()=>history.replaceState({},'','/'));
describe('ClawOS namespace and provenance boundaries',()=>{
  it('keeps standalone transport paths',()=>{history.replaceState({},'','/');expect(integrated()).toBe(false);expect(visionApiUrl('/api/runs')).toBe('/api/runs');});
  it('namespaces exactly once, without rewriting external assets',()=>{history.replaceState({},'','/academy/vision/');expect(visionApiUrl('/api/runs')).toBe('/api/vision/service/runs');expect(visionApiUrl('/api/vision/service/runs')).toBe('/api/vision/service/runs');expect(visionApiUrl('https://example.org/api/a')).toBe('https://example.org/api/a');});
  it('rewrites nested resource URLs but preserves actual text',()=>{history.replaceState({},'','/academy/vision/');expect(visionPayload({url:'/api/a',prompt:'/api/a',items:[{assetUrl:'/api/b',text:'/api/b'}]})).toEqual({url:'/api/vision/service/a',prompt:'/api/a',items:[{assetUrl:'/api/vision/service/b',text:'/api/b'}]});});
  it('never forwards an old standalone token in integrated mode',()=>{sessionStorage.setItem('clawvision.api-token','old-test-token');history.replaceState({},'','/academy/vision/');expect(getApiToken()).toBeNull();});
  it('accepts only known research domains',()=>{history.replaceState({},'','/academy/vision/?domain=rag');expect(researchContext()?.id).toBe('rag');history.replaceState({},'','/academy/vision/?domain=unknown');expect(researchContext()).toBeUndefined();});
});
