import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Web-only config (no Electron) for headless development
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, './shared'),
    },
  },
  build: {
    outDir: 'dist',
  },
  server: {
    watch: {
      usePolling: true,
      interval: 1000,
    },
  },
});
