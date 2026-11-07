import { expect, test } from '@playwright/test';

test('workspace navigation, experiment comparison and data dashboard', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('workspace-app')).toBeVisible();
  await page.getByTestId('nav-more').click();
  await page.getByTestId('nav-compare').click();
  await expect(page.locator('.compare-chart')).toBeVisible();
  await page.getByTestId('nav-data').click();
  await expect(page.getByTestId('data-lab')).toBeVisible();
  await expect(page.locator('.dashboard-tile')).toHaveCount(3);
  await expect(page).toHaveScreenshot('data-dashboard.png', { fullPage: true, maxDiffPixelRatio: 0.04 });
});

test('3D workbench survives WebGL initialization and reports a budget sample', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('nav-more').click();
  await page.getByTestId('nav-three').click();
  await expect(page.locator('.three-lab')).toBeVisible();
  await expect(page.locator('.three-lab canvas').first()).toBeVisible();
  const budget = await page.evaluate(() => ({
    canvases: document.querySelectorAll('canvas').length,
    heap: (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? 0,
    webgl: Boolean(document.querySelector('canvas')?.getContext('webgl2') || document.querySelector('canvas')?.getContext('webgl')),
  }));
  expect(budget.canvases).toBeGreaterThan(0);
  expect(budget.webgl).toBeTruthy();
  await expect.poll(() => page.evaluate(() => window.__CLAWVISION_3D_METRICS__?.['cad-model']?.frames ?? 0)).toBeGreaterThanOrEqual(20);
  const rendererBudget = await page.evaluate(() => window.__CLAWVISION_3D_METRICS__?.['cad-model']);
  expect(rendererBudget?.passed).toBeTruthy();
  expect(rendererBudget?.geometries).toBeGreaterThan(0);
  expect(rendererBudget?.contextLosses).toBe(0);
  expect(rendererBudget?.gpuRenderer.length).toBeGreaterThan(0);
  expect(rendererBudget?.webglVersion).toContain('WebGL');
  await expect(page).toHaveScreenshot('three-workbench.png', { fullPage: true, maxDiffPixelRatio: 0.04 });
});

test('AI Studio is lazily loaded without polluting the core workbench', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('nav-more').click();
  await page.getByTestId('nav-ai-studio').click();
  await expect(page.getByTestId('ai-studio')).toBeVisible();
  await page.getByRole('button', { name: /Agent/ }).click();
  await expect(page.locator('.studio-canvas canvas')).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => page.evaluate(() => Boolean(window.__CLAWVISION_3D_METRICS__?.['ai-studio']))).toBeTruthy();
});

test('WCAG keyboard, narrow viewport and 200% zoom acceptance', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /项目全局|研究工作|项目进展|团队工作区/ })).toBeVisible();
  await page.getByRole('button', { name: '导航' }).click();
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible();
  await expect(page.locator('.sidebar :focus')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeHidden();
  await expect(page.getByRole('button', { name: '导航' })).toBeFocused();
  // A 1280px desktop viewport at browser zoom 200% exposes roughly 640 CSS pixels.
  await page.setViewportSize({ width: 640, height: 720 });
  await expect(page.locator('body')).not.toHaveCSS('min-width', '1180px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2)).toBeTruthy();
  await page.addScriptTag({ path: 'node_modules/axe-core/axe.min.js' });
  const violations = await page.evaluate(async () => (await (window as typeof window & { axe: { run: () => Promise<{ violations: Array<{ id: string; nodes: Array<{ target: string[] }> }> }> } }).axe.run()).violations.map((item) => ({id:item.id,targets:item.nodes.flatMap((node)=>node.target)})));
  expect(violations).toEqual([]);
});

test('high DPI layout remains stable', async ({ browser, baseURL }) => {
  const context=await browser.newContext({viewport:{width:1280,height:720},deviceScaleFactor:2});
  const page=await context.newPage();
  await page.goto(baseURL!);
  await expect(page.getByTestId('workspace-app')).toBeVisible();
  expect(await page.evaluate(()=>window.devicePixelRatio)).toBe(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2)).toBeTruthy();
  await context.close();
});

test('workspace views are deep-linkable and follow browser history',async({page})=>{
  await page.goto('/#assets');await expect(page.locator('.asset-workbench')).toBeVisible();
  await page.getByTestId('nav-home').click();await expect(page).toHaveURL(/#home$/);
  await page.goBack();await expect(page).toHaveURL(/#assets$/);await expect(page.locator('.asset-workbench')).toBeVisible();
});

for (const target of [
  {name:'data',testId:'nav-data',ready:'data-lab'},
  {name:'assets',testId:'nav-assets',ready:undefined},
  {name:'three',testId:'nav-three',ready:undefined},
  {name:'ai-studio',testId:'nav-ai-studio',ready:'ai-studio'},
]) test(`${target.name} workbench passes narrow reflow and axe`,async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto('/');
  await page.getByRole('button',{name:'导航'}).click();
  if(['data','three','ai-studio'].includes(target.name))await page.getByTestId('nav-more').click();
  await page.getByTestId(target.testId).click();
  if(target.ready)await expect(page.getByTestId(target.ready)).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2)).toBeTruthy();
  await page.addScriptTag({path:'node_modules/axe-core/axe.min.js'});
  const violations=await page.evaluate(async()=>(await (window as typeof window & {axe:{run:()=>Promise<{violations:Array<{id:string;nodes:Array<{target:string[]}>}>}>}}).axe.run()).violations.map(item=>({id:item.id,targets:item.nodes.flatMap(node=>node.target)})));
  expect(violations).toEqual([]);
  const undersized=await page.evaluate(()=>Array.from(document.querySelectorAll<HTMLElement>('body *')).filter(element=>element.childElementCount===0&&element.textContent?.trim()&&getComputedStyle(element).display!=='none'&&element.getBoundingClientRect().width>0&&Number.parseFloat(getComputedStyle(element).fontSize)<12).slice(0,10).map(element=>({tag:element.tagName,text:element.textContent?.trim(),size:getComputedStyle(element).fontSize})));
  expect(undersized).toEqual([]);
});

for (const persona of [
  {role:'viewer',scopes:['*'],canCreate:false,canAdmin:false},
  {role:'researcher',scopes:['write'],canCreate:true,canAdmin:false},
  {role:'admin',scopes:['admin','write'],canCreate:true,canAdmin:true},
] as const) test(`${persona.role} capability ceiling is enforced in the workspace`,async({page})=>{
  await page.route('**/api/auth/me',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:{userId:`${persona.role}-1`,tenantId:'tenant-e2e',role:persona.role,scopes:persona.scopes}})}));
  await page.goto('/');await expect(page.getByTestId('workspace-app')).toBeVisible();
  await expect(page.locator('.new-experiment')).toHaveCount(persona.canCreate?1:0);
  await page.getByTestId('nav-more').click();
  await expect(page.locator('.sidebar-foot > button')).toHaveCount(persona.canAdmin?1:0);
  await page.getByTestId('nav-assets').click();
  await expect(page.locator('.read-only-notice')).toHaveCount(persona.canCreate?0:1);
});
