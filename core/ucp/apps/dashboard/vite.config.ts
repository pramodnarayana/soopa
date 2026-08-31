import tailwindcss from '@tailwindcss/vite';
import { TanStackRouterVite } from '@tanstack/router-vite-plugin';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig, loadEnv } from 'vite';

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, '../../../../', ['VITE_', 'ZITADEL_']);
  const proxyTarget = env.VITE_API_PROXY_TARGET;

  if (command === 'serve' && !proxyTarget) {
    throw new Error(
      'VITE_API_PROXY_TARGET environment variable is required for local development proxy.',
    );
  }

  return {
    envDir: '../../../../',
    envPrefix: ['VITE_', 'ZITADEL_'],
    plugins: [TanStackRouterVite(), react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@soopa/ui': path.resolve(__dirname, '../../../packages/ui/src'),
        '@soopa/edi-ui': path.resolve(__dirname, '../../../../apps/edi/packages/ui/src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
