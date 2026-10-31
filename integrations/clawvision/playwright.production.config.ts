import { defineConfig, devices } from '@playwright/test';
import { resolve, join } from 'node:path';

const externalURL = process.env.CLAWVISION_E2E_BASE_URL;
const dataDirectory = resolve(process.env.CLAWVISION_E2E_DATA_DIR ?? `output/playwright/production/data-${Date.now()}`);
process.env.CLAWVISION_E2E_DATA_DIR = dataDirectory;

export default defineConfig({
  testDir: './tests/e2e-production',
  outputDir: 'output/playwright/production/results',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  use: { baseURL: externalURL ?? 'http://127.0.0.1:5174', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'production-chromium', use: { ...devices['Desktop Chrome'], channel: process.env.CI ? undefined : 'chrome' } }],
  webServer: externalURL ? undefined : [
    {
      command: 'python -m uvicorn asgi:app --app-dir backend --host 127.0.0.1 --port 8788',
      url: 'http://127.0.0.1:8788/api/health',
      reuseExistingServer: false,
      stdout: 'pipe',
      env: { ...process.env, PYTHONUNBUFFERED: '1', DATABASE_URL: '', ARTIFACT_STORE: 'local', CLAWVISION_AUTH_MODE: 'enabled', CLAWVISION_EMBEDDED_WORKERS: 'false', CLAWVISION_DATA_DIR: dataDirectory, CLAWVISION_OBJECT_DIR: join(dataDirectory, 'objects'), CLAWVISION_TRAINING_SCRIPT: resolve('tests/fixtures/training_recovery.py') },
      timeout: 60_000,
    },
    {
      command: 'pnpm build && pnpm preview --host 127.0.0.1 --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      env: { ...process.env, CLAWVISION_API_URL: 'http://127.0.0.1:8788' },
      timeout: 60_000,
    },
  ],
});
