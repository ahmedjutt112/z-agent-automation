import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Vite configuration for the Electron renderer.
//
// Notes:
// - `base: './'` is required so the built index.html uses relative asset
//   paths. Electron loads the renderer over file:// and absolute paths
//   (e.g. `/assets/index-xyz.js`) would resolve to the filesystem root.
// - `server.strictPort: true` so the dev server never drifts off 5173,
//   which is the port `electron/main.ts` waits on via `wait-on tcp:5173`.
// - The `@` alias mirrors the `paths` mapping in tsconfig.json so imports
//   like `@/components/Sidebar` resolve the same way in dev and typecheck.
export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'renderer/src'),
    },
  },
  build: {
    outDir: 'renderer/dist',
    target: 'esnext',
    sourcemap: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'renderer/index.html'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
