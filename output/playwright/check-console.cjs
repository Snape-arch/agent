const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto('http://127.0.0.1:18790/console', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForSelector('#taskQueueTable', { timeout: 15000 });
  await page.waitForTimeout(1500);
  const checks = await page.evaluate(() => {
    const ids = ['taskQueueTable','taskTable','taskStepTable','taskEventTable'];
    const result = {};
    for (const id of ids) {
      const el = document.getElementById(id);
      const r = el ? el.getBoundingClientRect() : null;
      result[id] = r ? { exists: true, width: Math.round(r.width), height: Math.round(r.height) } : { exists: false };
    }
    return { title: document.title, text: document.body.innerText.slice(0, 2000), checks: result };
  });
  await page.screenshot({ path: 'output/playwright/console.png', fullPage: true });
  await browser.close();
  console.log(JSON.stringify(checks));
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
