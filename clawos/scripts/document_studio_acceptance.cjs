/* CI-owned browser contexts: synthetic inputs, no user Chrome profile or production data. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const args=process.argv.slice(2),option=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0?fallback:args[i+1];};
const url=option('url','http://127.0.0.1:18916'),out=path.resolve(option('out','clawos/output/document-studio-acceptance'));
if(!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw Error('Use an isolated loopback preview');
const pw=require(option('playwright','playwright'));fs.mkdirSync(out,{recursive:true});
const report={checks:[],errors:[],accessibility:[],viewports:[],screenReader:{status:'browser accessibility tree and keyboard only; no NVDA/Narrator audio verification'}};
let browser;
async function check(name,fn){await fn();report.checks.push(name);console.log('PASS '+name);}
async function ready(page){await page.waitForFunction(()=>document.querySelector('#docStatus')?.textContent.includes('版本')&&document.querySelector('#docLiveStatus')?.textContent.includes('已连接'),{},{timeout:10000});}
async function responseJSON(response){assert.equal(response.ok(),true,await response.text());return response.json();}
async function scan(page,state){if(!option('axe'))return;if(!await page.evaluate(()=>typeof window.axe!=='undefined'))await page.addScriptTag({path:option('axe')});const result=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),incomplete:r.incomplete.map(v=>v.id)};});report.accessibility.push({state,...result});assert.deepEqual(result.violations,[],state);}
(async()=>{
 browser=await pw.chromium.launch({headless:true,...(option('browser')?{executablePath:option('browser')}:{})});report.browser=browser.version();
 const owner=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']}),page=await owner.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 const environment=await responseJSON(await owner.request.get(url+'/api/qa/environment'));assert.equal(environment.isolated,true);assert.equal(environment.models_enabled,false);
 const fixture={title:'编辑事务与协作验收 · 合成资料',blocks:[{id:'p1',type:'paragraph',text:'alpha'},{id:'p2',type:'paragraph',text:'beta'},{id:'table',type:'table',text:'',cells:[['数据','数值'],['2','3'],['=SUM(A2:B2)','=A2*B2']]},{id:'math',type:'math',text:'\\frac{a^2+b^2}{c}',caption:'a squared plus b squared divided by c'}]};
 const doc=await responseJSON(await owner.request.post(url+'/api/academy/learning/documents',{data:fixture})),docURL=url+'/academy/notes?document='+doc.id;
 await page.goto(docURL);await ready(page);const p1=page.locator('[data-block=p1] .block-edit');
 await check('cross-block keyboard formatting and toggle preserve selection',async()=>{
  await p1.press('Control+Home');await p1.press('Control+Shift+ArrowDown');await page.keyboard.press('Control+b');
  assert.equal(await page.locator('[data-block=p1] strong').count(),1);assert.equal(await page.locator('[data-block=p2] strong').count(),1);
  await page.keyboard.press('Control+b');assert.equal(await page.locator('[data-block=p1] strong,[data-block=p2] strong').count(),0);
 });
 await check('cross-block copy omits block operation menus',async()=>{await p1.press('Control+Home');await p1.press('Control+Shift+ArrowDown');await page.keyboard.press('Control+c');const text=await page.evaluate(()=>navigator.clipboard.readText());assert.equal(text,'alpha\nbeta');});
 await check('cross-block replace and undo are one document transaction',async()=>{
  await page.keyboard.type('replacement');assert.equal(await page.locator('#docBlocks .paragraph').count(),1);assert.equal(await p1.innerText(),'replacement');
  await page.keyboard.press('Control+z');assert.equal(await page.locator('#docBlocks .paragraph').count(),2);assert.equal(await p1.innerText(),'alpha');
 });
 await check('Enter split and Backspace join preserve surrounding blocks',async()=>{
  await p1.press('Control+Home');await p1.press('ArrowRight');await p1.press('ArrowRight');await p1.press('Enter');assert.equal(await page.locator('#docBlocks .paragraph').count(),3);
  await page.keyboard.press('Backspace');assert.equal(await page.locator('#docBlocks .paragraph').count(),2);assert.equal(await p1.innerText(),'alpha');
 });
 await check('cross-block soft break, cut and rich paste remain undoable',async()=>{
  const select=async()=>{await p1.press('Control+Home');await p1.press('Control+Shift+ArrowDown');};
  await select();await page.keyboard.press('Shift+Enter');assert.equal(await page.locator('#docBlocks .paragraph').count(),1);assert.equal(await p1.locator('br').count(),1);
  await page.keyboard.press('Control+z');assert.equal(await page.locator('#docBlocks .paragraph').count(),2);
  await select();await page.keyboard.press('Control+x');assert.equal(await page.locator('#docBlocks .paragraph').count(),1);assert.equal(await p1.innerText(),'');
  await page.keyboard.press('Control+z');await select();
  await page.evaluate(async()=>navigator.clipboard.write([new ClipboardItem({'text/html':new Blob(['<h2>Heading</h2><p><strong>Evidence</strong></p>'],{type:'text/html'}),'text/plain':new Blob(['Heading\nEvidence'],{type:'text/plain'})})]));
  await page.keyboard.press('Control+v');assert.equal(await page.locator('#docBlocks .heading .block-edit').textContent(),'Heading');assert.equal(await page.locator('#docBlocks .paragraph strong').textContent(),'Evidence');
  await page.keyboard.press('Control+z');assert.equal(await p1.textContent(),'alpha');assert.equal(await page.locator('[data-block=p2] .block-edit').textContent(),'beta');
 });
 await check('rich table cell formatting keeps formula numeric inputs',async()=>{
  const cell=page.locator('[data-cell="1,0"]');await cell.press('Control+a');await page.keyboard.press('Control+b');assert.equal(await cell.locator('strong').count(),1);
  assert.equal(await page.locator('[data-result="2,0"]').innerText(),'5');assert.equal(await page.locator('[data-result="2,1"]').innerText(),'6');
  await cell.press('Alt+ArrowRight');assert.equal(await page.evaluate(()=>document.activeElement.dataset.cell),'1,1');
  await page.locator('summary').filter({hasText:'文档选项'}).click();await page.locator('#docSave').click();await ready(page);
  const saved=await responseJSON(await owner.request.get(url+'/api/academy/learning/documents/'+doc.id));assert.equal(saved.blocks.find(b=>b.id==='table').cell_inline[1][0][0].marks[0].type,'bold');
 });
 await check('local LaTeX preview includes MathML and refuses external image commands',async()=>{
  assert.equal(await page.locator('[data-math-preview] math mfrac').count(),1);let external=false;page.on('request',r=>{if(r.url().startsWith('https://example.invalid/'))external=true;});
  await page.locator('[aria-label="LaTeX 公式"]').fill('\\includegraphics{https://example.invalid/leak.png}');await page.waitForFunction(()=>document.querySelector('[data-math-preview]')?.textContent.includes('公式尚未完成'),{},{timeout:3000});assert.equal(external,false);assert.equal(await page.locator('[data-math-preview] img').count(),0);
  await page.locator('[aria-label="LaTeX 公式"]').fill('\\frac{a^2+b^2}{c}');await page.waitForFunction(()=>document.querySelector('[data-math-preview] math mfrac'),{},{timeout:3000});
 });
 await ready(page);
 await scan(page,'rich-editing');
 await page.locator('#docCollab').click();await scan(page,'collaboration-dialog');await page.locator('#collabClose').click();
 await page.locator('#docInsert').selectOption('drawing');await scan(page,'drawing-dialog');await page.locator('[aria-label="关闭绘图"]').click();
 await p1.press('Control+Home');await p1.press('Control+Shift+End');await page.locator('.doc-toolbar [data-format=link]').click();await scan(page,'link-dialog');await page.locator('#linkCancel').click();
 const guest=await browser.newContext({viewport:{width:1440,height:1000}}),guestPage=await guest.newPage();guestPage.on('pageerror',e=>report.errors.push(e.message));
 const invitation=await responseJSON(await owner.request.post(url+'/api/collaboration/documents/'+doc.id+'/invite',{data:{role:'editor'}}));
 const identity=await responseJSON(await guest.request.post(url+'/api/collaboration/join',{data:{code:invitation.code,name:'精确光标测试者'}}));
 await guestPage.goto(docURL);await ready(guestPage);await ready(page);
 await check('two authenticated contexts show an exact caret and selection',async()=>{
  await p1.scrollIntoViewIfNeeded();
  const host=guestPage.locator('[data-block=p1] .block-edit');await host.press('Control+Home');await host.press('ArrowRight');await host.press('ArrowRight');await host.press('Shift+ArrowRight');
  await page.waitForFunction(()=>document.querySelector('.remote-caret')?.textContent.includes('精确光标测试者')&&document.querySelector('.remote-selection'),{},{timeout:5000});
  const positions=await page.evaluate(()=>{const host=document.querySelector('[data-block=p1] .block-edit'),caret=document.querySelector('.remote-caret').getBoundingClientRect(),range=document.createRange();range.setStart(host.firstChild,3);range.collapse(true);const expected=range.getBoundingClientRect();return {actual:caret.left,expected:expected.left,selectionWidth:document.querySelector('.remote-selection').getBoundingClientRect().width};});
  assert.ok(Math.abs(positions.actual-positions.expected)<2);assert.ok(positions.selectionWidth>0);report.caretGeometry=positions;
 });
 await check('cross-block and rich-cell cursors use their own text boundaries',async()=>{
  const host=guestPage.locator('[data-block=p1] .block-edit');await host.press('Control+Home');await host.press('Control+Shift+ArrowDown');
  await page.waitForFunction(()=>document.querySelectorAll('.remote-selection').length>=2,{},{timeout:5000});
  await page.locator('[data-cell="1,0"]').scrollIntoViewIfNeeded();await guestPage.locator('[data-cell="1,0"]').press('Control+Home');await guestPage.keyboard.press('Shift+ArrowRight');
  await page.waitForFunction(()=>{const caret=document.querySelector('.remote-caret'),cell=document.querySelector('[data-cell="1,0"]');if(!caret||!cell)return false;const a=caret.getBoundingClientRect(),b=cell.getBoundingClientRect();return a.top>=b.top&&a.top<=b.bottom&&document.querySelector('.remote-selection');},{},{timeout:5000});
 });
 await check('remote cursors never reuse a stale version on a dirty draft',async()=>{
  await page.bringToFront();await p1.click();await p1.press('Control+End');await page.keyboard.type(' local');assert.ok((await p1.textContent()).includes(' local'));await page.waitForFunction(()=>!document.querySelector('.remote-caret'),{},{timeout:3000});await ready(page);
 });
 await check('revocation removes guest writes and ends its live access',async()=>{
  await responseJSON(await owner.request.post(url+'/api/collaboration/documents/'+doc.id+'/revoke',{data:{user_id:identity.id}}));
  await guestPage.waitForFunction(()=>document.querySelector('#docSave')?.disabled,{},{timeout:5000});assert.equal((await guest.request.get(url+'/api/academy/learning/documents/'+doc.id)).status(),403);
 });
 await check('reading exposes a document heading, table headers and math tree',async()=>{
  await page.locator('summary').filter({hasText:'文档选项'}).click();await page.locator('#docPreview').click();assert.equal(await page.locator('#docReadTitle').isVisible(),true);assert.equal(await page.locator('th[scope=col]').count(),2);
  const cdp=await owner.newCDPSession(page),ax=await cdp.send('Accessibility.getFullAXTree');const nodes=ax.nodes.filter(n=>!n.ignored).map(n=>({role:n.role?.value,name:n.name?.value}));report.screenReader.roles=nodes.filter(n=>['heading','table','columnheader','Math'].includes(n.role));assert.ok(nodes.some(n=>n.role==='heading'&&n.name===fixture.title));assert.ok(nodes.some(n=>n.role==='columnheader'));assert.ok(await page.locator('math').count());
 });
 await scan(page,'rich-reading');
 const mobile=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true}),mobilePage=await mobile.newPage();
 for(const route of ['/academy/notes?document='+doc.id,'/academy','/academy/materials','/academy/rag','/academy/code','/academy/quiz','/academy/ingest','/academy/paper','/meetings','/data-lab','/console?view=feishu']){
  await mobilePage.goto(url+route);await mobilePage.locator('.workspace-nav').waitFor({timeout:5000});if(route.startsWith('/academy/notes'))await ready(mobilePage);
  const widths=await mobilePage.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));report.viewports.push({route,...widths});assert.equal(widths.scroll,widths.client,route);
  if(['/academy','/academy/materials','/academy/rag'].includes(route))await scan(mobilePage,'mobile '+route);
 }
 report.pass=report.errors.length===0;assert.equal(report.pass,true);console.log('Acceptance complete');
})().catch(error=>{report.pass=false;report.failure=error.message;console.error(error);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));await browser?.close();});
