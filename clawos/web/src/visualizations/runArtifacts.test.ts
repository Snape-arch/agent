import {expect,it} from 'vitest';
import {parameterTableArtifact} from './runArtifacts';
import {defaultParams,type ExperimentRun} from '../domain';
it('keeps internal execution metadata out of the readable parameter table',()=>{
 const run={id:'r',params:{...defaultParams,_execution:{synthetic:true},_jobId:'job-private'}} as unknown as ExperimentRun;
 const data=parameterTableArtifact(run).data as {rows:Array<{key:string;value:string}>};
 expect(data.rows.some(r=>r.key.startsWith('_'))).toBe(false);expect(data.rows.find(r=>r.key==='学习率')?.value).toBe('0.001');expect(data.rows.find(r=>r.key==='混合精度')?.value).toBe('开启');
});
