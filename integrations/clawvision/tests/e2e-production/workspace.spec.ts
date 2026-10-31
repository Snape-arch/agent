import { expect, test } from '@playwright/test';
import { AcceptanceWorker } from './worker-control';

test('built workspace preserves real data through login, streaming, diagnostics and viewer access', async ({ page }) => {
  await page.goto('/');
  if (process.env.CLAWVISION_E2E_BASE_URL) {
    const health = await page.request.get('/api/health');
    expect((await health.json()).databaseKind).toBe('postgresql');
    expect((await health.json()).objectStore.kind).toBe('s3');
    expect(health.headers()['server']).toContain('nginx');
  }
  await page.getByRole('button', { name: '首次安装？初始化 Owner' }).click();
  await page.getByLabel('工作区名称').fill('Production acceptance');
  await page.getByLabel('邮箱').fill('owner@production.test');
  await page.getByLabel('密码').fill('production-owner-password');
  await page.getByRole('button', { name: '创建 Owner', exact: true }).click();
  await expect(page.getByTestId('workspace-app')).toBeVisible();
  await expect(page.getByText('已连接后端')).toBeVisible();
  await expect(page.locator('.home-status')).toContainText('0 全部 Run');
  await page.getByTestId('nav-overview').click();
  await expect(page.getByRole('heading', { name: '尚无实验', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '创建真实 Run 并对比' })).toBeEnabled();
  await expect(page.getByRole('button', { name: '锁定当前 Run' })).toBeDisabled();

  const token = await page.evaluate(() => sessionStorage.getItem('clawvision.api-token'));
  const headers = { Authorization: `Bearer ${token}` };
  expect((await page.request.get('/api/runs')).status()).toBe(401);
  const created = await page.request.post('/api/runs', { headers, data: { name: 'sdk-production-run', source: 'sdk', params: { epochs: 2 } } });
  expect(created.status()).toBe(201);
  const runId = (await created.json()).data.id as string;
  await page.reload();
  await expect(page.getByRole('heading', { name: 'sdk-production-run', exact: true })).toBeVisible();

  // Observe a real incremental event in the browser, independently of list polling.
  await page.evaluate(async (id) => {
    const response = await fetch(`/api/runs/${id}/stream?incremental=1`, { headers: { Authorization: `Bearer ${sessionStorage.getItem('clawvision.api-token')}` } });
    const reader = response.body!.getReader();
    (window as typeof window & { productionReader?: ReadableStreamDefaultReader<Uint8Array> }).productionReader = reader;
    await reader.read();
  }, runId);
  const updated = await page.request.post(`/api/runs/${runId}/metrics`, { headers, data: { step: 1, accuracy: 0.72, trainLoss: 0.5, valLoss: 0.6 } });
  expect(updated.status()).toBe(200);
  const event = await page.evaluate(async () => {
    const reader = (window as typeof window & { productionReader: ReadableStreamDefaultReader<Uint8Array> }).productionReader;
    let frame = '';
    while (!frame.includes('\n\n')) frame += new TextDecoder().decode((await reader.read()).value);
    await reader.cancel();
    return frame;
  });
  expect(event).toContain('"accuracy": 0.72');
  expect(event).toContain('event: run-delta');
  await expect(page.locator('.stat-grid')).toContainText('72.0%');
  await page.getByTestId('nav-more').click();
  await page.getByRole('button', { name: '模型诊断', exact: true }).click();
  await expect(page.getByText(/此 Run 尚未上传诊断产物/)).toBeVisible();
  await expect(page.locator('[data-plugin-id="core.confusion-matrix"]')).toHaveCount(0);
  await expect(page.locator('[data-plugin-id="core.embedding-3d"]')).toHaveCount(0);
  const artifact = await page.request.post(`/api/runs/${runId}/artifacts`, { headers, data: { name: 'SDK confusion', type: 'confusion-matrix', content: [[3, 1], [0, 4]], mimeType: 'application/json' } });
  expect(artifact.status()).toBe(201);
  await page.reload();
  await expect(page.locator('[data-plugin-id="core.confusion-matrix"]')).toHaveCount(1);
  await expect(page.getByText(/此 Run 尚未上传诊断产物/)).toHaveCount(0);
  const stopped = await page.request.post(`/api/runs/${runId}/stop`, { headers, data: { message: 'acceptance complete' } });
  expect(stopped.status()).toBe(200);
  // More than one page: searches must find the earliest Run across the tenant.
  for (let index = 0; index < 25; index++) {
    const created = await page.request.post('/api/runs', { headers, data: { name: `paging-${index}`, source: 'sdk', params: {} } });
    expect(created.status()).toBe(201);
  }
  const requests: string[] = [];
  page.on('request', (request) => { if (request.method() === 'GET' && request.url().includes('/api/runs')) requests.push(request.url()); });
  await page.goto('/#home');
  await page.reload();
  await expect(page.locator('.home-status')).toContainText('26 全部 Run');
  expect(requests.filter((url) => /\/api\/runs\/[^/?]+(?:\?|$)/.test(url))).toHaveLength(0);
  await page.getByTestId('nav-overview').click();
  await expect(page.locator('.run-row')).toHaveCount(25);
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeInViewport();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('.run-pagination')).toContainText('第 2 / 2 页');
  await expect(page.locator('.run-row')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'sdk-production-run', exact: true })).toBeVisible();
  await page.getByPlaceholder('搜索 Run').fill('sdk-production');
  await expect(page.locator('.run-pagination')).toContainText('第 1 / 1 页');
  await expect(page.locator('.run-row')).toHaveCount(1);
  expect(requests.some((url) => url.includes('summary=1') && url.includes('page=2'))).toBeTruthy();
  expect(requests.some((url) => url.includes('incremental=1'))).toBeTruthy();
  expect(requests.every((url) => !url.endsWith('/api/runs'))).toBeTruthy();
  const member = await page.request.post('/api/auth/members', { headers, data: { email: 'viewer@production.test', password: 'production-viewer-password', role: 'viewer' } });
  expect(member.ok()).toBeTruthy();
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await page.getByLabel('邮箱').fill('viewer@production.test');
  await page.getByLabel('密码').fill('production-viewer-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByTestId('workspace-app')).toBeVisible();
  await expect(page.locator('.new-experiment')).toHaveCount(0);
  const viewerToken = await page.evaluate(() => sessionStorage.getItem('clawvision.api-token'));
  const denied = await page.request.post('/api/runs', { headers: { Authorization: `Bearer ${viewerToken}` }, data: { name: 'forbidden', params: {} } });
  expect(denied.status()).toBe(403);
});

async function loginOwner(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByLabel('邮箱').fill('owner@production.test');
  await page.getByLabel('密码').fill('production-owner-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByTestId('workspace-app')).toBeVisible();
  return { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('clawvision.api-token'))}` };
}

test('asset approval persists through reload and rejects researcher publication bypasses', async ({ page }) => {
  const headers = await loginOwner(page);
  const owner = (await (await page.request.get('/api/auth/me', { headers })).json()).data;
  const asset = await page.request.post('/api/model-assets', { headers, data: { name: 'production-release.obj', format: 'obj', content: Buffer.from('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n').toString('base64') } });
  expect(asset.status()).toBe(201);
  const assetId = (await asset.json()).data.id as string;
  await page.getByTestId('nav-assets').click();
  await page.locator('.asset-list-row').filter({ hasText: 'production-release.obj' }).click();
  await page.getByRole('button', { name: '批准为 Release', exact: true }).click();
  await expect(page.getByText('发布审批通过，资产已进入 Release 阶段')).toBeVisible();
  await page.reload();
  await expect(page.locator('.asset-list-row').filter({ hasText: 'production-release.obj' }).locator('.asset-stage')).toHaveText('release');
  const detail = (await (await page.request.get(`/api/model-assets/${assetId}`, { headers })).json()).data;
  expect(detail.releases[0]).toMatchObject({ status: 'approved', reviewer: owner.userId });
  const content = await page.request.get(`/api/model-assets/${assetId}/content`, { headers: { ...headers, Range: 'bytes=0-7' } });
  expect(content.status()).toBe(206);
  expect((await content.body()).length).toBe(8);
  expect((await page.request.post('/api/auth/members', { headers, data: { email: 'release-researcher@production.test', password: 'production-researcher-password', role: 'researcher' } })).ok()).toBeTruthy();
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await page.getByLabel('邮箱').fill('release-researcher@production.test');
  await page.getByLabel('密码').fill('production-researcher-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByTestId('nav-assets').click();
  await page.locator('.asset-list-row').filter({ hasText: 'production-release.obj' }).click();
  await expect(page.locator('.asset-inspector h3')).toContainText('production-release.obj');
  await expect(page.getByRole('button', { name: '批准为 Release', exact: true })).toHaveCount(0);
  const researcher = { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('clawvision.api-token'))}` };
  expect((await page.request.post(`/api/model-assets/${assetId}/releases`, { headers: researcher, data: { status: 'approved', reviewer: owner.userId } })).status()).toBe(403);
  expect((await page.request.patch(`/api/model-assets/${assetId}`, { headers: researcher, data: { stage: 'release' } })).status()).toBe(403);
  expect((await page.request.post('/api/model-assets/batch', { headers: researcher, data: { ids: [assetId], patch: { stage: 'release' } } })).status()).toBe(403);
});

test('killed standalone Worker resumes its checkpoint and the same browser receives remaining steps', async ({ page }) => {
  test.setTimeout(90_000);
  const headers = await loginOwner(page);
  const worker = new AcceptanceWorker();
  try {
    await worker.start();
    const created = await page.request.post('/api/jobs', { headers, data: { name: 'checkpoint-recovery', kind: 'single', trainingProvider: 'local-python', configs: [{ epochs: 6, seed: 7 }], concurrency: 1, timeoutSeconds: 180 } });
    expect(created.status()).toBe(201);
    const runId = (await created.json()).data.runIds[0] as string;
    await page.getByPlaceholder('搜索 Run').fill('checkpoint-recovery');
    await page.getByTestId('nav-overview').click();
    await expect(page.getByRole('heading', { name: 'checkpoint-recovery', exact: true })).toBeVisible();
    let trainingId = '';
    await expect.poll(async () => {
      const tasks = (await (await page.request.get('/api/tasks', { headers })).json()).data;
      trainingId = tasks.find((task: { payload: { runId?: string }; resourceId: string }) => task.payload.runId === runId)?.resourceId ?? '';
      if (!trainingId) return false;
      const training = (await (await page.request.get(`/api/training-jobs/${trainingId}`, { headers })).json()).data;
      return Boolean(training.checkpoint_key && training.progress >= 33);
    }, { timeout: 20_000 }).toBe(true);
    await expect(page.locator('.stat-grid')).toContainText('60.0%');
    const before = (await (await page.request.get(`/api/runs/${runId}`, { headers })).json()).data;
    expect(before.metrics.map((point: { step: number }) => point.step)).toEqual([1, 2]);
    await worker.kill();
    await worker.start();
    await expect.poll(async () => (await (await page.request.get(`/api/runs/${runId}`, { headers })).json()).data.status, { timeout: 30_000 }).toBe('completed');
    await expect(page.locator('.stat-grid')).toContainText('80.0%');
    await expect(page.locator('.console-card')).toContainText('从 checkpoint step 2 恢复训练');
    const after = (await (await page.request.get(`/api/runs/${runId}`, { headers })).json()).data;
    expect(after.metrics.map((point: { step: number }) => point.step)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(after.metrics.slice(0, 2)).toEqual(before.metrics);
    const training = (await (await page.request.get(`/api/training-jobs/${trainingId}`, { headers })).json()).data;
    expect(training.result.resumedFrom).toBe(2);
    await expect.poll(async () => (await (await page.request.get('/api/tasks', { headers })).json()).data.find((task: { resourceId: string }) => task.resourceId === trainingId).status).toBe('completed');
    const tasks = (await (await page.request.get('/api/tasks', { headers })).json()).data;
    expect(tasks.find((task: { resourceId: string }) => task.resourceId === trainingId).attempts).toBe(2);
    await page.getByTestId('nav-more').click();
    await page.getByRole('button', { name: '模型诊断', exact: true }).click();
    await expect(page.locator('[data-plugin-id="core.confusion-matrix"]')).toHaveCount(1);
  } finally { await worker.kill(); }
});
