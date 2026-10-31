import { describe, expect, it, vi } from 'vitest';
import { createThreeBudgetMonitor } from './threeBudget';

describe('3D context recovery telemetry', () => {
  it('records WebGL context loss and restoration', () => {
    const canvas = document.createElement('canvas');
    const gl = { VENDOR: 1, RENDERER: 2, VERSION: 3, getExtension: vi.fn(() => null), getParameter: vi.fn(() => 'test-gpu'), deleteQuery: vi.fn() };
    const renderer = { domElement: canvas, getContext: () => gl, getPixelRatio: () => 1, info: { memory: { geometries: 1, textures: 1 }, render: { calls: 1, triangles: 2 } } };
    const monitor = createThreeBudgetMonitor(renderer as never, 'test');
    const loss = new Event('webglcontextlost', { cancelable: true });
    canvas.dispatchEvent(loss); canvas.dispatchEvent(new Event('webglcontextrestored'));
    expect(loss.defaultPrevented).toBe(true);
    expect(monitor.snapshot()).toMatchObject({ contextLosses: 1, contextRestores: 1, passed: false });
    monitor.dispose();
  });
});
