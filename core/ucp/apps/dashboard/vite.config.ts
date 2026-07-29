import tailwindcss from '@tailwindcss/vite';
import { TanStackRouterVite } from '@tanstack/router-vite-plugin';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  envDir: '../../',
  plugins: [TanStackRouterVite(), react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@soopa/ui': path.resolve(__dirname, '../../../packages/ui/src'),
      '@soopa/edi-ui': path.resolve(__dirname, '../../../../apps/edi/packages/ui/src'),
    },
  },
});
