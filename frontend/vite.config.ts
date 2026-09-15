import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The build lands directly in the Python package, so `bpmn-architect studio`
 * serves the API and the app from one origin and the user never runs two
 * processes or meets a CORS error.
 *
 * In development the app runs on Vite's own server and proxies `/api` to the
 * backend, which keeps hot reload while using the very same request paths as
 * production - no environment-dependent base URL anywhere in the code.
 */
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/bpmn_architect/server/static',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          // bpmn-js is by far the largest dependency; splitting it lets the
          // shell render while the modeller is still arriving.
          'bpmn-js': ['bpmn-js/lib/Modeler', 'diagram-js-minimap'],
        },
      },
    },
  },
  server: {
    port: Number(process.env.PORT ?? 5173),
    proxy: {
      // VITE_API_PROXY lets the dev server run in a container and reach the
      // API by service name instead of localhost.
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
