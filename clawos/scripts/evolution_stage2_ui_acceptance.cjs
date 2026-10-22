/* CI-owned Chromium profile; synthetic fixtures only, no user browser/session. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const args=process.argv.slice(2),opt=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=opt('url','http://127.0.0.1:18919'),out=path.resolve(opt('out','clawos/output/evolution-stage2-browser-20261004'));
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw Error('Isolated loopback preview required');
if(!out.startsWith(path.resolve('clawos/output')+path.sep))throw Error('Keep evidence under ignored clawos/output');
const cohort=opt('cohort',Date.now().toString(36)),uiTarget='ci-ui-stage2-'+cohort,pausedTarget='stage2-paused-'+cohort;
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
 const cases=Array.from({length:200},(_,i)=>({id:`ci-fixture-${i}`,group_id:`fixture-group-${i}`,query:`CI fixture route ${cohort} ${i}`,reviewed_by:'synthetic-ci-fixture',origin:'curated',
  route:{allowed_tools:['file_read','file_write','shell_exec','web_fetch','web_search']},required_tools:['file_read'],forbidden_tools:['file_write','shell_exec','web_fetch']}));
 const payload={target_type:'tool_routing_policy',target_key:uiTarget,baseline_payload:{},cases};
 const file=path.join(out,'fixture.json');fs.writeFileSync(file,JSON.stringify(payload));let experimentRow;
 await check('file picker freezes reviewed synthetic task dataset',async()=>{
  const chooser=page.waitForEvent('filechooser');await page.locator('#evolutionExperimentFile').click();await (await chooser).setFiles(file);
  await page.getByRole('button',{name:'冻结为实验',exact:true}).click();await page.locator('#evolutionExperimentStatus').filter({hasText:'已冻结'}).waitFor();
  experimentRow=page.locator('#evolutionExperimentTable tr').filter({hasText:'tool_routing_policy/'+uiTarget});await experimentRow.waitFor();
 });
 await check('paired replay completes with held-out evidence without user traffic',async()=>{
  const button=experimentRow.getByRole('button',{name:'成对回放',exact:true});if(await button.count()){await button.click();await page.locator('#evolutionExperimentStatus').filter({hasText:'留出验证通过'}).waitFor();}
  await experimentRow.filter({hasText:'completed'}).waitFor();
  assert.match(await experimentRow.innerText(),/163 \/ 37/);assert.match(await experimentRow.innerText(),/仍需回归和线上证据/);
 });
 await check('nomination creates candidate with zero live evidence',async()=>{
  await experimentRow.getByRole('button',{name:'提名候选',exact:true}).click();await page.locator('#evolutionExperimentStatus').filter({hasText:'已提名'}).waitFor();
  const row=page.locator('#evolutionRunTable tr').filter({hasText:'tool_routing_policy/'+uiTarget});await row.waitFor();
  assert.match(await row.innerText(),/candidate/);assert.match(await row.innerText(),/0 个任务/);assert.equal(await row.getByRole('button',{name:'激活',exact:true}).count(),0);
 });
 await check('download is a real JSON file with immutable replay and input fingerprints',async()=>{
  const pending=page.waitForEvent('download');await experimentRow.getByRole('button',{name:'下载证据',exact:true}).click();
  const download=await pending,filename=path.join(out,'downloaded-experiment.json');await download.saveAs(filename);
  const evidence=JSON.parse(fs.readFileSync(filename,'utf8'));assert.equal(evidence.status,'completed');assert.equal(evidence.report.runtime_promotion_evidence,false);
  assert.ok(evidence.report.report_digest);assert.ok(evidence.definition.loaded_executor_digest);assert.equal(evidence.report.holdout_groups,37);
 });
 await check('paused pending experiment resumes through the actual browser control',async()=>{
  const rows=Array.from({length:20},(_,i)=>({id:`paused-${i}`,group_id:`fixture-group-${i}`,query:`New paused UI task ${cohort} ${i}`,reviewed_by:'synthetic-ui',route:{allowed_tools:['file_read','file_write','shell_exec','web_fetch','web_search']},required_tools:['file_read'],forbidden_tools:['file_write','shell_exec','web_fetch']}));
  const response=await context.request.post('/api/self-evolution/experiments',{data:{target_type:'tool_routing_policy',target_key:pausedTarget,baseline_payload:{},cases:rows}});assert.ok(response.ok(),await response.text());
  const exp=(await response.json()).experiment;assert.ok((await context.request.post(`/api/self-evolution/experiments/${exp.id}/control`,{data:{action:'pause'}})).ok());
  await page.getByRole('button',{name:'刷新',exact:true}).click();const row=page.locator('#evolutionExperimentTable tr').filter({hasText:pausedTarget});await row.filter({hasText:'paused'}).waitFor();
  await row.getByRole('button',{name:'继续回放',exact:true}).click();await row.filter({hasText:'completed'}).waitFor({timeout:190000});assert.match(await row.innerText(),/检查点/);
 });
 await check('paired output file freezes an immutable blinded packet',async()=>{
  const exp=JSON.parse(fs.readFileSync(path.join(out,'downloaded-experiment.json'),'utf8'));
  const crypto=require('node:crypto'),canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
  const digest=v=>crypto.createHash('sha256').update(JSON.stringify(canonical(v))).digest('hex');
  const payload={actor_id:'synthetic-ui-submitter',definition_digest:exp.definition_digest,report_digest:exp.report.report_digest,outputs:exp.report.holdout_pairs.map(pair=>({case_id:pair.case_id,input_digest:pair.input_digest,variants:Object.fromEntries([['control',exp.definition.baseline_payload],['candidate',exp.report.selected_payload]].map(([variant,policy])=>[variant,{text:`Synthetic blinded answer for ${pair.case_id}; no model call.`,provider:'synthetic-ui',model:'fixture-only',policy_digest:digest(policy)}]))}))};
  fs.writeFileSync(path.join(out,'outputs.json'),JSON.stringify(payload));await experimentRow.getByRole('button',{name:'准备盲评',exact:true}).click();
  assert.equal(await page.getByRole('spinbutton',{name:'评审实验编号',exact:true}).inputValue(),String(exp.id));await page.getByRole('button',{name:'冻结模型输出',exact:true}).click();await page.locator('#evolutionReviewStatus').filter({hasText:'请选择实验并上传'}).waitFor();
  await page.locator('#evolutionReviewFile').setInputFiles(path.join(out,'outputs.json'));await page.getByRole('button',{name:'冻结模型输出',exact:true}).click();await page.locator('#evolutionReviewStatus').filter({hasText:'输出已冻结'}).waitFor();
  const pending=page.waitForEvent('download');await page.getByRole('button',{name:'下载盲评包',exact:true}).click();const download=await pending;await download.saveAs(path.join(out,'blind-packet.json'));
  const packet=JSON.parse(fs.readFileSync(path.join(out,'blind-packet.json'),'utf8'));assert.equal(packet.entries.length,37);assert.equal(packet.runtime_promotion_evidence,false);assert.ok(packet.entries.every(row=>!row.mapping&&Object.values(row.options).every(value=>!value.policy_digest&&!value.provider)));
 });
 await check('two imported reviews remain separate from verified runtime evidence',async()=>{
  const packet=JSON.parse(fs.readFileSync(path.join(out,'blind-packet.json'),'utf8'));
  for(const reviewer of ['synthetic-ui-reviewer-a','synthetic-ui-reviewer-b']){
    const rating={reviewer,packet_digest:packet.packet_digest,ratings:packet.entries.map(row=>({entry_id:row.entry_id,options:Object.fromEntries(Object.entries(row.options).map(([label,value])=>[label,{text_digest:value.text_digest,score:.8,rationale:'Synthetic browser check; not actual teacher review',critical_error:false}]))}))};
    const filename=path.join(out,reviewer+'.json');fs.writeFileSync(filename,JSON.stringify(rating));await page.locator('#evolutionReviewFile').setInputFiles(filename);await page.getByRole('button',{name:'收录审核评分',exact:true}).click();await page.locator('#evolutionReviewStatus').filter({hasText:reviewer.endsWith('-a')?'已收录 1':'已收录 2'}).waitFor();
  }
  assert.match(await page.locator('#evolutionReviewResult').innerText(),/评分报告通过/);const exp=JSON.parse(fs.readFileSync(path.join(out,'downloaded-experiment.json'),'utf8'));const summary=(await (await context.request.get(`/api/self-evolution/experiments/${exp.id}/review/summary`)).json()).summary;assert.equal(summary.reported_review_passed,true);assert.equal(summary.provider_execution_verified,false);assert.equal(summary.reviewer_identity_verified,false);assert.equal(summary.runtime_promotion_evidence,false);
  const pending=page.waitForEvent('download');await page.getByRole('button',{name:'下载评审证据',exact:true}).click();const download=await pending;await download.saveAs(path.join(out,'review-evidence.json'));assert.equal(JSON.parse(fs.readFileSync(path.join(out,'review-evidence.json'),'utf8')).reviews.length,2);
 });
 await check('desktop accessibility and contained tables',async()=>{await scan(page,'desktop');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});await page.locator('.evolution-review-panel').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'viewport.png')});});
 await check('mobile remains readable without page horizontal overflow',async()=>{
  await page.setViewportSize({width:390,height:844});await page.locator('#evolutionExperimentStatus').scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await scan(page,'mobile');await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 });
 assert.deepEqual(report.page_errors,[]);console.log('PASS no uncaught browser errors');report.checks.push('no uncaught browser errors');
})().catch(error=>{report.error=error.stack;console.error(error.stack);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));if(browser)await browser.close();});
