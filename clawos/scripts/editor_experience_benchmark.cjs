/* Real Chromium input/paint benchmark and axe scan; requires the isolated preview. */
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const args=process.argv.slice(2),option=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=option('url','http://127.0.0.1:18912');
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw Error('Use a loopback isolated preview URL');
const playwright=require(option('playwright','playwright'));
const root=path.resolve(__dirname,'..'),out=path.resolve(option('out',path.join(root,'output/editor-experience-benchmark')));
fs.mkdirSync(out,{recursive:true});
const percentile=(values,p)=>{const ordered=values.slice().sort((a,b)=>a-b);return ordered[Math.min(ordered.length-1,Math.floor(ordered.length*p))]||0;};
const report={date:new Date().toISOString(),runs:[],accessibility:[],errors:[]};
const fixture={title:'长文档性能验收 · 300 块',context:'仅用于隔离预览的合成资料',blocks:Array.from({length:300},(_,i)=>({id:'perf-'+i,type:i%30===0?'heading':'paragraph',text:i%30===0?'章节 '+i:'证据链与并发编辑的长文档测试。'.repeat(160),...(i%30===0?{level:2}:{})}))};
report.fixture={blocks:fixture.blocks.length,bytes:Buffer.byteLength(JSON.stringify(fixture)),characters:fixture.blocks.reduce((n,b)=>n+b.text.length,0)};
let browser;
(async()=>{
 browser=await playwright.chromium.launch({headless:true,...(option('browser')?{executablePath:option('browser')}:{})});report.browser=browser.version();
 const check=await browser.newContext();const environment=await check.request.get(url+'/api/qa/environment');
 if(!environment.ok()||(await environment.json()).isolated!==true)throw Error('Refusing fixture writes outside the isolated learning_preview');
 await check.close();
 const baseline={};if(option('baseline'))for(const name of ['academy-notes.html','assets/academy-documents.js','assets/academy-documents.css','assets/document-experience.css','assets/workspace-ui.js','assets/workspace-ui.css'])baseline['/'+name]=execFileSync('git',['show',option('baseline')+':clawos/static/'+name],{cwd:path.resolve(root,'..')});
 const variants=option('baseline')?['baseline','current']:['current'];
 for(const variant of variants)for(let repeat=0;repeat<(args.includes('--scan-only')?0:3);repeat++){
  const context=await browser.newContext({viewport:{width:1280,height:800}}),page=await context.newPage();page.on('pageerror',e=>report.errors.push({variant,message:e.message}));
  const response=await context.request.post(url+'/api/academy/learning/documents',{data:fixture});if(!response.ok())throw Error(await response.text());const doc=await response.json();
  if(variant==='baseline')await page.route('**/*',async route=>{const pathname=new URL(route.request().url()).pathname;const key=pathname==='/academy/notes'?'/academy-notes.html':pathname;const body=baseline[key];if(body)await route.fulfill({body,contentType:key.endsWith('.js')?'application/javascript':key.endsWith('.css')?'text/css':'text/html'});else await route.continue();});
  await page.addInitScript(()=>{
   window.qaTiming={keys:[],longTasks:[],readyMs:0};
   new PerformanceObserver(list=>window.qaTiming.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
   const observer=new MutationObserver(()=>{if(document.querySelectorAll('#docBlocks .doc-block').length===300){observer.disconnect();requestAnimationFrame(()=>requestAnimationFrame(()=>window.qaTiming.readyMs=performance.now()));}});observer.observe(document,{childList:true,subtree:true});
   document.addEventListener('keydown',e=>{if(e.target.isContentEditable&&e.key.length===1){const start=performance.now();requestAnimationFrame(()=>requestAnimationFrame(()=>window.qaTiming.keys.push(performance.now()-start)));}},true);
  });
  await page.goto(url+'/academy/notes?document='+doc.id);await page.waitForFunction(()=>window.qaTiming?.readyMs>0,{},{timeout:10000});
  const editor=page.locator('.doc-block.paragraph .block-edit').first();await editor.click();await editor.press('Control+Home');
  const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
  await page.keyboard.type('Evidence '.repeat(9),{delay:8});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const timing=await page.evaluate(()=>window.qaTiming),metrics=await cdp.send('Performance.getMetrics');
  const run={variant,repeat:repeat+1,readyMs:+timing.readyMs.toFixed(2),samples:timing.keys.length,inputPaintP50Ms:+percentile(timing.keys,.5).toFixed(2),inputPaintP95Ms:+percentile(timing.keys,.95).toFixed(2),inputPaintMaxMs:+Math.max(...timing.keys).toFixed(2),longTasks:timing.longTasks.length,longTaskMaxMs:+Math.max(0,...timing.longTasks.map(e=>e.duration)).toFixed(2),heapMB:+(metrics.metrics.find(m=>m.name==='JSHeapUsedSize').value/1048576).toFixed(2)};
  report.runs.push(run);console.log(JSON.stringify(run));await context.close();
 }
 for(const variant of variants){const runs=report.runs.filter(r=>r.variant===variant);if(runs.length)report[variant]={readyMedianMs:percentile(runs.map(r=>r.readyMs),.5),inputPaintP95MedianMs:percentile(runs.map(r=>r.inputPaintP95Ms),.5),heapMedianMB:percentile(runs.map(r=>r.heapMB),.5)};}
 if(option('axe')){
  const context=await browser.newContext({viewport:{width:1280,height:800}}),page=await context.newPage();
  for(const route of ['/academy/notes','/academy/code','/academy/path','/academy/quiz','/academy/ingest','/academy/paper','/meetings','/data-lab','/console?view=feishu']){
   await page.goto(url+route);await page.locator('.workspace-nav').waitFor({timeout:5000});
   await page.addScriptTag({path:option('axe')});const scan=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),passes:r.passes.length,incomplete:r.incomplete.map(v=>v.id)};});
   report.accessibility.push({route,...scan});console.log('axe '+route+' '+scan.violations.map(v=>v.id).join(','));
  }
  await context.close();
 }
 report.pass=report.errors.length===0&&report.accessibility.every(scan=>!scan.violations.length)&&(args.includes('--scan-only')||(report.current.readyMedianMs<2000&&report.current.inputPaintP95MedianMs<100));
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log('Report: '+path.join(out,'result.json'));
 if(!report.pass)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
