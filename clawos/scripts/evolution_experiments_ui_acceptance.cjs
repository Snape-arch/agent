/* CI-owned Chromium profile; synthetic fixtures only, no user browser/session. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const args=process.argv.slice(2),opt=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=opt('url','http://127.0.0.1:18918'),out=path.resolve(opt('out','clawos/output/evolution-experiments-browser-20261003'));
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw Error('Isolated loopback preview required');
if(!out.startsWith(path.resolve('clawos/output')+path.sep))throw Error('Keep evidence under ignored clawos/output');
const pw=require(opt('playwright','playwright'));fs.mkdirSync(out,{recursive:true});
const report={checks:[],accessibility:[],page_errors:[],scope:'synthetic CI-owned Chrome, no real model, user-quality gain or screen-reader speech claim'};
async function check(name,fn){await fn();report.checks.push(name);console.log('PASS '+name);}
async function scan(page,state){if(!opt('axe'))return;await page.addScriptTag({path:opt('axe')});const r=await page.evaluate(async()=>{
 const data=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});
 return {violations:data.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),incomplete:data.incomplete.map(v=>v.id)};
});report.accessibility.push({state,...r});assert.deepEqual(r.violations,[],state);}
let browser;
(async()=>{
 browser=await pw.chromium.launch({headless:true,...(opt('browser')?{executablePath:opt('browser')}:{})});report.browser=browser.version();
 const context=await browser.newContext({baseURL:url,viewport:{width:1440,height:1000},acceptDownloads:true}),page=await context.newPage();
 page.on('pageerror',e=>report.page_errors.push(e.message));
 const marker=await (await context.request.get('/api/qa/environment')).json();assert.equal(marker.isolated,true);assert.equal(marker.models_enabled,false);report.marker=marker;
 await page.goto(url+'/console?view=evolution');await page.locator('#evolutionExperimentTable th').first().waitFor();
 await check('labelled form compares multiple bounded candidates',async()=>{
  await page.getByRole('combobox',{name:'策略目标',exact:true}).selectOption('retrieval_params');await page.getByRole('textbox',{name:'当前基线 JSON',exact:true}).fill('{"top_k":10,"citation_aware":true}');
  await page.getByRole('button',{name:'比较多个候选',exact:true}).click();await page.locator('#evolutionCandidateGrid article').nth(2).waitFor();
  assert.equal(await page.locator('#evolutionCandidateGrid article').count(),3);assert.match(await page.locator('#evolutionSearchStatus').innerText(),/尚未验证质量提升/);
  await page.locator('#evolutionCandidateGrid summary').first().click();assert.match(await page.locator('#evolutionCandidateGrid pre').first().innerText(),/top_k/);
 });
 await check('missing upload stays on page with explicit guidance',async()=>{
  await page.getByRole('button',{name:'冻结为实验',exact:true}).click();assert.match(await page.locator('#evolutionExperimentStatus').innerText(),/请先选择/);
 });
 const cases=Array.from({length:200},(_,i)=>({id:`ci-fixture-${i}`,group_id:`fixture-group-${i}`,query:`CI fixture route ${i}`,reviewed_by:'synthetic-ci-fixture',origin:'curated',
  route:{allowed_tools:['file_read','file_write','shell_exec','web_fetch','web_search']},required_tools:['file_read'],forbidden_tools:['file_write','shell_exec','web_fetch']}));
 const payload={target_type:'tool_routing_policy',target_key:'ci-ui-acceptance',baseline_payload:{},cases};
 const file=path.join(out,'fixture.json');fs.writeFileSync(file,JSON.stringify(payload));let experimentRow;
 await check('file picker freezes reviewed synthetic task dataset',async()=>{
  const chooser=page.waitForEvent('filechooser');await page.locator('#evolutionExperimentFile').click();await (await chooser).setFiles(file);
  await page.getByRole('button',{name:'冻结为实验',exact:true}).click();await page.locator('#evolutionExperimentStatus').filter({hasText:'已冻结'}).waitFor();
  experimentRow=page.locator('#evolutionExperimentTable tr').filter({hasText:'tool_routing_policy/ci-ui-acceptance'});await experimentRow.waitFor();
 });
 await check('paired replay completes with held-out evidence without user traffic',async()=>{
  const button=experimentRow.getByRole('button',{name:'成对回放',exact:true});if(await button.count()){await button.click();await page.locator('#evolutionExperimentStatus').filter({hasText:'留出验证通过'}).waitFor();}
  await experimentRow.filter({hasText:'completed'}).waitFor();
  assert.match(await experimentRow.innerText(),/163 \/ 37/);assert.match(await experimentRow.innerText(),/仍需回归和线上证据/);
 });
 await check('nomination creates candidate with zero live evidence',async()=>{
  await experimentRow.getByRole('button',{name:'提名候选',exact:true}).click();await page.locator('#evolutionExperimentStatus').filter({hasText:'已提名'}).waitFor();
  const row=page.locator('#evolutionRunTable tr').filter({hasText:'tool_routing_policy/ci-ui-acceptance'});await row.waitFor();
  assert.match(await row.innerText(),/candidate/);assert.match(await row.innerText(),/0 个任务/);assert.equal(await row.getByRole('button',{name:'激活',exact:true}).count(),0);
 });
 await check('download is a real JSON file with immutable replay and input fingerprints',async()=>{
  const pending=page.waitForEvent('download');await experimentRow.getByRole('button',{name:'下载证据',exact:true}).click();
  const download=await pending,filename=path.join(out,'downloaded-experiment.json');await download.saveAs(filename);
  const evidence=JSON.parse(fs.readFileSync(filename,'utf8'));assert.equal(evidence.status,'completed');assert.equal(evidence.report.runtime_promotion_evidence,false);
  assert.ok(evidence.report.report_digest);assert.ok(evidence.definition.loaded_executor_digest);assert.equal(evidence.report.holdout_groups,37);
 });
 await check('desktop accessibility and contained tables',async()=>{await scan(page,'desktop');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});});
 await check('mobile remains readable without page horizontal overflow',async()=>{
  await page.setViewportSize({width:390,height:844});await page.locator('#evolutionExperimentStatus').scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await scan(page,'mobile');await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 });
 assert.deepEqual(report.page_errors,[]);console.log('PASS no uncaught browser errors');report.checks.push('no uncaught browser errors');
})().catch(error=>{report.error=error.stack;console.error(error.stack);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));if(browser)await browser.close();});
