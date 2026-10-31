import { defineConfig } from 'vitest/config';

export default defineConfig({
  cacheDir: '../../clawos/output/vision-vitest-cache',
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    clearMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      include: ['src/api.ts', 'src/permissions.ts', 'src/visualizations/threeBudget.ts'],
      // Ratchet the measured baseline; permissions and 3D budget retain their
      // stricter module floors below while API contract coverage is expanded.
      thresholds: {
        lines: 33, functions: 15, statements: 33, branches: 55,
        'src/permissions.ts': { lines: 95, functions: 95, statements: 95, branches: 95 },
        'src/visualizations/threeBudget.ts': { lines: 85, functions: 70, statements: 85, branches: 30 },
      },
    },
  },
});
