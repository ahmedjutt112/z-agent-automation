import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Vite configuration for the renderer (Electron + static web deploy).
//
// - `root: 'renderer'` makes Vite treat `renderer/` as the project root so
//   index.html + src/ resolve correctly. Output goes to `renderer/dist/`
//   (NOT `renderer/dist/renderer/`).
// - `base: './'` so the built index.html uses relative asset paths.
//   Electron loads the renderer over file:// — absolute paths would resolve
//   to the filesystem root.
// - `server.strictPort: true` so the dev server never drifts off 5173,
//   which is the port `electron/main.ts` waits on via `wait-on tcp:5173`.
// - The `@` alias mirrors the `paths` mapping in tsconfig.json so imports
//   like `@/components/Sidebar` resolve the same way in dev and typecheck.
export default defineConfig({
  plugins: [react()],
  root: path.resolve(__dirname, 'renderer'),
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'renderer/src'),
    },
  },
  build: {
    outDir: 'dist',
    target: 'esnext',
    sourcemap: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
