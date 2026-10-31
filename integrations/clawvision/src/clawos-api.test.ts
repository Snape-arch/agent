import {afterEach,expect,it,vi} from 'vitest';
import {createParameterJob} from './api';
import {defaultParams} from './domain';
afterEach(()=>{vi.unstubAllGlobals();history.replaceState({},'','/');});
it('persists the selected reading reference without claiming paper reproduction',async()=>{
  history.replaceState({},'','/academy/vision/?domain=rag');
  const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({data:{id:'job_1',runIds:['run_1'],totalRuns:1,concurrency:1}})}).mockResolvedValueOnce({ok:true,json:async()=>({data:{id:'artifact_1'}})});vi.stubGlobal('fetch',fetcher);
  const result=await createParameterJob({name:'source context test',kind:'single',configs:[defaultParams],concurrency:1,trainingProvider:'simulator',estimateSeconds:1,estimatedCost:0});
  expect(result.readingContext).toEqual({requested:1,attached:1});expect(fetcher.mock.calls[1][0]).toBe('/api/vision/service/runs/run_1/artifacts');
  const payload=JSON.parse(fetcher.mock.calls[1][1].body);expect(payload.content.domain).toBe('rag');expect(payload.content.paperReproductionVerified).toBe(false);
});
it('reports partial attachment without retrying an already-created experiment',async()=>{
  history.replaceState({},'','/academy/vision/?domain=peft');
  const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({data:{id:'job_2',runIds:['run_2'],totalRuns:1,concurrency:1}})}).mockRejectedValueOnce(new Error('test attachment failure'));vi.stubGlobal('fetch',fetcher);
  const result=await createParameterJob({name:'failure test',kind:'single',configs:[defaultParams],concurrency:1,trainingProvider:'simulator',estimateSeconds:1,estimatedCost:0});
  expect(result.readingContext).toEqual({requested:1,attached:0});expect(fetcher).toHaveBeenCalledTimes(2);
});
