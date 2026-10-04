/* Owned Chrome contexts and in-memory session cookies; synthetic human scores. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const args=process.argv.slice(2),opt=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=opt('url','http://127.0.0.1:18920'),out=path.resolve(opt('out','clawos/output/evolution-stage3-browser-20261004'));
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)||!out.startsWith(path.resolve('clawos/output')+path.sep))throw Error('Owned loopback and ignored output required');
const pw=require(opt('playwright','playwright'));fs.mkdirSync(out,{recursive:true});
const report={checks:[],accessibility:[],page_errors:[],scope:'actual Chrome and server-issued sessions; synthetic reviewers/scores, no teacher independence, screen-reader speech or quality gain claim'};
let browser;
async function check(name,fn){await fn();report.checks.push(name);console.log('PASS '+name);}
async function json(response){assert.ok(response.ok(),await response.text());return response.json();}
async function scan(page,state){if(!opt('axe'))return;await page.addScriptTag({path:opt('axe')});const result=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),incomplete:r.incomplete.map(v=>v.id)};});report.accessibility.push({state,...result});assert.deepEqual(result.violations,[],state);}
(async()=>{
 browser=await pw.chromium.launch({headless:true,...(opt('browser')?{executablePath:opt('browser')}:{})});report.browser=browser.version();
 const owner=await browser.newContext({baseURL:url,viewport:{width:1440,height:1000},acceptDownloads:true}),page=await owner.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));
 const marker=await json(await owner.request.get('/api/qa/environment'));assert.equal(marker.isolated,true);assert.equal(marker.models_enabled,true);
 const cohort=Date.now().toString(36),eidResult=await json(await owner.request.post('/api/self-evolution/experiments',{data:{target_type:'tool_routing_policy',target_key:'stage3-browser-'+cohort,baseline_payload:{},cases:Array.from({length:10},(_,i)=>({id:`browser-${i}`,group_id:`group-${i}`,query:`浏览器验收 ${cohort} ${i}：请简要列出 context 允许的工具。`,reviewed_by:'synthetic-browser',route:{allowed_tools:['file_read','file_write','shell_exec','web_fetch','web_search']},required_tools:['file_read'],forbidden_tools:['file_write','shell_exec','web_fetch']}))}}));
 const eid=eidResult.experiment.id,base=`/api/self-evolution/experiments/${eid}`,native=`/api/evolution-review/${eid}`;report.experiment_id=eid;
 await json(await owner.request.post(base+'/replay'));
 await page.goto(url+'/console?view=evolution');await page.locator('#evolutionExperimentTable th').first().waitFor();
 await page.locator('#evolutionReviewId').fill(String(eid));await page.locator('#evolutionCaptureTimeout').fill('60');
 await check('owner sees bounded call budget and captures actual primary-provider answers',async()=>{
  await page.getByRole('button',{name:'查看调用预算与进度',exact:true}).click();await page.locator('#evolutionCaptureStatus').filter({hasText:'计划 4 次调用'}).waitFor();
  await page.getByRole('button',{name:'捕获或继续模型回答',exact:true}).click();await page.locator('#evolutionReviewStatus').filter({hasText:'模型回答已捕获并冻结'}).waitFor({timeout:180000});
  const pending=page.waitForEvent('download');await page.getByRole('button',{name:'下载调用凭据',exact:true}).click();await (await pending).saveAs(path.join(out,'model-receipts.json'));
  const receipts=JSON.parse(fs.readFileSync(path.join(out,'model-receipts.json'),'utf8')).receipts;assert.equal(receipts.length,4);assert.ok(receipts.every(row=>row.duration_ms>=0));report.model_calls=receipts.length;
 });
 const doc=await json(await owner.request.post('/api/academy/learning/documents',{data:{title:'UI identity fixture',blocks:[{id:'p',type:'paragraph',text:'Synthetic owned sessions'}]}}));
 const users=[];
 for(const [i,role] of ['reviewer','reviewer','adjudicator'].entries()){
  const invite=await json(await owner.request.post(`/api/collaboration/documents/${doc.id}/invite`,{data:{role:'viewer'}}));
  const context=await browser.newContext({baseURL:url,viewport:{width:1440,height:1000}}),viewer=await json(await context.request.post('/api/collaboration/join',{data:{code:invite.code,name:`验收会话 ${i+1}`}}));
  users.push({context,viewer,role,page:await context.newPage()});users[i].page.on('pageerror',error=>report.page_errors.push(error.message));
 }
 await check('owner assigns reviewer and adjudicator roles through the actual form',async()=>{
  await page.getByRole('button',{name:'加载会话用户',exact:true}).click();await page.locator(`#evolutionReviewUser option[value="${users[0].viewer.id}"]`).waitFor({state:'attached'});
  for(const user of users){await page.locator('#evolutionReviewUser').selectOption(user.viewer.id);await page.locator('#evolutionReviewRole').selectOption(user.role);const pending=page.waitForResponse(response=>response.url().endsWith('/review-grants')&&response.request().method()==='POST');await page.getByRole('button',{name:'保存授权',exact:true}).click();await json(await pending);await page.locator('#evolutionGrantStatus').filter({hasText:'实验授权已保存'}).waitFor();}
 });
 await check('reviewer page binds session and keeps both answers anonymous',async()=>{
  const review=users[0];await review.page.goto(url+`/evolution-review?experiment=${eid}`);await review.page.locator('#workspace:not([hidden])').waitFor();assert.match(await review.page.locator('#identity').innerText(),/验收会话 1/);assert.equal(await review.page.locator('#prior:visible').count(),0);
  const payload=await json(await review.context.request.get(native+'/packet'));assert.equal(payload.viewer.id,review.viewer.id);assert.ok(!payload.summary.reviewed_gate&&!payload.packet.mapping&&!payload.packet.prior_ratings);
 });
 async function fill(p,score){for(const label of ['A','B']){await p.locator('#score'+label).fill(label==='A'?String(score):'.8');await p.locator('#rationale'+label).fill('浏览器协议验收评分，未代表真实教师判断。');}}
 await check('cross-question drafts survive navigation and incomplete packet cannot submit',async()=>{
  const p=users[0].page;await fill(p,.8);await p.getByRole('button',{name:'保存草稿并下一题',exact:true}).click();await p.getByRole('button',{name:'上一题',exact:true}).click();assert.equal(await p.locator('#scoreA').inputValue(),'0.8');
  await p.getByRole('button',{name:'提交整份评审',exact:true}).click();await p.locator('#status').filter({hasText:'请完成每题'}).waitFor();assert.equal(await p.locator('#navigator').inputValue(),'1');
 });
 await check('two authenticated reviewers submit immutable conflicting judgments through UI',async()=>{
  for(const [i,user] of users.slice(0,2).entries()){
   if(i)await user.page.goto(url+`/evolution-review?experiment=${eid}`);await user.page.locator('#workspace:not([hidden])').waitFor();
   await user.page.locator('#navigator').selectOption('0');await fill(user.page,i?.3:.8);await user.page.getByRole('button',{name:'保存草稿并下一题',exact:true}).click();await fill(user.page,i?.3:.8);
   await user.page.getByRole('button',{name:'提交整份评审',exact:true}).click();await user.page.locator('#status').filter({hasText:'整份评审已提交并冻结'}).waitFor();assert.equal(await user.page.locator('#scoreA').isDisabled(),true);
  }
  const summary=(await json(await owner.request.get(base+'/review/summary'))).summary;assert.equal(summary.authenticated_reviewer_count,2);assert.equal(summary.authenticated_adjudication_required.length,2);
 });
 await check('a separate adjudicator sees pseudonymous reasons and resolves exact review snapshot',async()=>{
  const p=users[2].page;await p.goto(url+`/evolution-review?experiment=${eid}`);await p.locator('#workspace:not([hidden])').waitFor();await p.locator('#prior summary').click();assert.match(await p.locator('#priorContent').innerText(),/评审 1/);assert.doesNotMatch(await p.locator('#priorContent').innerText(),/验收会话/);
  await fill(p,.8);await p.getByRole('button',{name:'提交当前题裁决',exact:true}).click();await p.locator('#progress').filter({hasText:'1 / 1'}).waitFor();await fill(p,.8);await p.getByRole('button',{name:'提交当前题裁决',exact:true}).click();await p.locator('#status').filter({hasText:'当前没有待裁决分歧'}).waitFor();
  const summary=(await json(await owner.request.get(base+'/review/summary'))).summary;assert.equal(summary.authenticated_resolved_entries,2);assert.equal(summary.authenticated_review_passed,false);assert.equal(summary.real_person_independence_verified,false);
 });
 await check('owner summary distinguishes captured execution, authenticated sessions and insufficient support',async()=>{
  await page.getByRole('button',{name:'刷新评审结果',exact:true}).click();await page.locator('#evolutionReviewResult').filter({hasText:'已认证会话评审者'}).waitFor();assert.match(await page.locator('#evolutionReviewResult').innerText(),/样本不足/);await scan(page,'owner-desktop');
 });
 await check('review page accessibility, mobile layout and keyboard focus',async()=>{
  const p=users[0].page;await p.reload();await p.locator('#status').filter({hasText:'你的评审已经提交'}).waitFor();assert.equal(await p.locator('#scoreA').inputValue(),'0.8');assert.match(await p.locator('#progress').innerText(),/已冻结判断/);await scan(p,'reviewer-desktop');await p.screenshot({path:path.join(out,'reviewer-desktop.png'),fullPage:true});
  await p.setViewportSize({width:390,height:844});assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await scan(p,'reviewer-mobile');await p.screenshot({path:path.join(out,'reviewer-mobile.png'),fullPage:true});
  await p.keyboard.press('Tab');assert.match(await p.locator(':focus').innerText(),/跳到当前问题/);await p.keyboard.press('Enter');assert.equal(await p.locator('#question').evaluate(node=>node===document.activeElement),true);
 });
 await check('revoked session loses UI write access and server rejects forged ratings',async()=>{
  await page.locator('#evolutionReviewUser').selectOption(users[1].viewer.id);await page.locator('#evolutionReviewRole').selectOption('revoked');const pending=page.waitForResponse(response=>response.url().endsWith('/review-grants')&&response.request().method()==='POST');await page.getByRole('button',{name:'保存授权',exact:true}).click();await json(await pending);await page.locator('#evolutionGrantStatus').filter({hasText:'实验授权已保存'}).waitFor();
  await users[1].page.getByRole('button',{name:'重新核对权限',exact:true}).click();await users[1].page.locator('#status').filter({hasText:'no active review role'}).waitFor();assert.equal(await users[1].page.locator('#scoreA').isDisabled(),true);
  assert.equal((await users[1].context.request.post(native+'/ratings',{data:{reviewer:users[0].viewer.id}})).status(),403);
 });
 await check('owner mobile layout contains expanded review and capture panels',async()=>{await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await scan(page,'owner-mobile');await page.locator('.evolution-review-panel').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'owner-mobile.png')});});
 await check('switching the logged-in session clears another reviewer’s in-memory judgments',async()=>{
  const user=users[0];await user.context.request.post('/api/collaboration/logout');
  const invite=await json(await owner.request.post(`/api/collaboration/documents/${doc.id}/invite`,{data:{role:'viewer'}}));
  const viewer=await json(await user.context.request.post('/api/collaboration/join',{data:{code:invite.code,name:'会话切换验收'}}));
  await json(await owner.request.post(base+'/review-grants',{data:{user_id:viewer.id,role:'reviewer'}}));
  await user.page.getByRole('button',{name:'重新核对权限',exact:true}).click();await user.page.locator('#identity').filter({hasText:'会话切换验收'}).waitFor();
  assert.equal(await user.page.locator('#scoreA').inputValue(),'');assert.equal(await user.page.locator('#rationaleA').inputValue(),'');assert.equal(await user.page.locator('#scoreA').isDisabled(),false);
 });
 const evidence=(await json(await owner.request.get(base+'/review/evidence'))).evidence;fs.writeFileSync(path.join(out,'review-evidence.json'),JSON.stringify(evidence,null,2));
 for(const user of users)await user.context.request.post('/api/collaboration/logout');
 assert.deepEqual(report.page_errors,[]);report.checks.push('no uncaught browser errors');
})().catch(error=>{report.error=error.stack;console.error(error.stack);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));if(browser)await browser.close();});
