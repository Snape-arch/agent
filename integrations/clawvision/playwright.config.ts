import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: 'output/playwright/results',
  snapshotDir: './tests/e2e/snapshots',
  snapshotPathTemplate: '{snapshotDir}/{testFilePath}-snapshots/{arg}{ext}',
  timeout: 45_000,
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixelRatio: 0.025 } },
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['html', { outputFolder: 'output/playwright/report', open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Keep the suite runnable against an installed Chrome without requiring a
    // separate Playwright ffmpeg download. Traces and failure screenshots retain
    // the actionable browser evidence.
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: process.env.CI ? undefined : 'chrome', launchOptions: { args: ['--use-angle=swiftshader'] } } }],
  webServer: [
    {
      command: 'python backend/server.py',
      url: 'http://127.0.0.1:8787/api/health',
      reuseExistingServer: !process.env.CI,
      env: { ...process.env, CLAWVISION_AUTH_MODE: 'disabled', CLAWVISION_DATA_DIR: '.e2e-data', CLAWVISION_OBJECT_DIR: '.e2e-data/objects' },
      timeout: 60_000,
    },
    { command: 'pnpm dev', url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.CI, timeout: 60_000 },
  ],
});
