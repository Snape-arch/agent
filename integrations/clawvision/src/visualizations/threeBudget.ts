import type * as THREE from 'three';
import { integrated, visionApiUrl } from '../clawos';

export interface ThreeBudgetSample {
  label: string; sessionId: string; assetId?: string; frames: number;
  averageFrameMs: number; maxFrameMs: number; gpuFrameMs?: number;
  gpuVendor: string; gpuRenderer: string; webglVersion: string;
  geometries: number; textures: number; drawCalls: number; triangles: number;
  contextLosses: number; contextRestores: number; heapBytes: number;
  transferredBytes: number; width: number; height: number; pixelRatio: number; passed: boolean;
}

declare global {
  interface Window { __CLAWVISION_3D_METRICS__?: Record<string, ThreeBudgetSample> }
}

interface TimerExtension { TIME_ELAPSED_EXT: number; GPU_DISJOINT_EXT: number }

export function createThreeBudgetMonitor(renderer: THREE.WebGLRenderer, label: string, options: { assetId?: string } = {}) {
  const samples: number[] = []; const gpuSamples: number[] = [];
  const sessionId = crypto.randomUUID(); let started = performance.now(); let losses = 0; let restores = 0; let transferredBytes = 0; let reportedFrames = 0;
  const gl = renderer.getContext() as WebGL2RenderingContext; const timer = gl.getExtension('EXT_disjoint_timer_query_webgl2') as TimerExtension | null;
  const debug = gl.getExtension('WEBGL_debug_renderer_info') as { UNMASKED_VENDOR_WEBGL: number; UNMASKED_RENDERER_WEBGL: number } | null;
  const gpuVendor = String(debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR) ?? 'unknown');
  const gpuRenderer = String(debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) ?? 'unknown');
  const webglVersion = String(gl.getParameter(gl.VERSION) ?? 'unknown');
  let activeQuery: WebGLQuery | null = null; let pendingQuery: WebGLQuery | null = null;
  const lost = (event: Event) => { event.preventDefault(); losses += 1; };
  const restored = () => { restores += 1; };
  renderer.domElement.addEventListener('webglcontextlost', lost); renderer.domElement.addEventListener('webglcontextrestored', restored);
  const pollGpu = () => {
    if (!timer || !pendingQuery) return;
    if (gl.getQueryParameter(pendingQuery, gl.QUERY_RESULT_AVAILABLE) && !gl.getParameter(timer.GPU_DISJOINT_EXT)) {
      gpuSamples.push(Number(gl.getQueryParameter(pendingQuery, gl.QUERY_RESULT)) / 1_000_000); if (gpuSamples.length > 120) gpuSamples.shift(); gl.deleteQuery(pendingQuery); pendingQuery = null;
    }
  };
  const snapshot = (): ThreeBudgetSample => {
    const heap = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? 0;
    const total = samples.reduce((sum, value) => sum + value, 0); const gpuTotal = gpuSamples.reduce((sum, value) => sum + value, 0);
    return {
      label, sessionId, assetId: options.assetId, frames: samples.length,
      averageFrameMs: samples.length ? total / samples.length : 0, maxFrameMs: Math.max(0, ...samples), gpuFrameMs: gpuSamples.length ? gpuTotal / gpuSamples.length : undefined,
      gpuVendor, gpuRenderer, webglVersion, geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures,
      drawCalls: renderer.info.render.calls, triangles: renderer.info.render.triangles, contextLosses: losses, contextRestores: restores,
      heapBytes: heap, transferredBytes, width: renderer.domElement.width, height: renderer.domElement.height, pixelRatio: renderer.getPixelRatio(),
      passed: renderer.info.memory.geometries <= 512 && renderer.info.memory.textures <= 128 && renderer.info.render.calls <= 1200 && Math.max(0, ...samples) <= 250 && losses === 0,
    };
  };
  const commit = (persist = false) => {
    const value = snapshot(); window.__CLAWVISION_3D_METRICS__ = { ...(window.__CLAWVISION_3D_METRICS__ ?? {}), [label]: value };
    if (persist && value.frames !== reportedFrames) {
      reportedFrames = value.frames; const token = integrated() ? null : sessionStorage.getItem('clawvision.api-token');
      void fetch(visionApiUrl('/api/telemetry/3d'), { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(value) }).catch(() => undefined);
    }
  };
  return {
    beginFrame() { pollGpu(); started = performance.now(); if (timer && !activeQuery && !pendingQuery) { activeQuery = gl.createQuery(); if (activeQuery) gl.beginQuery(timer.TIME_ELAPSED_EXT, activeQuery); } },
    endFrame() { if (activeQuery && timer) { gl.endQuery(timer.TIME_ELAPSED_EXT); pendingQuery = activeQuery; activeQuery = null; } samples.push(performance.now() - started); if (samples.length > 120) samples.shift(); if (samples.length % 20 === 0) commit(samples.length % 120 === 0); },
    addTransferredBytes(value: number) { transferredBytes += Math.max(0, value); },
    snapshot,
    dispose() { pollGpu(); if (activeQuery && timer) gl.endQuery(timer.TIME_ELAPSED_EXT); if (activeQuery) gl.deleteQuery(activeQuery); if (pendingQuery) gl.deleteQuery(pendingQuery); commit(true); renderer.domElement.removeEventListener('webglcontextlost', lost); renderer.domElement.removeEventListener('webglcontextrestored', restored); },
  };
}
