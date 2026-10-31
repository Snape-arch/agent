import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

const threeSourceEntry = decodeURIComponent(
  new URL('./node_modules/three/src/Three.js', import.meta.url).pathname,
).replace(/^\/([A-Za-z]:\/)/, '$1');

export default defineConfig(({ mode }) => {
  const apiUrl = loadEnv(mode, '.', 'CLAWVISION_').CLAWVISION_API_URL ?? 'http://127.0.0.1:8787';
  return {
    base: '/academy/vision/',
    cacheDir: '../../clawos/output/vision-vite-cache',
    plugins: [react()],
    resolve: { alias: [{ find: /^three$/, replacement: threeSourceEntry }] },
    build: {
      outDir: '../../clawos/static/vision',
      emptyOutDir: false,
      manifest: true,
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.indexOf('/node_modules/three/examples/jsm/controls/') !== -1) return 'three-controls';
            if (id.indexOf('/node_modules/three/examples/jsm/loaders/') !== -1) return 'three-loaders';
            if (id.indexOf('/node_modules/three/examples/jsm/geometries/') !== -1) return 'three-geometries';
            if (id.indexOf('/node_modules/three/examples/') !== -1) return 'three-addons';
            if (/\/node_modules\/three\/src\/(animation\/|helpers\/SkeletonHelper|objects\/SkinnedMesh|objects\/Bone|objects\/Skeleton)/.test(id)) return 'three-animation';
            if (id.indexOf('/node_modules/three/') !== -1) return 'three-core';
            if (id.indexOf('/node_modules/react') !== -1 || id.indexOf('/node_modules/react-dom') !== -1) return 'react-vendor';
            return undefined;
          },
        },
      },
    },
    server: {
      proxy: {
        '/api': apiUrl,
      },
    },
    preview: {
      proxy: { '/api': apiUrl },
    },
  };
});
