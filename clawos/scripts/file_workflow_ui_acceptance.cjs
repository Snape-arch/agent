/* CI-owned browser only: isolated loopback fixtures, never a user profile. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const args=process.argv.slice(2),opt=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=opt('url','http://127.0.0.1:18917'),out=path.resolve(opt('out','clawos/output/file-workflow-ui'));
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw Error('Use an isolated loopback preview');
const pw=require(opt('playwright','playwright'));fs.mkdirSync(out,{recursive:true});
const report={checks:[],accessibility:[],errors:[],screen_reader:'DOM and keyboard verification; no actual screen reader audio'};
async function check(name,fn){await fn();report.checks.push(name);console.log('PASS '+name);}
async function scan(page,state){if(!opt('axe'))return;await page.addScriptTag({path:opt('axe')});const result=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),incomplete:r.incomplete.map(v=>v.id)};});report.accessibility.push({state,...result});assert.deepEqual(result.violations,[],state);}
let browser;
(async()=>{
 browser=await pw.chromium.launch({headless:true,...(opt('browser')?{executablePath:opt('browser')}:{})});report.browser=browser.version();
 const context=await browser.newContext({baseURL:url,viewport:{width:1440,height:1000}}),page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 const environment=await (await context.request.get(url+'/api/qa/environment')).json();assert.equal(environment.isolated,true);assert.equal(environment.models_enabled,false);
 await page.goto(url+'/console');const session=page.locator('#sessions [data-session="acceptance-history"]');await session.waitFor();
 await check('clickable recent session and full chronological archived paging',async()=>{
  assert.ok((await session.boundingBox()).height>=40);await session.click();await page.waitForFunction(()=>document.querySelector('#historyControls')?.textContent.includes('50 / 112'));
  assert.match(await page.locator('#historyControls').innerText(),/50 \/ 112/);
  await page.locator('#historyOlder').click();await page.waitForFunction(()=>document.querySelectorAll('#chatInner .msg').length===100);
  await page.locator('#historyOlder').click();await page.waitForFunction(()=>document.querySelectorAll('#chatInner .msg').length===112);
  assert.ok((await page.locator('#chatInner .msg').first().innerText()).length>3000);assert.match(await page.locator('#chatInner .msg').last().innerText(),/111/);
 });
 await check('session survives reload and full history export is downloadable',async()=>{
  await page.reload();await page.locator('#historyControls').waitFor();assert.match(await page.locator('#historyControls').innerText(),/50 \/ 112/);
  const response=await context.request.get(await page.locator('#historyControls a').last().getAttribute('href'));assert.equal(response.status(),200);assert.equal((await response.json()).count,112);
 });
 await check('archive body search is preserved when absent from title and preview',async()=>{
  await page.locator('[data-view=search]').first().click();await page.locator('#sessionQuery').fill('完整记录 '.repeat(35).trim());
  await page.waitForResponse(r=>r.url().includes('/api/sessions?q='));await page.locator('#sessionSearchList [data-session="acceptance-history"]').waitFor();
  await page.locator('#sessionQuery').fill('不存在的归档证据XYZ');await page.getByText('暂无匹配会话',{exact:true}).waitFor();
 });
 await check('late history responses do not overwrite a new conversation',async()=>{
  await page.locator('[data-view=chat]').first().click();let release,started;
  const start=new Promise(resolve=>started=resolve),gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/history/acceptance-history',async route=>{const response=await route.fetch();started();await gate;await route.fulfill({response});});
  await session.click();await start;await page.getByRole('button',{name:'新对话',exact:true}).click();
  const finished=page.waitForResponse(r=>r.url().endsWith('/api/history/acceptance-history'));release();await finished;
  await page.waitForFunction(()=>!document.querySelector('#historyControls'));assert.match(await page.locator('#chatInner').innerText(),/开始一个新任务/);
  await page.unroute('**/api/history/acceptance-history');
 });
 await check('explicit connector view is not overridden by restored history',async()=>{
  await page.goto(url+'/console?view=feishu');await page.locator('[data-view=feishu].on').waitFor();assert.equal(await page.locator('#historyControls').count(),0);
 });
 await page.goto(url+'/academy/paper?document='+opt('document','1')+'&reader=window');const expand=page.getByRole('button',{name:'全窗口阅读报告',exact:true});await expand.waitFor();
 await check('persisted report offers a full window, source excerpts and three working downloads',async()=>{
  await expand.click();const dialog=page.getByRole('dialog',{name:'论文精读报告',exact:true});await dialog.waitFor();
  assert.ok((await dialog.boundingBox()).width>1000);assert.equal(await dialog.locator('a[download]').count(),3);
  assert.ok(await dialog.locator('blockquote').count()>0);assert.match(await dialog.innerText(),/实验条件/);
  for(const link of await dialog.locator('a[download]').all()){const response=await context.request.get(await link.getAttribute('href'));assert.equal(response.status(),200);assert.ok((await response.body()).length>100);}
  await scan(page,'full-window-report');await page.screenshot({path:path.join(out,'paper-fullscreen.png')});
 });
 await check('native dialog Escape restores focus and citations return to evidence',async()=>{
  await page.keyboard.press('Escape');assert.equal(await expand.evaluate(el=>document.activeElement===el),true);assert.equal(await page.locator('body.reader-window').count(),1);
  await expand.click();await page.locator('#paperReportDialog [data-report-citation]').first().click();assert.equal(await page.locator('#paperReportDialog[open]').count(),0);
  assert.ok(await page.locator('[data-reader-tab="evidence"].active,[data-reader-tab="evidence"].on').count()>0);
 });
 await check('390px report has no horizontal overflow and stays keyboard accessible',async()=>{
  await page.setViewportSize({width:390,height:844});await page.reload();await page.locator('#paperDeepReadOutput.grounded-paper-report').waitFor({state:'attached'});
  if(await page.locator('#academyReaderSideToggle').innerText()==='展开笔记')await page.locator('#academyReaderSideToggle').click();
  await expand.waitFor();await expand.click();const geometry=await page.locator('#paperReportDialog').evaluate(el=>({width:el.getBoundingClientRect().width,scroll:el.scrollWidth,viewport:innerWidth}));
  assert.ok(geometry.width<=geometry.viewport+1);assert.ok(geometry.scroll<=geometry.width+1);await scan(page,'mobile-full-window-report');
  await page.screenshot({path:path.join(out,'paper-mobile.png')});await page.keyboard.press('Escape');assert.equal(await expand.evaluate(el=>document.activeElement===el),true);
 });
 assert.deepEqual(report.errors,[]);report.passed=true;
})().catch(e=>{report.passed=false;report.failure=e.stack;console.error(e.stack);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'acceptance.json'),JSON.stringify(report,null,2));if(browser)await browser.close();});
